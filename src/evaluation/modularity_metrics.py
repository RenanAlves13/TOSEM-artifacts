from __future__ import annotations

import re

from .cohesion_metrics import build_component_to_service_map, compute_relational_cohesion_rc, tokenize
from .coupling_metrics import compute_inter_microservices_coupling
from .metric_models import EvaluationContext, MetricRecord


def compute_structural_modularity_quality_smq(context: EvaluationContext) -> list[MetricRecord]:
    cohesion_records = compute_relational_cohesion_rc(context)
    coupling_records = compute_inter_microservices_coupling(context)

    cohesion_record = cohesion_records[0]
    coupling_record = coupling_records[0]

    if cohesion_record.status != "calculated" or coupling_record.status != "calculated":
        return [
            MetricRecord(
                metric_name="structural_modularity_quality_smq",
                metric_category="modularity",
                metric_value=None,
                status="missing_required_data",
                formula_version="v1",
                notes="Missing structural cohesion or structural coupling prerequisites.",
            )
        ]

    cohesion = float(cohesion_record.metric_value or 0.0)
    coupling = float(coupling_record.metric_value or 0.0)
    denominator = cohesion + coupling
    value = 0.0 if denominator == 0 else (cohesion - coupling) / denominator

    return [
        MetricRecord(
            metric_name="structural_modularity_quality_smq",
            metric_category="modularity",
            metric_value=round(value, 6),
            status="calculated",
            formula_version="v1",
            notes="SMQ=(average_cohesion-average_coupling)/(average_cohesion+average_coupling).",
        )
    ]


def compute_non_extreme_distribution_ned(context: EvaluationContext) -> list[MetricRecord]:
    mapping = context.artifacts.component_to_service_mapping_df
    if mapping is not None and not mapping.empty:
        component_to_service = build_component_to_service_map(mapping)
        service_sizes: dict[str, int] = {}
        for service_name in component_to_service.values():
            service_sizes[service_name] = service_sizes.get(service_name, 0) + 1
        total_services = len(service_sizes)
        acceptable = sum(
            1
            for size in service_sizes.values()
            if context.min_service_size <= size <= context.max_service_size
        )
        value = acceptable / total_services if total_services > 0 else 0.0
        return [
            MetricRecord(
                metric_name="non_extreme_distribution_ned",
                metric_category="modularity",
                metric_value=round(value, 6),
                status="calculated",
                formula_version="v1",
                notes=(
                    "Structural size based on mapped components per service. "
                    f"Bounds: min={context.min_service_size}, max={context.max_service_size}."
                ),
            )
        ]

    service_sizes = [
        len(tokenize(str(responsibility)))
        for responsibility in context.result.valid_rows["responsibility"].fillna("").astype(str)
    ]
    total_services = len(service_sizes)
    acceptable = sum(
        1
        for size in service_sizes
        if context.min_service_size <= size <= context.max_service_size
    )
    value = acceptable / total_services if total_services > 0 else 0.0
    return [
        MetricRecord(
            metric_name="non_extreme_distribution_ned",
            metric_category="modularity",
            metric_value=round(value, 6),
            status="calculated_fallback",
            formula_version="v1_textual_fallback",
            notes=(
                "Fallback size estimated from responsibility token count only; not structural service size. "
                f"Bounds: min={context.min_service_size}, max={context.max_service_size}."
            ),
        )
    ]


def compute_interface_number_ifn(context: EvaluationContext) -> list[MetricRecord]:
    endpoints = context.artifacts.endpoints_df
    mapping = context.artifacts.component_to_service_mapping_df
    if endpoints is None or endpoints.empty or mapping is None or mapping.empty:
        return [
            MetricRecord(
                metric_name="interface_number_ifn",
                metric_category="modularity",
                metric_value=None,
                status="missing_required_data",
                formula_version="v1",
                notes="Missing endpoints/interfaces or component-to-service mapping.",
            )
        ]

    return [
        MetricRecord(
            metric_name="interface_number_ifn",
            metric_category="modularity",
            metric_value=None,
            status="error",
            formula_version="v1",
            notes="IFN requires endpoint-to-service mapping; no compatible mapping was detected.",
        )
    ]
