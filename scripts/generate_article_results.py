"""Generate article-ready Results text, tables, figures, and data extracts.

This script only reads already-calculated repository artifacts. It does not
invoke an LLM, rerun the generator, or change the source experiment outputs.
The output is written to docs/article_results/.
"""

from __future__ import annotations

import argparse
import json
import math
from functools import lru_cache
from pathlib import Path
import sys
from typing import Iterable, Sequence

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.comparison.evaluate import (  # noqa: E402
    build_approach_metric_summary,
    build_metric_rows,
    build_stability_rows,
    discover_run_descriptors,
    evaluate_run,
)

STATIC_SUMMARIES = ROOT / "analysis-results" / "static-analysis" / "project_summaries.csv"
OUTPUTS_DIR = ROOT / "outputs"
OUTPUT_DIR = ROOT / "docs" / "article_results"

PROVIDER_ORDER = ("openai", "anthropic", "deepseek")
TEMPLATE_ORDER = ("zero_shot", "few_shot")
PROVIDER_LABELS = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "deepseek": "DeepSeek",
}
PROVIDER_SHORT = {"openai": "O", "anthropic": "A", "deepseek": "D"}
TEMPLATE_SHORT = {"zero_shot": "ZS", "few_shot": "FS"}
PROVIDER_COLORS = {
    "openai": "#1677B8",
    "anthropic": "#D97706",
    "deepseek": "#6658B8",
}
ACCENT_BLUE = "#1F4E79"
TEXT = "#1F2937"
GRID = "#D1D5DB"
PALE = "#F8FAFC"

ARCHITECTURE_METRICS = (
    "service_count",
    "unique_service_count",
    "duplicate_service_name_count",
    "malformed_service_row_count",
    "raw_declared_communication_count",
    "declared_communication_count",
    "duplicate_communication_count",
    "valid_communication_count",
    "invalid_communication_target_count",
    "self_communication_count",
    "communication_density",
    "average_outgoing_communications",
    "max_outgoing_communications",
    "average_incoming_communications",
    "max_incoming_communications",
    "isolated_services_count",
    "isolated_services_ratio",
    "reciprocal_communication_pair_count",
    "reciprocity_ratio",
    "total_responsibility_word_count",
    "average_responsibility_word_count",
    "responsibility_word_count_stddev",
    "min_responsibility_word_count",
    "max_responsibility_word_count",
    "short_responsibility_count",
    "short_responsibility_ratio",
    "average_responsibility_token_jaccard",
)

PROCESS_METRICS = (
    "trace_available",
    "trace_event_count",
    "trace_invalid_json_line_count",
    "llm_call_count",
    "successful_llm_call_count",
    "failed_llm_call_count",
    "failed_llm_call_ratio",
    "api_error_count",
    "parse_error_count",
    "retry_call_count",
    "retry_call_ratio",
    "total_call_duration_ms",
    "average_call_duration_ms",
    "max_call_duration_ms",
    "trace_elapsed_ms",
    "total_system_prompt_char_count",
    "total_user_prompt_char_count",
    "total_response_char_count",
    "distinct_role_count",
    "critic_round_count",
    "revision_request_count",
    "critic_issue_count",
    "refinement_round_count",
    "workflow_converged",
    "stopped_by_iteration_limit",
    "services_added_during_refinement_count",
    "services_removed_during_refinement_count",
    "interactions_added_during_refinement_count",
    "interactions_removed_during_refinement_count",
    "final_snapshot_service_count",
    "final_snapshot_communication_count",
)

DISPLAY_NAMES = {
    "service_count": "Service count",
    "unique_service_count": "Unique service count",
    "duplicate_service_name_count": "Duplicate service names",
    "malformed_service_row_count": "Malformed service rows",
    "raw_declared_communication_count": "Raw declared communications",
    "declared_communication_count": "Distinct declared communications",
    "duplicate_communication_count": "Duplicate communications",
    "valid_communication_count": "Valid communications",
    "invalid_communication_target_count": "Invalid communication targets",
    "self_communication_count": "Self-communications",
    "communication_density": "Communication density",
    "average_outgoing_communications": "Mean outgoing communications",
    "max_outgoing_communications": "Maximum outgoing communications",
    "average_incoming_communications": "Mean incoming communications",
    "max_incoming_communications": "Maximum incoming communications",
    "isolated_services_count": "Isolated services",
    "isolated_services_ratio": "Isolated-service ratio",
    "reciprocal_communication_pair_count": "Reciprocal communication pairs",
    "reciprocity_ratio": "Reciprocity ratio",
    "total_responsibility_word_count": "Total responsibility words",
    "average_responsibility_word_count": "Mean responsibility words",
    "responsibility_word_count_stddev": "Responsibility-word standard deviation",
    "min_responsibility_word_count": "Minimum responsibility words",
    "max_responsibility_word_count": "Maximum responsibility words",
    "short_responsibility_count": "Short responsibilities",
    "short_responsibility_ratio": "Short-responsibility ratio",
    "average_responsibility_token_jaccard": "Mean responsibility-token Jaccard",
    "llm_call_count": "LLM calls",
    "successful_llm_call_count": "Successful LLM calls",
    "failed_llm_call_count": "Failed LLM calls",
    "trace_available": "Trace available (1=yes)",
    "trace_event_count": "Trace events",
    "trace_invalid_json_line_count": "Invalid trace JSON lines",
    "failed_llm_call_ratio": "Failed-call ratio",
    "api_error_count": "API errors",
    "parse_error_count": "Parse errors",
    "retry_call_count": "Retry calls",
    "retry_call_ratio": "Retry-call ratio",
    "total_call_duration_ms": "Total LLM call duration (ms)",
    "average_call_duration_ms": "Mean LLM call duration (ms)",
    "max_call_duration_ms": "Maximum LLM call duration (ms)",
    "trace_elapsed_ms": "Trace elapsed time (ms)",
    "total_system_prompt_char_count": "System-prompt characters",
    "total_user_prompt_char_count": "User-prompt characters",
    "total_response_char_count": "Response characters",
    "distinct_role_count": "Distinct workflow roles",
    "critic_round_count": "Critic rounds",
    "revision_request_count": "Revision requests",
    "critic_issue_count": "Critic issues",
    "refinement_round_count": "Refinement rounds",
    "workflow_converged": "Workflow converged (1=yes)",
    "stopped_by_iteration_limit": "Stopped by iteration limit (1=yes)",
    "services_added_during_refinement_count": "Services added during refinement",
    "services_removed_during_refinement_count": "Services removed during refinement",
    "interactions_added_during_refinement_count": "Interactions added during refinement",
    "interactions_removed_during_refinement_count": "Interactions removed during refinement",
    "final_snapshot_service_count": "Final-snapshot service count",
    "final_snapshot_communication_count": "Final-snapshot communication count",
}


def number(value: object) -> float | None:
    """Return a finite float, treating blank and non-numeric values as missing."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def finite_series(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(frame[column], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()


def fmt(value: float | int | None, decimals: int = 2) -> str:
    if value is None or not math.isfinite(float(value)):
        return "--"
    value = float(value)
    if decimals == 0:
        return f"{value:,.0f}"
    return f"{value:,.{decimals}f}"


def fmt_compact(value: float | int | None) -> str:
    if value is None or not math.isfinite(float(value)):
        return "--"
    value = float(value)
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    if abs(value - round(value)) < 1e-9:
        return f"{value:.0f}"
    return f"{value:.2f}"


def stat_summary(values: pd.Series) -> dict[str, float | int | None]:
    values = values.dropna()
    if values.empty:
        return {"n": 0, "mean": None, "median": None, "q1": None, "q3": None, "std": None, "min": None, "max": None}
    return {
        "n": int(values.size),
        "mean": float(values.mean()),
        "median": float(values.median()),
        "q1": float(values.quantile(0.25)),
        "q3": float(values.quantile(0.75)),
        "std": float(values.std(ddof=0)),
        "min": float(values.min()),
        "max": float(values.max()),
    }


def median_iqr(values: pd.Series, decimals: int = 1) -> str:
    summary = stat_summary(values)
    if not summary["n"]:
        return "--"
    return f"{fmt(summary['median'], decimals)} [{fmt(summary['q1'], decimals)}, {fmt(summary['q3'], decimals)}]"


def latex_escape(value: object) -> str:
    text = str(value)
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in text)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def write_latex_table(
    path: Path,
    headers: Sequence[str],
    rows: Iterable[Sequence[object]],
    caption: str,
    label: str,
    alignment: str | None = None,
    resize: bool = False,
) -> None:
    rows = list(rows)
    alignment = alignment or ("l" + "r" * (len(headers) - 1))
    start = r"\resizebox{\linewidth}{!}{%" if resize else ""
    end = "}" if resize else ""
    lines = [r"\begin{table}[t]", r"\centering", r"\small", start]
    lines.extend(
        [
            rf"\begin{{tabular}}{{{alignment}}}",
            r"\toprule",
            " & ".join(latex_escape(cell) for cell in headers) + r" \\",
            r"\midrule",
        ]
    )
    for row in rows:
        lines.append(" & ".join(latex_escape(cell) for cell in row) + r" \\")
    lines.extend([r"\bottomrule", r"\end{tabular}", end, rf"\caption{{{caption}}}", rf"\label{{{label}}}", r"\end{table}"])
    write_text(path, "\n".join(line for line in lines if line != ""))


@lru_cache(maxsize=32)
def get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    font_names = (
        ("C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/calibrib.ttf", "DejaVuSans-Bold.ttf")
        if bold
        else ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/calibri.ttf", "DejaVuSans.ttf")
    )
    for font_name in font_names:
        try:
            return ImageFont.truetype(font_name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def hex_color(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))


def text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def draw_centered(draw: ImageDraw.ImageDraw, xy: tuple[float, float], text: str, font: ImageFont.ImageFont, fill: str = TEXT) -> None:
    width, height = text_size(draw, text, font)
    draw.text((xy[0] - width / 2, xy[1] - height / 2), text, font=font, fill=fill)


def draw_right(draw: ImageDraw.ImageDraw, xy: tuple[float, float], text: str, font: ImageFont.ImageFont, fill: str = TEXT) -> None:
    width, height = text_size(draw, text, font)
    draw.text((xy[0] - width, xy[1] - height / 2), text, font=font, fill=fill)


def make_canvas(title: str, subtitle: str, width: int = 3200, height: int = 1900) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.text((120, 78), title, font=get_font(58, True), fill=hex_color(ACCENT_BLUE))
    draw.text((120, 157), subtitle, font=get_font(28), fill=hex_color("#4B5563"))
    return image, draw


def save_figure(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, dpi=(300, 300), optimize=True)


def nice_upper(maximum: float) -> float:
    if maximum <= 0:
        return 1.0
    exponent = math.floor(math.log10(maximum))
    fraction = maximum / (10 ** exponent)
    for candidate in (1, 2, 2.5, 5, 10):
        if fraction <= candidate:
            return candidate * (10 ** exponent)
    return 10 ** (exponent + 1)


def draw_linear_axis(
    draw: ImageDraw.ImageDraw,
    left: int,
    top: int,
    right: int,
    bottom: int,
    maximum: float,
    decimal: bool = False,
    upper_override: float | None = None,
) -> tuple[float, callable]:
    upper = upper_override if upper_override is not None else nice_upper(maximum * 1.12 if maximum else 1)
    for tick_index in range(6):
        value = upper * tick_index / 5
        y = bottom - (bottom - top) * tick_index / 5
        draw.line((left, y, right, y), fill=hex_color(GRID), width=2)
        label = f"{value:.2f}" if decimal else fmt_compact(value)
        draw_right(draw, (left - 18, y), label, get_font(21), fill="#4B5563")
    draw.line((left, top, left, bottom), fill=hex_color("#6B7280"), width=3)
    draw.line((left, bottom, right, bottom), fill=hex_color("#6B7280"), width=3)

    def scale(value: float) -> float:
        return bottom - (value / upper) * (bottom - top)

    return upper, scale


def draw_log_axis(
    draw: ImageDraw.ImageDraw,
    left: int,
    top: int,
    right: int,
    bottom: int,
    values: Sequence[float],
) -> callable:
    positive = [value for value in values if value > 0]
    lower_power = math.floor(math.log10(min(positive)))
    upper_power = math.ceil(math.log10(max(positive)))
    lower = 10 ** lower_power
    upper = 10 ** upper_power
    for power in range(lower_power, upper_power + 1):
        value = 10 ** power
        y = bottom - (math.log10(value) - lower_power) / (upper_power - lower_power or 1) * (bottom - top)
        draw.line((left, y, right, y), fill=hex_color(GRID), width=2)
        draw_right(draw, (left - 18, y), f"{value:,}", get_font(21), fill="#4B5563")
    draw.line((left, top, left, bottom), fill=hex_color("#6B7280"), width=3)
    draw.line((left, bottom, right, bottom), fill=hex_color("#6B7280"), width=3)

    def scale(value: float) -> float:
        return bottom - (math.log10(max(value, lower)) - lower_power) / (upper_power - lower_power or 1) * (bottom - top)

    return scale


def draw_bar_panel(
    draw: ImageDraw.ImageDraw,
    rect: tuple[int, int, int, int],
    labels: Sequence[str],
    values: Sequence[float],
    title: str,
    color: str,
    log_scale: bool = False,
) -> None:
    left, top, right, bottom = rect
    draw.text((left, top - 65), title, font=get_font(30, True), fill=hex_color(TEXT))
    chart_top = top + 15
    chart_bottom = bottom - 115
    chart_left = left + 110
    chart_right = right - 20
    scale = (
        draw_log_axis(draw, chart_left, chart_top, chart_right, chart_bottom, values)
        if log_scale
        else draw_linear_axis(draw, chart_left, chart_top, chart_right, chart_bottom, max(values))[1]
    )
    span = chart_right - chart_left
    step = span / len(labels)
    bar_width = min(step * 0.60, 75)
    for index, (label, value) in enumerate(zip(labels, values)):
        center = chart_left + step * (index + 0.5)
        y = scale(value)
        draw.rectangle((center - bar_width / 2, y, center + bar_width / 2, chart_bottom), fill=hex_color(color))
        number_label = fmt_compact(value)
        draw_centered(draw, (center, y - 28), number_label, get_font(17), fill="#374151")
        draw_centered(draw, (center, chart_bottom + 45), label, get_font(18), fill="#374151")


def static_corpus_figure(static: pd.DataFrame, target: Path) -> None:
    labels = {
        "7ep": "7ep",
        "acmeair": "AcmeAir",
        "cargo-tracker": "Cargo",
        "daytrader7": "DayTrader",
        "Jokul": "Jokul",
        "jpetstore": "JPetStore",
        "pet-clinic": "PetClinic",
        "TNTConcept": "TNT",
    }
    rows = static.copy()
    rows["display"] = rows["project"].map(labels).fillna(rows["project"])
    image, draw = make_canvas(
        "Source-corpus structural profile",
        "Per-project metrics from the source-based static analysis; eLOC uses a logarithmic axis.",
        width=3200,
        height=1550,
    )
    left, top, bottom, panel_width, gap = 120, 320, 1390, 900, 110
    draw_bar_panel(
        draw,
        (left, top, left + panel_width, bottom),
        rows["display"].tolist(),
        rows["effective_source_lines"].astype(float).tolist(),
        "Effective source lines (log scale)",
        "#1677B8",
        log_scale=True,
    )
    draw_bar_panel(
        draw,
        (left + panel_width + gap, top, left + 2 * panel_width + gap, bottom),
        rows["display"].tolist(),
        rows["analyzed_type_files"].astype(float).tolist(),
        "Analyzed Java type files",
        "#D97706",
    )
    draw_bar_panel(
        draw,
        (left + 2 * (panel_width + gap), top, left + 3 * panel_width + 2 * gap, bottom),
        rows["display"].tolist(),
        rows["internal_package_dependencies"].astype(float).tolist(),
        "Distinct internal package edges",
        "#6658B8",
    )
    save_figure(image, target)


def stable_jitter(value: str, scale: float = 0.22) -> float:
    return (((sum((index + 1) * ord(char) for index, char in enumerate(value)) % 1000) / 999.0) - 0.5) * scale


def grouped_dot_panel(
    draw: ImageDraw.ImageDraw,
    rect: tuple[int, int, int, int],
    data: pd.DataFrame,
    metric: str,
    title: str,
    decimal: bool = False,
    upper_override: float | None = None,
) -> None:
    left, top, right, bottom = rect
    draw.text((left, top - 52), title, font=get_font(27, True), fill=hex_color(TEXT))
    chart_left, chart_right = left + 115, right - 20
    chart_top, chart_bottom = top + 8, bottom - 100
    values = finite_series(data, metric)
    _, scale = draw_linear_axis(
        draw,
        chart_left,
        chart_top,
        chart_right,
        chart_bottom,
        float(values.max()),
        decimal=decimal,
        upper_override=upper_override,
    )
    groups = [(provider, template) for provider in PROVIDER_ORDER for template in TEMPLATE_ORDER]
    step = (chart_right - chart_left) / len(groups)
    for group_index, (provider, template) in enumerate(groups):
        subset = data[(data["provider"] == provider) & (data["prompt_template"] == template)]
        center = chart_left + step * (group_index + 0.5)
        color = hex_color(PROVIDER_COLORS[provider])
        for _, row in subset.iterrows():
            value = number(row[metric])
            if value is None:
                continue
            x = center + stable_jitter(str(row["project_name"]) + provider + template, step)
            y = scale(value)
            draw.ellipse((x - 10, y - 10, x + 10, y + 10), fill=color, outline="white", width=2)
        if not subset.empty:
            median = float(finite_series(subset, metric).median())
            y = scale(median)
            draw.line((center - 29, y, center + 29, y), fill=hex_color(TEXT), width=5)
        label = f"{PROVIDER_SHORT[provider]}-{TEMPLATE_SHORT[template]}"
        draw_centered(draw, (center, chart_bottom + 42), label, get_font(19), fill="#374151")


def direct_architecture_figure(direct: pd.DataFrame, target: Path) -> None:
    image, draw = make_canvas(
        "Structural metrics of valid direct-generation outputs",
        "One dot represents one system-condition output; horizontal bars are medians. O, A, and D denote providers; ZS and FS denote prompt templates.",
    )
    panels = [
        ((120, 330, 1570, 970), "service_count", "Service count", False, None),
        ((1660, 330, 3110, 970), "valid_communication_count", "Valid communication count", False, None),
        ((120, 1190, 1570, 1830), "communication_density", "Communication density", True, 1.0),
        ((1660, 1190, 3110, 1830), "average_responsibility_word_count", "Mean responsibility words", False, None),
    ]
    for rect, metric, title, decimal, upper_override in panels:
        grouped_dot_panel(draw, rect, direct, metric, title, decimal, upper_override)
    legend_y = 1030
    x = 235
    for provider in PROVIDER_ORDER:
        color = hex_color(PROVIDER_COLORS[provider])
        draw.ellipse((x, legend_y, x + 22, legend_y + 22), fill=color)
        draw.text((x + 32, legend_y - 4), PROVIDER_LABELS[provider], font=get_font(20), fill="#374151")
        x += 280
    save_figure(image, target)


def repository_relative(path: Path | None) -> str:
    """Return a readable repository-relative path when possible."""
    if path is None:
        return ""
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except (OSError, ValueError):
        return str(path)


def calculated_mask(frame: pd.DataFrame) -> pd.Series:
    return frame["architecture_status"].fillna("").astype(str).str.startswith("calculated")


def reconcile_and_calculate_current_outputs() -> dict[str, object]:
    """Calculate article data from current outputs without changing any source artifact.

    Four TNTConcept metadata rows refer to canonical ``run_1.csv`` paths that
    are absent even though their condition folders each contain exactly one
    named CSV artifact. For an article-only, read-only calculation, this
    function selects that unambiguous sibling CSV in memory and emits a log.
    It never writes into ``outputs/`` or ``comparison_outputs/`` and includes
    only direct-generation runs in the article materials.
    """
    descriptors, issues = discover_run_descriptors(OUTPUTS_DIR)
    descriptors = [
        descriptor
        for descriptor in descriptors
        if descriptor.identity.approach == "direct"
    ]
    issues = [
        issue
        for issue in issues
        if not issue.get("approach") or issue.get("approach") == "direct"
    ]
    reconciliation_rows: list[dict[str, str]] = []
    evaluated_runs = []

    for descriptor in descriptors:
        expected_csv = descriptor.selected_csv_path()
        if (
            descriptor.metadata_record_count
            and descriptor.metadata_status == "success"
            and expected_csv is not None
            and not expected_csv.exists()
        ):
            candidates = sorted(
                path for path in expected_csv.parent.glob("*.csv") if path.is_file()
            )
            if len(candidates) == 1:
                recovered_csv = candidates[0]
                descriptor.metadata_output_path = recovered_csv
                reconciliation_rows.append(
                    {
                        **descriptor.identity.as_row(),
                        "reconciliation_status": "recovered_unique_sibling_csv",
                        "metadata_selected_csv_path": repository_relative(expected_csv),
                        "article_selected_csv_path": repository_relative(recovered_csv),
                        "reason": (
                            "Latest successful metadata selected a missing canonical path; "
                            "the same condition folder contained exactly one CSV artifact."
                        ),
                    }
                )

        evaluated, run_issues = evaluate_run(
            descriptor,
            min_responsibility_words=5,
        )
        evaluated_runs.append(evaluated)
        issues.extend(run_issues)

    architecture_rows = [evaluated.architecture_row for evaluated in evaluated_runs]
    process_rows = [evaluated.process_row for evaluated in evaluated_runs]
    metric_rows = build_metric_rows(architecture_rows, process_rows)
    approach_summary_rows = build_approach_metric_summary(metric_rows)
    stability_rows = build_stability_rows(evaluated_runs)

    return {
        "architecture": pd.DataFrame(architecture_rows),
        "process": pd.DataFrame(process_rows),
        "metric_long": pd.DataFrame(metric_rows),
        "approach_summary": pd.DataFrame(approach_summary_rows),
        "stability": pd.DataFrame(stability_rows),
        "issues": pd.DataFrame(issues),
        "reconciliation": pd.DataFrame(reconciliation_rows),
        "descriptor_count": len(descriptors),
    }


def write_results_section(
    target: Path,
    static: pd.DataFrame,
    architecture: pd.DataFrame,
    process: pd.DataFrame,
    issues: pd.DataFrame,
    direct: pd.DataFrame,
    reconciliation: pd.DataFrame,
    descriptor_count: int,
) -> None:
    discovered = descriptor_count
    valid = int(calculated_mask(architecture).sum())
    direct_valid = len(direct)
    failed = architecture[~calculated_mask(architecture)]
    warning_count = len(issues)
    issue_type_counts = (
        issues["issue_type"].value_counts().to_dict()
        if not issues.empty and "issue_type" in issues
        else {}
    )
    static_projects = len(static)
    direct_summary = {metric: stat_summary(finite_series(direct, metric)) for metric in ARCHITECTURE_METRICS}
    min_static = static.loc[static["effective_source_lines"].idxmin()]
    max_static = static.loc[static["effective_source_lines"].idxmax()]
    if failed.empty:
        calculation_status = "Every included direct-generation run resolved to a calculable final architecture CSV."
    else:
        calculation_status = (
            f"{len(failed)} run records did not yield a calculable final architecture CSV and were excluded from architecture aggregates."
        )
    if reconciliation.empty:
        reconciliation_status = "No metadata-path reconciliation was required."
    else:
        reconciliation_status = (
            f"{len(reconciliation)} TNTConcept metadata paths selected missing canonical filenames; each was reconciled in memory to the unique CSV in the same condition folder. "
            "The source metadata and output artifacts were not modified."
        )
    integrity_metrics = (
        "malformed_service_row_count",
        "duplicate_service_name_count",
        "duplicate_communication_count",
        "invalid_communication_target_count",
        "self_communication_count",
        "short_responsibility_count",
    )
    integrity_total = sum(
        int(pd.to_numeric(architecture[metric], errors="coerce").fillna(0).sum())
        for metric in integrity_metrics
    )
    if integrity_total == 0:
        integrity_status = (
            "The structural parser found no malformed service rows, duplicate service names or communications, invalid communication targets, self-communications, or responsibilities shorter than the configured five-word threshold."
        )
    else:
        integrity_status = (
            f"The structural parser recorded {integrity_total} integrity flags across malformed rows, duplicate names or communications, invalid targets, self-communications, and short responsibilities."
        )
    if issue_type_counts and set(issue_type_counts) == {"duplicate_metadata_run"}:
        audit_notice_status = (
            f"All {warning_count} audit notices were repeated metadata records; the latest successful record was selected for each logical run."
        )
    else:
        audit_notice_status = (
            f"The calculation retained {warning_count} discovery, metadata, architecture, or trace notices for auditability."
        )

    lines = [
        r"\section{Results}",
        r"\label{sec:results}",
        "",
        "This section reports descriptive results derived from the repository artifacts available in the analyzed snapshot. "
        "The measures characterize direct-generation architecture CSVs, their execution traces, and the static source corpus. "
        "They do not constitute human-quality ratings or an external validity assessment.",
        "",
        r"\subsection{Result availability and artifact quality}",
        "",
        f"A read-only artifact calculation discovered {discovered} direct-generation run identities. Of these, {valid} yielded a calculable final architecture CSV. "
        f"{calculation_status} {reconciliation_status} "
        f"{audit_notice_status}",
        "",
        integrity_status,
        "",
        r"\input{docs/article_results/tables/tab_result_availability.tex}",
        "",
        "The direct-generation snapshot has one run per project--provider--prompt condition. Therefore, there are no within-condition run pairs from which to estimate output stability; the corresponding Jaccard stability values are unavailable rather than zero. No human-evaluation data are included in this replication package.",
        "",
        r"\subsection{Static characteristics of the source corpus}",
        "",
        f"The static analysis covers {static_projects} Java systems. The corpus ranges from {min_static['project']} ({fmt(min_static['effective_source_lines'], 0)} effective source lines) to {max_static['project']} ({fmt(max_static['effective_source_lines'], 0)} effective source lines), providing a marked variation in codebase scale and package-level structure. "
        "Figure~\\ref{fig:static-corpus-profile} visualizes the variation in effective source lines, analyzed type files, and distinct internal package dependencies. "
        "The full corpus profile is reported in Table~\\ref{tab:static-corpus}.",
        "",
        r"\begin{figure*}[t]",
        r"\centering",
        r"\includegraphics[width=\textwidth]{docs/article_results/figures/fig_static_corpus_profile.png}",
        r"\caption{Static source-corpus profile. Effective source lines are shown on a logarithmic scale; package edges are distinct internal import-derived relations.}",
        r"\label{fig:static-corpus-profile}",
        r"\end{figure*}",
        "",
        r"\input{docs/article_results/tables/tab_static_corpus.tex}",
        "",
        "Supplementary Tables~S3--S5 report the remaining source-structure, code-volume, heuristic-classification, and import-derived dependency fields for all eight systems.",
        "",
        r"\subsection{Structural properties of direct-generation outputs}",
        "",
        f"Across the {direct_valid} valid direct-generation outputs, the median service count was {fmt(direct_summary['service_count']['median'], 0)} "
        f"(IQR {fmt(direct_summary['service_count']['q1'], 0)}--{fmt(direct_summary['service_count']['q3'], 0)}), and the median number of valid directed communications was {fmt(direct_summary['valid_communication_count']['median'], 0)} "
        f"(IQR {fmt(direct_summary['valid_communication_count']['q1'], 0)}--{fmt(direct_summary['valid_communication_count']['q3'], 0)}). "
        f"Median communication density was {fmt(direct_summary['communication_density']['median'], 2)}, while the median responsibility length was {fmt(direct_summary['average_responsibility_word_count']['median'], 1)} words per service. "
        "These values summarize output structure and lexical detail; they do not establish that a larger or denser architecture is better.",
        "",
        r"\input{docs/article_results/tables/tab_direct_by_condition.tex}",
        "",
        r"\begin{figure*}[t]",
        r"\centering",
        r"\includegraphics[width=\textwidth]{docs/article_results/figures/fig_direct_architecture_metrics.png}",
        r"\caption{Distribution of structural metrics across valid direct-generation outputs. Each point is one system-condition output, and horizontal bars denote medians within a provider--prompt condition.}",
        r"\label{fig:direct-architecture-metrics}",
        r"\end{figure*}",
        "",
        "Supplementary Table~S1 provides the complete descriptive summary for every calculated architecture metric, while Supplementary Table~S2 provides all direct-generation trace metrics. The row-level exports accompanying this section preserve every calculated value, including malformed rows, invalid targets, isolation, reciprocity, responsibility-length, lexical-overlap, retry, duration, prompt-volume, role, and final-snapshot measures.",
        "",
        r"\subsection{Interpretation boundary}",
        "",
        "The reported measures are deliberately descriptive. Structural regularity, prompt volume, and trace duration are useful audit signals, but none independently demonstrates requirement coverage, domain correctness, implementability, or superiority. "
        "Those claims require the planned expert-review data and, where appropriate, independent architectural validation.",
    ]
    write_text(target, "\n".join(lines))


def build_tables(
    tables: Path,
    static: pd.DataFrame,
    architecture: pd.DataFrame,
    process: pd.DataFrame,
    issues: pd.DataFrame,
    direct: pd.DataFrame,
    reconciliation: pd.DataFrame,
    descriptor_count: int,
) -> None:
    failed = architecture[~calculated_mask(architecture)]
    availability_rows = [
        ("Discovered run identities", descriptor_count, "Current outputs/ inventory"),
        ("Calculable final architecture CSVs", int(calculated_mask(architecture).sum()), "Included in architecture metrics"),
        ("Valid direct outputs", len(direct), "Eight projects; included in direct aggregates"),
        ("In-memory metadata-path recoveries", len(reconciliation), "Unique sibling CSV selected; source artifacts unchanged"),
        ("Outputs without calculable final CSV", len(failed), "Excluded from architecture aggregates"),
        ("Recorded audit notices", len(issues), "Discovery, metadata, architecture, or trace notices retained"),
        ("Within-condition stability pairs", 0, "One run per condition; stability Jaccard unavailable"),
    ]
    write_latex_table(
        tables / "tab_result_availability.tex",
        ("Artifact status", "Count", "Scope or treatment"),
        availability_rows,
        "Availability of calculated artifacts in the analyzed repository snapshot.",
        "tab:result-availability",
        alignment="lrl",
    )

    static_rows = []
    for _, row in static.iterrows():
        static_rows.append(
            (
                row["project"],
                fmt(row["build_files"], 0),
                fmt(row["analyzed_type_files"], 0),
                fmt(row["packages"], 0),
                fmt(row["methods"], 0),
                fmt(row["effective_source_lines"], 0),
                fmt(row["internal_imports"], 0),
                fmt(row["internal_package_dependencies"], 0),
                fmt(row["entrypoints"], 0),
            )
        )
    write_latex_table(
        tables / "tab_static_corpus.tex",
        ("Project", "Build files", "Type files", "Packages", "Methods", "eLOC", "Internal imports", "Internal edges", "Entrypoints"),
        static_rows,
        "Static source-corpus profile. Type files are analyzed Java type files; internal edges are distinct import-derived package relations.",
        "tab:static-corpus",
        alignment="lrrrrrrrr",
        resize=True,
    )

    static_structure_rows = []
    for _, row in static.iterrows():
        static_structure_rows.append(
            (
                row["project"],
                row["build_tools"],
                fmt(row["build_files"], 0),
                fmt(row["declared_submodules"], 0),
                fmt(row["modules_with_parse_errors"], 0),
                fmt(row["source_roots"], 0),
                fmt(row["java_files"], 0),
                fmt(row["java_descriptor_files"], 0),
                fmt(row["analyzed_type_files"], 0),
                fmt(row["packages"], 0),
                fmt(row["package_roots"], 0),
                fmt(row["classes"], 0),
            )
        )
    write_latex_table(
        tables / "tab_S3_static_structure.tex",
        (
            "Project",
            "Build tools",
            "Build files",
            "Declared modules",
            "Parse-error modules",
            "Source roots",
            "Java files",
            "Descriptor files",
            "Type files",
            "Packages",
            "Package roots",
            "Classes",
        ),
        static_structure_rows,
        "Supplementary static-analysis structure metrics for every project. Descriptor files are Java files without a detected type declaration.",
        "tab:s3-static-structure",
        alignment="llrrrrrrrrrr",
        resize=True,
    )

    static_code_rows = []
    for _, row in static.iterrows():
        static_code_rows.append(
            (
                row["project"],
                fmt(row["entrypoints"], 0),
                fmt(row["main_classes"], 0),
                fmt(row["test_classes"], 0),
                fmt(row["ui_test_classes"], 0),
                fmt(row["methods"], 0),
                fmt(row["public_methods"], 0),
                fmt(row["source_lines"], 0),
                fmt(row["effective_source_lines"], 0),
                fmt(row["inferred_roles"], 0),
                fmt(row["type_kinds"], 0),
            )
        )
    write_latex_table(
        tables / "tab_S4_static_code_volume.tex",
        (
            "Project",
            "Entrypoints",
            "Main classes",
            "Test classes",
            "UI-test classes",
            "Methods",
            "Public methods",
            "Source lines",
            "eLOC",
            "Inferred roles",
            "Type kinds",
        ),
        static_code_rows,
        "Supplementary static-analysis code-volume and heuristic-classification metrics. Entrypoints and roles are heuristic source-based indicators.",
        "tab:s4-static-code-volume",
        alignment="lrrrrrrrrrr",
        resize=True,
    )

    static_dependency_rows = []
    for _, row in static.iterrows():
        static_dependency_rows.append(
            (
                row["project"],
                fmt(row["imports"], 0),
                fmt(row["internal_imports"], 0),
                fmt(row["external_imports"], 0),
                fmt(row["package_dependency_edges"], 0),
                fmt(row["internal_package_dependencies"], 0),
                fmt(row["external_package_dependencies"], 0),
                fmt(row["internal_package_dependency_occurrences"] + row["external_package_dependency_occurrences"], 0),
                fmt(row["internal_package_dependency_occurrences"], 0),
                fmt(row["external_package_dependency_occurrences"], 0),
                fmt(row["external_dependency_roots"], 0),
            )
        )
    write_latex_table(
        tables / "tab_S5_static_dependencies.tex",
        (
            "Project",
            "Imports",
            "Internal imports",
            "External imports",
            "Package edges",
            "Internal edges",
            "External edges",
            "Edge occurrences",
            "Internal occurrences",
            "External occurrences",
            "External roots",
        ),
        static_dependency_rows,
        "Supplementary import-derived dependency metrics. Package edges are distinct directed package relations; occurrences count imports that induce an inter-package edge.",
        "tab:s5-static-dependencies",
        alignment="lrrrrrrrrrr",
        resize=True,
    )

    condition_rows = []
    for provider in PROVIDER_ORDER:
        for template in TEMPLATE_ORDER:
            subset = direct[(direct["provider"] == provider) & (direct["prompt_template"] == template)]
            condition_rows.append(
                (
                    PROVIDER_LABELS[provider],
                    template.replace("_", "-"),
                    len(subset),
                    median_iqr(finite_series(subset, "service_count"), 1),
                    median_iqr(finite_series(subset, "valid_communication_count"), 1),
                    median_iqr(finite_series(subset, "communication_density"), 2),
                    median_iqr(finite_series(subset, "average_responsibility_word_count"), 1),
                )
            )
    write_latex_table(
        tables / "tab_direct_by_condition.tex",
        ("Provider", "Prompt", "n", "Services", "Valid links", "Density", "Responsibility words"),
        condition_rows,
        "Descriptive structural statistics for valid direct-generation outputs. Entries are median [Q1, Q3] across available systems.",
        "tab:direct-by-condition",
        alignment="llrrrrr",
    )

    architecture_rows = []
    for metric in ARCHITECTURE_METRICS:
        values = finite_series(direct, metric)
        summary = stat_summary(values)
        decimal = 2 if any(token in metric for token in ("ratio", "density", "jaccard", "stddev", "average")) else 1
        architecture_rows.append(
            (
                DISPLAY_NAMES.get(metric, metric),
                summary["n"],
                fmt(summary["mean"], decimal),
                fmt(summary["median"], decimal),
                fmt(summary["std"], decimal),
                fmt(summary["min"], decimal),
                fmt(summary["max"], decimal),
            )
        )
    write_latex_table(
        tables / "tab_S1_direct_architecture_metrics.tex",
        ("Metric", "n", "Mean", "Median", "SD", "Min", "Max"),
        architecture_rows,
        "Supplementary descriptive summary of all calculated architecture metrics across valid direct-generation outputs.",
        "tab:s1-direct-architecture-metrics",
        alignment="lrrrrrr",
    )

    process_rows = []
    direct_process = process[
        (process["approach"] == "direct") & (process["run_status"] == "success")
    ]
    for metric in PROCESS_METRICS:
        values = finite_series(direct_process, metric)
        if not len(values):
            continue
        decimal = 2 if "ratio" in metric else 1
        process_rows.append(
            (
                DISPLAY_NAMES.get(metric, metric),
                len(values),
                fmt(values.median(), decimal),
                fmt(values.min(), decimal),
                fmt(values.max(), decimal),
            )
        )
    write_latex_table(
        tables / "tab_S2_direct_process_metrics.tex",
        ("Direct-generation trace metric", "n", "Median", "Min", "Max"),
        process_rows,
        "Supplementary trace-metric summary across all successful direct-generation runs.",
        "tab:s2-direct-process-metrics",
        alignment="lrrrr",
        resize=True,
    )


def build_manifest(
    target: Path,
    static: pd.DataFrame,
    architecture: pd.DataFrame,
    process: pd.DataFrame,
    issues: pd.DataFrame,
    reconciliation: pd.DataFrame,
    descriptor_count: int,
) -> None:
    payload = {
        "source_files": {
            "static_project_summaries": str(STATIC_SUMMARIES.relative_to(ROOT).as_posix()),
            "generation_metadata": "outputs/metadata.csv",
            "generation_outputs": "outputs/",
            "calculation_module": "src/comparison/evaluate.py",
        },
        "counts": {
            "static_projects": int(len(static)),
            "discovered_runs": int(descriptor_count),
            "calculable_architectures": int(calculated_mask(architecture).sum()),
            "valid_direct_architectures": int(((architecture["approach"] == "direct") & calculated_mask(architecture)).sum()),
            "process_rows": int(len(process)),
            "comparison_issue_rows": int(len(issues)),
            "metadata_path_recoveries": int(len(reconciliation)),
        },
        "artifact_reconciliation": {
            "performed_in_memory_only": True,
            "rule": (
                "For a latest-successful metadata row whose selected CSV path is missing, use a CSV only when the same condition folder contains exactly one CSV artifact."
            ),
            "log": "data/reconciliation_log.csv",
        },
        "interpretation": {
            "scope": "This article-results bundle intentionally includes direct-generation runs only.",
            "stability": "One run per condition prevents within-condition stability estimation.",
            "human_review": "No human-evaluation data are included in this replication package.",
            "statistics": "All article summaries are descriptive; no hypothesis tests are computed.",
        },
    }
    write_text(target, json.dumps(payload, indent=2))


def write_supplementary_tables_wrapper(target: Path) -> None:
    write_text(
        target,
        r"""\section{Supplementary Results Tables}
\label{sec:supplementary-results-tables}

\input{docs/article_results/tables/tab_S1_direct_architecture_metrics.tex}
\input{docs/article_results/tables/tab_S2_direct_process_metrics.tex}
\input{docs/article_results/tables/tab_S3_static_structure.tex}
\input{docs/article_results/tables/tab_S4_static_code_volume.tex}
\input{docs/article_results/tables/tab_S5_static_dependencies.tex}
""",
    )


def build_readme(target: Path) -> None:
    write_text(
        target,
        r"""# Article Results Materials

This directory is generated from the already-calculated artifacts in
`analysis-results/static-analysis/` and `outputs/`. It does not rerun LLM
generation, modify source outputs, or overwrite `comparison_outputs/`.

## Article assets

- `Results.tex` is the English Results section.
- `Supplementary_Tables.tex` includes the five supplementary LaTeX tables.
- `tables/` contains main-text and supplementary LaTeX tables.
- `figures/` contains 300-DPI PNG figures.
- `data/` preserves the row-level calculated CSV exports used by the section.
- `results_manifest.json` records scope and interpretation constraints.

Use `\usepackage{booktabs}` and `\usepackage{graphicx}` in the article
preamble. The paths in `Results.tex` assume compilation from the repository
root; adjust them if the article is elsewhere.

## Important scope limitations

This bundle reports direct-generation outputs only. Each condition has one
run, so within-condition stability is not estimable. It does not include
human-evaluation data.

## Current-artifact reconciliation

The article calculation performs a documented in-memory reconciliation for a
small number of successful metadata rows whose canonical CSV filename is
absent. A replacement is accepted only if the same condition directory
contains exactly one CSV artifact. `data/reconciliation_log.csv` records each
such selection. This rule does not change `outputs/`, its metadata, or the
older `comparison_outputs/` reports.

## Regeneration

```powershell
.\.venv\Scripts\python.exe scripts\generate_article_results.py
```
""",
    )


def remove_retired_agent_material(output: Path) -> None:
    """Remove only known agent-derived files from a prior generated bundle."""
    retired_paths = (
        "figures/fig_paired_7ep_workflow.png",
        "figures/fig_paired_7ep_similarity.png",
        "tables/tab_paired_7ep.tex",
        "tables/tab_agent_trace_7ep.tex",
        "tables/tab_S2_process_metrics.tex",
        "data/reconciled_pairing_report.csv",
        "data/reconciled_paired_architecture_similarity.csv",
        "data/reconciled_paired_metric_deltas.csv",
        "data/reconciled_paired_metric_summary.csv",
    )
    output_root = output.resolve()
    for relative_path in retired_paths:
        target = (output / relative_path).resolve()
        try:
            target.relative_to(output_root)
        except ValueError as error:
            raise RuntimeError(f"Refusing to remove a file outside the article output directory: {target}") from error
        if target.is_file():
            target.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR, help="Directory for generated article materials.")
    args = parser.parse_args()
    output = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    figures = output / "figures"
    tables = output / "tables"
    data = output / "data"
    for directory in (output, figures, tables, data):
        directory.mkdir(parents=True, exist_ok=True)
    remove_retired_agent_material(output)

    required = {
        "static summaries": STATIC_SUMMARIES,
        "generation metadata": OUTPUTS_DIR / "metadata.csv",
    }
    missing = [f"{name}: {path}" for name, path in required.items() if not path.exists()]
    if missing:
        raise FileNotFoundError("Required calculated artifacts are missing:\n" + "\n".join(missing))

    static = pd.read_csv(STATIC_SUMMARIES)
    calculated = reconcile_and_calculate_current_outputs()
    architecture = calculated["architecture"]
    process = calculated["process"]
    issues = calculated["issues"]
    reconciliation = calculated["reconciliation"]
    descriptor_count = int(calculated["descriptor_count"])
    direct = architecture[(architecture["approach"] == "direct") & calculated_mask(architecture)].copy()

    # Preserve every calculated row used for the article, while keeping the
    # repository's original result locations untouched.
    exports = {
        "static_project_summaries.csv": static,
        "reconciled_architecture_metrics_by_run.csv": architecture,
        "reconciled_process_metrics_by_run.csv": process,
        "reconciled_run_metrics_long.csv": calculated["metric_long"],
        "reconciled_approach_metric_summary.csv": calculated["approach_summary"],
        "reconciled_stability_by_approach.csv": calculated["stability"],
        "calculation_issues.csv": issues,
        "reconciliation_log.csv": reconciliation,
    }
    for file_name, frame in exports.items():
        frame.to_csv(data / file_name, index=False)

    static_corpus_figure(static, figures / "fig_static_corpus_profile.png")
    direct_architecture_figure(direct, figures / "fig_direct_architecture_metrics.png")
    build_tables(
        tables,
        static,
        architecture,
        process,
        issues,
        direct,
        reconciliation,
        descriptor_count,
    )
    write_results_section(
        output / "Results.tex",
        static,
        architecture,
        process,
        issues,
        direct,
        reconciliation,
        descriptor_count,
    )
    build_manifest(
        output / "results_manifest.json",
        static,
        architecture,
        process,
        issues,
        reconciliation,
        descriptor_count,
    )
    write_supplementary_tables_wrapper(output / "Supplementary_Tables.tex")
    build_readme(output / "README.md")

    print(json.dumps({
        "output_dir": str(output),
        "figures": 2,
        "tables": 8,
        "discovered_run_identities": descriptor_count,
        "valid_direct_outputs": len(direct),
        "metadata_path_recoveries": len(reconciliation),
    }, indent=2))


if __name__ == "__main__":
    main()
