from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..project_loader import locate_requirements_csv
from .metric_models import ProjectArtifacts


MAPPING_FILE_HINTS = ("mapping", "map")
RUNTIME_LOG_HINTS = ("runtime", "execution", "trace", "request", "access")
PROCESS_LOG_HINTS = ("process", "event", "xes", "trace")


def scan_project_artifacts(
    project_name: str,
    systems_dir: Path,
    static_analysis_root: Path,
) -> ProjectArtifacts:
    system_dir = systems_dir / project_name
    static_analysis_dir = static_analysis_root / project_name
    if not system_dir.exists():
        raise FileNotFoundError(f"Project directory not found: {system_dir}")

    available_data: set[str] = set()
    notes: list[str] = []

    requirements_df = None
    try:
        requirements_path = locate_requirements_csv(system_dir)
        requirements_df = read_csv_flexible(requirements_path)
        available_data.add("requirements")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"Requirements not loaded: {exc}")

    static_classes_df = None
    static_package_metrics_df = None
    static_package_dependencies_df = None
    static_entrypoints_df = None
    endpoints_df = None
    entities_df = None
    structural_dependencies_df = None

    if static_analysis_dir.exists():
        classes_path = static_analysis_dir / "classes.csv"
        package_metrics_path = static_analysis_dir / "package_metrics.csv"
        package_dependencies_path = static_analysis_dir / "package_dependencies.csv"
        entrypoints_path = static_analysis_dir / "entrypoints.csv"

        if classes_path.exists():
            static_classes_df = read_csv_flexible(classes_path)
            available_data.add("static_classes")
            endpoints_df = derive_endpoints(static_classes_df)
            if not endpoints_df.empty:
                available_data.add("public_interfaces")
                available_data.add("endpoints")
            entities_df = derive_entities(static_classes_df)
            if not entities_df.empty:
                available_data.add("entities")

        if package_metrics_path.exists():
            static_package_metrics_df = read_csv_flexible(package_metrics_path)
            available_data.add("static_package_metrics")

        if package_dependencies_path.exists():
            static_package_dependencies_df = read_csv_flexible(package_dependencies_path)
            available_data.add("static_package_dependencies")
            structural_dependencies_df = normalize_dependency_frame(static_package_dependencies_df)
            if not structural_dependencies_df.empty:
                available_data.add("structural_dependency_graph")

        if entrypoints_path.exists():
            static_entrypoints_df = read_csv_flexible(entrypoints_path)
            available_data.add("static_entrypoints")
            if endpoints_df is None:
                endpoints_df = static_entrypoints_df.copy()
            elif not static_entrypoints_df.empty:
                endpoints_df = pd.concat([endpoints_df, static_entrypoints_df], ignore_index=True)

    component_to_service_mapping_df = detect_mapping_dataframe(
        roots=[system_dir, static_analysis_dir] if static_analysis_dir.exists() else [system_dir],
        component_keywords=("class", "component", "artifact", "package", "module"),
    )
    if component_to_service_mapping_df is not None and not component_to_service_mapping_df.empty:
        available_data.add("component_to_service_mapping")

    requirement_to_service_mapping_df = detect_mapping_dataframe(
        roots=[system_dir, static_analysis_dir] if static_analysis_dir.exists() else [system_dir],
        component_keywords=("requirement", "feature", "use_case", "story"),
    )
    if requirement_to_service_mapping_df is not None and not requirement_to_service_mapping_df.empty:
        available_data.add("requirement_to_service_mapping")

    runtime_log_files = discover_log_files(system_dir, RUNTIME_LOG_HINTS)
    if runtime_log_files:
        available_data.add("runtime_logs")

    process_log_files = discover_log_files(system_dir, PROCESS_LOG_HINTS)
    if process_log_files:
        available_data.add("process_logs")

    return ProjectArtifacts(
        project_name=project_name,
        system_dir=system_dir,
        static_analysis_dir=static_analysis_dir if static_analysis_dir.exists() else None,
        available_data=available_data,
        requirements_df=requirements_df,
        static_classes_df=static_classes_df,
        static_package_metrics_df=static_package_metrics_df,
        static_package_dependencies_df=static_package_dependencies_df,
        static_entrypoints_df=static_entrypoints_df,
        endpoints_df=endpoints_df,
        entities_df=entities_df,
        structural_dependencies_df=structural_dependencies_df,
        component_to_service_mapping_df=component_to_service_mapping_df,
        requirement_to_service_mapping_df=requirement_to_service_mapping_df,
        runtime_log_files=runtime_log_files,
        process_log_files=process_log_files,
        notes=notes,
    )


def read_csv_flexible(path: Path) -> pd.DataFrame:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError:
            continue
    return pd.read_csv(path, encoding="utf-8", encoding_errors="replace")


def derive_endpoints(static_classes_df: pd.DataFrame) -> pd.DataFrame:
    if "role" not in static_classes_df.columns:
        return pd.DataFrame()

    roles = static_classes_df["role"].fillna("").astype(str).str.lower()
    return static_classes_df[roles.eq("controller")].copy()


def derive_entities(static_classes_df: pd.DataFrame) -> pd.DataFrame:
    if "role" not in static_classes_df.columns:
        return pd.DataFrame()

    roles = static_classes_df["role"].fillna("").astype(str).str.lower()
    return static_classes_df[roles.eq("domain")].copy()


def normalize_dependency_frame(dataframe: pd.DataFrame) -> pd.DataFrame:
    column_map = {}
    for column in dataframe.columns:
        lowered = column.strip().lower()
        if lowered in {"source_package", "source", "from"}:
            column_map[column] = "source"
        elif lowered in {"target_package", "target", "to"}:
            column_map[column] = "target"
        elif lowered == "count":
            column_map[column] = "count"
        elif lowered == "category":
            column_map[column] = "category"

    normalized = dataframe.rename(columns=column_map)
    required = {"source", "target"}
    if not required.issubset(set(normalized.columns)):
        return pd.DataFrame()

    normalized = normalized.copy()
    normalized["source"] = normalized["source"].fillna("").astype(str).str.strip()
    normalized["target"] = normalized["target"].fillna("").astype(str).str.strip()
    if "count" not in normalized.columns:
        normalized["count"] = 1
    return normalized[(normalized["source"] != "") & (normalized["target"] != "")]


def detect_mapping_dataframe(roots: list[Path], component_keywords: tuple[str, ...]) -> pd.DataFrame | None:
    for root in roots:
        if root is None or not root.exists():
            continue
        for candidate in sorted(root.rglob("*.csv")):
            if not any(hint in candidate.name.lower() for hint in MAPPING_FILE_HINTS):
                continue
            try:
                dataframe = read_csv_flexible(candidate)
            except Exception:  # noqa: BLE001
                continue
            normalized_columns = {column: column.strip().lower() for column in dataframe.columns}
            service_column = find_column(normalized_columns, ("microservice", "service"))
            component_column = find_column(normalized_columns, component_keywords)
            if service_column and component_column:
                result = dataframe[[component_column, service_column]].copy()
                result.columns = ["component_name", "microservice_name"]
                result["component_name"] = result["component_name"].fillna("").astype(str).str.strip()
                result["microservice_name"] = (
                    result["microservice_name"].fillna("").astype(str).str.strip()
                )
                result = result[
                    (result["component_name"] != "") & (result["microservice_name"] != "")
                ]
                if not result.empty:
                    return result
    return None


def find_column(normalized_columns: dict[str, str], keywords: tuple[str, ...]) -> str | None:
    for original, normalized in normalized_columns.items():
        if any(keyword in normalized for keyword in keywords):
            return original
    return None


def discover_log_files(system_dir: Path, hints: tuple[str, ...]) -> list[Path]:
    matched: list[Path] = []
    for candidate in system_dir.rglob("*"):
        if not candidate.is_file():
            continue
        name = candidate.name.lower()
        if candidate.suffix.lower() not in {".log", ".txt", ".csv", ".json", ".xes"}:
            continue
        if any(hint in name for hint in hints):
            matched.append(candidate)
    return sorted(matched)
