from __future__ import annotations

from .models import ArchitectureCritique, DomainAnalysis, StructuralAnalysis
from ..prompt_builder import FEW_SHOT_EXAMPLES, JSON_SCHEMA_SNIPPET
from ..response_parser import MicroserviceProposal


DOMAIN_SYSTEM_PROMPT = """You are the domain-analysis agent in a microservice architecture team.
Extract business capabilities, domain entities, and business rules only when supported by the supplied evidence.
Keep evidence references short and traceable. Record uncertainty instead of inventing information.
Return valid JSON only."""

STRUCTURAL_SYSTEM_PROMPT = """You are the structural-analysis agent in a microservice architecture team.
Identify cohesive code clusters, modules, entrypoints, and dependency risks from static evidence.
Do not infer business boundaries from package names alone. Record uncertainty explicitly.
Return valid JSON only."""

ARCHITECT_SYSTEM_PROMPT = """You are the synthesis agent in a microservice architecture team.
Create a conservative architecture by reconciling domain and structural evidence.
Each service must represent a cohesive business capability and be supported by evidence.
Avoid nanoservices, generic umbrella services, technology-layer services, and unsupported services.
Every communication target must name a declared service. Return valid JSON only."""

CRITIC_SYSTEM_PROMPT = """You are the independent architecture-critic agent.
Evaluate the candidate against the original evidence and the two specialist analyses.
Do not redesign merely for stylistic preference. Request revision only for evidence-backed defects.
Return valid JSON only."""

REFINER_SYSTEM_PROMPT = """You are the refinement agent in a microservice architecture team.
Revise the candidate only where the critic found an evidence-backed defect. Preserve sound decisions.
The result must use cohesive business boundaries and internally consistent directed interactions.
Return valid JSON only."""


def build_domain_prompt(evidence: str) -> str:
    return _with_schema(
        "Analyze the evidence and produce the domain view.\n\nEvidence:\n" + evidence,
        DomainAnalysis,
    )


def build_structural_prompt(evidence: str) -> str:
    return _with_schema(
        "Analyze the evidence and produce the structural view.\n\nEvidence:\n" + evidence,
        StructuralAnalysis,
    )


def build_synthesis_prompt(
    *,
    evidence: str,
    domain_analysis: DomainAnalysis,
    structural_analysis: StructuralAnalysis,
    template_name: str,
) -> str:
    example = FEW_SHOT_EXAMPLES + "\n" if template_name == "few_shot" else ""
    return (
        f"{example}Reconcile the evidence and specialist analyses into one candidate architecture.\n"
        "Return JSON only using this schema:\n"
        f"{JSON_SCHEMA_SNIPPET}\n\n"
        f"Domain analysis:\n{domain_analysis.model_dump_json(indent=2)}\n\n"
        f"Structural analysis:\n{structural_analysis.model_dump_json(indent=2)}\n\n"
        f"Original evidence:\n{evidence}"
    )


def build_critique_prompt(
    *,
    evidence: str,
    domain_analysis: DomainAnalysis,
    structural_analysis: StructuralAnalysis,
    candidate: MicroserviceProposal,
) -> str:
    rubric = """Inspect these defect categories and use exactly the identifier in parentheses:
- unsupported or invented service (unsupported_service);
- omitted capability supported by evidence (omitted_capability);
- nano- or overly coarse service (nanoservice, coarse_service);
- overlapping responsibilities or weak cohesion (responsibility_overlap);
- excessive, missing, or unsupported interaction (excessive_coupling, missing_interaction, unsupported_interaction);
- interaction target not declared as a service (invalid_interaction_target);
- boundary based only on a technical layer (technical_layer_boundary);
- conflict between domain and structural evidence (domain_structure_conflict);
- another material defect not covered above (other).
Use requires_revision=false when there is no material evidence-backed issue."""
    body = (
        f"{rubric}\n\nCandidate:\n{candidate.model_dump_json(indent=2)}\n\n"
        f"Domain analysis:\n{domain_analysis.model_dump_json(indent=2)}\n\n"
        f"Structural analysis:\n{structural_analysis.model_dump_json(indent=2)}\n\n"
        f"Original evidence:\n{evidence}"
    )
    return _with_schema(body, ArchitectureCritique)


def build_refinement_prompt(
    *,
    evidence: str,
    domain_analysis: DomainAnalysis,
    structural_analysis: StructuralAnalysis,
    candidate: MicroserviceProposal,
    critique: ArchitectureCritique,
) -> str:
    return (
        "Refine the candidate using the critique. Preserve decisions listed as sound and do not add unsupported services.\n"
        "Return JSON only using this schema:\n"
        f"{JSON_SCHEMA_SNIPPET}\n\n"
        f"Candidate:\n{candidate.model_dump_json(indent=2)}\n\n"
        f"Critique:\n{critique.model_dump_json(indent=2)}\n\n"
        f"Domain analysis:\n{domain_analysis.model_dump_json(indent=2)}\n\n"
        f"Structural analysis:\n{structural_analysis.model_dump_json(indent=2)}\n\n"
        f"Original evidence:\n{evidence}"
    )


def _with_schema(prompt: str, schema_type: type) -> str:
    schema = schema_type.model_json_schema()
    import json

    return prompt + "\n\nRequired JSON schema:\n" + json.dumps(schema, ensure_ascii=False)
