from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .metric_models import DecompositionResult


EXPECTED_COLUMNS = ["microservice_name", "responsibility", "communicates_with"]


@dataclass(slots=True)
class RunDescriptor:
    project_name: str
    provider: str
    model_name: str
    prompt_template: str
    run_id: str
    csv_path: Path


def discover_run_descriptors(outputs_dir: Path) -> list[RunDescriptor]:
    descriptors: list[RunDescriptor] = []
    for csv_path in sorted(outputs_dir.rglob("run_*.csv")):
        descriptor = parse_run_path(outputs_dir, csv_path)
        if descriptor is not None:
            descriptors.append(descriptor)
    return descriptors


def parse_run_path(outputs_dir: Path, csv_path: Path) -> RunDescriptor | None:
    relative = csv_path.relative_to(outputs_dir)
    parts = relative.parts
    if len(parts) != 5:
        return None

    project_name, provider, model_name, prompt_template, file_name = parts
    if not file_name.startswith("run_") or not file_name.endswith(".csv"):
        return None

    run_id = file_name[:-4]
    return RunDescriptor(
        project_name=project_name,
        provider=provider,
        model_name=model_name,
        prompt_template=prompt_template,
        run_id=run_id,
        csv_path=csv_path,
    )


def load_decomposition_result(descriptor: RunDescriptor) -> DecompositionResult:
    dataframe = pd.read_csv(descriptor.csv_path)
    missing_columns = [column for column in EXPECTED_COLUMNS if column not in dataframe.columns]
    if missing_columns:
        raise ValueError(
            f"Result CSV {descriptor.csv_path} is missing required columns: {missing_columns}"
        )

    normalized = dataframe.copy()
    normalized["microservice_name"] = normalized["microservice_name"].fillna("").astype(str).str.strip()
    normalized["responsibility"] = normalized["responsibility"].fillna("").astype(str).str.strip()
    normalized["communicates_with"] = normalized["communicates_with"].fillna("").astype(str)

    valid_rows = normalized[normalized["microservice_name"] != ""].copy()
    service_names = valid_rows["microservice_name"].tolist()
    unique_service_names = list(dict.fromkeys(service_names))
    declared_services = set(unique_service_names)

    edges: set[tuple[str, str]] = set()
    warnings: list[str] = []

    duplicate_names = [name for name, count in Counter(service_names).items() if count > 1]
    if duplicate_names:
        warnings.append(
            "Duplicate microservice names detected: " + ", ".join(sorted(duplicate_names))
        )

    for row in valid_rows.itertuples(index=False):
        source = row.microservice_name
        targets = parse_communicates_with(row.communicates_with)
        seen_in_row: set[str] = set()

        for target in targets:
            if target in seen_in_row:
                continue
            seen_in_row.add(target)

            if target == source:
                warnings.append(f"Self-communication ignored for service '{source}'.")
                continue
            if target not in declared_services:
                warnings.append(
                    f"Unknown communication target '{target}' referenced by service '{source}'."
                )
                continue

            edges.add((source, target))

    incoming_counts = {service_name: 0 for service_name in unique_service_names}
    outgoing_counts = {service_name: 0 for service_name in unique_service_names}
    for source, target in edges:
        outgoing_counts[source] += 1
        incoming_counts[target] += 1

    responsibility_word_counts = {
        row.microservice_name: count_words(row.responsibility) for row in valid_rows.itertuples(index=False)
    }

    return DecompositionResult(
        project_name=descriptor.project_name,
        provider=descriptor.provider,
        model_name=descriptor.model_name,
        prompt_template=descriptor.prompt_template,
        run_id=descriptor.run_id,
        csv_path=descriptor.csv_path,
        dataframe=dataframe,
        valid_rows=valid_rows,
        service_names=service_names,
        unique_service_names=unique_service_names,
        edges=edges,
        incoming_counts=incoming_counts,
        outgoing_counts=outgoing_counts,
        responsibility_word_counts=responsibility_word_counts,
        warnings=sorted(set(warnings)),
    )


def parse_communicates_with(value: object) -> list[str]:
    if value is None or pd.isna(value):
        return []

    text = str(value).strip()
    if not text or text.lower() in {"none", "nan"}:
        return []

    parts = [part.strip() for part in text.split(";")]
    return [part for part in parts if part]


def count_words(text: str) -> int:
    return len([part for part in str(text).split() if part.strip()])
