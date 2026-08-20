from __future__ import annotations

import json
import logging
from time import monotonic
from typing import Any, Callable, TypeVar

from pydantic import BaseModel, ValidationError

from .models import ArchitectureCritique, DomainAnalysis, StructuralAnalysis
from .prompts import (
    ARCHITECT_SYSTEM_PROMPT,
    CRITIC_SYSTEM_PROMPT,
    DOMAIN_SYSTEM_PROMPT,
    REFINER_SYSTEM_PROMPT,
    STRUCTURAL_SYSTEM_PROMPT,
    build_critique_prompt,
    build_domain_prompt,
    build_refinement_prompt,
    build_structural_prompt,
    build_synthesis_prompt,
)
from .trace import TraceWriter
from ..config import ModelConfig
from ..response_parser import (
    MicroserviceProposal,
    build_candidate_json_strings,
    decode_candidate,
    parse_model_response,
)


LOGGER = logging.getLogger("microservice-decomposition")
StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


class AgentWorkflow:
    def __init__(
        self,
        *,
        client: Any,
        model_config: ModelConfig,
        max_attempts: int,
        max_refinement_rounds: int,
        trace_writer: TraceWriter,
    ) -> None:
        self.client = client
        self.model_config = model_config
        self.max_attempts = max_attempts
        self.max_refinement_rounds = max_refinement_rounds
        self.trace_writer = trace_writer

    def run(self, *, evidence: str, template_name: str) -> MicroserviceProposal:
        domain = self._invoke_model(
            role="domain_analyst",
            phase="analysis",
            iteration=0,
            system_prompt=DOMAIN_SYSTEM_PROMPT,
            user_prompt=build_domain_prompt(evidence),
            parser=lambda raw: parse_typed_response(raw, DomainAnalysis),
            schema=DomainAnalysis,
        )
        structural = self._invoke_model(
            role="structural_analyst",
            phase="analysis",
            iteration=0,
            system_prompt=STRUCTURAL_SYSTEM_PROMPT,
            user_prompt=build_structural_prompt(evidence),
            parser=lambda raw: parse_typed_response(raw, StructuralAnalysis),
            schema=StructuralAnalysis,
        )
        proposal = self._invoke_model(
            role="architect",
            phase="synthesis",
            iteration=0,
            system_prompt=ARCHITECT_SYSTEM_PROMPT,
            user_prompt=build_synthesis_prompt(
                evidence=evidence,
                domain_analysis=domain,
                structural_analysis=structural,
                template_name=template_name,
            ),
            parser=parse_model_response,
            schema=MicroserviceProposal,
        )
        self._record_snapshot(proposal, phase="candidate", iteration=0)

        for iteration in range(1, self.max_refinement_rounds + 1):
            critique = self._invoke_model(
                role="critic",
                phase="critique",
                iteration=iteration,
                system_prompt=CRITIC_SYSTEM_PROMPT,
                user_prompt=build_critique_prompt(
                    evidence=evidence,
                    domain_analysis=domain,
                    structural_analysis=structural,
                    candidate=proposal,
                ),
                parser=lambda raw: parse_typed_response(raw, ArchitectureCritique),
                schema=ArchitectureCritique,
            )
            self.trace_writer.record(
                "critique_decision",
                iteration=iteration,
                requires_revision=critique.requires_revision,
                issue_count=len(critique.issues),
                issue_categories=[issue.category for issue in critique.issues],
                issue_severities=[issue.severity for issue in critique.issues],
            )
            if not critique.requires_revision:
                self.trace_writer.record("workflow_converged", iteration=iteration)
                return proposal

            previous = proposal
            proposal = self._invoke_model(
                role="refiner",
                phase="refinement",
                iteration=iteration,
                system_prompt=REFINER_SYSTEM_PROMPT,
                user_prompt=build_refinement_prompt(
                    evidence=evidence,
                    domain_analysis=domain,
                    structural_analysis=structural,
                    candidate=proposal,
                    critique=critique,
                ),
                parser=parse_model_response,
                schema=MicroserviceProposal,
            )
            self._record_snapshot(
                proposal,
                phase="refined",
                iteration=iteration,
                changes=compare_proposals(previous, proposal),
            )

        self.trace_writer.record(
            "workflow_stopped",
            reason="max_refinement_rounds_reached",
            iteration=self.max_refinement_rounds,
        )
        return proposal

    def _invoke_model(
        self,
        *,
        role: str,
        phase: str,
        iteration: int,
        system_prompt: str,
        user_prompt: str,
        parser: Callable[[str], StructuredModel],
        schema: type[BaseModel],
    ) -> StructuredModel:
        conversation = [{"role": "user", "content": user_prompt}]
        last_error = "No attempts performed."

        for attempt in range(1, self.max_attempts + 1):
            started = monotonic()
            try:
                raw_response = self.client.generate(
                    system_prompt=system_prompt,
                    messages=conversation,
                    model_config=self.model_config,
                )
            except Exception as exc:  # noqa: BLE001
                last_error = f"API error: {exc}"
                self.trace_writer.record(
                    "agent_call",
                    role=role,
                    phase=phase,
                    iteration=iteration,
                    attempt=attempt,
                    status="api_error",
                    duration_ms=round((monotonic() - started) * 1000, 3),
                    system_prompt=system_prompt,
                    user_prompt=conversation[-1]["content"],
                    error=str(exc),
                )
                continue

            try:
                parsed = parser(raw_response)
            except Exception as exc:  # noqa: BLE001
                last_error = f"Parse error: {exc}"
                self.trace_writer.record(
                    "agent_call",
                    role=role,
                    phase=phase,
                    iteration=iteration,
                    attempt=attempt,
                    status="parse_error",
                    duration_ms=round((monotonic() - started) * 1000, 3),
                    system_prompt=system_prompt,
                    user_prompt=conversation[-1]["content"],
                    raw_response=raw_response,
                    error=str(exc),
                )
                if attempt < self.max_attempts:
                    conversation.append({"role": "assistant", "content": raw_response})
                    conversation.append(
                        {
                            "role": "user",
                            "content": build_schema_repair_prompt(schema, str(exc)),
                        }
                    )
                continue

            self.trace_writer.record(
                "agent_call",
                role=role,
                phase=phase,
                iteration=iteration,
                attempt=attempt,
                status="success",
                duration_ms=round((monotonic() - started) * 1000, 3),
                system_prompt=system_prompt,
                user_prompt=conversation[-1]["content"],
                raw_response=raw_response,
                parsed_output=parsed.model_dump(mode="json"),
            )
            return parsed

        raise RuntimeError(f"Agent '{role}' failed. Last error: {last_error}")

    def _record_snapshot(
        self,
        proposal: MicroserviceProposal,
        *,
        phase: str,
        iteration: int,
        changes: dict[str, Any] | None = None,
    ) -> None:
        self.trace_writer.record(
            "architecture_snapshot",
            phase=phase,
            iteration=iteration,
            architecture=proposal.model_dump(mode="json"),
            changes=changes or {},
        )


def parse_typed_response(raw_response: str, schema: type[StructuredModel]) -> StructuredModel:
    errors: list[str] = []
    for candidate in build_candidate_json_strings(raw_response):
        try:
            return schema.model_validate(decode_candidate(candidate))
        except (ValidationError, ValueError, SyntaxError) as exc:
            errors.append(f"{exc.__class__.__name__}: {exc}")
    raise ValueError("\n".join(errors[:5]) or "No JSON candidate detected.")


def build_schema_repair_prompt(schema: type[BaseModel], error: str) -> str:
    return (
        "The previous response did not match the required JSON schema. Return corrected JSON only.\n"
        f"Error: {error[:1000]}\n"
        f"Schema: {json.dumps(schema.model_json_schema(), ensure_ascii=False)}"
    )


def compare_proposals(
    previous: MicroserviceProposal,
    current: MicroserviceProposal,
) -> dict[str, list[str]]:
    previous_names = {item.microservice_name for item in previous.microservices}
    current_names = {item.microservice_name for item in current.microservices}
    previous_edges = {
        f"{item.microservice_name} -> {target}"
        for item in previous.microservices
        for target in item.communicates_with
    }
    current_edges = {
        f"{item.microservice_name} -> {target}"
        for item in current.microservices
        for target in item.communicates_with
    }
    return {
        "services_added": sorted(current_names - previous_names),
        "services_removed": sorted(previous_names - current_names),
        "interactions_added": sorted(current_edges - previous_edges),
        "interactions_removed": sorted(previous_edges - current_edges),
    }
