from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from .requirements_loader import RequirementsData, normalize_header


TRANSLATIONS_DIR = Path(__file__).resolve().parents[1] / "requirements_en"


def load_english_requirements(
    requirements: RequirementsData,
    *,
    project_name: str,
) -> RequirementsData:
    """Return the reviewed English requirement text for a known project.

    The source CSVs remain the authoritative, Portuguese-language evidence.  A
    versioned English overlay is used exclusively when composing model prompts,
    so every model receives the same translated requirements without changing
    the original corpus.
    """

    path = TRANSLATIONS_DIR / f"{project_name}.json"
    if not path.exists():
        return requirements

    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("complete") is False:
        return requirements
    translated_rows = payload.get("requirements")
    if not isinstance(translated_rows, list):
        raise ValueError(f"English requirements file {path} must contain a requirements list.")
    if len(translated_rows) != requirements.row_count:
        raise ValueError(
            f"English requirements file {path} has {len(translated_rows)} rows; "
            f"expected {requirements.row_count}."
        )

    identifier_column = find_field(
        requirements.columns,
        ["identificacao", "identification", "identifier", "codigo", "id"],
    )
    category_column = find_field(requirements.columns, ["categoria", "category"])
    description_column = find_field(
        requirements.columns,
        ["descricao", "description", "requirement", "texto"],
    )
    if not identifier_column or not description_column:
        raise ValueError(f"Could not identify requirement fields in {requirements.file_path}.")

    rows: list[dict[str, str]] = []
    for source, translated in zip(requirements.rows, translated_rows, strict=True):
        if not isinstance(translated, dict):
            raise ValueError(f"English requirements file {path} contains an invalid row.")
        if translated.get("identifier", "").strip() != source.get(identifier_column, "").strip():
            raise ValueError(f"English requirements file {path} does not preserve source identifiers.")

        row = dict(source)
        row[description_column] = str(translated.get("description", "")).strip()
        if category_column:
            row[category_column] = str(translated.get("category", "")).strip()
        rows.append(row)

    return replace(requirements, columns=["Category", "Identifier", "Description"], rows=[
        {
            "Category": row.get(category_column, "") if category_column else "",
            "Identifier": row.get(identifier_column, ""),
            "Description": row.get(description_column, ""),
        }
        for row in rows
    ])


def find_field(columns: list[str], candidates: list[str]) -> str | None:
    """Find either a source-language or already-translated requirement column."""

    normalized = {column: normalize_header(column) for column in columns}
    for candidate in candidates:
        if candidate in normalized.values():
            return next(column for column, value in normalized.items() if value == candidate)
    for candidate in candidates:
        if len(candidate) > 2:
            match = next(
                (column for column, value in normalized.items() if candidate in value),
                None,
            )
            if match:
                return match
    return None
