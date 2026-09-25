"""Create English requirement overlays used by prompt generation.

The script never changes the original requirement CSVs.  It preserves every
source row and identifier, and writes English categories and descriptions to
``requirements_en/<project>.json``.  Existing investigator-reviewed overlays
are reused where available.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import requests

from src.project_loader import discover_projects
from src.prompt_builder import find_column
from src.requirements_loader import RequirementsData, load_requirements


OUTPUT_DIR = ROOT / "requirements_en"


def build_overlay(
    project_name: str,
    requirements: RequirementsData,
    *,
    existing: dict[str, object] | None = None,
    text_limit: int | None = None,
) -> dict[str, object]:
    category_column = find_column(requirements.columns, ["categoria", "category"])
    identifier_column = find_column(requirements.columns, ["identificacao", "identification", "id", "codigo"])
    description_column = find_column(
        requirements.columns,
        ["descricao", "description", "requirement", "texto"],
    )
    if not identifier_column or not description_column:
        raise ValueError(f"Could not identify requirement fields in {requirements.file_path}.")

    existing_rows = existing.get("requirements", []) if isinstance(existing, dict) else []
    if len(existing_rows) != requirements.row_count:
        existing_rows = [{} for _ in requirements.rows]

    translated_rows = []
    untranslated: list[tuple[int, str, str]] = []
    for index, row in enumerate(requirements.rows):
        previous = existing_rows[index] if isinstance(existing_rows[index], dict) else {}
        translated = {
            "identifier": row[identifier_column].strip(),
            "category": str(previous.get("category", "")).strip(),
            "description": str(previous.get("description", "")).strip(),
        }
        for field, source_value in (
            ("category", row.get(category_column, "") if category_column else ""),
            ("description", row[description_column]),
        ):
            if translated[field] or not source_value.strip():
                continue
            if text_limit is not None and len(untranslated) >= text_limit:
                continue
            untranslated.append((index, field, source_value.strip()))
        translated_rows.append(translated)

    for (index, field, _), translated in zip(
        untranslated,
        translate_batch(untranslated),
        strict=True,
    ):
        translated_rows[index][field] = translated

    complete = all(
        row["description"] and (not source.get(category_column, "").strip() or row["category"])
        for source, row in zip(requirements.rows, translated_rows, strict=True)
    )
    return {"complete": complete, "requirements": translated_rows}


def translate_batch(items: list[tuple[int, str, str]]) -> list[str]:
    """Translate several requirements at once while retaining deterministic markers."""

    translations: dict[tuple[int, str], str] = {}
    chunk: list[tuple[int, str, str]] = []
    chunk_size = 0
    for item in items:
        marker = marker_for(*item[:2])
        item_size = len(marker) + len(item[2]) + 2
        if chunk and chunk_size + item_size > 4000:
            translations.update(translate_chunk(chunk))
            chunk, chunk_size = [], 0
            time.sleep(0.5)
        chunk.append(item)
        chunk_size += item_size
    if chunk:
        translations.update(translate_chunk(chunk))
    return [translations[(index, field)] for index, field, _ in items]


def marker_for(index: int, field: str) -> str:
    return f"[[PROMPT-{index:03d}-{field.upper()}]]"


def translate_chunk(items: list[tuple[int, str, str]]) -> dict[tuple[int, str], str]:
    source = "\n".join(
        f"{marker_for(index, field)} {value}" for index, field, value in items
    )
    response = requests.get(
        "https://translate.google.com/m",
        params={"sl": "pt", "tl": "en", "q": source},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=60,
    )
    response.raise_for_status()
    match = re.search(
        r'<div class="result-container">(.*?)</div>',
        response.text,
        flags=re.DOTALL,
    )
    if not match:
        raise ValueError("Google Translate did not return a translated result.")
    translated = html.unescape(re.sub(r"<[^>]+>", "", match.group(1)))
    markers = list(re.finditer(r"\[\[PROMPT-(\d+)-(CATEGORY|DESCRIPTION)\]\]", translated))
    if len(markers) != len(items):
        raise ValueError("Google Translate did not preserve every requirement marker.")

    result: dict[tuple[int, str], str] = {}
    for position, current in enumerate(markers):
        following = markers[position + 1].start() if position + 1 < len(markers) else len(translated)
        key = (int(current.group(1)), current.group(2).lower())
        result[key] = translated[current.end() : following].strip()
    expected = {(index, field) for index, field, _ in items}
    if set(result) != expected or any(not value for value in result.values()):
        raise ValueError("Google Translate returned incomplete requirement text.")
    return result


def validate_overlay(requirements: RequirementsData, overlay: object, path: Path) -> None:
    if not isinstance(overlay, dict) or not isinstance(overlay.get("requirements"), list):
        raise ValueError(f"Invalid English overlay: {path}")
    identifier_column = find_column(requirements.columns, ["identificacao", "identification", "id", "codigo"])
    translated = overlay["requirements"]
    if not identifier_column or len(translated) != requirements.row_count:
        raise ValueError(f"English overlay does not match {requirements.file_path}: {path}")
    source_ids = [row[identifier_column].strip() for row in requirements.rows]
    translated_ids = [str(row.get("identifier", "")).strip() for row in translated]
    if source_ids != translated_ids:
        raise ValueError(f"English overlay does not preserve identifier order: {path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Regenerate existing overlay files.")
    parser.add_argument("--project", help="Translate only one discovered project.")
    parser.add_argument(
        "--text-limit",
        type=int,
        help="Maximum untranslated category/description fields to process in this run.",
    )
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(exist_ok=True)
    projects = discover_projects(
        ROOT / "systems",
        ROOT / "analysis-results/static-analysis",
        [".csv", ".json", ".txt", ".md"],
    )
    for project in projects:
        if args.project and project.name != args.project:
            continue
        target = OUTPUT_DIR / f"{project.name}.json"
        existing = json.loads(target.read_text(encoding="utf-8")) if target.exists() else None
        if target.exists() and existing.get("complete") is not False and not args.force:
            print(f"Skipping {project.name}: {target.relative_to(ROOT)} already exists")
            continue
        overlay = build_overlay(
            project.name,
            load_requirements(project.requirements_csv),
            existing=None if args.force else existing,
            text_limit=args.text_limit,
        )
        target.write_text(json.dumps(overlay, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {target.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
