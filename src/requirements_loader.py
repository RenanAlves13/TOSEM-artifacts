from __future__ import annotations

import csv
import io
import unicodedata
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class RequirementsData:
    file_path: Path
    columns: list[str]
    rows: list[dict[str, str]]

    @property
    def row_count(self) -> int:
        return len(self.rows)


def load_requirements(csv_path: Path) -> RequirementsData:
    text = read_text(csv_path)
    delimiter = detect_delimiter(text)
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)

    columns = [column.strip() for column in (reader.fieldnames or []) if column and column.strip()]
    rows: list[dict[str, str]] = []
    for raw_row in reader:
        row: dict[str, str] = {}
        for key, value in raw_row.items():
            if key is None:
                continue
            clean_key = key.strip()
            row[clean_key] = (value or "").strip()
        if any(value for value in row.values()):
            rows.append(row)

    if not columns:
        raise ValueError(f"Could not infer columns from requirements CSV: {csv_path}")

    return RequirementsData(file_path=csv_path, columns=columns, rows=rows)


def read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def detect_delimiter(text: str) -> str:
    sample = "\n".join(text.splitlines()[:10])
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;|\t").delimiter
    except csv.Error:
        if sample.count(";") > sample.count(","):
            return ";"
        return ","


def normalize_header(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = "".join(char for char in normalized if not unicodedata.combining(char))
    return "".join(char.lower() if char.isalnum() else "_" for char in ascii_only)
