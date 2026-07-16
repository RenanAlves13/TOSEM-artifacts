from __future__ import annotations

from .metric_models import EvaluationContext, MetricRecord

try:
    import networkx as nx
except Exception:  # noqa: BLE001
    nx = None


def build_declared_graph(context: EvaluationContext):
    if nx is None:
        return None
    graph = nx.DiGraph()
    graph.add_nodes_from(context.result.unique_service_names)
    graph.add_edges_from(context.result.edges)
    return graph


def compute_run_level_graph_metrics(context: EvaluationContext) -> list[MetricRecord]:
    service_count = context.result.service_count
    communication_count = len(context.result.edges)
    warnings_note = " | ".join(context.result.warnings)

    if service_count <= 1:
        communication_density = 0.0
    else:
        communication_density = communication_count / (service_count * (service_count - 1))

    average_outgoing = communication_count / service_count if service_count > 0 else 0.0

    graph = build_declared_graph(context)
    if graph is not None:
        isolated_services = [
            node
            for node in graph.nodes
            if graph.in_degree(node) == 0 and graph.out_degree(node) == 0
        ]
    else:
        isolated_services = [
            service_name
            for service_name in context.result.unique_service_names
            if context.result.incoming_counts.get(service_name, 0) == 0
            and context.result.outgoing_counts.get(service_name, 0) == 0
        ]

    isolated_count = len(isolated_services)
    isolated_ratio = isolated_count / service_count if service_count > 0 else 0.0

    responsibility_lengths = list(context.result.responsibility_word_counts.values())
    average_responsibility_length = (
        sum(responsibility_lengths) / len(responsibility_lengths)
        if responsibility_lengths
        else 0.0
    )

    return [
        MetricRecord(
            metric_name="number_of_microservices",
            metric_category="basic",
            metric_value=service_count,
            status="calculated",
            formula_version="v1",
            notes=warnings_note,
        ),
        MetricRecord(
            metric_name="number_of_communications",
            metric_category="basic",
            metric_value=communication_count,
            status="calculated",
            formula_version="v1",
            notes=warnings_note,
        ),
        MetricRecord(
            metric_name="communication_density",
            metric_category="coupling",
            metric_value=round(communication_density, 6),
            status="calculated",
            formula_version="v1",
            notes=warnings_note,
        ),
        MetricRecord(
            metric_name="average_outgoing_communications",
            metric_category="coupling",
            metric_value=round(average_outgoing, 6),
            status="calculated",
            formula_version="v1",
            notes=warnings_note,
        ),
        MetricRecord(
            metric_name="isolated_services_count",
            metric_category="basic",
            metric_value=isolated_count,
            status="calculated",
            formula_version="v1",
            notes=warnings_note,
        ),
        MetricRecord(
            metric_name="isolated_services_ratio",
            metric_category="basic",
            metric_value=round(isolated_ratio, 6),
            status="calculated",
            formula_version="v1",
            notes=warnings_note,
        ),
        MetricRecord(
            metric_name="average_responsibility_length",
            metric_category="basic",
            metric_value=round(average_responsibility_length, 6),
            status="calculated",
            formula_version="v1",
            notes=warnings_note,
        ),
    ]


def compute_service_level_graph_metrics(context: EvaluationContext) -> list[MetricRecord]:
    warnings_note = " | ".join(context.result.warnings)
    rows: list[MetricRecord] = []
    for service_name in context.result.unique_service_names:
        rows.append(
            MetricRecord(
                metric_name="incoming_communications",
                metric_category="coupling",
                metric_value=context.result.incoming_counts.get(service_name, 0),
                status="calculated",
                formula_version="v1",
                notes=warnings_note,
                microservice_name=service_name,
            )
        )
        rows.append(
            MetricRecord(
                metric_name="outgoing_communications",
                metric_category="coupling",
                metric_value=context.result.outgoing_counts.get(service_name, 0),
                status="calculated",
                formula_version="v1",
                notes=warnings_note,
                microservice_name=service_name,
            )
        )
    return rows
