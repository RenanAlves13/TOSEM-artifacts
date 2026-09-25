#!/usr/bin/env python3
"""Evaluate generated architectures against the reference decompositions.

The ``--approach`` option selects either direct-prompt or agent-based outputs.
The score uses a responsibility-aware one-to-one service mapping: service names
contribute to a match, but a different name is not required when the
responsibilities share domain concepts and sufficiently similar specific terms.
Communications are then evaluated after translating their endpoints through that
semantic service mapping.

The produced workbook contains one tab per selected project, provider averages,
embedded charts, and the complete service/communication matching audit.

The score is deterministic and deliberately transparent rather than a black-box
quality judgement.  The matching threshold and every selected mapping are written
into the workbook so that a researcher can review or adjust the decision rule.
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import statistics
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import xlsxwriter


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS_DIR = ROOT / "outputs"
REFERENCE_DIR = ROOT / "ground true"
SERVICE_MATCH_THRESHOLD = 0.42
PROVIDER_ORDER = ("deepseek", "openai", "anthropic")
PROVIDER_LABELS = {
    "deepseek": "DeepSeek",
    "openai": "OpenAI",
    "anthropic": "Claude",
}
PROMPT_ORDER = ("zero_shot", "few_shot")

REFERENCE_PATHS = {
    "7ep": REFERENCE_DIR / "7ep" / "reference_microservice_architecture_7ep.csv",
    "acmeair": REFERENCE_DIR / "acmeair" / "reference_microservices_architecture_acmeair.csv",
    "cargo-tracker": REFERENCE_DIR
    / "cargo-tracker"
    / "reference_microservices_architecture_cargo_tracker.csv",
    "daytrader7": REFERENCE_DIR
    / "daytrader7"
    / "reference_microservices_architecture_daytrader.csv",
    "Jokul": REFERENCE_DIR / "jokul" / "reference_microservices_architecture_jokul.csv",
    "jpetstore": REFERENCE_DIR
    / "jpetstore"
    / "reference_microservices_architecture_jpetstore.csv",
    "pet-clinic": REFERENCE_DIR
    / "pet-clinic"
    / "reference_microservices_architecture_spring_petclinic_modulith.csv",
    "TNTConcept": REFERENCE_DIR
    / "TNTConcept"
    / "reference_microservices_architecture_tntconcept.csv",
}

STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "each", "for", "from",
    "in", "including", "is", "it", "its", "of", "on", "or", "that", "the", "their", "to",
    "with", "while", "will", "would", "shall", "should", "must", "may", "this", "these",
    "those", "through", "across", "into", "using", "used", "use", "service", "services",
    "system", "application", "data", "information", "manage", "manages", "managed", "managing",
    "responsible", "responsibility", "handle", "handles", "handled", "handling", "provide",
    "provides", "provided", "providing", "support", "supports", "supported", "supporting",
    "allow", "allows", "allowed", "allowing", "ensure", "ensures", "ensuring", "maintain",
    "maintains", "maintaining", "control", "controls", "controlling", "complete", "current",
    "associated", "related", "based", "within", "without", "when", "where", "which", "also",
    "all", "any", "more", "than", "such", "other", "one", "two", "new", "existing",
}

# Concept aliases make semantically equivalent vocabulary comparable.  They are
# broad domain terms, not project/run-specific labels.  Raw terms remain in the
# comparison too, so the aliases supplement rather than replace textual evidence.
CONCEPT_ALIASES = {
    "identity": {
        "auth", "authentication", "authenticate", "authorization", "authorize", "identity",
        "access", "login", "logon", "signin", "signon", "logout", "signout", "credential",
        "credentials", "password", "session", "role", "roles", "profile", "profiles",
    },
    "catalog": {
        "catalog", "catalogue", "listing", "listings", "browse", "search", "product",
        "products", "category", "categories", "movie", "movies", "film", "films", "book",
        "books", "asset", "assets", "item", "items",
    },
    "media": {
        "media", "video", "videos", "playback", "stream", "streaming", "download", "uploads",
        "upload", "file", "files", "mp4", "repository", "storage", "delivery",
    },
    "cargo": {"cargo", "shipment", "shipments", "consignment", "consignments", "delivery"},
    "routing": {
        "route", "routes", "routing", "itinerary", "itineraries", "voyage", "voyages", "trip",
        "trips", "path", "paths", "planning", "replanning", "rerouting",
    },
    "tracking": {
        "track", "tracking", "monitor", "monitoring", "status", "location", "locations",
        "history", "geographic", "dashboard", "dashboards",
    },
    "event": {
        "event", "events", "handling", "receipt", "receiving", "loading", "unloading",
        "customs", "pickup", "claim", "ingestion", "ingest", "ingests",
    },
    "network": {"logistics", "network", "airport", "airports", "flight", "flights"},
    "booking": {"booking", "bookings", "reservation", "reservations", "checkout", "order", "orders"},
    "customer": {"customer", "customers", "client", "clients"},
    "reader": {"reader", "readers", "librarian", "librarians"},
    "owner": {"owner", "owners", "guardian", "guardians", "tutor", "tutors"},
    "inventory": {"inventory", "stock", "availability", "backorder", "backordered", "quantity", "quantities"},
    "cart": {"cart", "carts", "basket", "baskets"},
    "trade": {"trade", "trading", "market", "markets", "quotation", "quotations", "portfolio", "position", "positions"},
    "account": {"account", "accounts", "investor", "investors", "loyalty", "miles", "balance", "balances"},
    "environment": {"environment", "administration", "administrative", "reset", "recreate", "recreation", "simulation"},
    "audit": {"audit", "auditing", "traceability", "diagnostic", "diagnostics", "failure", "failures"},
    "pet": {"pet", "pets", "animal", "animals"},
    "visit": {"visit", "visits", "appointment", "appointments", "treatment", "treatments"},
    "veterinarian": {"veterinarian", "veterinarians", "veterinary", "vet", "vets", "specialty", "specialties"},
    "workforce": {"workforce", "employee", "employees", "contract", "contracts", "vacation", "vacations", "probation"},
    "work_tracking": {"timesheet", "timesheets", "time", "activity", "activities", "occupation", "occupations", "workload", "hours"},
    "crm": {"crm", "organization", "organizations", "contact", "contacts", "collaborator", "collaborators", "interaction", "interactions"},
    "proposal": {"proposal", "proposals", "potential", "potentials", "billable", "quotation", "quotations"},
    "project": {"project", "projects", "projectlinked", "projectrelated"},
    "financial": {"financial", "finance", "finances", "accounting", "cashflow", "credit", "funding", "fiscal"},
    "billing": {"billing", "billings", "invoice", "invoices", "receivable", "payable", "tax", "taxes"},
    "content": {"content", "publication", "publications", "tutorial", "tutorials", "notice", "notices", "magazine", "magazines"},
    "file_storage": {"attachment", "attachments", "storage", "uploaded", "upload", "directory", "directories", "filename", "filenames"},
    "notification": {"notification", "notifications", "email", "emails", "mail", "alert", "alerts"},
    "commissioning": {"commissioning", "commission", "commissions", "reviewer", "reviewers"},
    "reporting": {"report", "reports", "reporting", "export", "exports", "csv", "pdf", "html", "rtf", "xls", "odt"},
    "configuration": {"configuration", "configurable", "settings", "setting", "reference", "preferences", "preference", "department", "departments"},
    "demo_utility": {"demo", "demonstration", "mathematics", "mathematical", "fibonacci", "ackermann", "addition", "integer"},
}

ALIAS_BY_TOKEN = {
    token: concept for concept, tokens in CONCEPT_ALIASES.items() for token in tokens
}


@dataclass(frozen=True)
class Service:
    name: str
    responsibility: str
    communicates_with: tuple[str, ...]

    @property
    def key(self) -> str:
        return normalized_label(self.name)


@dataclass(frozen=True)
class Candidate:
    project: str
    provider: str
    model: str
    prompt: str
    csv_path: Path


@dataclass
class Evaluation:
    candidate: Candidate
    reference_path: Path
    generated_services: list[Service]
    reference_services: list[Service]
    service_matches: dict[int, int]
    pair_scores: dict[tuple[int, int], float]
    service_rows: list[dict[str, object]]
    edge_rows: list[dict[str, object]]
    metrics: dict[str, float | int]


def read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def canonical(value: str) -> str:
    value = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", value)
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    return value.casefold()


def normalized_label(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", canonical(value)))


def normalize_token(token: str) -> str:
    if token == "routing":
        return "route"
    if token.endswith("ies") and len(token) > 4:
        return f"{token[:-3]}y"
    if token.endswith("s") and len(token) > 4 and not token.endswith("ss"):
        return token[:-1]
    return token


def raw_tokens(value: str) -> set[str]:
    tokens = {
        normalize_token(token)
        for token in re.findall(r"[a-z0-9]+", canonical(value))
    }
    return {token for token in tokens if len(token) > 2 and token not in STOP_WORDS}


def features(value: str) -> tuple[set[str], set[str]]:
    tokens = raw_tokens(value)
    concepts = {
        ALIAS_BY_TOKEN[token]
        for token in tokens
        if token in ALIAS_BY_TOKEN
    }
    return tokens, concepts


def jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 0.0
    return len(left & right) / len(left | right)


def dice(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 0.0
    return (2 * len(left & right)) / (len(left) + len(right))


def pair_similarity(generated: Service, reference: Service) -> float:
    """Return a transparent name + responsibility semantic similarity in [0, 1]."""
    generated_name_tokens, generated_name_concepts = features(generated.name)
    reference_name_tokens, reference_name_concepts = features(reference.name)
    generated_resp_tokens, generated_resp_concepts = features(generated.responsibility)
    reference_resp_tokens, reference_resp_concepts = features(reference.responsibility)

    name_jaccard = jaccard(generated_name_tokens, reference_name_tokens)
    name_concept = dice(generated_name_concepts, reference_name_concepts)
    name_sequence = SequenceMatcher(
        None, normalized_label(generated.name), normalized_label(reference.name)
    ).ratio()
    name_score = max(name_jaccard, 0.65 * name_jaccard + 0.25 * name_concept + 0.10 * name_sequence)

    token_jaccard = jaccard(generated_resp_tokens, reference_resp_tokens)
    token_dice = dice(generated_resp_tokens, reference_resp_tokens)
    concept_score = dice(generated_resp_concepts, reference_resp_concepts)
    # The maximum guards against long descriptions diluting a clear common
    # responsibility concept; the raw lexical terms prevent aliases alone from
    # deciding a match.
    responsibility_score = max(
        0.55 * token_jaccard + 0.15 * token_dice + 0.30 * concept_score,
        0.40 * token_dice + 0.60 * concept_score,
    )

    return min(1.0, 0.40 * name_score + 0.60 * responsibility_score)


def precision_recall_f1(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def parse_services(path: Path) -> list[Service]:
    reader = csv.DictReader(io.StringIO(read_text(path)))
    columns = {normalized_label(name): name for name in reader.fieldnames or [] if name}
    name_column = columns.get("microservice name") or columns.get("microservice_name")
    responsibility_column = columns.get("description") or columns.get("responsibility")
    communication_column = columns.get("communicate with") or columns.get("communicates with")
    if not name_column or not responsibility_column:
        raise ValueError(f"{path} does not contain service-name and responsibility columns.")

    services: list[Service] = []
    for raw_row in reader:
        name = (raw_row.get(name_column) or "").strip()
        responsibility = (raw_row.get(responsibility_column) or "").strip()
        if not name or not responsibility:
            continue
        targets = tuple(
            target.strip()
            for target in (raw_row.get(communication_column) or "").split(";")
            if target.strip() and canonical(target).strip() not in {"none", "n/a", "na", "-"}
        )
        services.append(Service(name, responsibility, targets))
    return services


def selected_candidates(
    approach: str,
    projects: tuple[str, ...],
) -> tuple[list[Candidate], list[str]]:
    """Use the latest successful metadata record and reconcile TNT filenames."""
    metadata_path = OUTPUTS_DIR / "metadata.csv"
    records: dict[tuple[str, str, str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in csv.DictReader(io.StringIO(read_text(metadata_path))):
        if (row.get("approach") or "direct").casefold() != approach:
            continue
        project = (row.get("project_name") or "").strip()
        if project not in projects:
            continue
        provider = (row.get("provider") or "").strip().casefold()
        model = (row.get("model") or row.get("model_name") or "").strip()
        prompt = (row.get("prompt_template") or "").strip()
        run = (row.get("run_number") or row.get("run_id") or "").strip()
        if not all((project, provider, model, prompt, run)):
            continue
        records[(project, provider, model, prompt, run)].append(row)

    candidates: list[Candidate] = []
    notices: list[str] = []
    for (project, provider, model, prompt, run), rows in records.items():
        successful_rows = [row for row in rows if (row.get("status") or "").casefold() == "success"]
        if not successful_rows:
            continue
        row = successful_rows[-1]
        output_path_text = (row.get("output_path") or "").strip()
        possible = Path(output_path_text)
        csv_path = possible if possible.is_absolute() else ROOT / possible
        if not csv_path.exists():
            sibling_csvs = sorted(csv_path.parent.glob("*.csv"))
            if len(sibling_csvs) == 1:
                notices.append(
                    f"{project}/{provider}/{prompt}: reconciled missing metadata filename to {sibling_csvs[0].name}."
                )
                csv_path = sibling_csvs[0]
            else:
                notices.append(f"{project}/{provider}/{prompt}: output CSV not found.")
                continue
        if project not in REFERENCE_PATHS:
            notices.append(f"{project}/{provider}/{prompt}: no reference architecture configured.")
            continue
        candidates.append(Candidate(project, provider, model, prompt, csv_path))

    candidates.sort(
        key=lambda item: (
            projects.index(item.project),
            PROVIDER_ORDER.index(item.provider) if item.provider in PROVIDER_ORDER else 99,
            PROMPT_ORDER.index(item.prompt) if item.prompt in PROMPT_ORDER else 99,
            item.model,
        )
    )
    return candidates, notices


def best_service_mapping(
    generated: list[Service], reference: list[Service]
) -> tuple[dict[int, int], dict[tuple[int, int], float]]:
    scores = {
        (generated_index, reference_index): pair_similarity(generated_service, reference_service)
        for generated_index, generated_service in enumerate(generated)
        for reference_index, reference_service in enumerate(reference)
    }

    @lru_cache(maxsize=None)
    def solve(generated_index: int, used_mask: int) -> tuple[float, tuple[tuple[int, int], ...]]:
        if generated_index == len(generated):
            return 0.0, ()
        best_score, best_pairs = solve(generated_index + 1, used_mask)
        for reference_index in range(len(reference)):
            if used_mask & (1 << reference_index):
                continue
            score = scores[(generated_index, reference_index)]
            if score < SERVICE_MATCH_THRESHOLD:
                continue
            tail_score, tail_pairs = solve(generated_index + 1, used_mask | (1 << reference_index))
            candidate_score = score + tail_score
            if candidate_score > best_score:
                best_score = candidate_score
                best_pairs = ((generated_index, reference_index), *tail_pairs)
        return best_score, best_pairs

    _, pairs = solve(0, 0)
    return {generated_index: reference_index for generated_index, reference_index in pairs}, scores


def target_index(target: str, services: list[Service]) -> int | None:
    normalized_target = normalized_label(target)
    exact = [index for index, service in enumerate(services) if service.key == normalized_target]
    if len(exact) == 1:
        return exact[0]
    # A tolerant fallback deals with punctuation/"Service" differences in a
    # communication list without using semantic guesswork for an undeclared node.
    stripped_target = normalized_target.replace(" service", "").strip()
    matches = [
        index
        for index, service in enumerate(services)
        if service.key.replace(" service", "").strip() == stripped_target
    ]
    return matches[0] if len(matches) == 1 else None


def evaluate(candidate: Candidate) -> Evaluation:
    generated = parse_services(candidate.csv_path)
    reference_path = REFERENCE_PATHS[candidate.project]
    reference = parse_services(reference_path)
    mapping, scores = best_service_mapping(generated, reference)

    service_rows: list[dict[str, object]] = []
    for generated_index, service in enumerate(generated):
        reference_index = mapping.get(generated_index)
        matched_reference = reference[reference_index] if reference_index is not None else None
        service_rows.append(
            {
                "provider": PROVIDER_LABELS.get(candidate.provider, candidate.provider),
                "prompt": candidate.prompt,
                "generated_service": service.name,
                "generated_responsibility": service.responsibility,
                "matched_reference_service": matched_reference.name if matched_reference else "",
                "reference_responsibility": matched_reference.responsibility if matched_reference else "",
                "similarity_score": scores[(generated_index, reference_index)] if reference_index is not None else max(
                    scores[(generated_index, reference_index)] for reference_index in range(len(reference))
                ) if reference else 0.0,
                "decision": "TP — semantic service match" if matched_reference else "FP — no reference service match",
            }
        )
    for reference_index, service in enumerate(reference):
        if reference_index not in mapping.values():
            service_rows.append(
                {
                    "provider": PROVIDER_LABELS.get(candidate.provider, candidate.provider),
                    "prompt": candidate.prompt,
                    "generated_service": "",
                    "generated_responsibility": "",
                    "matched_reference_service": service.name,
                    "reference_responsibility": service.responsibility,
                    "similarity_score": "",
                    "decision": "FN — unmatched reference service",
                }
            )

    reference_edges = {
        (source_index, target_index_value)
        for source_index, source in enumerate(reference)
        for target in source.communicates_with
        if (target_index_value := target_index(target, reference)) is not None
        and source_index != target_index_value
    }
    predicted_edges: set[tuple[int, int | None, str]] = set()
    for source_index, source in enumerate(generated):
        for target in source.communicates_with:
            predicted_edges.add((source_index, target_index(target, generated), target))

    matched_reference_edges: set[tuple[int, int]] = set()
    edge_rows: list[dict[str, object]] = []
    for source_index, target_generated_index, target_text in sorted(
        predicted_edges, key=lambda item: (item[0], item[2])
    ):
        source_reference_index = mapping.get(source_index)
        target_reference_index = mapping.get(target_generated_index) if target_generated_index is not None else None
        mapped_edge = (
            (source_reference_index, target_reference_index)
            if source_reference_index is not None and target_reference_index is not None
            else None
        )
        is_true_positive = mapped_edge in reference_edges and mapped_edge not in matched_reference_edges
        if is_true_positive and mapped_edge is not None:
            matched_reference_edges.add(mapped_edge)
        decision = (
            "TP — mapped semantic communication"
            if is_true_positive
            else "FP — communication absent from reference after service mapping"
        )
        edge_rows.append(
            {
                "provider": PROVIDER_LABELS.get(candidate.provider, candidate.provider),
                "prompt": candidate.prompt,
                "generated_source": generated[source_index].name,
                "generated_target": target_text,
                "mapped_reference_source": reference[source_reference_index].name if source_reference_index is not None else "",
                "mapped_reference_target": reference[target_reference_index].name if target_reference_index is not None else "",
                "decision": decision,
            }
        )
    for source_reference_index, target_reference_index in sorted(reference_edges - matched_reference_edges):
        edge_rows.append(
            {
                "provider": PROVIDER_LABELS.get(candidate.provider, candidate.provider),
                "prompt": candidate.prompt,
                "generated_source": "",
                "generated_target": "",
                "mapped_reference_source": reference[source_reference_index].name,
                "mapped_reference_target": reference[target_reference_index].name,
                "decision": "FN — unmatched reference communication",
            }
        )

    service_tp = len(mapping)
    service_fp = len(generated) - service_tp
    service_fn = len(reference) - service_tp
    edge_tp = len(matched_reference_edges)
    edge_fp = sum(1 for row in edge_rows if str(row["decision"]).startswith("FP"))
    edge_fn = len(reference_edges) - edge_tp
    service_precision, service_recall, service_f1 = precision_recall_f1(service_tp, service_fp, service_fn)
    edge_precision, edge_recall, edge_f1 = precision_recall_f1(edge_tp, edge_fp, edge_fn)
    total_precision, total_recall, total_f1 = precision_recall_f1(
        service_tp + edge_tp, service_fp + edge_fp, service_fn + edge_fn
    )
    metrics: dict[str, float | int] = {
        "generated_services": len(generated),
        "reference_services": len(reference),
        "service_tp": service_tp,
        "service_fp": service_fp,
        "service_fn": service_fn,
        "service_precision": service_precision,
        "service_recall": service_recall,
        "service_f1": service_f1,
        "generated_communications": len(predicted_edges),
        "reference_communications": len(reference_edges),
        "communication_tp": edge_tp,
        "communication_fp": edge_fp,
        "communication_fn": edge_fn,
        "communication_precision": edge_precision,
        "communication_recall": edge_recall,
        "communication_f1": edge_f1,
        "combined_precision": total_precision,
        "combined_recall": total_recall,
        "combined_f1": total_f1,
    }
    return Evaluation(
        candidate, reference_path, generated, reference, mapping, scores, service_rows, edge_rows, metrics
    )


METRIC_COLUMNS = (
    ("Provider", "provider"), ("Model", "model"), ("Prompt", "prompt"),
    ("Generated services", "generated_services"), ("Reference services", "reference_services"),
    ("Service TP", "service_tp"), ("Service FP", "service_fp"), ("Service FN", "service_fn"),
    ("Service precision", "service_precision"), ("Service recall", "service_recall"), ("Service F1", "service_f1"),
    ("Generated communications", "generated_communications"), ("Reference communications", "reference_communications"),
    ("Communication TP", "communication_tp"), ("Communication FP", "communication_fp"), ("Communication FN", "communication_fn"),
    ("Communication precision", "communication_precision"), ("Communication recall", "communication_recall"), ("Communication F1", "communication_f1"),
    ("Combined precision", "combined_precision"), ("Combined recall", "combined_recall"), ("Combined F1", "combined_f1"),
)


def write_metric_table(
    worksheet: xlsxwriter.worksheet.Worksheet,
    start_row: int,
    evaluations: list[Evaluation],
    formats: dict[str, xlsxwriter.format.Format],
) -> tuple[int, int]:
    worksheet.write_row(start_row, 0, [title for title, _ in METRIC_COLUMNS], formats["header"])
    for row_offset, evaluation in enumerate(evaluations, start=1):
        values = {
            "provider": PROVIDER_LABELS.get(evaluation.candidate.provider, evaluation.candidate.provider),
            "model": evaluation.candidate.model,
            "prompt": evaluation.candidate.prompt,
            **evaluation.metrics,
        }
        for column, (_, key) in enumerate(METRIC_COLUMNS):
            value = values[key]
            cell_format = formats["percentage"] if key.endswith(("precision", "recall", "f1")) else formats["body"]
            worksheet.write(start_row + row_offset, column, value, cell_format)
    return start_row, start_row + len(evaluations)


def provider_average_rows(evaluations: list[Evaluation]) -> list[dict[str, object]]:
    grouped: dict[str, list[Evaluation]] = defaultdict(list)
    for evaluation in evaluations:
        grouped[evaluation.candidate.provider].append(evaluation)
    averages: list[dict[str, object]] = []
    for provider in PROVIDER_ORDER:
        provider_evaluations = grouped.get(provider, [])
        if not provider_evaluations:
            continue
        averages.append(
            {
                "provider": PROVIDER_LABELS[provider],
                "model": "Mean across prompt templates",
                "prompt": "zero_shot + few_shot",
                **{
                    key: statistics.fmean(float(item.metrics[key]) for item in provider_evaluations)
                    for _, key in METRIC_COLUMNS[3:]
                },
            }
        )
    return averages


def write_provider_average_table(
    worksheet: xlsxwriter.worksheet.Worksheet,
    start_row: int,
    average_rows: list[dict[str, object]],
    formats: dict[str, xlsxwriter.format.Format],
) -> tuple[int, int]:
    worksheet.write(start_row, 0, "Provider means (macro average across direct prompts)", formats["section"])
    header_row = start_row + 1
    worksheet.write_row(header_row, 0, [title for title, _ in METRIC_COLUMNS], formats["header"])
    for row_offset, values in enumerate(average_rows, start=1):
        for column, (_, key) in enumerate(METRIC_COLUMNS):
            cell_format = formats["percentage"] if key.endswith(("precision", "recall", "f1")) else formats["body"]
            worksheet.write(header_row + row_offset, column, values[key], cell_format)
    return header_row, header_row + len(average_rows)


def write_audit_tables(
    worksheet: xlsxwriter.worksheet.Worksheet,
    start_row: int,
    evaluations: list[Evaluation],
    formats: dict[str, xlsxwriter.format.Format],
) -> int:
    worksheet.write(start_row, 0, "Semantic service-matching audit", formats["section"])
    service_header_row = start_row + 1
    service_headers = [
        "Provider", "Prompt", "Generated service", "Generated responsibility", "Matched reference service",
        "Reference responsibility", "Similarity score", "Decision",
    ]
    worksheet.write_row(service_header_row, 0, service_headers, formats["header"])
    row = service_header_row + 1
    for evaluation in evaluations:
        for audit in evaluation.service_rows:
            decision = str(audit["decision"])
            decision_format = formats["true_positive"] if decision.startswith("TP") else formats["false_negative"] if decision.startswith("FN") else formats["false_positive"]
            values = [
                audit["provider"], audit["prompt"], audit["generated_service"], audit["generated_responsibility"],
                audit["matched_reference_service"], audit["reference_responsibility"], audit["similarity_score"], decision,
            ]
            for column, value in enumerate(values):
                fmt = formats["score"] if column == 6 and isinstance(value, float) else decision_format if column == 7 else formats["audit"]
                worksheet.write(row, column, value, fmt)
            row += 1

    row += 1
    worksheet.write(row, 0, "Communication-matching audit", formats["section"])
    edge_header_row = row + 1
    edge_headers = [
        "Provider", "Prompt", "Generated source", "Generated target", "Mapped reference source",
        "Mapped reference target", "Decision",
    ]
    worksheet.write_row(edge_header_row, 0, edge_headers, formats["header"])
    row = edge_header_row + 1
    for evaluation in evaluations:
        for audit in evaluation.edge_rows:
            decision = str(audit["decision"])
            decision_format = formats["true_positive"] if decision.startswith("TP") else formats["false_negative"] if decision.startswith("FN") else formats["false_positive"]
            values = [
                audit["provider"], audit["prompt"], audit["generated_source"], audit["generated_target"],
                audit["mapped_reference_source"], audit["mapped_reference_target"], decision,
            ]
            for column, value in enumerate(values):
                worksheet.write(row, column, value, decision_format if column == 6 else formats["audit"])
            row += 1
    return row


def add_charts(
    workbook: xlsxwriter.Workbook,
    worksheet: xlsxwriter.worksheet.Worksheet,
    metric_header_row: int,
    metric_last_row: int,
    average_header_row: int,
    average_last_row: int,
    project: str,
) -> None:
    # xlsxwriter uses zero-indexed rows/columns.  The categories combine provider
    # and prompt in a hidden helper column so the first chart remains legible.
    helper_column = len(METRIC_COLUMNS) + 1
    worksheet.write(metric_header_row, helper_column, "Provider / prompt")
    for row in range(metric_header_row + 1, metric_last_row + 1):
        worksheet.write_formula(row, helper_column, f'=A{row + 1}&" / "&C{row + 1}')

    chart_f1 = workbook.add_chart({"type": "column"})
    for title, metric_key, color in (
        ("Service F1", "service_f1", "#2F75B5"),
        ("Communication F1", "communication_f1", "#ED7D31"),
        ("Combined F1", "combined_f1", "#70AD47"),
    ):
        column = next(index for index, (_, key) in enumerate(METRIC_COLUMNS) if key == metric_key)
        chart_f1.add_series({
            "name": title,
            "categories": [worksheet.name, metric_header_row + 1, helper_column, metric_last_row, helper_column],
            "values": [worksheet.name, metric_header_row + 1, column, metric_last_row, column],
            "fill": {"color": color},
        })
    chart_f1.set_title({"name": f"{project}: F1 by provider and prompt"})
    chart_f1.set_y_axis({"name": "F1", "min": 0, "max": 1, "major_gridlines": {"visible": True}})
    chart_f1.set_legend({"position": "bottom"})
    chart_f1.set_size({"width": 740, "height": 340})
    worksheet.insert_chart("A2", chart_f1)

    chart_prf = workbook.add_chart({"type": "column"})
    for title, metric_key, color in (
        ("Combined precision", "combined_precision", "#5B9BD5"),
        ("Combined recall", "combined_recall", "#FFC000"),
        ("Combined F1", "combined_f1", "#A5A5A5"),
    ):
        column = next(index for index, (_, key) in enumerate(METRIC_COLUMNS) if key == metric_key)
        chart_prf.add_series({
            "name": title,
            "categories": [worksheet.name, average_header_row + 1, 0, average_last_row, 0],
            "values": [worksheet.name, average_header_row + 1, column, average_last_row, column],
            "fill": {"color": color},
        })
    chart_prf.set_title({"name": f"{project}: mean overall precision, recall and F1"})
    chart_prf.set_y_axis({"name": "Score", "min": 0, "max": 1, "major_gridlines": {"visible": True}})
    chart_prf.set_legend({"position": "bottom"})
    chart_prf.set_size({"width": 740, "height": 340})
    worksheet.insert_chart("M2", chart_prf)


def result_paths(approach: str) -> tuple[Path, Path, Path]:
    result_dir = OUTPUTS_DIR / f"{approach}_reference_evaluation"
    stem = f"{approach}_reference_semantic_metrics"
    return result_dir, result_dir / f"{stem}.xlsx", result_dir / f"{stem}.csv"


def approach_label(approach: str) -> str:
    return "Direct-prompt" if approach == "direct" else "Agent-based"


def write_workbook(
    evaluations: list[Evaluation],
    notices: list[str],
    *,
    approach: str,
    projects: tuple[str, ...],
) -> tuple[Path, Path]:
    result_dir, workbook_path, csv_path = result_paths(approach)
    result_dir.mkdir(parents=True, exist_ok=True)
    label = approach_label(approach)
    workbook = xlsxwriter.Workbook(workbook_path)
    workbook.set_properties({
        "title": f"{label} semantic reference evaluation",
        "subject": "Precision, recall and F1 against reference architectures",
        "comments": f"Generated from {approach} outputs only.",
    })
    formats = {
        "title": workbook.add_format({"bold": True, "font_size": 16, "font_color": "#1F4E78"}),
        "subtitle": workbook.add_format({"font_color": "#595959", "italic": True, "text_wrap": True}),
        "section": workbook.add_format({"bold": True, "font_size": 12, "font_color": "#1F4E78"}),
        "header": workbook.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": "#1F4E78", "text_wrap": True, "valign": "vcenter", "border": 1}),
        "body": workbook.add_format({"border": 1, "valign": "top"}),
        "percentage": workbook.add_format({"border": 1, "num_format": "0.0%", "valign": "top"}),
        "audit": workbook.add_format({"border": 1, "text_wrap": True, "valign": "top"}),
        "score": workbook.add_format({"border": 1, "num_format": "0.000", "valign": "top"}),
        "true_positive": workbook.add_format({"border": 1, "bg_color": "#E2F0D9", "text_wrap": True, "valign": "top"}),
        "false_positive": workbook.add_format({"border": 1, "bg_color": "#FCE4D6", "text_wrap": True, "valign": "top"}),
        "false_negative": workbook.add_format({"border": 1, "bg_color": "#FFF2CC", "text_wrap": True, "valign": "top"}),
    }

    by_project: dict[str, list[Evaluation]] = defaultdict(list)
    for evaluation in evaluations:
        by_project[evaluation.candidate.project].append(evaluation)

    for project in projects:
        project_evaluations = by_project.get(project, [])
        worksheet = workbook.add_worksheet(project[:31])
        worksheet.freeze_panes(6, 0)
        worksheet.hide_gridlines(2)
        worksheet.set_tab_color("#1F4E78")
        worksheet.set_column("A:A", 17)
        worksheet.set_column("B:B", 28)
        worksheet.set_column("C:C", 24)
        worksheet.set_column("D:F", 15)
        worksheet.set_column("G:H", 14)
        worksheet.set_column("I:V", 16)
        worksheet.set_column("W:W", 24)
        worksheet.set_column("X:X", 3, None, {"hidden": True})
        worksheet.write("A1", f"{project} -- {label} vs. reference architecture", formats["title"])
        worksheet.merge_range(
            "A6:V6",
            f"Only {approach} outputs are included.  A true-positive service may have a different name when its responsibility has sufficient semantic similarity to a reference service.  Communications are evaluated after this service mapping.  Threshold: 0.420.",
            formats["subtitle"],
        )
        if not project_evaluations:
            worksheet.write("A8", f"No {approach} outputs were available for this project.", formats["subtitle"])
            continue
        metric_header_row, metric_last_row = write_metric_table(worksheet, 7, project_evaluations, formats)
        average_header_row, average_last_row = write_provider_average_table(
            worksheet, metric_last_row + 3, provider_average_rows(project_evaluations), formats
        )
        add_charts(
            workbook, worksheet, metric_header_row, metric_last_row, average_header_row, average_last_row, project
        )
        audit_end_row = write_audit_tables(worksheet, average_last_row + 3, project_evaluations, formats)
        worksheet.autofilter(metric_header_row, 0, metric_last_row, len(METRIC_COLUMNS) - 1)
        worksheet.set_row(5, 42)
        worksheet.set_row(metric_header_row, 38)
        worksheet.set_landscape()
        worksheet.set_paper(9)
        worksheet.fit_to_pages(1, 0)
        worksheet.set_footer(f"Generated {approach} semantic evaluation")

    workbook.close()

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["project", *[key for _, key in METRIC_COLUMNS]],
        )
        writer.writeheader()
        for evaluation in evaluations:
            writer.writerow(
                {
                    "project": evaluation.candidate.project,
                    "provider": PROVIDER_LABELS.get(evaluation.candidate.provider, evaluation.candidate.provider),
                    "model": evaluation.candidate.model,
                    "prompt": evaluation.candidate.prompt,
                    **evaluation.metrics,
                }
            )

    if notices:
        (result_dir / "generation_notices.txt").write_text("\n".join(notices) + "\n", encoding="utf-8")
    return workbook_path, csv_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Calculate reference-aware precision, recall, and F1 for generated architectures.",
    )
    parser.add_argument(
        "--approach",
        choices=("direct", "agent"),
        default="direct",
        help="Generation approach to evaluate (default: direct).",
    )
    parser.add_argument(
        "--project",
        action="append",
        choices=tuple(REFERENCE_PATHS),
        help="Project to include. Repeat for multiple projects; defaults to all projects.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    projects = tuple(args.project) if args.project else tuple(REFERENCE_PATHS)
    candidates, notices = selected_candidates(args.approach, projects)
    expected_count = len(projects) * len(PROVIDER_ORDER) * len(PROMPT_ORDER)
    if len(candidates) != expected_count:
        notices.append(f"Expected {expected_count} {args.approach} outputs; selected {len(candidates)}.")
    evaluations = [evaluate(candidate) for candidate in candidates]
    workbook_path, csv_path = write_workbook(
        evaluations,
        notices,
        approach=args.approach,
        projects=projects,
    )
    print(f"Wrote {workbook_path}")
    print(f"Wrote {csv_path}")
    print(f"Evaluated {len(evaluations)} {args.approach} outputs across {len(projects)} projects.")
    for notice in notices:
        print(f"NOTICE: {notice}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
