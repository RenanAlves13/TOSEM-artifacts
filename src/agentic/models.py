from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class EvidenceItem(BaseModel):
    name: str
    description: str
    evidence: list[str] = Field(default_factory=list)


class DomainAnalysis(BaseModel):
    capabilities: list[EvidenceItem] = Field(default_factory=list)
    domain_entities: list[str] = Field(default_factory=list)
    business_rules: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)


class StructuralCluster(BaseModel):
    name: str
    components: list[str] = Field(default_factory=list)
    rationale: str
    dependencies: list[str] = Field(default_factory=list)


class StructuralAnalysis(BaseModel):
    modules: list[str] = Field(default_factory=list)
    dependency_clusters: list[StructuralCluster] = Field(default_factory=list)
    entrypoints: list[str] = Field(default_factory=list)
    structural_risks: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)


class CritiqueIssue(BaseModel):
    category: Literal[
        "unsupported_service",
        "omitted_capability",
        "nanoservice",
        "coarse_service",
        "responsibility_overlap",
        "excessive_coupling",
        "missing_interaction",
        "unsupported_interaction",
        "invalid_interaction_target",
        "technical_layer_boundary",
        "domain_structure_conflict",
        "other",
    ]
    severity: str
    description: str
    evidence: list[str] = Field(default_factory=list)
    recommendation: str

    @field_validator("severity", mode="before")
    @classmethod
    def normalize_severity(cls, value: Any) -> str:
        normalized = str(value or "medium").strip().lower()
        return normalized if normalized in {"low", "medium", "high"} else "medium"


class ArchitectureCritique(BaseModel):
    requires_revision: bool
    summary: str
    issues: list[CritiqueIssue] = Field(default_factory=list)
    preserved_decisions: list[str] = Field(default_factory=list)
