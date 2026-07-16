from __future__ import annotations

from .metric_models import EvaluationContext, MetricRecord


def compute_process_fitness(context: EvaluationContext) -> list[MetricRecord]:
    return [
        MetricRecord(
            metric_name="process_fitness",
            metric_category="process",
            metric_value=None,
            status="missing_required_data",
            formula_version="v1",
            notes="Missing process/event logs and process model.",
        )
    ]


def compute_process_precision(context: EvaluationContext) -> list[MetricRecord]:
    return [
        MetricRecord(
            metric_name="process_precision",
            metric_category="process",
            metric_value=None,
            status="missing_required_data",
            formula_version="v1",
            notes="Missing process/event logs and behavioral model.",
        )
    ]
