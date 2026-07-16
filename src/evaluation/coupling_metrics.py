from __future__ import annotations

from collections import defaultdict

from .cohesion_metrics import build_component_to_service_map, invert_component_mapping
from .metric_models import EvaluationContext, MetricRecord


def compute_declared_inter_service_coupling(context: EvaluationContext) -> list[MetricRecord]:
    service_count = context.result.service_count
    edge_count = len(context.result.edges)
    if service_count <= 1:
        value = 0.0
    else:
        value = edge_count / (service_count * (service_count - 1))
    return [
        MetricRecord(
            metric_name="declared_inter_service_coupling",
            metric_category="coupling",
            metric_value=round(value, 6),
            status="calculated",
            formula_version="v1_textual_declared_graph",
            notes="Calculated from declared communicates_with edges only; not structural coupling.",
        )
    ]


def compute_afferent_coupling_ac(context: EvaluationContext) -> list[MetricRecord]:
    return compute_structural_coupling(context, coupling_direction="afferent")


def compute_efferent_coupling_ec(context: EvaluationContext) -> list[MetricRecord]:
    return compute_structural_coupling(context, coupling_direction="efferent")


def compute_instability(context: EvaluationContext) -> list[MetricRecord]:
    mapping = context.artifacts.component_to_service_mapping_df
    dependencies = context.artifacts.structural_dependencies_df
    if mapping is None or dependencies is None or mapping.empty or dependencies.empty:
        return [
            MetricRecord(
                metric_name="instability",
                metric_category="coupling",
                metric_value=None,
                status="missing_required_data",
                formula_version="v1",
                notes="Missing AC/EC prerequisites: component-to-service mapping or structural dependencies.",
            )
        ]

    service_values = compute_service_ac_ec(mapping, dependencies)
    if not service_values:
        return [
            MetricRecord(
                metric_name="instability",
                metric_category="coupling",
                metric_value=0.0,
                status="calculated",
                formula_version="v1",
                notes="No structural service dependencies were found. Convention: instability=0.",
            )
        ]

    per_service_scores = []
    for counts in service_values.values():
        ac = counts["ac"]
        ec = counts["ec"]
        denominator = ac + ec
        per_service_scores.append(0.0 if denominator == 0 else ec / denominator)

    average_instability = sum(per_service_scores) / len(per_service_scores)
    return [
        MetricRecord(
            metric_name="instability",
            metric_category="coupling",
            metric_value=round(average_instability, 6),
            status="calculated",
            formula_version="v1",
            notes="Average instability across services. Convention when AC+EC=0: instability=0.",
        )
    ]


def compute_inter_microservices_coupling(context: EvaluationContext) -> list[MetricRecord]:
    mapping = context.artifacts.component_to_service_mapping_df
    dependencies = context.artifacts.structural_dependencies_df
    if mapping is None or dependencies is None or mapping.empty or dependencies.empty:
        return [
            MetricRecord(
                metric_name="inter_microservices_coupling",
                metric_category="coupling",
                metric_value=None,
                status="missing_required_data",
                formula_version="v1",
                notes="Missing component-to-service mapping or structural dependency graph.",
            )
        ]

    component_to_service = build_component_to_service_map(mapping)
    service_to_components = invert_component_mapping(component_to_service)

    interactions_by_pair: dict[tuple[str, str], int] = defaultdict(int)
    for row in dependencies.itertuples(index=False):
        source = str(row.source).strip()
        target = str(row.target).strip()
        source_service = component_to_service.get(source)
        target_service = component_to_service.get(target)
        if not source_service or not target_service or source_service == target_service:
            continue
        interactions_by_pair[(source_service, target_service)] += int(getattr(row, "count", 1) or 1)

    if not interactions_by_pair:
        return [
            MetricRecord(
                metric_name="inter_microservices_coupling",
                metric_category="coupling",
                metric_value=0.0,
                status="calculated",
                formula_version="v1",
                notes="No structural inter-service relations were found.",
            )
        ]

    scores: list[float] = []
    for (source_service, target_service), interaction_count in interactions_by_pair.items():
        size_source = len(service_to_components.get(source_service, []))
        size_target = len(service_to_components.get(target_service, []))
        denominator = max(size_source, size_target, 1)
        scores.append(interaction_count / denominator)

    value = sum(scores) / len(scores)
    return [
        MetricRecord(
            metric_name="inter_microservices_coupling",
            metric_category="coupling",
            metric_value=round(value, 6),
            status="calculated",
            formula_version="v1",
            notes="Average pairwise structural coupling between services.",
        )
    ]


def compute_structural_coupling(
    context: EvaluationContext,
    *,
    coupling_direction: str,
) -> list[MetricRecord]:
    mapping = context.artifacts.component_to_service_mapping_df
    dependencies = context.artifacts.structural_dependencies_df
    metric_name = "afferent_coupling_ac" if coupling_direction == "afferent" else "efferent_coupling_ec"
    if mapping is None or dependencies is None or mapping.empty or dependencies.empty:
        return [
            MetricRecord(
                metric_name=metric_name,
                metric_category="coupling",
                metric_value=None,
                status="missing_required_data",
                formula_version="v1",
                notes="Missing component-to-service mapping or structural dependency graph.",
            )
        ]

    service_values = compute_service_ac_ec(mapping, dependencies)
    if not service_values:
        value = 0.0
    else:
        key = "ac" if coupling_direction == "afferent" else "ec"
        value = sum(counts[key] for counts in service_values.values()) / len(service_values)

    return [
        MetricRecord(
            metric_name=metric_name,
            metric_category="coupling",
            metric_value=round(value, 6),
            status="calculated",
            formula_version="v1",
            notes="Average structural coupling across services.",
        )
    ]


def compute_service_ac_ec(mapping_df, dependencies_df) -> dict[str, dict[str, int]]:
    component_to_service = build_component_to_service_map(mapping_df)
    incoming_external: dict[str, set[str]] = defaultdict(set)
    outgoing_external: dict[str, set[str]] = defaultdict(set)

    for row in dependencies_df.itertuples(index=False):
        source = str(row.source).strip()
        target = str(row.target).strip()
        source_service = component_to_service.get(source)
        target_service = component_to_service.get(target)
        if not source_service or not target_service or source_service == target_service:
            continue
        incoming_external[target_service].add(source)
        outgoing_external[source_service].add(target)

    services = set(component_to_service.values())
    return {
        service_name: {
            "ac": len(incoming_external.get(service_name, set())),
            "ec": len(outgoing_external.get(service_name, set())),
        }
        for service_name in services
    }
