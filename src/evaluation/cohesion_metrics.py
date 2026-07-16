from __future__ import annotations

import math
import re
from collections import defaultdict

from .metric_models import EvaluationContext, MetricRecord


TOKEN_RE = re.compile(r"[A-Za-zÀ-ÿ0-9]+")


def compute_chm(context: EvaluationContext) -> list[MetricRecord]:
    return [
        MetricRecord(
            metric_name="cohesion_message_level_chm",
            metric_category="cohesion",
            metric_value=None,
            status="missing_required_data",
            formula_version="v1",
            notes="Missing public-operation message signatures mapped to microservices.",
        )
    ]


def compute_chd(context: EvaluationContext) -> list[MetricRecord]:
    mapping = context.artifacts.component_to_service_mapping_df
    classes_df = context.artifacts.static_classes_df
    if mapping is None or classes_df is None or mapping.empty or classes_df.empty:
        return [
            MetricRecord(
                metric_name="cohesion_domain_level_chd",
                metric_category="cohesion",
                metric_value=None,
                status="missing_required_data",
                formula_version="v1",
                notes="Missing component-to-service mapping or internal artifact inventory.",
            )
        ]

    return [
        MetricRecord(
            metric_name="cohesion_domain_level_chd",
            metric_category="cohesion",
            metric_value=None,
            status="error",
            formula_version="v1",
            notes="CHD structural calculation is defined but no compatible mapping format was provided.",
        )
    ]


def compute_responsibility_domain_similarity(context: EvaluationContext) -> list[MetricRecord]:
    token_sets = [
        tokenize(text)
        for text in context.result.valid_rows["responsibility"].fillna("").astype(str).tolist()
        if tokenize(text)
    ]
    if len(token_sets) < 2:
        return [
            MetricRecord(
                metric_name="responsibility_domain_similarity",
                metric_category="cohesion",
                metric_value=0.0,
                status="calculated_fallback",
                formula_version="v1_textual_fallback",
                notes="Insufficient number of non-empty responsibilities for pairwise comparison.",
            )
        ]

    scores: list[float] = []
    for index, left in enumerate(token_sets):
        for right in token_sets[index + 1 :]:
            scores.append(jaccard_similarity(left, right))

    value = sum(scores) / len(scores) if scores else 0.0
    return [
        MetricRecord(
            metric_name="responsibility_domain_similarity",
            metric_category="cohesion",
            metric_value=round(value, 6),
            status="calculated_fallback",
            formula_version="v1_textual_fallback",
            notes="Calculated from responsibility text only; this is not real CHD.",
        )
    ]


def compute_relational_cohesion_rc(context: EvaluationContext) -> list[MetricRecord]:
    mapping = context.artifacts.component_to_service_mapping_df
    dependencies = context.artifacts.structural_dependencies_df
    if mapping is None or dependencies is None or mapping.empty or dependencies.empty:
        return [
            MetricRecord(
                metric_name="relational_cohesion_rc",
                metric_category="cohesion",
                metric_value=None,
                status="missing_required_data",
                formula_version="v1",
                notes="Missing component-to-service mapping or structural dependency graph.",
            )
        ]

    component_to_service = build_component_to_service_map(mapping)
    service_to_components = invert_component_mapping(component_to_service)
    dependency_pairs = {
        tuple(sorted((str(row.source).strip(), str(row.target).strip())))
        for row in dependencies.itertuples(index=False)
        if getattr(row, "source", None) and getattr(row, "target", None)
    }

    scores: list[float] = []
    for service_name, components in service_to_components.items():
        if len(components) < 2:
            scores.append(0.0)
            continue

        possible = len(components) * (len(components) - 1) / 2
        internal_relations = 0
        component_set = set(components)
        for left, right in dependency_pairs:
            if left in component_set and right in component_set:
                internal_relations += 1
        scores.append(internal_relations / possible if possible > 0 else 0.0)

    value = sum(scores) / len(scores) if scores else 0.0
    return [
        MetricRecord(
            metric_name="relational_cohesion_rc",
            metric_category="cohesion",
            metric_value=round(value, 6),
            status="calculated",
            formula_version="v1",
            notes="Average RC across services using available structural relations.",
        )
    ]


def build_component_to_service_map(mapping_df) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in mapping_df.itertuples(index=False):
        component = str(row.component_name).strip()
        service_name = str(row.microservice_name).strip()
        if component and service_name:
            result[component] = service_name
    return result


def invert_component_mapping(component_to_service: dict[str, str]) -> dict[str, list[str]]:
    service_to_components: dict[str, list[str]] = defaultdict(list)
    for component, service_name in component_to_service.items():
        service_to_components[service_name].append(component)
    return service_to_components


def tokenize(text: str) -> set[str]:
    tokens = TOKEN_RE.findall(str(text).lower())
    return {token for token in tokens if len(token) > 2}


def jaccard_similarity(left: set[str], right: set[str]) -> float:
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)
