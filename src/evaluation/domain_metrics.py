from __future__ import annotations

from .cohesion_metrics import jaccard_similarity, tokenize
from .metric_models import EvaluationContext, MetricRecord


def compute_business_context_purity_bcp(context: EvaluationContext) -> list[MetricRecord]:
    mapping = context.artifacts.requirement_to_service_mapping_df
    if mapping is None or mapping.empty:
        return [
            MetricRecord(
                metric_name="business_context_purity_bcp",
                metric_category="domain",
                metric_value=None,
                status="missing_required_data",
                formula_version="v1",
                notes="Missing requirement-to-service or feature-to-service mapping.",
            )
        ]
    return [
        MetricRecord(
            metric_name="business_context_purity_bcp",
            metric_category="domain",
            metric_value=None,
            status="error",
            formula_version="v1",
            notes="BCP calculation requires explicit context distribution inside each service.",
        )
    ]


def compute_requirement_service_semantic_alignment(context: EvaluationContext) -> list[MetricRecord]:
    requirements_df = context.artifacts.requirements_df
    if requirements_df is None or requirements_df.empty:
        return [
            MetricRecord(
                metric_name="requirement_service_semantic_alignment",
                metric_category="domain",
                metric_value=None,
                status="missing_required_data",
                formula_version="v1_textual_fallback",
                notes="Requirements were not available for textual alignment.",
            )
        ]

    requirement_texts = [
        tokenize(" ".join(str(value) for value in row if str(value).strip()))
        for row in requirements_df.fillna("").astype(str).itertuples(index=False, name=None)
    ]
    requirement_texts = [tokens for tokens in requirement_texts if tokens]
    if not requirement_texts:
        return [
            MetricRecord(
                metric_name="requirement_service_semantic_alignment",
                metric_category="domain",
                metric_value=0.0,
                status="calculated_fallback",
                formula_version="v1_textual_fallback",
                notes="Requirement text was available but did not yield comparable tokens.",
            )
        ]

    service_scores: list[float] = []
    for responsibility in context.result.valid_rows["responsibility"].fillna("").astype(str):
        service_terms = tokenize(responsibility)
        if not service_terms:
            service_scores.append(0.0)
            continue
        best_score = max(jaccard_similarity(service_terms, requirement_terms) for requirement_terms in requirement_texts)
        service_scores.append(best_score)

    value = sum(service_scores) / len(service_scores) if service_scores else 0.0
    return [
        MetricRecord(
            metric_name="requirement_service_semantic_alignment",
            metric_category="domain",
            metric_value=round(value, 6),
            status="calculated_fallback",
            formula_version="v1_textual_fallback",
            notes="Textual semantic alignment between service responsibilities and requirements; not real BCP.",
        )
    ]


def compute_feature_modularization(context: EvaluationContext) -> list[MetricRecord]:
    mapping = context.artifacts.requirement_to_service_mapping_df
    if mapping is None or mapping.empty:
        return [
            MetricRecord(
                metric_name="feature_modularization",
                metric_category="domain",
                metric_value=None,
                status="missing_required_data",
                formula_version="v1",
                notes="Missing feature/requirement-to-service mapping.",
            )
        ]
    return [
        MetricRecord(
            metric_name="feature_modularization",
            metric_category="domain",
            metric_value=None,
            status="error",
            formula_version="v1",
            notes="Feature modularization calculation requires explicit feature occurrence mapping.",
        )
    ]


def compute_data_independence_da(context: EvaluationContext) -> list[MetricRecord]:
    return [
        MetricRecord(
            metric_name="data_independence_da",
            metric_category="domain",
            metric_value=None,
            status="missing_required_data",
            formula_version="v1",
            notes="Missing data-access map and component-to-service mapping.",
        )
    ]
