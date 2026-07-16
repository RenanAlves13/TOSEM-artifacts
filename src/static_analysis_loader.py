from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class StaticArtifact:
    path: Path
    artifact_type: str
    content: Any
    row_count: int = 0


@dataclass(slots=True)
class StaticAnalysisData:
    root_dir: Path
    files: list[Path]
    summary: dict[str, Any] | None = None
    modules: list[dict[str, str]] = field(default_factory=list)
    package_metrics: list[dict[str, str]] = field(default_factory=list)
    package_dependencies: list[dict[str, str]] = field(default_factory=list)
    entrypoints: list[dict[str, str]] = field(default_factory=list)
    classes: list[dict[str, str]] = field(default_factory=list)
    extras: list[StaticArtifact] = field(default_factory=list)


def load_static_analysis(static_analysis_dir: Path, files: list[Path]) -> StaticAnalysisData:
    data = StaticAnalysisData(root_dir=static_analysis_dir, files=files)

    for path in files:
        lower_name = path.name.lower()
        if path.suffix.lower() == ".json":
            parsed = json.loads(path.read_text(encoding="utf-8"))
            if lower_name == "summary.json":
                data.summary = parsed
            else:
                data.extras.append(StaticArtifact(path=path, artifact_type="json", content=parsed))
            continue

        if path.suffix.lower() == ".csv":
            rows = load_csv_rows(path)
            if lower_name == "modules.csv":
                data.modules = rows
            elif lower_name == "package_metrics.csv":
                data.package_metrics = rows
            elif lower_name == "package_dependencies.csv":
                data.package_dependencies = rows
            elif lower_name == "entrypoints.csv":
                data.entrypoints = rows
            elif lower_name == "classes.csv":
                data.classes = rows
            else:
                data.extras.append(
                    StaticArtifact(
                        path=path,
                        artifact_type="csv",
                        content=rows,
                        row_count=len(rows),
                    )
                )
            continue

        if path.suffix.lower() in {".txt", ".md"}:
            text = read_text(path)
            data.extras.append(StaticArtifact(path=path, artifact_type="text", content=text))

    return data


def load_csv_rows(path: Path) -> list[dict[str, str]]:
    text = read_text(path)
    reader = csv.DictReader(text.splitlines())
    rows: list[dict[str, str]] = []
    for row in reader:
        rows.append({(key or "").strip(): (value or "").strip() for key, value in row.items()})
    return rows


def read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")
