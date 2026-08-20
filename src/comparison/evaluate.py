from __future__ import annotations

import argparse
import csv
import io
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .architecture_metrics import (
    ARCHITECTURE_NUMERIC_METRICS,
    ArchitectureMetrics,
    analyze_architecture_csv,
    mean_or_none,
    read_text,
)
from .trace_metrics import TRACE_NUMERIC_METRICS, analyze_trace, unavailable_trace_metrics


IDENTITY_FIELDS = (
    "project_name",
    "approach",
    "provider",
    "model_name",
    "prompt_template",
    "run_id",
)
ARCHITECTURE_OUTPUT_FIELDS = (
    *IDENTITY_FIELDS,
    "metadata_status",
    "metadata_timestamp",
    "metadata_record_count",
    "csv_path",
    "architecture_status",
    "architecture_warnings",
    *ARCHITECTURE_NUMERIC_METRICS,
)
PROCESS_OUTPUT_FIELDS = (
    *IDENTITY_FIELDS,
    "metadata_status",
    "metadata_timestamp",
    "metadata_record_count",
    "trace_path",
    "trace_status",
    "run_status",
    "trace_warnings",
    *TRACE_NUMERIC_METRICS,
    "roles",
    "critic_issue_categories",
    "critic_issue_severities",
)
METRIC_LONG_FIELDS = (
    *IDENTITY_FIELDS,
    "metric_group",
    "metric_name",
    "metric_value",
)
APPROACH_SUMMARY_FIELDS = (
    "project_name",
    "approach",
    "provider",
    "model_name",
    "prompt_template",
    "metric_group",
    "metric_name",
    "run_count",
    "mean",
    "median",
    "population_stddev",
    "minimum",
    "maximum",
)
PAIRING_FIELDS = (
    "project_name",
    "provider",
    "model_name",
    "prompt_template",
    "run_id",
    "pair_status",
    "direct_csv_path",
    "agent_csv_path",
    "direct_architecture_status",
    "agent_architecture_status",
    "pairing_warning",
)
PAIR_SIMILARITY_FIELDS = (
    "project_name",
    "provider",
    "model_name",
    "prompt_template",
    "run_id",
    "service_set_jaccard",
    "declared_communication_set_jaccard",
    "communication_set_jaccard",
    "agent_minus_direct_service_count",
    "agent_minus_direct_valid_communication_count",
)
PAIR_DELTA_FIELDS = (
    "project_name",
    "provider",
    "model_name",
    "prompt_template",
    "run_id",
    "metric_group",
    "metric_name",
    "direct_value",
    "agent_value",
    "agent_minus_direct",
    "relative_change_from_direct",
)
PAIR_SUMMARY_FIELDS = (
    "project_name",
    "provider",
    "model_name",
    "prompt_template",
    "metric_group",
    "metric_name",
    "paired_run_count",
    "direct_mean",
    "agent_mean",
    "mean_agent_minus_direct",
    "median_agent_minus_direct",
    "population_stddev_agent_minus_direct",
    "agent_higher_count",
    "equal_count",
    "agent_lower_count",
)
STABILITY_FIELDS = (
    "project_name",
    "approach",
    "provider",
    "model_name",
    "prompt_template",
    "run_count",
    "run_pair_count",
    "service_count_mean",
    "service_count_population_stddev",
    "valid_communication_count_mean",
    "valid_communication_count_population_stddev",
    "mean_service_set_jaccard",
    "mean_communication_set_jaccard",
)
ISSUE_FIELDS = (
    "source",
    "path",
    "project_name",
    "approach",
    "provider",
    "model_name",
    "prompt_template",
    "run_id",
    "issue_type",
    "message",
)


@dataclass(frozen=True, slots=True)
class RunIdentity:
    project_name: str
    approach: str
    provider: str
    model_name: str
    prompt_template: str
    run_id: str

    def storage_key(self) -> tuple[str, str, str, str, str, str]:
        return (
            self.project_name,
            self.approach,
            self.provider,
            safe_model_fragment(self.model_name),
            self.prompt_template,
            self.run_id,
        )

    def pair_key(self) -> tuple[str, str, str, str, str]:
        return (
            self.project_name,
            self.provider,
            safe_model_fragment(self.model_name),
            self.prompt_template,
            self.run_id,
        )

    def as_row(self) -> dict[str, str]:
        return {
            "project_name": self.project_name,
            "approach": self.approach,
            "provider": self.provider,
            "model_name": self.model_name,
            "prompt_template": self.prompt_template,
            "run_id": self.run_id,
        }


@dataclass(slots=True)
class MetadataRecord:
    identity: RunIdentity
    status: str
    timestamp: str
    error: str
    output_path: Path | None
    trace_path: Path | None
    row_number: int


@dataclass(slots=True)
class RunDescriptor:
    identity: RunIdentity
    metadata_status: str = "inferred"
    metadata_timestamp: str = ""
    metadata_error: str = ""
    metadata_record_count: int = 0
    metadata_output_path: Path | None = None
    metadata_trace_path: Path | None = None
    scanned_csv_paths: list[Path] = field(default_factory=list)
    scanned_trace_paths: list[Path] = field(default_factory=list)

    def selected_csv_path(self) -> Path | None:
        if self.metadata_record_count:
            if self.metadata_status != "success":
                return None
            return self.metadata_output_path
        return first_path(self.scanned_csv_paths)

    def selected_trace_path(self) -> Path | None:
        if self.metadata_trace_path is not None:
            return self.metadata_trace_path
        csv_path = self.selected_csv_path()
        if csv_path is not None:
            sibling = csv_path.with_suffix(".trace.jsonl")
            if sibling.exists():
                return sibling
        return first_path(self.scanned_trace_paths)

    def pairing_warnings(self) -> list[str]:
        warnings: list[str] = []
        if self.metadata_record_count > 1:
            warnings.append("multiple metadata records; latest successful record selected")
        if len(self.scanned_csv_paths) > 1:
            warnings.append("multiple CSV files discovered for the same run identity")
        if len(self.scanned_trace_paths) > 1:
            warnings.append("multiple trace files discovered for the same run identity")
        if self.metadata_record_count == 0:
            warnings.append(
                "run and model name inferred from path; metadata is absent and sanitized model names can be ambiguous"
            )
        return warnings


@dataclass(slots=True)
class EvaluatedRun:
    descriptor: RunDescriptor
    architecture_row: dict[str, Any]
    process_row: dict[str, Any]
    architecture: ArchitectureMetrics | None


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    discovered_run_count: int
    architecture_run_count: int
    paired_run_count: int
    issue_count: int
    comparison_dir: Path


def main() -> None:
    args = parse_args()
    result = run_comparison(
        outputs_dir=Path(args.outputs_dir),
        comparison_dir=Path(args.comparison_dir),
        project_name=args.project,
        provider=args.provider,
        model_name=args.model,
        prompt_template=args.prompt_template,
        run_id=args.run_id,
        min_responsibility_words=args.min_responsibility_words,
    )
    print(
        "Comparison finished: "
        f"runs={result.discovered_run_count}, "
        f"architectures={result.architecture_run_count}, "
        f"pairs={result.paired_run_count}, "
        f"issues={result.issue_count}."
    )
    print(f"Reports written to: {result.comparison_dir.as_posix()}")


def run_comparison(
    *,
    outputs_dir: Path,
    comparison_dir: Path,
    project_name: str | None = None,
    provider: str | None = None,
    model_name: str | None = None,
    prompt_template: str | None = None,
    run_id: str | None = None,
    min_responsibility_words: int = 5,
) -> ComparisonResult:
    """Discover runs, calculate metrics, and write comparison reports."""
    descriptors, issues = discover_run_descriptors(outputs_dir)
    descriptors = filter_descriptors(
        descriptors,
        project_name=project_name,
        provider=provider,
        model_name=model_name,
        prompt_template=prompt_template,
        run_id=run_id,
    )

    evaluated_runs: list[EvaluatedRun] = []
    for descriptor in descriptors:
        evaluated, run_issues = evaluate_run(
            descriptor,
            min_responsibility_words=min_responsibility_words,
        )
        evaluated_runs.append(evaluated)
        issues.extend(run_issues)

    architecture_rows = [evaluated.architecture_row for evaluated in evaluated_runs]
    process_rows = [evaluated.process_row for evaluated in evaluated_runs]
    metric_rows = build_metric_rows(architecture_rows, process_rows)
    pairing_rows, paired_runs, excluded_storage_keys = build_pairing_rows(evaluated_runs)
    aggregate_runs = [
        evaluated
        for evaluated in evaluated_runs
        if evaluated.descriptor.identity.storage_key() not in excluded_storage_keys
    ]
    aggregate_metric_rows = build_metric_rows(
        [evaluated.architecture_row for evaluated in aggregate_runs],
        [evaluated.process_row for evaluated in aggregate_runs],
    )
    approach_summary_rows = build_approach_metric_summary(aggregate_metric_rows)
    similarity_rows = build_pair_similarity_rows(paired_runs)
    paired_delta_rows = build_paired_metric_deltas(paired_runs)
    paired_summary_rows = build_paired_metric_summary(paired_delta_rows)
    stability_rows = build_stability_rows(aggregate_runs)

    comparison_dir.mkdir(parents=True, exist_ok=True)
    write_csv(comparison_dir / "architecture_metrics_by_run.csv", architecture_rows, ARCHITECTURE_OUTPUT_FIELDS)
    write_csv(comparison_dir / "process_metrics_by_run.csv", process_rows, PROCESS_OUTPUT_FIELDS)
    write_csv(comparison_dir / "run_metrics_long.csv", metric_rows, METRIC_LONG_FIELDS)
    write_csv(
        comparison_dir / "approach_metric_summary.csv",
        approach_summary_rows,
        APPROACH_SUMMARY_FIELDS,
    )
    write_csv(comparison_dir / "pairing_report.csv", pairing_rows, PAIRING_FIELDS)
    write_csv(
        comparison_dir / "paired_architecture_similarity.csv",
        similarity_rows,
        PAIR_SIMILARITY_FIELDS,
    )
    write_csv(
        comparison_dir / "paired_metric_deltas.csv",
        paired_delta_rows,
        PAIR_DELTA_FIELDS,
    )
    write_csv(
        comparison_dir / "paired_metric_summary.csv",
        paired_summary_rows,
        PAIR_SUMMARY_FIELDS,
    )
    write_csv(comparison_dir / "stability_by_approach.csv", stability_rows, STABILITY_FIELDS)
    write_csv(comparison_dir / "comparison_issues.csv", issues, ISSUE_FIELDS)

    return ComparisonResult(
        discovered_run_count=len(descriptors),
        architecture_run_count=sum(
            1
            for row in architecture_rows
            if str(row["architecture_status"]).startswith("calculated")
        ),
        paired_run_count=len(paired_runs),
        issue_count=len(issues),
        comparison_dir=comparison_dir,
    )


def discover_run_descriptors(outputs_dir: Path) -> tuple[list[RunDescriptor], list[dict[str, str]]]:
    descriptors: dict[tuple[str, str, str, str, str, str], RunDescriptor] = {}
    issues: list[dict[str, str]] = []
    metadata_path = outputs_dir / "metadata.csv"

    for record, record_count in read_selected_metadata_records(metadata_path, outputs_dir, issues):
        descriptor = get_or_create_descriptor(descriptors, record.identity)
        descriptor.identity = record.identity
        descriptor.metadata_status = record.status
        descriptor.metadata_timestamp = record.timestamp
        descriptor.metadata_error = record.error
        descriptor.metadata_record_count = record_count
        descriptor.metadata_output_path = record.output_path
        descriptor.metadata_trace_path = record.trace_path

    if outputs_dir.exists():
        for csv_path in sorted(outputs_dir.rglob("run_*.csv")):
            try:
                identity = identity_from_path(outputs_dir, csv_path)
            except ValueError as exc:
                issues.append(issue_row("discovery", csv_path, None, "ambiguous_output_path", str(exc)))
                continue
            descriptor = get_or_create_descriptor(descriptors, identity)
            descriptor.scanned_csv_paths.append(csv_path)

        for trace_path in sorted(outputs_dir.rglob("run_*.trace.jsonl")):
            try:
                identity = identity_from_path(outputs_dir, trace_path)
            except ValueError as exc:
                issues.append(issue_row("discovery", trace_path, None, "ambiguous_trace_path", str(exc)))
                continue
            descriptor = get_or_create_descriptor(descriptors, identity)
            descriptor.scanned_trace_paths.append(trace_path)
    else:
        issues.append(
            issue_row(
                "discovery",
                outputs_dir,
                None,
                "missing_outputs_directory",
                "The outputs directory does not exist.",
            )
        )

    for descriptor in descriptors.values():
        if len(descriptor.scanned_csv_paths) > 1:
            issues.append(
                issue_row(
                    "discovery",
                    first_path(descriptor.scanned_csv_paths),
                    descriptor.identity,
                    "duplicate_output_csv",
                    "Multiple CSV files share the same logical run identity.",
                )
            )
        if len(descriptor.scanned_trace_paths) > 1:
            issues.append(
                issue_row(
                    "discovery",
                    first_path(descriptor.scanned_trace_paths),
                    descriptor.identity,
                    "duplicate_trace",
                    "Multiple trace files share the same logical run identity.",
                )
            )
    return sorted(descriptors.values(), key=descriptor_sort_key), issues


def read_selected_metadata_records(
    metadata_path: Path,
    outputs_dir: Path,
    issues: list[dict[str, str]],
) -> list[tuple[MetadataRecord, int]]:
    if not metadata_path.exists():
        return []

    try:
        reader = csv.DictReader(io.StringIO(read_text(metadata_path)))
        raw_rows = list(reader)
    except (OSError, csv.Error) as exc:
        issues.append(issue_row("metadata", metadata_path, None, "metadata_read_error", str(exc)))
        return []

    records_by_key: dict[tuple[str, str, str, str, str, str], list[MetadataRecord]] = defaultdict(list)
    for row_number, row in enumerate(raw_rows, start=2):
        try:
            record = metadata_record_from_row(row, row_number, metadata_path, outputs_dir)
        except ValueError as exc:
            issues.append(issue_row("metadata", metadata_path, None, "invalid_metadata_row", str(exc)))
            continue
        records_by_key[record.identity.storage_key()].append(record)

    selected: list[tuple[MetadataRecord, int]] = []
    for records in records_by_key.values():
        successful_records = [record for record in records if record.status == "success"]
        chosen = successful_records[-1] if successful_records else records[-1]
        model_names = {record.identity.model_name for record in records}
        if len(model_names) > 1:
            issues.append(
                issue_row(
                    "metadata",
                    metadata_path,
                    chosen.identity,
                    "ambiguous_sanitized_model_name",
                    "Different model names map to the same sanitized output-path fragment.",
                )
            )
        if len(records) > 1:
            issues.append(
                issue_row(
                    "metadata",
                    metadata_path,
                    chosen.identity,
                    "duplicate_metadata_run",
                    "Multiple metadata rows share this run identity; the latest successful row was selected.",
                )
            )
        selected.append((chosen, len(records)))
    return selected


def metadata_record_from_row(
    row: dict[str, str | None],
    row_number: int,
    metadata_path: Path,
    outputs_dir: Path,
) -> MetadataRecord:
    project_name = string_cell(row, "project_name")
    provider = string_cell(row, "provider")
    model_name = string_cell(row, "model") or string_cell(row, "model_name")
    prompt_template = string_cell(row, "prompt_template")
    run_id = normalize_run_id(string_cell(row, "run_number") or string_cell(row, "run_id"))
    approach = (string_cell(row, "approach") or "direct").casefold()
    if approach not in {"direct", "agent"}:
        raise ValueError(f"Metadata row {row_number} has unsupported approach '{approach}'.")
    if not all((project_name, provider, model_name, prompt_template, run_id)):
        raise ValueError(f"Metadata row {row_number} is missing run identity fields.")

    identity = RunIdentity(
        project_name=project_name,
        approach=approach,
        provider=provider,
        model_name=model_name,
        prompt_template=prompt_template,
        run_id=run_id,
    )
    return MetadataRecord(
        identity=identity,
        status=(string_cell(row, "status") or "unknown").casefold(),
        timestamp=string_cell(row, "timestamp"),
        error=string_cell(row, "error"),
        output_path=resolve_metadata_path(
            string_cell(row, "output_path"), metadata_path, outputs_dir
        ),
        trace_path=resolve_metadata_path(
            string_cell(row, "trace_path"), metadata_path, outputs_dir
        ),
        row_number=row_number,
    )


def resolve_metadata_path(
    raw_path: str,
    metadata_path: Path,
    outputs_dir: Path,
) -> Path | None:
    """Resolve a metadata artifact without allowing the comparison to leave outputs_dir."""
    if not raw_path:
        return None
    candidate = Path(raw_path)
    if candidate.is_absolute():
        candidates = [candidate]
    else:
        candidates = [
            Path.cwd() / candidate,
            outputs_dir / candidate,
            outputs_dir.parent / candidate,
            metadata_path.parent / candidate,
        ]

    safe_candidates = [
        possible_path.resolve()
        for possible_path in candidates
        if path_is_within(possible_path, outputs_dir)
    ]
    for possible_path in safe_candidates:
        if possible_path.exists():
            return possible_path
    if safe_candidates:
        return safe_candidates[0]
    raise ValueError(
        f"Metadata artifact path is outside the selected outputs directory: {raw_path}"
    )


def path_is_within(path: Path, parent: Path) -> bool:
    """Return whether a path, including a symlink, stays within a directory."""
    try:
        path.resolve().relative_to(parent.resolve())
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def identity_from_path(outputs_dir: Path, path: Path) -> RunIdentity:
    try:
        parts = path.relative_to(outputs_dir).parts
    except ValueError as exc:
        raise ValueError(f"Path is outside outputs directory: {path}") from exc

    run_id = run_id_from_file_name(path.name)
    if len(parts) == 6 and parts[1] in {"direct", "agent"}:
        project_name, approach, provider, model_name, prompt_template, _ = parts
    elif len(parts) == 5:
        project_name, provider, model_name, prompt_template, _ = parts
        approach = "direct"
    else:
        raise ValueError(
            "Expected outputs/<project>/<approach>/<provider>/<model>/<template>/run_N.* "
            "or legacy outputs/<project>/<provider>/<model>/<template>/run_N.*."
        )
    return RunIdentity(
        project_name=project_name,
        approach=approach,
        provider=provider,
        model_name=model_name,
        prompt_template=prompt_template,
        run_id=run_id,
    )


def run_id_from_file_name(file_name: str) -> str:
    if file_name.endswith(".trace.jsonl"):
        run_id = file_name[: -len(".trace.jsonl")]
    else:
        run_id = Path(file_name).stem
    return normalize_run_id(run_id)


def normalize_run_id(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        return ""
    return cleaned if cleaned.startswith("run_") else f"run_{cleaned}"


def get_or_create_descriptor(
    descriptors: dict[tuple[str, str, str, str, str, str], RunDescriptor],
    identity: RunIdentity,
) -> RunDescriptor:
    key = identity.storage_key()
    if key not in descriptors:
        descriptors[key] = RunDescriptor(identity=identity)
    return descriptors[key]


def filter_descriptors(
    descriptors: list[RunDescriptor],
    *,
    project_name: str | None,
    provider: str | None,
    model_name: str | None,
    prompt_template: str | None,
    run_id: str | None,
) -> list[RunDescriptor]:
    normalized_run_id = normalize_run_id(run_id) if run_id else None
    filtered: list[RunDescriptor] = []
    for descriptor in descriptors:
        identity = descriptor.identity
        if project_name and identity.project_name != project_name:
            continue
        if provider and identity.provider != provider:
            continue
        if model_name and identity.model_name != model_name:
            continue
        if prompt_template and identity.prompt_template != prompt_template:
            continue
        if normalized_run_id and identity.run_id != normalized_run_id:
            continue
        filtered.append(descriptor)
    return filtered


def evaluate_run(
    descriptor: RunDescriptor,
    *,
    min_responsibility_words: int,
) -> tuple[EvaluatedRun, list[dict[str, str]]]:
    issues: list[dict[str, str]] = []
    identity_row = descriptor.identity.as_row()
    csv_path = descriptor.selected_csv_path()
    trace_path = descriptor.selected_trace_path()
    architecture: ArchitectureMetrics | None = None
    architecture_warnings: list[str] = []
    architecture_status = ""
    architecture_metric_values: dict[str, int | float | None] = {
        metric_name: None for metric_name in ARCHITECTURE_NUMERIC_METRICS
    }

    if csv_path is None:
        architecture_status = (
            f"skipped_{descriptor.metadata_status}"
            if descriptor.metadata_record_count
            else "missing_output"
        )
    elif not csv_path.exists():
        architecture_status = "missing_output"
        issues.append(
            issue_row(
                "architecture",
                csv_path,
                descriptor.identity,
                "missing_output_csv",
                "The selected run has no CSV output file.",
            )
        )
    else:
        try:
            architecture = analyze_architecture_csv(
                csv_path,
                min_responsibility_words=min_responsibility_words,
            )
            architecture_metric_values = architecture.metrics
            architecture_warnings = architecture.warnings
            architecture_status = (
                "calculated_with_warnings" if architecture_warnings else "calculated"
            )
            for warning in architecture_warnings:
                issues.append(
                    issue_row(
                        "architecture",
                        csv_path,
                        descriptor.identity,
                        "architecture_warning",
                        warning,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            architecture_status = "error"
            issues.append(
                issue_row(
                    "architecture",
                    csv_path,
                    descriptor.identity,
                    exc.__class__.__name__,
                    str(exc),
                )
            )

    try:
        trace_values, trace_warnings = analyze_trace(trace_path)
    except Exception as exc:  # noqa: BLE001
        trace_values = unavailable_trace_metrics()
        trace_values["trace_available"] = int(trace_path is not None and trace_path.exists())
        trace_values["trace_status"] = "error"
        trace_warnings = [f"Trace could not be processed: {exc}"]
        issues.append(
            issue_row(
                "trace",
                trace_path,
                descriptor.identity,
                exc.__class__.__name__,
                str(exc),
            )
        )
    for warning in trace_warnings:
        issues.append(
            issue_row(
                "trace",
                trace_path,
                descriptor.identity,
                "trace_warning",
                warning,
            )
        )

    architecture_row: dict[str, Any] = {
        **identity_row,
        "metadata_status": descriptor.metadata_status,
        "metadata_timestamp": descriptor.metadata_timestamp,
        "metadata_record_count": descriptor.metadata_record_count,
        "csv_path": path_text(csv_path),
        "architecture_status": architecture_status,
        "architecture_warnings": " | ".join(architecture_warnings),
        **architecture_metric_values,
    }
    process_row: dict[str, Any] = {
        **identity_row,
        "metadata_status": descriptor.metadata_status,
        "metadata_timestamp": descriptor.metadata_timestamp,
        "metadata_record_count": descriptor.metadata_record_count,
        "trace_path": path_text(trace_path),
        "trace_warnings": " | ".join(trace_warnings),
        **trace_values,
    }
    return (
        EvaluatedRun(
            descriptor=descriptor,
            architecture_row=architecture_row,
            process_row=process_row,
            architecture=architecture,
        ),
        issues,
    )


def build_metric_rows(
    architecture_rows: list[dict[str, Any]],
    process_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in architecture_rows:
        if not str(row["architecture_status"]).startswith("calculated"):
            continue
        rows.extend(metric_rows_for_run(row, "architecture", ARCHITECTURE_NUMERIC_METRICS))
    for row in process_rows:
        if row.get("trace_status") not in {"calculated", "partial"}:
            continue
        rows.extend(metric_rows_for_run(row, "process", TRACE_NUMERIC_METRICS))
    return rows


def metric_rows_for_run(
    row: dict[str, Any],
    metric_group: str,
    metric_names: Iterable[str],
) -> list[dict[str, Any]]:
    metric_rows: list[dict[str, Any]] = []
    for metric_name in metric_names:
        value = row.get(metric_name)
        if not is_number(value):
            continue
        metric_rows.append(
            {
                **{field: row[field] for field in IDENTITY_FIELDS},
                "metric_group": metric_group,
                "metric_name": metric_name,
                "metric_value": value,
            }
        )
    return metric_rows


def build_approach_metric_summary(metric_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values_by_key: dict[tuple[str, ...], list[float]] = defaultdict(list)
    for row in metric_rows:
        key = tuple(
            str(row[field])
            for field in (
                "project_name",
                "approach",
                "provider",
                "model_name",
                "prompt_template",
                "metric_group",
                "metric_name",
            )
        )
        values_by_key[key].append(float(row["metric_value"]))

    summary_rows: list[dict[str, Any]] = []
    for key, values in sorted(values_by_key.items()):
        (
            project_name,
            approach,
            provider,
            model_name,
            prompt_template,
            metric_group,
            metric_name,
        ) = key
        summary_rows.append(
            {
                "project_name": project_name,
                "approach": approach,
                "provider": provider,
                "model_name": model_name,
                "prompt_template": prompt_template,
                "metric_group": metric_group,
                "metric_name": metric_name,
                **summary_statistics(values, count_name="run_count"),
            }
        )
    return summary_rows


def build_pairing_rows(
    evaluated_runs: list[EvaluatedRun],
) -> tuple[
    list[dict[str, Any]],
    list[tuple[EvaluatedRun, EvaluatedRun]],
    set[tuple[str, str, str, str, str, str]],
]:
    grouped: dict[tuple[str, str, str, str, str], dict[str, list[EvaluatedRun]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for evaluated in evaluated_runs:
        grouped[evaluated.descriptor.identity.pair_key()][
            evaluated.descriptor.identity.approach
        ].append(evaluated)

    pairing_rows: list[dict[str, Any]] = []
    paired_runs: list[tuple[EvaluatedRun, EvaluatedRun]] = []
    excluded_storage_keys: set[tuple[str, str, str, str, str, str]] = set()
    for pair_key, by_approach in sorted(grouped.items()):
        direct_runs = by_approach.get("direct", [])
        agent_runs = by_approach.get("agent", [])
        direct = direct_runs[0] if len(direct_runs) == 1 else None
        agent = agent_runs[0] if len(agent_runs) == 1 else None
        pair_status = select_pair_status(direct_runs, agent_runs)
        warnings = []
        if direct:
            warnings.extend(direct.descriptor.pairing_warnings())
        if agent:
            warnings.extend(agent.descriptor.pairing_warnings())
        if pair_status == "paired" and direct and agent:
            paired_runs.append((direct, agent))
        elif pair_status in {
            "duplicate_direct",
            "duplicate_agent",
            "ambiguous_model_identity",
        }:
            excluded_storage_keys.update(
                evaluated.descriptor.identity.storage_key()
                for evaluated in direct_runs + agent_runs
            )

        project_name, provider, _, prompt_template, run_id = pair_key
        model_name = (
            direct.descriptor.identity.model_name
            if direct
            else agent.descriptor.identity.model_name
            if agent
            else ""
        )
        pairing_rows.append(
            {
                "project_name": project_name,
                "provider": provider,
                "model_name": model_name,
                "prompt_template": prompt_template,
                "run_id": run_id,
                "pair_status": pair_status,
                "direct_csv_path": path_text(direct.descriptor.selected_csv_path()) if direct else "",
                "agent_csv_path": path_text(agent.descriptor.selected_csv_path()) if agent else "",
                "direct_architecture_status": (
                    direct.architecture_row["architecture_status"] if direct else ""
                ),
                "agent_architecture_status": (
                    agent.architecture_row["architecture_status"] if agent else ""
                ),
                "pairing_warning": " | ".join(sorted(set(warnings))),
            }
        )
    return pairing_rows, paired_runs, excluded_storage_keys


def select_pair_status(
    direct_runs: list[EvaluatedRun],
    agent_runs: list[EvaluatedRun],
) -> str:
    if not direct_runs:
        return "missing_direct"
    if not agent_runs:
        return "missing_agent"
    if len(direct_runs) > 1:
        return "duplicate_direct"
    if len(agent_runs) > 1:
        return "duplicate_agent"
    if len(direct_runs[0].descriptor.scanned_csv_paths) > 1:
        return "duplicate_direct"
    if len(agent_runs[0].descriptor.scanned_csv_paths) > 1:
        return "duplicate_agent"
    if model_identity_conflicts(direct_runs[0], agent_runs[0]):
        return "ambiguous_model_identity"
    if not str(direct_runs[0].architecture_row["architecture_status"]).startswith("calculated"):
        return "invalid_direct_output"
    if not str(agent_runs[0].architecture_row["architecture_status"]).startswith("calculated"):
        return "invalid_agent_output"
    return "paired"


def model_identity_conflicts(direct: EvaluatedRun, agent: EvaluatedRun) -> bool:
    """Avoid pairing different raw model names that collapse to the same path fragment."""
    direct_has_metadata = direct.descriptor.metadata_record_count > 0
    agent_has_metadata = agent.descriptor.metadata_record_count > 0
    return (
        direct_has_metadata
        and agent_has_metadata
        and direct.descriptor.identity.model_name != agent.descriptor.identity.model_name
    )


def build_pair_similarity_rows(
    paired_runs: list[tuple[EvaluatedRun, EvaluatedRun]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for direct, agent in paired_runs:
        assert direct.architecture is not None
        assert agent.architecture is not None
        identity = direct.descriptor.identity
        rows.append(
            {
                "project_name": identity.project_name,
                "provider": identity.provider,
                "model_name": identity.model_name,
                "prompt_template": identity.prompt_template,
                "run_id": identity.run_id,
                "service_set_jaccard": set_jaccard(
                    direct.architecture.service_names,
                    agent.architecture.service_names,
                ),
                "declared_communication_set_jaccard": set_jaccard(
                    direct.architecture.declared_edges,
                    agent.architecture.declared_edges,
                ),
                "communication_set_jaccard": set_jaccard(
                    direct.architecture.valid_edges,
                    agent.architecture.valid_edges,
                ),
                "agent_minus_direct_service_count": (
                    agent.architecture_row["service_count"]
                    - direct.architecture_row["service_count"]
                ),
                "agent_minus_direct_valid_communication_count": (
                    agent.architecture_row["valid_communication_count"]
                    - direct.architecture_row["valid_communication_count"]
                ),
            }
        )
    return rows


def build_paired_metric_deltas(
    paired_runs: list[tuple[EvaluatedRun, EvaluatedRun]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    metric_groups = (
        ("architecture", ARCHITECTURE_NUMERIC_METRICS, "architecture_row"),
        ("process", TRACE_NUMERIC_METRICS, "process_row"),
    )
    for direct, agent in paired_runs:
        identity = direct.descriptor.identity
        for metric_group, metric_names, row_name in metric_groups:
            direct_values = getattr(direct, row_name)
            agent_values = getattr(agent, row_name)
            for metric_name in metric_names:
                direct_value = direct_values.get(metric_name)
                agent_value = agent_values.get(metric_name)
                if not is_number(direct_value) or not is_number(agent_value):
                    continue
                delta = float(agent_value) - float(direct_value)
                rows.append(
                    {
                        "project_name": identity.project_name,
                        "provider": identity.provider,
                        "model_name": identity.model_name,
                        "prompt_template": identity.prompt_template,
                        "run_id": identity.run_id,
                        "metric_group": metric_group,
                        "metric_name": metric_name,
                        "direct_value": direct_value,
                        "agent_value": agent_value,
                        "agent_minus_direct": delta,
                        "relative_change_from_direct": (
                            delta / abs(float(direct_value)) if direct_value else None
                        ),
                    }
                )
    return rows


def build_paired_metric_summary(paired_deltas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in paired_deltas:
        key = tuple(
            str(row[field])
            for field in (
                "project_name",
                "provider",
                "model_name",
                "prompt_template",
                "metric_group",
                "metric_name",
            )
        )
        grouped[key].append(row)

    summary_rows: list[dict[str, Any]] = []
    for key, rows in sorted(grouped.items()):
        (
            project_name,
            provider,
            model_name,
            prompt_template,
            metric_group,
            metric_name,
        ) = key
        direct_values = [float(row["direct_value"]) for row in rows]
        agent_values = [float(row["agent_value"]) for row in rows]
        deltas = [float(row["agent_minus_direct"]) for row in rows]
        summary_rows.append(
            {
                "project_name": project_name,
                "provider": provider,
                "model_name": model_name,
                "prompt_template": prompt_template,
                "metric_group": metric_group,
                "metric_name": metric_name,
                "paired_run_count": len(rows),
                "direct_mean": statistics.fmean(direct_values),
                "agent_mean": statistics.fmean(agent_values),
                "mean_agent_minus_direct": statistics.fmean(deltas),
                "median_agent_minus_direct": statistics.median(deltas),
                "population_stddev_agent_minus_direct": population_stddev(deltas),
                "agent_higher_count": sum(1 for delta in deltas if delta > 0),
                "equal_count": sum(1 for delta in deltas if delta == 0),
                "agent_lower_count": sum(1 for delta in deltas if delta < 0),
            }
        )
    return summary_rows


def build_stability_rows(evaluated_runs: list[EvaluatedRun]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, str, str], list[EvaluatedRun]] = defaultdict(list)
    for evaluated in evaluated_runs:
        if evaluated.architecture is None:
            continue
        identity = evaluated.descriptor.identity
        groups[
            (
                identity.project_name,
                identity.approach,
                identity.provider,
                identity.model_name,
                identity.prompt_template,
            )
        ].append(evaluated)

    stability_rows: list[dict[str, Any]] = []
    for key, runs in sorted(groups.items()):
        project_name, approach, provider, model_name, prompt_template = key
        service_count_values = [float(run.architecture_row["service_count"]) for run in runs]
        communication_count_values = [
            float(run.architecture_row["valid_communication_count"]) for run in runs
        ]
        service_jaccards: list[float] = []
        communication_jaccards: list[float] = []
        for index, left in enumerate(runs):
            assert left.architecture is not None
            for right in runs[index + 1 :]:
                assert right.architecture is not None
                service_jaccards.append(
                    set_jaccard(left.architecture.service_names, right.architecture.service_names)
                )
                communication_jaccards.append(
                    set_jaccard(left.architecture.valid_edges, right.architecture.valid_edges)
                )
        stability_rows.append(
            {
                "project_name": project_name,
                "approach": approach,
                "provider": provider,
                "model_name": model_name,
                "prompt_template": prompt_template,
                "run_count": len(runs),
                "run_pair_count": len(service_jaccards),
                "service_count_mean": statistics.fmean(service_count_values),
                "service_count_population_stddev": population_stddev(service_count_values),
                "valid_communication_count_mean": statistics.fmean(communication_count_values),
                "valid_communication_count_population_stddev": population_stddev(
                    communication_count_values
                ),
                "mean_service_set_jaccard": mean_or_none(service_jaccards),
                "mean_communication_set_jaccard": mean_or_none(communication_jaccards),
            }
        )
    return stability_rows


def summary_statistics(values: list[float], *, count_name: str) -> dict[str, Any]:
    return {
        count_name: len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "population_stddev": population_stddev(values),
        "minimum": min(values),
        "maximum": max(values),
    }


def population_stddev(values: list[float]) -> float:
    return statistics.pstdev(values) if len(values) > 1 else 0.0


def set_jaccard(left: set[Any], right: set[Any]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def issue_row(
    source: str,
    path: Path | None,
    identity: RunIdentity | None,
    issue_type: str,
    message: str,
) -> dict[str, str]:
    identity_row = identity.as_row() if identity else {field: "" for field in IDENTITY_FIELDS}
    return {
        "source": source,
        "path": path_text(path),
        **identity_row,
        "issue_type": issue_type,
        "message": message,
    }


def path_text(path: Path | None) -> str:
    return path.as_posix() if path is not None else ""


def first_path(paths: list[Path]) -> Path | None:
    return sorted(paths)[0] if paths else None


def descriptor_sort_key(descriptor: RunDescriptor) -> tuple[str, str, str, str, str, str]:
    return descriptor.identity.storage_key()


def safe_model_fragment(value: str) -> str:
    sanitized = value.replace("/", "_").replace("\\", "_").replace(":", "_").strip()
    return sanitized or "model"


def string_cell(row: dict[str, str | None], field_name: str) -> str:
    return (row.get(field_name) or "").strip()


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Calculate and compare metrics for direct and agentic decomposition runs."
    )
    parser.add_argument("--outputs-dir", default="outputs")
    parser.add_argument("--comparison-dir", default="comparison_outputs")
    parser.add_argument("--project")
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--prompt-template")
    parser.add_argument("--run-id")
    parser.add_argument(
        "--min-responsibility-words",
        type=int,
        default=5,
        help="Responsibilities with fewer words than this threshold are counted as short.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    main()
