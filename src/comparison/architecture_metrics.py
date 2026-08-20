from __future__ import annotations

import csv
import io
import math
import re
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ARCHITECTURE_NUMERIC_METRICS = (
    "service_count",
    "unique_service_count",
    "duplicate_service_name_count",
    "malformed_service_row_count",
    "raw_declared_communication_count",
    "declared_communication_count",
    "duplicate_communication_count",
    "valid_communication_count",
    "invalid_communication_target_count",
    "self_communication_count",
    "communication_density",
    "average_outgoing_communications",
    "max_outgoing_communications",
    "average_incoming_communications",
    "max_incoming_communications",
    "isolated_services_count",
    "isolated_services_ratio",
    "reciprocal_communication_pair_count",
    "reciprocity_ratio",
    "total_responsibility_word_count",
    "average_responsibility_word_count",
    "responsibility_word_count_stddev",
    "min_responsibility_word_count",
    "max_responsibility_word_count",
    "short_responsibility_count",
    "short_responsibility_ratio",
    "average_responsibility_token_jaccard",
)

REQUIRED_COLUMNS = {
    "microservice_name",
    "responsibility",
    "communicates_with",
}


@dataclass(slots=True)
class ArchitectureMetrics:
    metrics: dict[str, int | float | None]
    service_names: set[str]
    declared_edges: set[tuple[str, str]]
    valid_edges: set[tuple[str, str]]
    warnings: list[str]


def analyze_architecture_csv(
    csv_path: Path,
    *,
    min_responsibility_words: int = 5,
) -> ArchitectureMetrics:
    """Calculate architecture metrics from a generated decomposition CSV."""
    if min_responsibility_words < 1:
        raise ValueError("min_responsibility_words must be at least 1.")

    text = read_text(csv_path)
    reader = csv.DictReader(io.StringIO(text))
    columns = {column.strip() for column in (reader.fieldnames or []) if column}
    missing_columns = REQUIRED_COLUMNS - columns
    if missing_columns:
        formatted = ", ".join(sorted(missing_columns))
        raise ValueError(f"Missing required CSV columns: {formatted}.")

    records: list[tuple[str, str, list[str]]] = []
    warnings: list[str] = []
    malformed_service_row_count = 0

    for row_number, raw_row in enumerate(reader, start=2):
        row = {(key or "").strip(): (value or "").strip() for key, value in raw_row.items()}
        service_name = row.get("microservice_name", "")
        responsibility = row.get("responsibility", "")
        if not service_name or not responsibility:
            malformed_service_row_count += 1
            warnings.append(
                f"Row {row_number} was ignored because microservice_name or responsibility is empty."
            )
            continue

        records.append(
            (
                normalize_label(service_name),
                responsibility,
                parse_communication_targets(row.get("communicates_with", "")),
            )
        )

    service_names = {service_name for service_name, _, _ in records}
    service_count = len(records)
    unique_service_count = len(service_names)
    duplicate_service_name_count = service_count - unique_service_count
    if duplicate_service_name_count:
        warnings.append(
            f"Found {duplicate_service_name_count} duplicate normalized service name(s)."
        )

    raw_declared_communication_count = 0
    declared_edges: set[tuple[str, str]] = set()
    self_edges: set[tuple[str, str]] = set()
    invalid_edges: set[tuple[str, str]] = set()

    for source, _, targets in records:
        for target_text in targets:
            target = normalize_label(target_text)
            if not target:
                continue
            raw_declared_communication_count += 1
            edge = (source, target)
            declared_edges.add(edge)
            if source == target:
                self_edges.add(edge)
            elif target not in service_names:
                invalid_edges.add(edge)

    valid_edges = {
        edge
        for edge in declared_edges
        if edge[0] != edge[1] and edge[1] in service_names
    }
    duplicate_communication_count = raw_declared_communication_count - len(declared_edges)

    outgoing = {service_name: 0 for service_name in service_names}
    incoming = {service_name: 0 for service_name in service_names}
    for source, target in valid_edges:
        outgoing[source] += 1
        incoming[target] += 1

    isolated_services_count = sum(
        1
        for service_name in service_names
        if outgoing[service_name] == 0 and incoming[service_name] == 0
    )
    reciprocal_pairs = {
        tuple(sorted((source, target)))
        for source, target in valid_edges
        if (target, source) in valid_edges
    }

    responsibility_word_counts = [word_count(responsibility) for _, responsibility, _ in records]
    responsibility_token_sets = [tokenize(responsibility) for _, responsibility, _ in records]
    overlap_values = [
        jaccard_similarity(left, right)
        for index, left in enumerate(responsibility_token_sets)
        for right in responsibility_token_sets[index + 1 :]
    ]

    denominator = unique_service_count * (unique_service_count - 1)
    metrics: dict[str, int | float | None] = {
        "service_count": service_count,
        "unique_service_count": unique_service_count,
        "duplicate_service_name_count": duplicate_service_name_count,
        "malformed_service_row_count": malformed_service_row_count,
        "raw_declared_communication_count": raw_declared_communication_count,
        "declared_communication_count": len(declared_edges),
        "duplicate_communication_count": duplicate_communication_count,
        "valid_communication_count": len(valid_edges),
        "invalid_communication_target_count": len(invalid_edges),
        "self_communication_count": len(self_edges),
        "communication_density": (len(valid_edges) / denominator) if denominator else 0.0,
        "average_outgoing_communications": mean_or_none(list(outgoing.values())),
        "max_outgoing_communications": max(outgoing.values(), default=0),
        "average_incoming_communications": mean_or_none(list(incoming.values())),
        "max_incoming_communications": max(incoming.values(), default=0),
        "isolated_services_count": isolated_services_count,
        "isolated_services_ratio": (
            isolated_services_count / unique_service_count if unique_service_count else None
        ),
        "reciprocal_communication_pair_count": len(reciprocal_pairs),
        "reciprocity_ratio": (
            (2 * len(reciprocal_pairs)) / len(valid_edges) if valid_edges else 0.0
        ),
        "total_responsibility_word_count": sum(responsibility_word_counts),
        "average_responsibility_word_count": mean_or_none(responsibility_word_counts),
        "responsibility_word_count_stddev": population_stddev_or_none(
            responsibility_word_counts
        ),
        "min_responsibility_word_count": min(responsibility_word_counts, default=None),
        "max_responsibility_word_count": max(responsibility_word_counts, default=None),
        "short_responsibility_count": sum(
            1 for count in responsibility_word_counts if count < min_responsibility_words
        ),
        "short_responsibility_ratio": (
            sum(1 for count in responsibility_word_counts if count < min_responsibility_words)
            / service_count
            if service_count
            else None
        ),
        "average_responsibility_token_jaccard": mean_or_none(overlap_values),
    }
    return ArchitectureMetrics(
        metrics=metrics,
        service_names=service_names,
        declared_edges=declared_edges,
        valid_edges=valid_edges,
        warnings=warnings,
    )


def read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def normalize_label(value: str) -> str:
    return " ".join(value.casefold().split())


def parse_communication_targets(value: str) -> list[str]:
    return [target.strip() for target in value.split(";") if target.strip()]


def word_count(value: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", value, flags=re.UNICODE))


def tokenize(value: str) -> set[str]:
    return {
        token.casefold()
        for token in re.findall(r"\b[\w'-]+\b", value, flags=re.UNICODE)
        if len(token) > 2
    }


def jaccard_similarity(left: set[str], right: set[str]) -> float:
    union = left | right
    if not union:
        return 1.0
    return len(left & right) / len(union)


def mean_or_none(values: list[int | float]) -> float | None:
    return statistics.fmean(values) if values else None


def population_stddev_or_none(values: list[int | float]) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return 0.0
    return math.sqrt(statistics.pvariance(values))
