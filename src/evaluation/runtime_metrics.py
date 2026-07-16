from __future__ import annotations

from .metric_models import EvaluationContext, MetricRecord


def compute_inter_call_percentage_icp(context: EvaluationContext) -> list[MetricRecord]:
    return [
        MetricRecord(
            metric_name="inter_call_percentage_icp",
            metric_category="runtime",
            metric_value=None,
            status="missing_required_data",
            formula_version="v1",
            notes="Missing runtime logs and component-to-service mapping for real runtime calls.",
        )
    ]


def compute_network_overhead(context: EvaluationContext) -> list[MetricRecord]:
    return [
        MetricRecord(
            metric_name="network_overhead",
            metric_category="runtime",
            metric_value=None,
            status="missing_required_data",
            formula_version="v1",
            notes="Missing runtime logs or payload size information.",
        )
    ]
