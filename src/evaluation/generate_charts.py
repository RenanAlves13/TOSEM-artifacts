from __future__ import annotations

import argparse
import html
import math
from pathlib import Path

import pandas as pd


DEFAULT_CORE_METRICS = [
    "number_of_microservices",
    "number_of_communications",
    "communication_density",
    "isolated_services_ratio",
    "average_responsibility_length",
    "declared_inter_service_coupling",
    "non_extreme_distribution_ned",
]

SERIES_COLORS = [
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
    "#bcbd22",
    "#17becf",
]

STATUS_COLORS = {
    "calculated": "#2a9d8f",
    "calculated_fallback": "#e9c46a",
    "not_applicable": "#a8dadc",
    "missing_required_data": "#f4a261",
    "error": "#e63946",
}


def main() -> None:
    args = parse_args()

    evaluation_dir = Path(args.evaluation_dir)
    charts_dir = Path(args.charts_dir)

    metrics_by_run_df = pd.read_csv(evaluation_dir / "metrics_by_run.csv")
    applicability_df = pd.read_csv(evaluation_dir / "metric_applicability_report.csv")

    generated_files = generate_charts(
        metrics_by_run_df=metrics_by_run_df,
        applicability_df=applicability_df,
        charts_dir=charts_dir,
        project_name=args.project,
        provider=args.provider,
        model_name=args.model,
        prompt_template=args.prompt_template,
        core_metrics=args.metrics or DEFAULT_CORE_METRICS,
    )

    print(f"Generated {len(generated_files)} file(s) in {charts_dir.as_posix()}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate SVG charts from evaluation CSVs.")
    parser.add_argument("--evaluation-dir", default="evaluation_outputs")
    parser.add_argument("--charts-dir", default="evaluation_outputs/charts")
    parser.add_argument("--project")
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--prompt-template")
    parser.add_argument("--metrics", nargs="*")
    return parser.parse_args()


def generate_charts(
    *,
    metrics_by_run_df: pd.DataFrame,
    applicability_df: pd.DataFrame,
    charts_dir: Path,
    project_name: str | None = None,
    provider: str | None = None,
    model_name: str | None = None,
    prompt_template: str | None = None,
    core_metrics: list[str] | None = None,
) -> list[Path]:
    charts_dir.mkdir(parents=True, exist_ok=True)

    metrics_df = normalize_metrics_by_run(metrics_by_run_df)
    applicability = normalize_applicability(applicability_df)

    metrics_df = apply_run_filters(
        metrics_df,
        project_name=project_name,
        provider=provider,
        model_name=model_name,
        prompt_template=prompt_template,
    )
    applicability = apply_applicability_filters(
        applicability,
        project_name=project_name,
    )

    generated_files: list[Path] = []
    chart_sections: list[dict[str, object]] = []
    selected_metrics = core_metrics or DEFAULT_CORE_METRICS

    for metric_name in selected_metrics:
        metric_rows = metrics_df[
            (metrics_df["metric_name"] == metric_name)
            & (metrics_df["status"].isin(["calculated", "calculated_fallback"]))
            & (metrics_df["metric_value"].notna())
        ].copy()
        if metric_rows.empty:
            continue

        run_summary = (
            metric_rows.groupby(
                ["project_name", "provider", "model_name", "prompt_template"],
                as_index=False,
            )["metric_value"]
            .mean()
            .sort_values(["project_name", "provider", "model_name", "prompt_template"])
        )

        series_column = "series_name"
        run_summary[series_column] = run_summary.apply(
            lambda row: format_series_name(
                provider=str(row["provider"]),
                model_name=str(row["model_name"]),
                prompt_template=str(row["prompt_template"]),
            ),
            axis=1,
        )

        grouped_chart_path = charts_dir / f"run_metric_{slugify(metric_name)}.svg"
        write_grouped_bar_chart(
            path=grouped_chart_path,
            title=f"{metric_name} by project and configuration",
            dataframe=run_summary,
            category_column="project_name",
            series_column=series_column,
            value_column="metric_value",
            y_label=metric_name,
        )
        generated_files.append(grouped_chart_path)

        provider_summary = (
            metric_rows.groupby("provider", as_index=False)["metric_value"]
            .mean()
            .sort_values("provider")
        )
        provider_chart_path = charts_dir / f"provider_summary_{slugify(metric_name)}.svg"
        write_single_series_bar_chart(
            path=provider_chart_path,
            title=f"{metric_name} by provider",
            dataframe=provider_summary,
            category_column="provider",
            value_column="metric_value",
            y_label=metric_name,
            bar_color="#457b9d",
        )
        generated_files.append(provider_chart_path)

        prompt_summary = (
            metric_rows.groupby("prompt_template", as_index=False)["metric_value"]
            .mean()
            .sort_values("prompt_template")
        )
        prompt_chart_path = charts_dir / f"prompt_summary_{slugify(metric_name)}.svg"
        write_single_series_bar_chart(
            path=prompt_chart_path,
            title=f"{metric_name} by prompt template",
            dataframe=prompt_summary,
            category_column="prompt_template",
            value_column="metric_value",
            y_label=metric_name,
            bar_color="#2a9d8f",
        )
        generated_files.append(prompt_chart_path)

        chart_sections.append(
            {
                "title": metric_name,
                "description": "Comparison by project/configuration, provider summary, and prompt summary.",
                "files": [
                    grouped_chart_path.name,
                    provider_chart_path.name,
                    prompt_chart_path.name,
                ],
            }
        )

    if not applicability.empty:
        status_by_metric = (
            applicability.groupby(["metric_name", "status"]).size().unstack(fill_value=0)
        )
        if not status_by_metric.empty:
            applicability_metric_path = charts_dir / "applicability_by_metric.svg"
            write_stacked_bar_chart(
                path=applicability_metric_path,
                title="Metric applicability status by metric",
                dataframe=status_by_metric,
                y_label="project count",
                color_map=STATUS_COLORS,
            )
            generated_files.append(applicability_metric_path)

        status_by_project = (
            applicability.groupby(["project_name", "status"]).size().unstack(fill_value=0)
        )
        if not status_by_project.empty:
            applicability_project_path = charts_dir / "applicability_by_project.svg"
            write_stacked_bar_chart(
                path=applicability_project_path,
                title="Metric applicability status by project",
                dataframe=status_by_project,
                y_label="metric count",
                color_map=STATUS_COLORS,
            )
            generated_files.append(applicability_project_path)

        applicability_summary = charts_dir / "applicability_summary.html"
        write_applicability_summary_html(
            path=applicability_summary,
            applicability=applicability,
        )
        generated_files.append(applicability_summary)

        chart_sections.append(
            {
                "title": "Applicability",
                "description": "Status distribution of calculated and unavailable metrics.",
                "files": [
                    path.name
                    for path in generated_files
                    if path.name.startswith("applicability_")
                ],
            }
        )

    index_path = charts_dir / "index.html"
    write_dashboard_index(
        path=index_path,
        metrics_df=metrics_df,
        applicability_df=applicability,
        chart_sections=chart_sections,
        filters={
            "project": project_name,
            "provider": provider,
            "model": model_name,
            "prompt_template": prompt_template,
        },
    )
    generated_files.append(index_path)

    return generated_files


def normalize_metrics_by_run(dataframe: pd.DataFrame) -> pd.DataFrame:
    normalized = dataframe.copy()
    normalized["metric_value"] = pd.to_numeric(normalized["metric_value"], errors="coerce")
    for column in [
        "project_name",
        "provider",
        "model_name",
        "prompt_template",
        "run_id",
        "metric_name",
        "status",
    ]:
        normalized[column] = normalized[column].fillna("").astype(str).str.strip()
    return normalized


def normalize_applicability(dataframe: pd.DataFrame) -> pd.DataFrame:
    normalized = dataframe.copy()
    for column in [
        "project_name",
        "metric_name",
        "metric_category",
        "required_data",
        "available_data",
        "status",
        "notes",
    ]:
        normalized[column] = normalized[column].fillna("").astype(str).str.strip()
    return normalized


def apply_run_filters(
    dataframe: pd.DataFrame,
    *,
    project_name: str | None,
    provider: str | None,
    model_name: str | None,
    prompt_template: str | None,
) -> pd.DataFrame:
    filtered = dataframe.copy()
    if project_name:
        filtered = filtered[filtered["project_name"] == project_name]
    if provider:
        filtered = filtered[filtered["provider"] == provider]
    if model_name:
        filtered = filtered[filtered["model_name"] == model_name]
    if prompt_template:
        filtered = filtered[filtered["prompt_template"] == prompt_template]
    return filtered


def apply_applicability_filters(
    dataframe: pd.DataFrame,
    *,
    project_name: str | None,
) -> pd.DataFrame:
    filtered = dataframe.copy()
    if project_name:
        filtered = filtered[filtered["project_name"] == project_name]
    return filtered


def format_series_name(*, provider: str, model_name: str, prompt_template: str) -> str:
    return f"{provider} | {model_name} | {prompt_template}"


def write_grouped_bar_chart(
    *,
    path: Path,
    title: str,
    dataframe: pd.DataFrame,
    category_column: str,
    series_column: str,
    value_column: str,
    y_label: str,
) -> None:
    categories = sorted(dataframe[category_column].dropna().unique().tolist())
    series_names = sorted(dataframe[series_column].dropna().unique().tolist())
    value_map = {
        (str(row[category_column]), str(row[series_column])): float(row[value_column])
        for _, row in dataframe.iterrows()
    }
    series_data = [
        {
            "name": series_name,
            "color": SERIES_COLORS[index % len(SERIES_COLORS)],
            "values": [
                value_map.get((category, series_name))
                for category in categories
            ],
        }
        for index, series_name in enumerate(series_names)
    ]
    write_svg_grouped_bars(
        path=path,
        title=title,
        categories=categories,
        series_data=series_data,
        y_label=y_label,
    )


def write_single_series_bar_chart(
    *,
    path: Path,
    title: str,
    dataframe: pd.DataFrame,
    category_column: str,
    value_column: str,
    y_label: str,
    bar_color: str,
) -> None:
    categories = dataframe[category_column].astype(str).tolist()
    values = [float(value) for value in dataframe[value_column].tolist()]
    write_svg_grouped_bars(
        path=path,
        title=title,
        categories=categories,
        series_data=[{"name": y_label, "color": bar_color, "values": values}],
        y_label=y_label,
    )


def write_stacked_bar_chart(
    *,
    path: Path,
    title: str,
    dataframe: pd.DataFrame,
    y_label: str,
    color_map: dict[str, str],
) -> None:
    categories = [str(index) for index in dataframe.index.tolist()]
    series_data = []
    for column in dataframe.columns.tolist():
        series_data.append(
            {
                "name": str(column),
                "color": color_map.get(str(column), "#888888"),
                "values": [float(value) for value in dataframe[column].tolist()],
            }
        )
    write_svg_stacked_bars(
        path=path,
        title=title,
        categories=categories,
        series_data=series_data,
        y_label=y_label,
    )


def write_svg_grouped_bars(
    *,
    path: Path,
    title: str,
    categories: list[str],
    series_data: list[dict[str, object]],
    y_label: str,
) -> None:
    width = max(1200, 140 * max(len(categories), 1))
    height = 760
    margin_left = 90
    margin_right = 40
    margin_top = 120
    margin_bottom = 220
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom

    valid_values = [
        float(value)
        for series in series_data
        for value in list(series["values"])
        if value is not None and not pd.isna(value)
    ]
    max_value = max(valid_values, default=0.0)
    y_max = nice_upper_bound(max_value)

    group_width = plot_width / max(len(categories), 1)
    inner_group_width = group_width * 0.75
    bar_width = inner_group_width / max(len(series_data), 1)
    group_offset = (group_width - inner_group_width) / 2

    parts = [svg_header(width=width, height=height)]
    parts.append(svg_background(width=width, height=height))
    parts.append(svg_title(title=title, width=width))
    parts.append(svg_legend(series_data=series_data, start_x=margin_left, start_y=60, max_width=width - 120))

    for tick_index in range(6):
        tick_value = y_max * tick_index / 5
        y = margin_top + plot_height - (plot_height * tick_value / y_max if y_max else 0)
        parts.append(
            f'<line x1="{margin_left}" y1="{y:.2f}" x2="{width - margin_right}" y2="{y:.2f}" '
            'stroke="#d9d9d9" stroke-width="1" />'
        )
        parts.append(
            text_svg(
                x=margin_left - 10,
                y=y + 5,
                text=format_number(tick_value),
                anchor="end",
                size=12,
                fill="#444444",
            )
        )

    parts.append(
        f'<line x1="{margin_left}" y1="{margin_top + plot_height}" x2="{width - margin_right}" '
        f'y2="{margin_top + plot_height}" stroke="#444444" stroke-width="1.5" />'
    )
    parts.append(
        f'<line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{margin_top + plot_height}" '
        'stroke="#444444" stroke-width="1.5" />'
    )

    for category_index, category in enumerate(categories):
        group_start = margin_left + category_index * group_width + group_offset
        for series_index, series in enumerate(series_data):
            value = list(series["values"])[category_index]
            if value is None or pd.isna(value):
                continue

            numeric_value = float(value)
            bar_height = 0 if y_max == 0 else plot_height * numeric_value / y_max
            x = group_start + series_index * bar_width
            y = margin_top + plot_height - bar_height

            parts.append(
                f'<rect x="{x:.2f}" y="{y:.2f}" width="{max(bar_width - 2, 1):.2f}" height="{bar_height:.2f}" '
                f'fill="{series["color"]}" rx="2" ry="2" />'
            )
            parts.append(
                text_svg(
                    x=x + (bar_width / 2),
                    y=max(y - 6, margin_top - 4),
                    text=format_number(numeric_value),
                    anchor="middle",
                    size=10,
                    fill="#333333",
                )
            )

        label_x = margin_left + category_index * group_width + (group_width / 2)
        label_y = margin_top + plot_height + 20
        parts.append(
            f'<g transform="translate({label_x:.2f},{label_y:.2f}) rotate(45)">'
            f'{text_svg(x=0, y=0, text=category, anchor="start", size=12, fill="#333333")}'
            "</g>"
        )

    parts.append(
        text_svg(
            x=width / 2,
            y=height - 40,
            text=category_column_label(categories),
            anchor="middle",
            size=13,
            fill="#444444",
        )
    )
    parts.append(
        f'<g transform="translate(28,{margin_top + (plot_height / 2):.2f}) rotate(-90)">'
        f'{text_svg(x=0, y=0, text=y_label, anchor="middle", size=13, fill="#444444")}'
        "</g>"
    )
    parts.append("</svg>")
    path.write_text("".join(parts), encoding="utf-8")


def write_svg_stacked_bars(
    *,
    path: Path,
    title: str,
    categories: list[str],
    series_data: list[dict[str, object]],
    y_label: str,
) -> None:
    width = max(1400, 130 * max(len(categories), 1))
    height = 760
    margin_left = 90
    margin_right = 40
    margin_top = 120
    margin_bottom = 220
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom

    totals = []
    for category_index in range(len(categories)):
        totals.append(
            sum(
                float(list(series["values"])[category_index] or 0.0)
                for series in series_data
            )
        )
    y_max = nice_upper_bound(max(totals, default=0.0))
    group_width = plot_width / max(len(categories), 1)
    bar_width = group_width * 0.6

    parts = [svg_header(width=width, height=height)]
    parts.append(svg_background(width=width, height=height))
    parts.append(svg_title(title=title, width=width))
    parts.append(svg_legend(series_data=series_data, start_x=margin_left, start_y=60, max_width=width - 120))

    for tick_index in range(6):
        tick_value = y_max * tick_index / 5
        y = margin_top + plot_height - (plot_height * tick_value / y_max if y_max else 0)
        parts.append(
            f'<line x1="{margin_left}" y1="{y:.2f}" x2="{width - margin_right}" y2="{y:.2f}" '
            'stroke="#d9d9d9" stroke-width="1" />'
        )
        parts.append(
            text_svg(
                x=margin_left - 10,
                y=y + 5,
                text=format_number(tick_value),
                anchor="end",
                size=12,
                fill="#444444",
            )
        )

    parts.append(
        f'<line x1="{margin_left}" y1="{margin_top + plot_height}" x2="{width - margin_right}" '
        f'y2="{margin_top + plot_height}" stroke="#444444" stroke-width="1.5" />'
    )
    parts.append(
        f'<line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{margin_top + plot_height}" '
        'stroke="#444444" stroke-width="1.5" />'
    )

    for category_index, category in enumerate(categories):
        x = margin_left + category_index * group_width + (group_width - bar_width) / 2
        current_height = 0.0

        for series in series_data:
            value = float(list(series["values"])[category_index] or 0.0)
            if value <= 0:
                continue
            segment_height = 0 if y_max == 0 else plot_height * value / y_max
            y = margin_top + plot_height - current_height - segment_height
            parts.append(
                f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_width:.2f}" height="{segment_height:.2f}" '
                f'fill="{series["color"]}" rx="2" ry="2" />'
            )
            current_height += segment_height

        total_value = totals[category_index]
        parts.append(
            text_svg(
                x=x + (bar_width / 2),
                y=max(margin_top + plot_height - current_height - 6, margin_top - 4),
                text=format_number(total_value),
                anchor="middle",
                size=10,
                fill="#333333",
            )
        )
        label_x = margin_left + category_index * group_width + (group_width / 2)
        label_y = margin_top + plot_height + 20
        parts.append(
            f'<g transform="translate({label_x:.2f},{label_y:.2f}) rotate(45)">'
            f'{text_svg(x=0, y=0, text=category, anchor="start", size=12, fill="#333333")}'
            "</g>"
        )

    parts.append(
        f'<g transform="translate(28,{margin_top + (plot_height / 2):.2f}) rotate(-90)">'
        f'{text_svg(x=0, y=0, text=y_label, anchor="middle", size=13, fill="#444444")}'
        "</g>"
    )
    parts.append("</svg>")
    path.write_text("".join(parts), encoding="utf-8")


def write_dashboard_index(
    *,
    path: Path,
    metrics_df: pd.DataFrame,
    applicability_df: pd.DataFrame,
    chart_sections: list[dict[str, object]],
    filters: dict[str, str | None],
) -> None:
    run_count = (
        metrics_df[["project_name", "provider", "model_name", "prompt_template", "run_id"]]
        .drop_duplicates()
        .shape[0]
        if not metrics_df.empty
        else 0
    )
    project_count = metrics_df["project_name"].nunique() if not metrics_df.empty else 0
    metric_count = metrics_df["metric_name"].nunique() if not metrics_df.empty else 0
    applicability_status_counts = (
        applicability_df["status"].value_counts().sort_index().to_dict()
        if not applicability_df.empty
        else {}
    )

    filter_rows = "".join(
        f"<li><strong>{html.escape(key)}</strong>: {html.escape(value or 'all')}</li>"
        for key, value in filters.items()
    )
    status_rows = "".join(
        f"<li><strong>{html.escape(status)}</strong>: {count}</li>"
        for status, count in applicability_status_counts.items()
    )
    section_html = []
    for section in chart_sections:
        file_links = "".join(
            f'<li><a href="{html.escape(str(file_name))}">{html.escape(str(file_name))}</a></li>'
            for file_name in list(section["files"])
        )
        previews = "".join(
            (
                f'<div class="chart-card"><h3>{html.escape(str(file_name))}</h3>'
                f'<img src="{html.escape(str(file_name))}" alt="{html.escape(str(file_name))}" /></div>'
            )
            for file_name in list(section["files"])
            if str(file_name).endswith(".svg")
        )
        section_html.append(
            "<section>"
            f"<h2>{html.escape(str(section['title']))}</h2>"
            f"<p>{html.escape(str(section['description']))}</p>"
            f"<ul>{file_links}</ul>"
            f'<div class="chart-grid">{previews}</div>'
            "</section>"
        )

    document = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Evaluation Charts</title>
  <style>
    body {{
      font-family: "Segoe UI", Tahoma, sans-serif;
      margin: 0;
      padding: 32px;
      background: linear-gradient(180deg, #f7fbff 0%, #eef3f8 100%);
      color: #1f2933;
    }}
    h1, h2, h3 {{
      color: #102a43;
    }}
    section {{
      background: #ffffff;
      border-radius: 16px;
      padding: 24px;
      margin-bottom: 24px;
      box-shadow: 0 10px 30px rgba(16, 42, 67, 0.08);
    }}
    .summary {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
    }}
    .summary-card {{
      background: #f8fbff;
      border: 1px solid #d9e2ec;
      border-radius: 12px;
      padding: 16px;
    }}
    .chart-grid {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 16px;
      margin-top: 16px;
    }}
    .chart-card {{
      background: #fcfdff;
      border: 1px solid #e6edf5;
      border-radius: 12px;
      padding: 16px;
      overflow-x: auto;
    }}
    .chart-card img {{
      width: 100%;
      height: auto;
      display: block;
    }}
    ul {{
      line-height: 1.7;
    }}
  </style>
</head>
<body>
  <section>
    <h1>Evaluation Charts</h1>
    <p>Visual summary of the metrics generated by the evaluation pipeline.</p>
    <div class="summary">
      <div class="summary-card">
        <h3>Runs</h3>
        <p>{run_count}</p>
      </div>
      <div class="summary-card">
        <h3>Projects</h3>
        <p>{project_count}</p>
      </div>
      <div class="summary-card">
        <h3>Distinct metrics</h3>
        <p>{metric_count}</p>
      </div>
    </div>
  </section>
  <section>
    <h2>Filters</h2>
    <ul>{filter_rows}</ul>
  </section>
  <section>
    <h2>Applicability Status Summary</h2>
    <ul>{status_rows}</ul>
  </section>
  {''.join(section_html)}
</body>
</html>
"""
    path.write_text(document, encoding="utf-8")


def write_applicability_summary_html(*, path: Path, applicability: pd.DataFrame) -> None:
    grouped = (
        applicability.groupby(["metric_name", "status"]).size().unstack(fill_value=0)
        if not applicability.empty
        else pd.DataFrame()
    )
    table_html = grouped.to_html(classes="summary-table") if not grouped.empty else "<p>No data.</p>"
    document = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Applicability Summary</title>
  <style>
    body {{ font-family: "Segoe UI", Tahoma, sans-serif; margin: 24px; color: #1f2933; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px 10px; text-align: left; }}
    th {{ background: #f0f4f8; }}
  </style>
</head>
<body>
  <h1>Applicability Summary</h1>
  {table_html}
</body>
</html>
"""
    path.write_text(document, encoding="utf-8")


def category_column_label(categories: list[str]) -> str:
    if len(categories) <= 1:
        return "category"
    return "group"


def slugify(value: str) -> str:
    result = []
    for character in value.lower():
        if character.isalnum():
            result.append(character)
        else:
            result.append("_")
    collapsed = "".join(result)
    while "__" in collapsed:
        collapsed = collapsed.replace("__", "_")
    return collapsed.strip("_")


def nice_upper_bound(value: float) -> float:
    if value <= 0:
        return 1.0
    exponent = math.floor(math.log10(value))
    fraction = value / (10**exponent)
    if fraction <= 1:
        nice_fraction = 1
    elif fraction <= 2:
        nice_fraction = 2
    elif fraction <= 5:
        nice_fraction = 5
    else:
        nice_fraction = 10
    return nice_fraction * (10**exponent)


def svg_header(*, width: int, height: int) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
    )


def svg_background(*, width: int, height: int) -> str:
    return (
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff" />'
        f'<rect x="12" y="12" width="{width - 24}" height="{height - 24}" fill="none" '
        'stroke="#edf2f7" stroke-width="1" rx="14" ry="14" />'
    )


def svg_title(*, title: str, width: int) -> str:
    return text_svg(x=width / 2, y=30, text=title, anchor="middle", size=24, fill="#102a43", weight="700")


def svg_legend(*, series_data: list[dict[str, object]], start_x: int, start_y: int, max_width: int) -> str:
    parts: list[str] = []
    current_x = start_x
    current_y = start_y
    row_height = 22

    for series in series_data:
        label = str(series["name"])
        estimated_width = 22 + len(label) * 7
        if current_x + estimated_width > max_width:
            current_x = start_x
            current_y += row_height

        parts.append(
            f'<rect x="{current_x}" y="{current_y - 12}" width="14" height="14" '
            f'fill="{series["color"]}" rx="2" ry="2" />'
        )
        parts.append(
            text_svg(
                x=current_x + 20,
                y=current_y,
                text=label,
                anchor="start",
                size=12,
                fill="#334e68",
            )
        )
        current_x += estimated_width

    return "".join(parts)


def text_svg(
    *,
    x: float,
    y: float,
    text: str,
    anchor: str,
    size: int,
    fill: str,
    weight: str = "400",
) -> str:
    return (
        f'<text x="{x:.2f}" y="{y:.2f}" text-anchor="{anchor}" font-size="{size}" '
        f'font-family="Segoe UI, Tahoma, sans-serif" font-weight="{weight}" fill="{fill}">'
        f"{html.escape(text)}</text>"
    )


def format_number(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    if abs(value) >= 100:
        return f"{value:.1f}"
    if abs(value) >= 10:
        return f"{value:.2f}"
    return f"{value:.3f}".rstrip("0").rstrip(".")


if __name__ == "__main__":
    main()
