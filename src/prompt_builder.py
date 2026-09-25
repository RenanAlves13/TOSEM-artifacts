from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import PromptLimits
from .requirements_loader import RequirementsData, normalize_header
from .requirement_translations import load_english_requirements
from .static_analysis_loader import StaticAnalysisData, StaticArtifact


JSON_SCHEMA_SNIPPET = """{
  "microservices": [
    {
      "microservice_name": "string",
      "responsibility": "string",
      "communicates_with": ["string"]
    }
  ]
}"""

BASE_SYSTEM_PROMPT = """You are a software architect specialized in decomposing monolithic systems into microservice architectures.

Your task is to analyze the provided system information and propose the best possible microservice architecture.

You will receive two types of evidence:

1. Requirements extracted from a CSV file.
2. Static analysis results extracted from the source code.

Use the requirements to understand the system's functional responsibilities and domain concepts.
Use the static analysis results to understand code structure, dependencies, modules, entities, and coupling.
Treat packages, build modules, and technical layers as evidence, not as pre-defined microservice boundaries.
Do not assume that the number of modules or packages should equal the number of microservices.
Group or split code only when the business responsibilities and structural evidence support that decision.

Your goal is to propose a microservice architecture that maximizes functional cohesion and minimizes unnecessary coupling.

Do not invent unsupported services.
Do not create nanoservices.
Do not create generic services such as "System Service" or "Management Service" unless strongly justified by the evidence.
Prefer services aligned with business capabilities, domain entities, and cohesive functional responsibilities.
Consider:
- requirements-derived responsibilities;
- domain entities and concepts;
- structural code dependencies;
- coupling between modules/classes;
- possible bounded contexts;
- internal cohesion;
- low inter-service coupling;
- communication between services.

Return only valid JSON following this schema:
""" + JSON_SCHEMA_SNIPPET

FEW_SHOT_EXAMPLES = """Examples (generic and independent from the real system):

These examples show that packages and build modules are structural clues, not a one-to-one list of microservices.

Example 1 — online store: several technical packages, four business services

Requirements:
- [REQ-01] Users can create and update customer profiles.
- [REQ-02] Users can browse a product catalog and search items.
- [REQ-03] Users can place orders and track order status.
- [REQ-04] Payments must be authorized and recorded.

Static analysis evidence:
- Packages: web, application, persistence, common, customer, catalog, ordering, payment.
- The web, application, persistence, and common packages are technical layers shared by the customer, catalog, and ordering code.
- Internal dependencies: ordering depends on customer and catalog; payment depends on ordering.
- Entry points: CustomerController, CatalogController, OrderController, PaymentController.
- There are eight packages, but the technical-layer packages are not business-service candidates.

Valid answer:
{
  "microservices": [
    {
      "microservice_name": "Customer Service",
      "responsibility": "Manages customer profiles and customer-related account data.",
      "communicates_with": ["Order Service"]
    },
    {
      "microservice_name": "Catalog Service",
      "responsibility": "Manages product browsing, search, and product information.",
      "communicates_with": ["Order Service"]
    },
    {
      "microservice_name": "Order Service",
      "responsibility": "Handles order placement, order status, and order lifecycle orchestration.",
      "communicates_with": ["Customer Service", "Catalog Service", "Payment Service"]
    },
    {
      "microservice_name": "Payment Service",
      "responsibility": "Handles payment authorization and payment records.",
      "communicates_with": ["Order Service"]
    }
  ]
}

Example 2 — appointment scheduling: two build modules, three business services

Requirements:
- [REQ-01] Patients maintain contact information and search for available professionals.
- [REQ-02] Patients can book, confirm, and cancel appointments.
- [REQ-03] Patients receive a reminder when an appointment is confirmed.

Static analysis evidence:
- Build modules: clinic-web and clinic-core.
- clinic-web contains PatientController, ProfessionalController, AppointmentController, and ReminderController.
- clinic-core contains profile, availability, appointment, and reminder classes.
- Appointment classes depend on profile and availability classes; reminder classes consume confirmed appointment events.
- clinic-core is one build module but contains multiple cohesive business capabilities.

Valid answer:
{
  "microservices": [
    {
      "microservice_name": "Care Directory Service",
      "responsibility": "Manages patient contact information, professional profiles, and professional availability.",
      "communicates_with": ["Appointment Service"]
    },
    {
      "microservice_name": "Appointment Service",
      "responsibility": "Handles appointment booking, confirmation, cancellation, and appointment lifecycle events.",
      "communicates_with": ["Care Directory Service", "Notification Service"]
    },
    {
      "microservice_name": "Notification Service",
      "responsibility": "Sends appointment confirmation and reminder notifications.",
      "communicates_with": ["Appointment Service"]
    }
  ]
}

Example 3 — parcel delivery: six technical packages, two cohesive services

Requirements:
- [REQ-01] Customers create delivery requests and provide pickup and destination addresses.
- [REQ-02] Operators assign parcels to routes and update delivery progress.
- [REQ-03] Customers track a parcel until delivery is completed.

Static analysis evidence:
- Packages: api.customer, api.delivery, application.delivery, domain.delivery, persistence, shared.
- Delivery request, route assignment, and tracking event classes share one parcel lifecycle and a single transaction boundary.
- The customer API depends on delivery application services; the delivery API exposes requests, route assignments, and tracking updates.
- There are six packages, most of them technical layers around one delivery-domain aggregate.

Valid answer:
{
  "microservices": [
    {
      "microservice_name": "Customer Service",
      "responsibility": "Manages customer identity and delivery address information.",
      "communicates_with": ["Delivery Operations Service"]
    },
    {
      "microservice_name": "Delivery Operations Service",
      "responsibility": "Manages delivery requests, parcel lifecycle, route assignment, and delivery tracking as one cohesive operation.",
      "communicates_with": ["Customer Service"]
    }
  ]
}
"""


@dataclass(slots=True)
class PromptPayload:
    template_name: str
    system_prompt: str
    user_prompt: str


def build_prompt(
    project_name: str,
    requirements: RequirementsData,
    static_analysis: StaticAnalysisData,
    template_name: str,
    limits: PromptLimits,
) -> PromptPayload:
    evidence = build_evidence_context(
        project_name=project_name,
        requirements=requirements,
        static_analysis=static_analysis,
        limits=limits,
    )

    if template_name == "zero_shot":
        prefix = ""
    elif template_name == "few_shot":
        prefix = FEW_SHOT_EXAMPLES + "\n"
    else:
        raise ValueError(
            f"Unsupported prompt template '{template_name}'. "
            "Available templates: zero_shot, few_shot."
        )

    user_prompt = (
        f"{prefix}"
        "Analyze the evidence below and produce one final microservice proposal.\n"
        "Make conservative decisions when evidence is weak.\n"
        "Avoid hallucinating unsupported services, generic umbrella services, and nanoservices.\n"
        "Return only JSON, without markdown fences, comments, or prose.\n\n"
        f"{evidence}\n"
    )
    return PromptPayload(
        template_name=template_name,
        system_prompt=BASE_SYSTEM_PROMPT,
        user_prompt=user_prompt,
    )


def build_evidence_context(
    *,
    project_name: str,
    requirements: RequirementsData,
    static_analysis: StaticAnalysisData,
    limits: PromptLimits,
) -> str:
    english_requirements = load_english_requirements(
        requirements,
        project_name=project_name,
    )
    requirements_content = build_requirements_context(english_requirements, limits)
    static_analysis_content = build_static_analysis_context(static_analysis, limits)
    return (
        f"Project name: {project_name}\n\n"
        "System requirements:\n"
        f"{requirements_content}\n\n"
        "Static analysis evidence:\n"
        f"{static_analysis_content}"
    )


def build_repair_prompt(raw_response: str, error_message: str) -> str:
    trimmed_response = clip_text(raw_response.strip(), 4000)
    trimmed_error = clip_text(error_message.strip(), 1000)
    return (
        "Your previous answer could not be parsed as valid JSON for the required schema.\n"
        f"Validation/parsing error:\n{trimmed_error}\n\n"
        "Rewrite the answer as valid JSON only, following exactly this schema:\n"
        f"{JSON_SCHEMA_SNIPPET}\n\n"
        "Previous invalid answer:\n"
        f"{trimmed_response}\n"
    )


def build_requirements_context(requirements: RequirementsData, limits: PromptLimits) -> str:
    lines = [
        "- Source: reviewed English translation of the project requirements CSV",
        f"- Columns: {', '.join(requirements.columns)}",
        f"- Total requirement rows: {requirements.row_count}",
    ]

    category_column = find_column(requirements.columns, ["categoria", "category"])
    id_column = find_column(requirements.columns, ["identificacao", "identification", "id", "codigo"])
    description_column = find_column(
        requirements.columns,
        ["descricao", "description", "requirement", "texto"],
    )

    if category_column:
        category_counts: dict[str, int] = {}
        for row in requirements.rows:
            category = row.get(category_column, "").strip() or "(uncategorized)"
            category_counts[category] = category_counts.get(category, 0) + 1
        top_categories = sorted(category_counts.items(), key=lambda item: (-item[1], item[0]))[:10]
        lines.append(
            "- Top requirement categories: "
            + "; ".join(f"{name} ({count})" for name, count in top_categories)
        )

    lines.append("- Representative requirement rows:")
    for row in requirements.rows[: limits.requirements_rows]:
        identifier = row.get(id_column, "").strip() if id_column else ""
        category = row.get(category_column, "").strip() if category_column else ""
        description = row.get(description_column, "").strip() if description_column else ""

        fragments: list[str] = []
        if identifier:
            fragments.append(f"[{identifier}]")
        if category:
            fragments.append(f"category={category}")
        if description:
            fragments.append(description)

        extra_fields = []
        for column in requirements.columns:
            if column in {id_column, category_column, description_column}:
                continue
            value = row.get(column, "").strip()
            if value:
                extra_fields.append(f"{column}={value}")
        if extra_fields:
            fragments.append(" | ".join(extra_fields[:3]))

        lines.append("  - " + " | ".join(fragment for fragment in fragments if fragment))

    omitted = requirements.row_count - min(requirements.row_count, limits.requirements_rows)
    if omitted > 0:
        lines.append(f"  - ... {omitted} additional requirement rows omitted for brevity.")

    return clip_text("\n".join(lines), limits.max_section_chars)


def build_static_analysis_context(static_analysis: StaticAnalysisData, limits: PromptLimits) -> str:
    lines = [
        f"- Source directory: {static_analysis.root_dir.as_posix()}",
        f"- Static analysis files found: {len(static_analysis.files)}",
    ]

    if static_analysis.summary:
        summary = static_analysis.summary
        lines.append(f"- Summary file: {static_analysis.root_dir.joinpath('summary.json').as_posix()}")

        counts = summary.get("counts", {})
        if counts:
            lines.append(
                "- Summary counts: "
                + ", ".join(f"{key}={value}" for key, value in counts.items())
            )
        if summary.get("build_tools"):
            lines.append("- Build tools: " + ", ".join(summary["build_tools"]))
        if summary.get("role_counts"):
            role_counts = summary["role_counts"]
            lines.append(
                "- Role counts: "
                + ", ".join(f"{role}={count}" for role, count in sorted(role_counts.items()))
            )
        if summary.get("package_roots"):
            lines.append(
                "- Package roots: "
                + "; ".join(
                    f"{item['package_root']} ({item['package_count']})"
                    for item in summary["package_roots"][: limits.static_rows]
                )
            )
        if summary.get("top_internal_dependencies"):
            lines.append("- Top internal package dependencies:")
            for dependency in summary["top_internal_dependencies"][: limits.static_rows]:
                lines.append(
                    "  - "
                    f"{dependency['source_package']} -> {dependency['target_package']} "
                    f"(count={dependency['count']})"
                )
        if summary.get("top_external_dependency_roots"):
            lines.append(
                "- Frequent external dependencies: "
                + "; ".join(
                    f"{item['dependency_root']} ({item['count']})"
                    for item in summary["top_external_dependency_roots"][: limits.static_rows]
                )
            )

    if static_analysis.modules:
        lines.append("- Detected modules/build files:")
        for row in static_analysis.modules[: limits.static_rows]:
            lines.append(
                "  - "
                f"module={row.get('module_path', '.')}, "
                f"tool={row.get('build_tool', '')}, "
                f"artifact={row.get('artifact_id', '')}, "
                f"packaging={row.get('packaging', '')}, "
                f"java={row.get('java_version', '')}"
            )

    if static_analysis.package_metrics:
        top_packages = sorted(
            static_analysis.package_metrics,
            key=lambda row: (
                -safe_int(row.get("class_count")),
                row.get("package", ""),
            ),
        )[: limits.static_rows]
        lines.append("- Top packages by structural weight:")
        for row in top_packages:
            lines.append(
                "  - "
                f"{row.get('package', '')}: "
                f"classes={row.get('class_count', '')}, "
                f"methods={row.get('method_count', '')}, "
                f"roles={row.get('roles', '')}, "
                f"incoming_internal={row.get('incoming_internal_dependencies', '')}, "
                f"outgoing_internal={row.get('outgoing_internal_dependencies', '')}"
            )

    if static_analysis.package_dependencies:
        internal_edges = [
            row
            for row in static_analysis.package_dependencies
            if row.get("category", "").strip().lower() == "internal"
        ]
        internal_edges = sorted(
            internal_edges,
            key=lambda row: (-safe_int(row.get("count")), row.get("source_package", "")),
        )[: limits.static_rows]
        if internal_edges:
            lines.append("- Internal dependency edges:")
            for row in internal_edges:
                lines.append(
                    "  - "
                    f"{row.get('source_package', '')} -> {row.get('target_package', '')} "
                    f"(count={row.get('count', '')})"
                )

    if static_analysis.entrypoints:
        lines.append("- Entrypoints detected in code:")
        for row in static_analysis.entrypoints[: limits.static_rows]:
            lines.append(
                "  - "
                f"{row.get('type_name', '')} ({row.get('package', '')}) "
                f"reasons={row.get('entrypoint_reasons', '')}"
            )

    extra_artifacts = static_analysis.extras[:5]
    if extra_artifacts:
        lines.append("- Additional static analysis artifacts:")
        for artifact in extra_artifacts:
            lines.extend(describe_extra_artifact(artifact, limits))

    return clip_text("\n".join(lines), limits.max_section_chars)


def describe_extra_artifact(artifact: StaticArtifact, limits: PromptLimits) -> list[str]:
    header = f"  - {artifact.path.name} ({artifact.artifact_type})"
    if artifact.artifact_type == "csv":
        preview_rows = artifact.content[:3] if isinstance(artifact.content, list) else []
        body = [f"{header}: rows={artifact.row_count}"]
        for row in preview_rows:
            preview = ", ".join(f"{key}={value}" for key, value in list(row.items())[:4])
            body.append(f"    * {preview}")
        return body
    if artifact.artifact_type == "json":
        preview = clip_text(render_json_preview(artifact.content), limits.text_preview_chars)
        return [header + ":", preview]
    preview_text = clip_text(str(artifact.content).strip(), limits.text_preview_chars)
    return [header + ":", preview_text]


def render_json_preview(payload: Any) -> str:
    if isinstance(payload, dict):
        items = list(payload.items())[:8]
        return "\n".join(f"    * {key}={value}" for key, value in items)
    if isinstance(payload, list):
        return "\n".join(f"    * {item}" for item in payload[:5])
    return str(payload)


def find_column(columns: list[str], keywords: list[str]) -> str | None:
    normalized_map = {column: normalize_header(column) for column in columns}
    for keyword in keywords:
        for column, normalized in normalized_map.items():
            if keyword in normalized:
                return column
    return None


def safe_int(value: Any) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def clip_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    clipped = value[: max_chars - 64].rstrip()
    return clipped + "\n... [content truncated to fit prompt budget]"
