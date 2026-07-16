from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal

import pandas as pd


MetricStatus = Literal[
    "calculated",
    "calculated_fallback",
    "not_applicable",
    "missing_required_data",
    "error",
]
MetricLevel = Literal["run_level", "service_level"]


@dataclass(slots=True)
class DecompositionResult:
    project_name: str
    provider: str
    model_name: str
    prompt_template: str
    run_id: str
    csv_path: Path
    dataframe: pd.DataFrame
    valid_rows: pd.DataFrame
    service_names: list[str]
    unique_service_names: list[str]
    edges: set[tuple[str, str]]
    incoming_counts: dict[str, int]
    outgoing_counts: dict[str, int]
    responsibility_word_counts: dict[str, int]
    warnings: list[str] = field(default_factory=list)

    @property
    def service_count(self) -> int:
        return len(self.service_names)


@dataclass(slots=True)
class ProjectArtifacts:
    project_name: str
    system_dir: Path
    static_analysis_dir: Path | None
    available_data: set[str]
    requirements_df: pd.DataFrame | None = None
    static_classes_df: pd.DataFrame | None = None
    static_package_metrics_df: pd.DataFrame | None = None
    static_package_dependencies_df: pd.DataFrame | None = None
    static_entrypoints_df: pd.DataFrame | None = None
    endpoints_df: pd.DataFrame | None = None
    entities_df: pd.DataFrame | None = None
    structural_dependencies_df: pd.DataFrame | None = None
    component_to_service_mapping_df: pd.DataFrame | None = None
    requirement_to_service_mapping_df: pd.DataFrame | None = None
    runtime_log_files: list[Path] = field(default_factory=list)
    process_log_files: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EvaluationContext:
    result: DecompositionResult
    artifacts: ProjectArtifacts
    min_service_size: int
    max_service_size: int

    @property
    def available_data(self) -> set[str]:
        data = set(self.artifacts.available_data)
        data.update(
            {
                "llm_output_csv",
                "llm_output_services",
                "llm_output_communications",
                "llm_output_responsibilities",
            }
        )
        return data


@dataclass(slots=True)
class MetricRecord:
    metric_name: str
    metric_category: str
    metric_value: float | int | str | None
    status: MetricStatus
    formula_version: str
    notes: str = ""
    microservice_name: str | None = None


@dataclass(slots=True)
class MetricDefinition:
    name: str
    category: str
    description: str
    required_data: tuple[str, ...]
    output_level: MetricLevel
    formula_version: str
    calculator: Callable[[EvaluationContext], list[MetricRecord]]
