from __future__ import annotations

import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

TRACE_NUMERIC_METRICS = (
    "trace_available",
    "trace_event_count",
    "trace_invalid_json_line_count",
    "llm_call_count",
    "successful_llm_call_count",
    "failed_llm_call_count",
    "failed_llm_call_ratio",
    "api_error_count",
    "parse_error_count",
    "retry_call_count",
    "retry_call_ratio",
    "total_call_duration_ms",
    "average_call_duration_ms",
    "max_call_duration_ms",
    "trace_elapsed_ms",
    "total_system_prompt_char_count",
    "total_user_prompt_char_count",
    "total_response_char_count",
    "distinct_role_count",
    "critic_round_count",
    "revision_request_count",
    "critic_issue_count",
    "refinement_round_count",
    "workflow_converged",
    "stopped_by_iteration_limit",
    "services_added_during_refinement_count",
    "services_removed_during_refinement_count",
    "interactions_added_during_refinement_count",
    "interactions_removed_during_refinement_count",
    "final_snapshot_service_count",
    "final_snapshot_communication_count",
)


def unavailable_trace_metrics() -> dict[str, int | float | None | str]:
    metrics: dict[str, int | float | None | str] = {
        "trace_available": 0,
        "trace_status": "missing",
        "run_status": "",
        "roles": "",
        "critic_issue_categories": "",
        "critic_issue_severities": "",
    }
    for name in TRACE_NUMERIC_METRICS:
        if name != "trace_available":
            metrics[name] = None
    return metrics


def analyze_trace(
    trace_path: Path | None,
    *,
    max_events: int | None = None,
    max_bytes: int | None = None,
) -> tuple[dict[str, int | float | None | str], list[str]]:
    """Extract automatic process metrics from a run JSONL trace.

    The comparison CLI leaves both limits unset and therefore analyzes the full
    trace. UI callers can pass bounds to keep an interactive preview responsive.
    """
    if trace_path is None or not trace_path.exists():
        return unavailable_trace_metrics(), []

    events: list[dict[str, Any]] = []
    warnings: list[str] = []
    invalid_json_line_count = 0
    bytes_read = 0
    line_number = 0
    with trace_path.open("rb") as handle:
        while max_events is None or len(events) < max_events:
            if max_bytes is None:
                raw_line = handle.readline()
            else:
                remaining_bytes = max_bytes - bytes_read
                if remaining_bytes <= 0:
                    if handle.read(1):
                        warnings.append(
                            f"Trace analysis stopped after {max_bytes:,} bytes; process metrics are partial."
                        )
                    break
                raw_line = handle.readline(remaining_bytes + 1)
                if len(raw_line) > remaining_bytes:
                    warnings.append(
                        f"Trace analysis stopped after {max_bytes:,} bytes; process metrics are partial."
                    )
                    break
                bytes_read += len(raw_line)
            if not raw_line:
                break
            line_number += 1
            line = raw_line.decode("utf-8", errors="replace")
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                warnings.append(f"Trace line {line_number} is not valid JSON: {exc.msg}.")
                invalid_json_line_count += 1
                continue
            if not isinstance(event, dict):
                warnings.append(f"Trace line {line_number} is not a JSON object.")
                invalid_json_line_count += 1
                continue
            events.append(event)

        if max_events is not None and len(events) >= max_events and handle.read(1):
            warnings.append(
                f"Trace analysis stopped after {max_events:,} valid events; process metrics are partial."
            )

    if not events:
        metrics = unavailable_trace_metrics()
        metrics["trace_available"] = 1
        metrics["trace_status"] = "partial" if warnings else "empty"
        metrics["trace_event_count"] = 0
        metrics["trace_invalid_json_line_count"] = invalid_json_line_count
        return metrics, warnings

    calls = [event for event in events if event.get("event_type") == "agent_call"]
    for event in calls:
        raw_duration = event.get("duration_ms")
        if raw_duration not in (None, "") and not is_finite_number(raw_duration):
            warnings.append("An agent_call contains a non-finite duration_ms value; zero was used.")
    call_durations = [float_value(event.get("duration_ms")) for event in calls]
    api_error_count = sum(1 for event in calls if event.get("status") == "api_error")
    parse_error_count = sum(1 for event in calls if event.get("status") == "parse_error")
    failed_llm_call_count = api_error_count + parse_error_count
    retry_call_count = sum(1 for event in calls if integer_value(event.get("attempt")) > 1)
    critique_decisions = [
        event for event in events if event.get("event_type") == "critique_decision"
    ]
    snapshots = [
        event for event in events if event.get("event_type") == "architecture_snapshot"
    ]
    roles = sorted(
        {
            str(event.get("role", "")).strip()
            for event in calls
            if str(event.get("role", "")).strip()
        }
    )
    issue_categories: Counter[str] = Counter()
    issue_severities: Counter[str] = Counter()
    for decision in critique_decisions:
        issue_categories.update(string_items(decision.get("issue_categories")))
        issue_severities.update(string_items(decision.get("issue_severities")))

    latest_snapshot = snapshots[-1].get("architecture", {}) if snapshots else {}
    final_services, final_communications = snapshot_sizes(latest_snapshot)
    timestamps = [parse_timestamp(event.get("timestamp")) for event in events]
    timestamps = [timestamp for timestamp in timestamps if timestamp is not None]
    run_finished = next(
        (event for event in reversed(events) if event.get("event_type") == "run_finished"),
        None,
    )

    if run_finished is None:
        warnings.append("Trace has no run_finished event and may be incomplete.")

    metrics: dict[str, int | float | None | str] = {
        "trace_available": 1,
        "trace_status": "partial" if warnings else "calculated",
        "trace_event_count": len(events),
        "trace_invalid_json_line_count": invalid_json_line_count,
        "llm_call_count": len(calls),
        "successful_llm_call_count": sum(
            1 for event in calls if event.get("status") == "success"
        ),
        "failed_llm_call_count": failed_llm_call_count,
        "failed_llm_call_ratio": failed_llm_call_count / len(calls) if calls else None,
        "api_error_count": api_error_count,
        "parse_error_count": parse_error_count,
        "retry_call_count": retry_call_count,
        "retry_call_ratio": retry_call_count / len(calls) if calls else None,
        "total_call_duration_ms": sum(call_durations),
        "average_call_duration_ms": sum(call_durations) / len(calls) if calls else None,
        "max_call_duration_ms": max(call_durations, default=None),
        "trace_elapsed_ms": (
            round((max(timestamps) - min(timestamps)).total_seconds() * 1000, 3)
            if len(timestamps) >= 2
            else 0.0
        ),
        "total_system_prompt_char_count": sum(
            len(string_value(event.get("system_prompt"))) for event in calls
        ),
        "total_user_prompt_char_count": sum(
            len(string_value(event.get("user_prompt"))) for event in calls
        ),
        "total_response_char_count": sum(
            len(string_value(event.get("raw_response"))) for event in calls
        ),
        "distinct_role_count": len(roles),
        "critic_round_count": len(critique_decisions),
        "revision_request_count": sum(
            1 for event in critique_decisions if bool(event.get("requires_revision"))
        ),
        "critic_issue_count": sum(
            integer_value(event.get("issue_count")) for event in critique_decisions
        ),
        "refinement_round_count": sum(
            1 for event in snapshots if event.get("phase") == "refined"
        ),
        "workflow_converged": int(
            any(event.get("event_type") == "workflow_converged" for event in events)
        ),
        "stopped_by_iteration_limit": int(
            any(event.get("event_type") == "workflow_stopped" for event in events)
        ),
        "services_added_during_refinement_count": sum(
            len(string_items(event.get("changes", {}).get("services_added")))
            for event in snapshots
            if event.get("phase") == "refined" and isinstance(event.get("changes"), dict)
        ),
        "services_removed_during_refinement_count": sum(
            len(string_items(event.get("changes", {}).get("services_removed")))
            for event in snapshots
            if event.get("phase") == "refined" and isinstance(event.get("changes"), dict)
        ),
        "interactions_added_during_refinement_count": sum(
            len(string_items(event.get("changes", {}).get("interactions_added")))
            for event in snapshots
            if event.get("phase") == "refined" and isinstance(event.get("changes"), dict)
        ),
        "interactions_removed_during_refinement_count": sum(
            len(string_items(event.get("changes", {}).get("interactions_removed")))
            for event in snapshots
            if event.get("phase") == "refined" and isinstance(event.get("changes"), dict)
        ),
        "final_snapshot_service_count": final_services,
        "final_snapshot_communication_count": final_communications,
        "run_status": string_value(run_finished.get("status")) if run_finished else "",
        "roles": "|".join(roles),
        "critic_issue_categories": format_counter(issue_categories),
        "critic_issue_severities": format_counter(issue_severities),
    }
    return metrics, warnings


def string_value(value: Any) -> str:
    return value if isinstance(value, str) else ""


def string_items(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def integer_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def float_value(value: Any) -> float:
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return 0.0
    return numeric_value if math.isfinite(numeric_value) else 0.0


def is_finite_number(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def snapshot_sizes(architecture: Any) -> tuple[int | None, int | None]:
    if not isinstance(architecture, dict):
        return (None, None)
    microservices = architecture.get("microservices")
    if not isinstance(microservices, list):
        return (None, None)

    service_count = len(microservices)
    communication_count = 0
    for microservice in microservices:
        if not isinstance(microservice, dict):
            continue
        communications = microservice.get("communicates_with")
        if isinstance(communications, list):
            communication_count += len(communications)
    return (service_count, communication_count)


def format_counter(counter: Counter[str]) -> str:
    return "|".join(f"{key}:{count}" for key, count in sorted(counter.items()))
