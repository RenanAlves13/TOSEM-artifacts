from __future__ import annotations

import ast
import json
import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator


class ParseFailure(RuntimeError):
    """Raised when the model response cannot be parsed into the expected schema."""


class MicroserviceRecord(BaseModel):
    microservice_name: str
    responsibility: str
    communicates_with: list[str] = Field(default_factory=list)

    @field_validator("microservice_name", "responsibility", mode="before")
    @classmethod
    def normalize_text(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("Field cannot be empty.")
        return text

    @field_validator("communicates_with", mode="before")
    @classmethod
    def normalize_communications(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            cleaned = [str(item).strip() for item in value if str(item).strip()]
            return deduplicate_preserving_order(cleaned)
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped or stripped.lower() == "none":
                return []
            parts = re.split(r"[;,]", stripped)
            cleaned = [part.strip() for part in parts if part.strip()]
            return deduplicate_preserving_order(cleaned)
        return [str(value).strip()]


class MicroserviceProposal(BaseModel):
    microservices: list[MicroserviceRecord]


def parse_model_response(raw_response: str) -> MicroserviceProposal:
    errors: list[str] = []
    for candidate in build_candidate_json_strings(raw_response):
        try:
            payload = decode_candidate(candidate)
            normalized_payload = normalize_payload(payload)
            proposal = MicroserviceProposal.model_validate(normalized_payload)
            return normalize_proposal(proposal)
        except (json.JSONDecodeError, SyntaxError, ValidationError, ValueError) as exc:
            errors.append(f"{exc.__class__.__name__}: {exc}")
            continue

    error_summary = "\n".join(errors[:5]) if errors else "No JSON candidate detected."
    raise ParseFailure(error_summary)


def normalize_proposal(proposal: MicroserviceProposal) -> MicroserviceProposal:
    seen_names: set[str] = set()
    normalized: list[MicroserviceRecord] = []
    for item in proposal.microservices:
        if item.microservice_name in seen_names:
            continue
        seen_names.add(item.microservice_name)
        communications = [
            service_name
            for service_name in deduplicate_preserving_order(item.communicates_with)
            if service_name and service_name != item.microservice_name
        ]
        normalized.append(
            MicroserviceRecord(
                microservice_name=item.microservice_name.strip(),
                responsibility=item.responsibility.strip(),
                communicates_with=communications,
            )
        )
    return MicroserviceProposal(microservices=normalized)


def build_candidate_json_strings(raw_response: str) -> list[str]:
    stripped = strip_markdown_fences(raw_response).strip()
    candidates: list[str] = []

    if stripped:
        candidates.append(stripped)

    code_blocks = re.findall(r"```(?:json)?\s*(.*?)```", raw_response, flags=re.DOTALL | re.IGNORECASE)
    candidates.extend(block.strip() for block in code_blocks if block.strip())

    if "{" in raw_response and "}" in raw_response:
        start = raw_response.find("{")
        end = raw_response.rfind("}") + 1
        snippet = raw_response[start:end].strip()
        if snippet:
            candidates.append(snippet)

    unique_candidates: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        candidate = candidate.strip()
        if candidate and candidate not in seen:
            seen.add(candidate)
            unique_candidates.append(candidate)
    return unique_candidates


def decode_candidate(candidate: str) -> Any:
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        repaired = repair_json_string(candidate)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            parsed = ast.literal_eval(repair_python_literal(candidate))
            if not isinstance(parsed, (dict, list)):
                raise ValueError("Parsed candidate is not a JSON object/list.")
            return parsed


def normalize_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, list):
        return {"microservices": payload}
    if not isinstance(payload, dict):
        raise ValueError("Top-level payload must be an object or list.")

    if "microservices" in payload:
        return payload

    for alternative_key in ("services", "microservice_list", "proposed_microservices"):
        if alternative_key in payload:
            return {"microservices": payload[alternative_key]}

    raise ValueError("Payload does not contain a 'microservices' field.")


def repair_json_string(candidate: str) -> str:
    repaired = candidate.strip()
    repaired = strip_markdown_fences(repaired)
    repaired = repaired.replace("“", '"').replace("”", '"').replace("’", "'")
    repaired = re.sub(r",(\s*[}\]])", r"\1", repaired)
    repaired = re.sub(r"\bNone\b", "null", repaired)
    repaired = re.sub(r"\bTrue\b", "true", repaired)
    repaired = re.sub(r"\bFalse\b", "false", repaired)
    return repaired


def repair_python_literal(candidate: str) -> str:
    repaired = strip_markdown_fences(candidate.strip())
    repaired = repaired.replace("“", '"').replace("”", '"').replace("’", "'")
    repaired = re.sub(r",(\s*[}\]])", r"\1", repaired)
    repaired = re.sub(r"\btrue\b", "True", repaired)
    repaired = re.sub(r"\bfalse\b", "False", repaired)
    repaired = re.sub(r"\bnull\b", "None", repaired)
    return repaired


def strip_markdown_fences(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped, flags=re.IGNORECASE).strip()
        stripped = re.sub(r"```$", "", stripped).strip()
    return stripped


def deduplicate_preserving_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
