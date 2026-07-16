from __future__ import annotations

import argparse
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .metric_models import EvaluationContext, MetricDefinition, MetricRecord
from .metric_registry import MetricRegistry
from .project_artifact_scanner import scan_project_artifacts
from .report_writer import write_dataframe
from .result_loader import discover_run_descriptors, load_decomposition_result


LOGGER = logging.getLogger("microservice-evaluation")

RUN_OUTPUT_COLUMNS = [
    "project_name",
    "provider",
    "model_name",
    "prompt_template",
    "run_id",
    "metric_name",
    "metric_value",
    "metric_category",
    "status",
    "formula_version",
    "notes",
]
SERVICE_OUTPUT_COLUMNS = [
    "project_name",
    "provider",
    "model_name",
    "prompt_template",
    "run_id",
    "microservice_name",
    "metric_name",
    "metric_value",
    "metric_category",
    "status",
    "formula_version",
    "notes",
]
APPLICABILITY_OUTPUT_COLUMNS = [
    "project_name",
    "metric_name",
    "metric_category",
    "required_data",
    "available_data",
    "status",
    "notes",
]
ERROR_OUTPUT_COLUMNS = [
    "timestamp",
    "project_name",
    "provider",
    "model_name",
    "prompt_template",
    "run_id",
    "metric_name",
    "error_type",
    "error_message",
]


def main() -> None:
    args = parse_args()
    configure_logging(args.log_level)

    outputs_dir = Path(args.outputs_dir)
    systems_dir = Path(args.systems_dir)
    static_analysis_dir = Path(args.static_analysis_dir)
    evaluation_dir = Path(args.evaluation_dir)

    registry = MetricRegistry()
    descriptors = discover_run_descriptors(outputs_dir)
    descriptors = filter_descriptors(
        descriptors,
        project_name=args.project,
        provider=args.provider,
        model_name=args.model,
        prompt_template=args.prompt_template,
        run_id=args.run_id,
    )

    LOGGER.info("Discovered %s run file(s) for evaluation.", len(descriptors))

    metrics_by_run_rows: list[dict[str, object]] = []
    metrics_by_service_rows: list[dict[str, object]] = []
    applicability_rows: list[dict[str, object]] = []
    error_rows: list[dict[str, object]] = []

    artifacts_cache: dict[str, object] = {}
    applicability_index: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)

    for descriptor in descriptors:
        LOGGER.info(
            "Evaluating project=%s provider=%s model=%s prompt=%s run=%s",
            descriptor.project_name,
            descriptor.provider,
            descriptor.model_name,
            descriptor.prompt_template,
            descriptor.run_id,
        )
        try:
            result = load_decomposition_result(descriptor)
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Failed to load result CSV: %s", descriptor.csv_path)
            error_rows.append(
                build_error_row(
                    descriptor,
                    metric_name="__load_result__",
                    error_type=exc.__class__.__name__,
                    error_message=str(exc),
                )
            )
            continue

        artifacts = artifacts_cache.get(descriptor.project_name)
        if artifacts is None:
            try:
                artifacts = scan_project_artifacts(
                    project_name=descriptor.project_name,
                    systems_dir=systems_dir,
                    static_analysis_root=static_analysis_dir,
                )
                artifacts_cache[descriptor.project_name] = artifacts
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Failed to scan project artifacts for %s", descriptor.project_name)
                error_rows.append(
                    build_error_row(
                        descriptor,
                        metric_name="__scan_project_artifacts__",
                        error_type=exc.__class__.__name__,
                        error_message=str(exc),
                    )
                )
                continue

        context = EvaluationContext(
            result=result,
            artifacts=artifacts,
            min_service_size=args.min_service_size,
            max_service_size=args.max_service_size,
        )

        for metric_definition in registry.list_metrics():
            try:
                records = metric_definition.calculator(context)
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception(
                    "Metric %s failed for %s/%s/%s/%s/%s",
                    metric_definition.name,
                    descriptor.project_name,
                    descriptor.provider,
                    descriptor.model_name,
                    descriptor.prompt_template,
                    descriptor.run_id,
                )
                error_rows.append(
                    build_error_row(
                        descriptor,
                        metric_name=metric_definition.name,
                        error_type=exc.__class__.__name__,
                        error_message=str(exc),
                    )
                )
                records = [
                    MetricRecord(
                        metric_name=metric_definition.name,
                        metric_category=metric_definition.category,
                        metric_value=None,
                        status="error",
                        formula_version=metric_definition.formula_version,
                        notes=str(exc),
                    )
                ]

            for record in records:
                if record.microservice_name is None:
                    metrics_by_run_rows.append(build_run_row(descriptor, record))
                else:
                    metrics_by_service_rows.append(build_service_row(descriptor, record))

            current_applicability_rows = build_applicability_rows(
                project_name=descriptor.project_name,
                metric_definition=metric_definition,
                context=context,
                records=records,
            )
            applicability_rows.extend(current_applicability_rows)
            for applicability_row in current_applicability_rows:
                applicability_index[
                    (descriptor.project_name, str(applicability_row["metric_name"]))
                ].append(applicability_row)

    final_applicability_rows = aggregate_applicability_rows(applicability_index)

    write_dataframe(
        evaluation_dir / "metrics_by_run.csv",
        pd.DataFrame(metrics_by_run_rows, columns=RUN_OUTPUT_COLUMNS),
    )
    write_dataframe(
        evaluation_dir / "metrics_by_service.csv",
        pd.DataFrame(metrics_by_service_rows, columns=SERVICE_OUTPUT_COLUMNS),
    )
    write_dataframe(
        evaluation_dir / "metric_applicability_report.csv",
        pd.DataFrame(final_applicability_rows, columns=APPLICABILITY_OUTPUT_COLUMNS),
    )
    write_dataframe(
        evaluation_dir / "errors.csv",
        pd.DataFrame(error_rows, columns=ERROR_OUTPUT_COLUMNS),
    )

    LOGGER.info("Evaluation finished. Results written to %s", evaluation_dir.as_posix())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate generated microservice decompositions.")
    parser.add_argument("--systems-dir", default="systems")
    parser.add_argument("--outputs-dir", default="outputs")
    parser.add_argument("--evaluation-dir", default="evaluation_outputs")
    parser.add_argument("--static-analysis-dir", default="analysis-results/static-analysis")
    parser.add_argument("--project")
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--prompt-template")
    parser.add_argument("--run-id")
    parser.add_argument("--min-service-size", type=int, default=5)
    parser.add_argument("--max-service-size", type=int, default=20)
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args()


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(message)s",
    )


def filter_descriptors(
    descriptors,
    *,
    project_name: str | None,
    provider: str | None,
    model_name: str | None,
    prompt_template: str | None,
    run_id: str | None,
):
    filtered = []
    for descriptor in descriptors:
        if project_name and descriptor.project_name != project_name:
            continue
        if provider and descriptor.provider != provider:
            continue
        if model_name and descriptor.model_name != model_name:
            continue
        if prompt_template and descriptor.prompt_template != prompt_template:
            continue
        if run_id and descriptor.run_id != run_id:
            continue
        filtered.append(descriptor)
    return filtered


def build_run_row(descriptor, record: MetricRecord) -> dict[str, object]:
    return {
        "project_name": descriptor.project_name,
        "provider": descriptor.provider,
        "model_name": descriptor.model_name,
        "prompt_template": descriptor.prompt_template,
        "run_id": descriptor.run_id,
        "metric_name": record.metric_name,
        "metric_value": record.metric_value,
        "metric_category": record.metric_category,
        "status": record.status,
        "formula_version": record.formula_version,
        "notes": record.notes,
    }


def build_service_row(descriptor, record: MetricRecord) -> dict[str, object]:
    return {
        "project_name": descriptor.project_name,
        "provider": descriptor.provider,
        "model_name": descriptor.model_name,
        "prompt_template": descriptor.prompt_template,
        "run_id": descriptor.run_id,
        "microservice_name": record.microservice_name,
        "metric_name": record.metric_name,
        "metric_value": record.metric_value,
        "metric_category": record.metric_category,
        "status": record.status,
        "formula_version": record.formula_version,
        "notes": record.notes,
    }


def build_error_row(descriptor, *, metric_name: str, error_type: str, error_message: str) -> dict[str, object]:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "project_name": descriptor.project_name,
        "provider": descriptor.provider,
        "model_name": descriptor.model_name,
        "prompt_template": descriptor.prompt_template,
        "run_id": descriptor.run_id,
        "metric_name": metric_name,
        "error_type": error_type,
        "error_message": error_message,
    }


def build_applicability_rows(
    *,
    project_name: str,
    metric_definition: MetricDefinition,
    context: EvaluationContext,
    records: list[MetricRecord],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    records_by_metric_name: dict[str, list[MetricRecord]] = defaultdict(list)

    for record in records:
        records_by_metric_name[record.metric_name].append(record)

    for metric_name, metric_records in sorted(records_by_metric_name.items()):
        rows.append(
            {
                "project_name": project_name,
                "metric_name": metric_name,
                "metric_category": metric_records[0].metric_category,
                "required_data": ";".join(metric_definition.required_data),
                "available_data": ";".join(sorted(context.available_data)),
                "status": select_applicability_status(metric_records),
                "notes": " | ".join(
                    sorted(set(filter(None, (record.notes for record in metric_records))))
                ),
            }
        )

    return rows


def select_applicability_status(records: list[MetricRecord]) -> str:
    statuses = {record.status for record in records}
    for candidate in ("calculated", "calculated_fallback", "not_applicable", "missing_required_data", "error"):
        if candidate in statuses:
            return candidate
    return "error"


def aggregate_applicability_rows(index: dict[tuple[str, str], list[dict[str, object]]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for (project_name, metric_name), entries in sorted(index.items()):
        statuses = {str(entry["status"]) for entry in entries}
        status = select_applicability_status(
            [MetricRecord(metric_name=metric_name, metric_category=str(entries[0]["metric_category"]), metric_value=None, status=status_value, formula_version="v1") for status_value in statuses]  # type: ignore[arg-type]
        )
        notes = " | ".join(sorted(set(filter(None, (str(entry["notes"]) for entry in entries)))))
        rows.append(
            {
                "project_name": project_name,
                "metric_name": metric_name,
                "metric_category": entries[0]["metric_category"],
                "required_data": entries[0]["required_data"],
                "available_data": entries[0]["available_data"],
                "status": status,
                "notes": notes,
            }
        )
    return rows


if __name__ == "__main__":
    main()
