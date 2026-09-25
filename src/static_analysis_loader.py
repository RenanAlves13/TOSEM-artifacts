from __future__ import annotations

import csv
import io
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
                data.extras.append(
                    StaticArtifact(
                        path=path,
                        artifact_type="json",
                        content=parsed,
                        row_count=len(parsed) if isinstance(parsed, (dict, list)) else 0,
                    )
                )
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
            data.extras.append(
                StaticArtifact(
                    path=path,
                    artifact_type="text",
                    content=text,
                    row_count=len(text.splitlines()),
                )
            )

    return data


def load_csv_rows(path: Path) -> list[dict[str, str]]:
    text = read_text(path)
    reader = csv.DictReader(io.StringIO(text, newline=""))
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


def static_analysis_totals(data: StaticAnalysisData) -> dict[str, int | None]:
    """Return project-level totals, preferring loaded artifacts over summary fallbacks.

    Older static-analysis snapshots do not have every aggregate field. Returning
    ``None`` for those fields lets callers omit an unknown total instead of
    presenting it as zero.
    """

    summary = data.summary if isinstance(data.summary, dict) else {}
    summary_counts = summary.get("counts", {}) if isinstance(summary.get("counts"), dict) else {}

    def integer(value: Any) -> int | None:
        try:
            return int(float(str(value).strip()))
        except (TypeError, ValueError):
            return None

    def summary_total(field: str) -> int | None:
        return integer(summary_counts.get(field))

    def row_total(rows: list[dict[str, str]], field: str) -> int | None:
        if not rows:
            return None
        return sum(integer(row.get(field)) or 0 for row in rows)

    def rows_or_summary(
        rows: list[dict[str, str]], row_field: str, summary_field: str
    ) -> int | None:
        calculated = row_total(rows, row_field)
        return calculated if calculated is not None else summary_total(summary_field)

    def category_count(category: str) -> int | None:
        if not data.package_dependencies:
            return summary_total(f"{category}_package_dependencies")
        return sum(1 for row in data.package_dependencies if row.get("category") == category)

    def category_occurrences(category: str) -> int | None:
        if not data.package_dependencies:
            return summary_total(f"{category}_package_dependency_occurrences")
        return sum(
            integer(row.get("count")) or 0
            for row in data.package_dependencies
            if row.get("category") == category
        )

    type_kinds = {
        row.get("type_kind", "").strip()
        for row in data.classes
        if row.get("type_kind", "").strip()
    }
    roles = {
        row.get("role", "").strip()
        for row in data.classes
        if row.get("role", "").strip()
    }
    declared_submodules = sum(
        len([item for item in row.get("declared_submodules", "").split("|") if item])
        for row in data.modules
    )
    java_files = summary_total("java_files")
    analyzed_type_files = (
        len(data.classes) if data.classes else summary_total("analyzed_type_files")
    )
    package_root_rows = summary.get("package_roots", [])
    external_root_rows = summary.get("top_external_dependency_roots", [])
    package_roots = summary_total("package_roots")
    external_dependency_roots = summary_total("external_dependency_roots")
    if package_roots is None and isinstance(package_root_rows, list) and len(package_root_rows) < 10:
        package_roots = len(package_root_rows)
    if (
        external_dependency_roots is None
        and isinstance(external_root_rows, list)
        and len(external_root_rows) < 20
    ):
        external_dependency_roots = len(external_root_rows)
    java_descriptor_files = summary_total("java_descriptor_files")
    if java_descriptor_files is None and java_files is not None and analyzed_type_files is not None:
        java_descriptor_files = java_files - analyzed_type_files

    return {
        "build_files": len(data.modules) if data.modules else summary_total("build_files"),
        "declared_submodules": (
            declared_submodules if data.modules else summary_total("declared_submodules")
        ),
        "modules_with_parse_errors": (
            sum(1 for row in data.modules if row.get("parse_error", "").strip())
            if data.modules
            else summary_total("modules_with_parse_errors")
        ),
        "source_roots": summary_total("source_roots"),
        "java_files": java_files,
        "java_descriptor_files": java_descriptor_files,
        "analyzed_type_files": analyzed_type_files,
        "packages": (
            len(data.package_metrics) if data.package_metrics else summary_total("packages")
        ),
        "package_roots": package_roots,
        "classes": len(data.classes) if data.classes else summary_total("classes"),
        "entrypoints": (
            len(data.entrypoints) if data.entrypoints else summary_total("entrypoints")
        ),
        "main_classes": (
            sum(1 for row in data.classes if row.get("source_set") == "main")
            if data.classes
            else summary_total("main_classes")
        ),
        "test_classes": (
            sum(1 for row in data.classes if row.get("source_set") == "test")
            if data.classes
            else summary_total("test_classes")
        ),
        "ui_test_classes": (
            sum(1 for row in data.classes if row.get("source_set") == "ui-test")
            if data.classes
            else summary_total("ui_test_classes")
        ),
        "methods": rows_or_summary(data.classes, "method_count", "methods"),
        "public_methods": rows_or_summary(
            data.classes, "public_method_count", "public_methods"
        ),
        "source_lines": rows_or_summary(data.classes, "line_count", "source_lines"),
        "effective_source_lines": rows_or_summary(
            data.classes, "effective_line_count", "effective_source_lines"
        ),
        "imports": rows_or_summary(data.classes, "import_count", "imports"),
        "internal_imports": rows_or_summary(
            data.classes, "internal_import_count", "internal_imports"
        ),
        "external_imports": rows_or_summary(
            data.classes, "external_import_count", "external_imports"
        ),
        "internal_package_dependencies": category_count("internal"),
        "external_package_dependencies": category_count("external"),
        "package_dependency_edges": (
            len(data.package_dependencies)
            if data.package_dependencies
            else summary_total("package_dependency_edges")
        ),
        "internal_package_dependency_occurrences": category_occurrences("internal"),
        "external_package_dependency_occurrences": category_occurrences("external"),
        "external_dependency_roots": external_dependency_roots,
        "inferred_roles": len(roles) if data.classes else summary_total("inferred_roles"),
        "type_kinds": len(type_kinds) if data.classes else summary_total("type_kinds"),
    }
