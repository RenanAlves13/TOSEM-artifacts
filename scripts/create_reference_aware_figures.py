#!/usr/bin/env python3
"""Create publication figures from direct-reference semantic metrics.

The figure summarizes the mean F1 across the zero-shot and few-shot direct
conditions for each provider and project.  It is intentionally separated into
service and directed-communication panels, since the two objects have distinct
denominators and should not be conflated.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "outputs" / "direct_reference_evaluation" / "direct_reference_semantic_metrics.csv"
OUTPUT = ROOT / "docs" / "article_results" / "figures" / "fig_reference_aware_project_f1.png"

PROJECTS = ("7ep", "acmeair", "cargo-tracker", "daytrader7", "Jokul", "jpetstore", "pet-clinic", "TNTConcept")
PROJECT_LABELS = {
    "7ep": "7ep", "acmeair": "AcmeAir", "cargo-tracker": "Cargo\nTracker",
    "daytrader7": "DayTrader7", "Jokul": "Jokul", "jpetstore": "JPetStore",
    "pet-clinic": "PetClinic", "TNTConcept": "TNTConcept",
}
PROVIDERS = ("DeepSeek", "OpenAI", "Claude")
COLORS = {"DeepSeek": "#2F75B5", "OpenAI": "#ED7D31", "Claude": "#70AD47"}


def load_means() -> dict[tuple[str, str], dict[str, float]]:
    values: dict[tuple[str, str], list[dict[str, float]]] = defaultdict(list)
    with INPUT.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            values[(row["project"], row["provider"])].append({
                "service_f1": float(row["service_f1"]),
                "communication_f1": float(row["communication_f1"]),
            })
    return {
        key: {
            metric: sum(item[metric] for item in rows) / len(rows)
            for metric in ("service_f1", "communication_f1")
        }
        for key, rows in values.items()
    }


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "arialbd.ttf" if bold else "arial.ttf"
    return ImageFont.truetype(Path("C:/Windows/Fonts") / name, size)


def draw_panel(
    draw: ImageDraw.ImageDraw,
    means: dict[tuple[str, str], dict[str, float]],
    metric: str,
    title: str,
    bounds: tuple[int, int, int, int],
) -> None:
    left, top, right, bottom = bounds
    title_font = font(26, bold=True)
    label_font = font(18)
    tiny_font = font(16)
    draw.text((left, top), title, fill="#1F1F1F", font=title_font)
    plot_top = top + 52
    plot_left = left + 58
    plot_right = right - 18
    plot_bottom = bottom - 76
    chart_height = plot_bottom - plot_top
    for tick in range(0, 6):
        value = tick / 5
        y = plot_bottom - value * chart_height
        draw.line((plot_left, y, plot_right, y), fill="#D9E2F3", width=2)
        anchor = "rs"
        draw.text((plot_left - 10, y + 5), f"{value:.1f}", fill="#595959", font=tiny_font, anchor=anchor)
    draw.line((plot_left, plot_top, plot_left, plot_bottom), fill="#595959", width=2)
    draw.line((plot_left, plot_bottom, plot_right, plot_bottom), fill="#595959", width=2)

    group_width = (plot_right - plot_left) / len(PROJECTS)
    bar_width = min(24, group_width * 0.22)
    offsets = (-bar_width * 1.2, 0, bar_width * 1.2)
    for project_index, project in enumerate(PROJECTS):
        center = plot_left + group_width * (project_index + 0.5)
        for provider_index, provider in enumerate(PROVIDERS):
            value = means[(project, provider)][metric]
            x0 = center + offsets[provider_index] - bar_width / 2
            x1 = x0 + bar_width
            y0 = plot_bottom - value * chart_height
            draw.rounded_rectangle((x0, y0, x1, plot_bottom), radius=3, fill=COLORS[provider])
        label = PROJECT_LABELS[project]
        draw.multiline_text((center, plot_bottom + 13), label, fill="#404040", font=label_font, anchor="ma", align="center", spacing=1)


def main() -> None:
    means = load_means()
    missing = [
        (project, provider)
        for project in PROJECTS for provider in PROVIDERS
        if (project, provider) not in means
    ]
    if missing:
        raise ValueError(f"Missing expected project/provider means: {missing}")

    image = Image.new("RGB", (1800, 860), "white")
    draw = ImageDraw.Draw(image)
    draw.text((900, 28), "Reference-aware F1 by project and provider", fill="#17365D", font=font(34, bold=True), anchor="ma")
    draw.text((900, 74), "Mean across zero-shot and few-shot direct-prompt outputs", fill="#595959", font=font(21), anchor="ma")
    draw_panel(draw, means, "service_f1", "(a) Service-boundary F1", (60, 140, 885, 805))
    draw_panel(draw, means, "communication_f1", "(b) Directed-communication F1", (915, 140, 1740, 805))
    legend_y = 118
    legend_x = 700
    for provider in PROVIDERS:
        draw.rounded_rectangle((legend_x, legend_y, legend_x + 24, legend_y + 24), radius=4, fill=COLORS[provider])
        draw.text((legend_x + 34, legend_y + 2), provider, fill="#404040", font=font(19))
        legend_x += 150

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUTPUT, format="PNG", optimize=True)
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
