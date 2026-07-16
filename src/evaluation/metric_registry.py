from __future__ import annotations

from .cohesion_metrics import (
    compute_chd,
    compute_chm,
    compute_relational_cohesion_rc,
    compute_responsibility_domain_similarity,
)
from .coupling_metrics import (
    compute_afferent_coupling_ac,
    compute_declared_inter_service_coupling,
    compute_efferent_coupling_ec,
    compute_instability,
    compute_inter_microservices_coupling,
)
from .domain_metrics import (
    compute_business_context_purity_bcp,
    compute_data_independence_da,
    compute_feature_modularization,
    compute_requirement_service_semantic_alignment,
)
from .graph_metrics import compute_run_level_graph_metrics, compute_service_level_graph_metrics
from .metric_models import MetricDefinition
from .modularity_metrics import compute_interface_number_ifn, compute_non_extreme_distribution_ned, compute_structural_modularity_quality_smq
from .process_metrics import compute_process_fitness, compute_process_precision
from .runtime_metrics import compute_inter_call_percentage_icp, compute_network_overhead


class MetricRegistry:
    def __init__(self) -> None:
        self.metrics = build_metric_definitions()

    def list_metrics(self) -> list[MetricDefinition]:
        return self.metrics


def build_metric_definitions() -> list[MetricDefinition]:
    return [
        MetricDefinition(
            name="basic_run_metrics",
            category="basic",
            description="Run-level metrics computed from the declared communication graph.",
            required_data=("llm_output_services", "llm_output_communications", "llm_output_responsibilities"),
            output_level="run_level",
            formula_version="v1",
            calculator=compute_run_level_graph_metrics,
        ),
        MetricDefinition(
            name="service_graph_metrics",
            category="coupling",
            description="Incoming and outgoing communications per service.",
            required_data=("llm_output_services", "llm_output_communications"),
            output_level="service_level",
            formula_version="v1",
            calculator=compute_service_level_graph_metrics,
        ),
        MetricDefinition(
            name="declared_inter_service_coupling",
            category="coupling",
            description="Declared communication density derived from communicates_with.",
            required_data=("llm_output_services", "llm_output_communications"),
            output_level="run_level",
            formula_version="v1_textual_declared_graph",
            calculator=compute_declared_inter_service_coupling,
        ),
        MetricDefinition(
            name="cohesion_message_level_chm",
            category="cohesion",
            description="Cohesion at message level using public operation messages.",
            required_data=("public_interfaces", "component_to_service_mapping", "input_output_messages"),
            output_level="run_level",
            formula_version="v1",
            calculator=compute_chm,
        ),
        MetricDefinition(
            name="cohesion_domain_level_chd",
            category="cohesion",
            description="Domain-level cohesion across internal artifacts per service.",
            required_data=("component_to_service_mapping", "static_classes"),
            output_level="run_level",
            formula_version="v1",
            calculator=compute_chd,
        ),
        MetricDefinition(
            name="responsibility_domain_similarity",
            category="cohesion",
            description="Fallback textual similarity between service responsibilities.",
            required_data=("llm_output_responsibilities",),
            output_level="run_level",
            formula_version="v1_textual_fallback",
            calculator=compute_responsibility_domain_similarity,
        ),
        MetricDefinition(
            name="relational_cohesion_rc",
            category="cohesion",
            description="Structural internal cohesion based on internal relations.",
            required_data=("component_to_service_mapping", "structural_dependency_graph"),
            output_level="run_level",
            formula_version="v1",
            calculator=compute_relational_cohesion_rc,
        ),
        MetricDefinition(
            name="afferent_coupling_ac",
            category="coupling",
            description="Average afferent coupling across services.",
            required_data=("component_to_service_mapping", "structural_dependency_graph"),
            output_level="run_level",
            formula_version="v1",
            calculator=compute_afferent_coupling_ac,
        ),
        MetricDefinition(
            name="efferent_coupling_ec",
            category="coupling",
            description="Average efferent coupling across services.",
            required_data=("component_to_service_mapping", "structural_dependency_graph"),
            output_level="run_level",
            formula_version="v1",
            calculator=compute_efferent_coupling_ec,
        ),
        MetricDefinition(
            name="instability",
            category="coupling",
            description="Average instability across services.",
            required_data=("component_to_service_mapping", "structural_dependency_graph"),
            output_level="run_level",
            formula_version="v1",
            calculator=compute_instability,
        ),
        MetricDefinition(
            name="inter_microservices_coupling",
            category="coupling",
            description="Average structural coupling between services.",
            required_data=("component_to_service_mapping", "structural_dependency_graph"),
            output_level="run_level",
            formula_version="v1",
            calculator=compute_inter_microservices_coupling,
        ),
        MetricDefinition(
            name="structural_modularity_quality_smq",
            category="modularity",
            description="Structural modularity quality using cohesion and coupling.",
            required_data=("component_to_service_mapping", "structural_dependency_graph"),
            output_level="run_level",
            formula_version="v1",
            calculator=compute_structural_modularity_quality_smq,
        ),
        MetricDefinition(
            name="interface_number_ifn",
            category="modularity",
            description="Average number of public interfaces per service.",
            required_data=("public_interfaces", "component_to_service_mapping"),
            output_level="run_level",
            formula_version="v1",
            calculator=compute_interface_number_ifn,
        ),
        MetricDefinition(
            name="non_extreme_distribution_ned",
            category="modularity",
            description="Ratio of services with acceptable size bounds.",
            required_data=("component_to_service_mapping",),
            output_level="run_level",
            formula_version="v1",
            calculator=compute_non_extreme_distribution_ned,
        ),
        MetricDefinition(
            name="business_context_purity_bcp",
            category="domain",
            description="Business context purity using mapped requirements/features.",
            required_data=("requirement_to_service_mapping",),
            output_level="run_level",
            formula_version="v1",
            calculator=compute_business_context_purity_bcp,
        ),
        MetricDefinition(
            name="requirement_service_semantic_alignment",
            category="domain",
            description="Fallback textual alignment between service responsibilities and requirements.",
            required_data=("requirements", "llm_output_responsibilities"),
            output_level="run_level",
            formula_version="v1_textual_fallback",
            calculator=compute_requirement_service_semantic_alignment,
        ),
        MetricDefinition(
            name="feature_modularization",
            category="domain",
            description="Feature concentration across services.",
            required_data=("requirement_to_service_mapping",),
            output_level="run_level",
            formula_version="v1",
            calculator=compute_feature_modularization,
        ),
        MetricDefinition(
            name="data_independence_da",
            category="domain",
            description="Data independence using accessed and exclusively owned data.",
            required_data=("data_access_map", "component_to_service_mapping"),
            output_level="run_level",
            formula_version="v1",
            calculator=compute_data_independence_da,
        ),
        MetricDefinition(
            name="inter_call_percentage_icp",
            category="runtime",
            description="Runtime inter-call percentage.",
            required_data=("runtime_logs", "component_to_service_mapping"),
            output_level="run_level",
            formula_version="v1",
            calculator=compute_inter_call_percentage_icp,
        ),
        MetricDefinition(
            name="network_overhead",
            category="runtime",
            description="Estimated network overhead from runtime logs and payload sizes.",
            required_data=("runtime_logs", "payload_sizes"),
            output_level="run_level",
            formula_version="v1",
            calculator=compute_network_overhead,
        ),
        MetricDefinition(
            name="process_fitness",
            category="process",
            description="Process fitness based on event logs and process model.",
            required_data=("process_logs", "process_model"),
            output_level="run_level",
            formula_version="v1",
            calculator=compute_process_fitness,
        ),
        MetricDefinition(
            name="process_precision",
            category="process",
            description="Process precision based on event logs and process model.",
            required_data=("process_logs", "process_model"),
            output_level="run_level",
            formula_version="v1",
            calculator=compute_process_precision,
        ),
    ]
