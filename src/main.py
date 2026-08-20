from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from time import monotonic

from .agentic import AgentWorkflow, TraceWriter
from .config import AppConfig, ModelConfig, ProviderConfig, load_app_config
from .csv_writer import write_microservices_csv
from .llm_clients import build_client
from .metadata_writer import MetadataWriter
from .project_loader import ProjectContext, discover_projects
from .prompt_builder import (
    PromptPayload,
    build_evidence_context,
    build_prompt,
    build_repair_prompt,
)
from .prompt_writer import render_prompt_text, write_prompt_file
from .requirements_loader import load_requirements
from .response_parser import MicroserviceProposal, ParseFailure, parse_model_response
from .static_analysis_loader import load_static_analysis


LOGGER = logging.getLogger("microservice-decomposition")


def main() -> None:
    args = parse_args()
    config = load_app_config(args.config)
    configure_logging(args.log_level or config.experiment.log_level)

    systems_dir = Path(args.systems_dir)
    static_analysis_dir = Path(args.static_analysis_dir)
    output_dir = Path(args.output_dir)

    projects = discover_projects(
        systems_dir=systems_dir,
        static_analysis_root=static_analysis_dir,
        analysis_extensions=config.experiment.analysis_extensions,
    )
    projects = filter_projects(projects, args.project)
    prompt_templates = filter_prompt_templates(
        config.experiment.prompt_templates,
        args.prompt_template,
    )
    approaches = select_approaches(config.experiment.approaches, args.approach)
    selected_models = select_models(config, args.provider, args.model)

    metadata_writer = MetadataWriter(output_dir / "metadata.csv")
    run_count = args.runs or config.experiment.default_runs
    max_attempts = args.max_attempts or config.experiment.max_attempts

    LOGGER.info(
        "Starting experiment with %s project(s), %s model target(s), %s prompt template(s), "
        "%s approach(es), runs=%s",
        len(projects),
        len(selected_models),
        len(prompt_templates),
        len(approaches),
        run_count,
    )

    for project in projects:
        requirements = load_requirements(project.requirements_csv)
        static_analysis = load_static_analysis(project.static_analysis_dir, project.static_analysis_files)

        for provider_name, provider_config, model_config in selected_models:
            client = None if args.dry_run else build_client(provider_name, provider_config)

            for prompt_template in prompt_templates:
                prompt = build_prompt(
                    project_name=project.name,
                    requirements=requirements,
                    static_analysis=static_analysis,
                    template_name=prompt_template,
                    limits=config.experiment.prompt_limits,
                )
                evidence = build_evidence_context(
                    project_name=project.name,
                    requirements=requirements,
                    static_analysis=static_analysis,
                    limits=config.experiment.prompt_limits,
                )

                for approach, run_number in product(
                    approaches,
                    range(1, run_count + 1),
                ):
                    output_path = build_output_path(
                        output_dir=output_dir,
                        project_name=project.name,
                        approach=approach,
                        provider_name=provider_name,
                        model_name=model_config.name,
                        prompt_template=prompt_template,
                        run_number=run_number,
                    )
                    prompt_path = build_prompt_path(
                        output_dir=output_dir,
                        project_name=project.name,
                        approach=approach,
                        provider_name=provider_name,
                        model_name=model_config.name,
                        prompt_template=prompt_template,
                        run_number=run_number,
                    )
                    trace_path = output_path.with_suffix(".trace.jsonl")
                    timestamp = utc_now()

                    LOGGER.info(
                        "Project=%s | Approach=%s | Provider=%s | Model=%s | Prompt=%s | Run=%s",
                        project.name,
                        approach,
                        provider_name,
                        model_config.name,
                        prompt_template,
                        run_number,
                    )

                    if args.print_prompts:
                        print_prompt_preview(
                            project_name=project.name,
                            approach=approach,
                            provider_name=provider_name,
                            model_name=model_config.name,
                            prompt_template=prompt_template,
                            run_number=run_number,
                            prompt=prompt_for_approach(
                                approach=approach,
                                direct_prompt=prompt,
                                evidence=evidence,
                            ),
                        )

                    if args.save_prompts:
                        write_prompt_file(
                            prompt_path,
                            prompt_for_approach(
                                approach=approach,
                                direct_prompt=prompt,
                                evidence=evidence,
                            ),
                        )
                        LOGGER.info("Saved prompt file: %s", prompt_path.as_posix())

                    if args.dry_run:
                        LOGGER.info(
                            "Dry-run enabled. Prompt built for %s (%s/%s).",
                            project.name,
                            provider_name,
                            f"{approach}/{prompt_template}",
                        )
                        metadata_writer.append_row(
                            project_name=project.name,
                            approach=approach,
                            provider=provider_name,
                            model=model_config.name,
                            prompt_template=prompt_template,
                            run_number=run_number,
                            output_path="",
                            trace_path="",
                            timestamp=timestamp,
                            status="dry_run",
                            error="",
                        )
                        continue

                    trace_writer = TraceWriter(
                        trace_path,
                        {
                            "project_name": project.name,
                            "approach": approach,
                            "provider": provider_name,
                            "model": model_config.name,
                            "prompt_template": prompt_template,
                            "run_number": run_number,
                        },
                    )
                    try:
                        assert client is not None
                        if approach == "direct":
                            proposal = execute_generation(
                                client=client,
                                prompt=prompt,
                                model_config=model_config,
                                max_attempts=max_attempts,
                                trace_writer=trace_writer,
                            )
                        else:
                            proposal = AgentWorkflow(
                                client=client,
                                model_config=model_config,
                                max_attempts=max_attempts,
                                max_refinement_rounds=(
                                    config.experiment.agent.max_refinement_rounds
                                ),
                                trace_writer=trace_writer,
                            ).run(evidence=evidence, template_name=prompt_template)
                        write_microservices_csv(
                            output_path=output_path,
                            proposal=proposal,
                            empty_communication_value=config.experiment.empty_communication_value,
                        )
                        trace_writer.finish(status="success")
                        metadata_writer.append_row(
                            project_name=project.name,
                            approach=approach,
                            provider=provider_name,
                            model=model_config.name,
                            prompt_template=prompt_template,
                            run_number=run_number,
                            output_path=output_path.as_posix(),
                            trace_path=trace_path.as_posix(),
                            timestamp=timestamp,
                            status="success",
                            error="",
                        )
                        LOGGER.info("Generated file: %s", output_path.as_posix())
                    except Exception as exc:  # noqa: BLE001
                        trace_writer.finish(status="error", error=str(exc))
                        LOGGER.exception(
                            "Execution failed for project=%s provider=%s model=%s prompt=%s run=%s",
                            project.name,
                            provider_name,
                            model_config.name,
                            prompt_template,
                            run_number,
                        )
                        metadata_writer.append_row(
                            project_name=project.name,
                            approach=approach,
                            provider=provider_name,
                            model=model_config.name,
                            prompt_template=prompt_template,
                            run_number=run_number,
                            output_path="",
                            trace_path=trace_path.as_posix(),
                            timestamp=timestamp,
                            status="error",
                            error=str(exc),
                        )


def execute_generation(
    *,
    client,
    prompt: PromptPayload,
    model_config: ModelConfig,
    max_attempts: int,
    trace_writer: TraceWriter | None = None,
) -> MicroserviceProposal:
    conversation = [{"role": "user", "content": prompt.user_prompt}]
    last_error = "No attempts performed."

    for attempt in range(1, max_attempts + 1):
        LOGGER.info("  API attempt %s/%s", attempt, max_attempts)
        started = monotonic()
        try:
            raw_response = client.generate(
                system_prompt=prompt.system_prompt,
                messages=conversation,
                model_config=model_config,
            )
        except Exception as exc:  # noqa: BLE001
            last_error = f"API error: {exc}"
            LOGGER.warning("  API error on attempt %s: %s", attempt, exc)
            if trace_writer:
                trace_writer.record(
                    "agent_call",
                    role="direct_generator",
                    phase="one_shot",
                    iteration=0,
                    attempt=attempt,
                    status="api_error",
                    duration_ms=round((monotonic() - started) * 1000, 3),
                    system_prompt=prompt.system_prompt,
                    user_prompt=conversation[-1]["content"],
                    error=str(exc),
                )
            continue

        try:
            proposal = parse_model_response(raw_response)
            if trace_writer:
                trace_writer.record(
                    "agent_call",
                    role="direct_generator",
                    phase="one_shot",
                    iteration=0,
                    attempt=attempt,
                    status="success",
                    duration_ms=round((monotonic() - started) * 1000, 3),
                    system_prompt=prompt.system_prompt,
                    user_prompt=conversation[-1]["content"],
                    raw_response=raw_response,
                    parsed_output=proposal.model_dump(mode="json"),
                )
                trace_writer.record(
                    "architecture_snapshot",
                    phase="final",
                    iteration=0,
                    architecture=proposal.model_dump(mode="json"),
                    changes={},
                )
            return proposal
        except ParseFailure as exc:
            last_error = str(exc)
            LOGGER.warning("  Parsing failed on attempt %s: %s", attempt, exc)
            if trace_writer:
                trace_writer.record(
                    "agent_call",
                    role="direct_generator",
                    phase="one_shot",
                    iteration=0,
                    attempt=attempt,
                    status="parse_error",
                    duration_ms=round((monotonic() - started) * 1000, 3),
                    system_prompt=prompt.system_prompt,
                    user_prompt=conversation[-1]["content"],
                    raw_response=raw_response,
                    error=str(exc),
                )
            if attempt == max_attempts:
                break
            conversation.append({"role": "assistant", "content": raw_response})
            conversation.append(
                {
                    "role": "user",
                    "content": build_repair_prompt(raw_response=raw_response, error_message=str(exc)),
                }
            )

    raise RuntimeError(f"Failed to obtain a valid microservice proposal. Last error: {last_error}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate microservice decomposition proposals from requirements and static analysis."
    )
    parser.add_argument("--config", default="config.yaml", help="Path to the YAML configuration file.")
    parser.add_argument("--systems-dir", default="systems", help="Directory containing the system projects.")
    parser.add_argument(
        "--static-analysis-dir",
        default="analysis-results/static-analysis",
        help="Directory containing per-project static analysis artifacts.",
    )
    parser.add_argument("--output-dir", default="outputs", help="Directory for generated outputs.")
    parser.add_argument("--project", help="Run only one project, e.g. 7ep or pet-clinic.")
    parser.add_argument("--provider", help="Run only one provider, e.g. openai.")
    parser.add_argument("--model", help="Run only one model name from the config.")
    parser.add_argument(
        "--approach",
        action="append",
        choices=("direct", "agent"),
        help="Generation approach(s). Repeat to run both direct and agent conditions.",
    )
    parser.add_argument(
        "--prompt-template",
        action="append",
        help="Prompt template(s) to run. Repeat the flag to pass more than one value.",
    )
    parser.add_argument("--runs", type=int, help="Number of runs per project/provider/model/template.")
    parser.add_argument(
        "--max-attempts",
        type=int,
        help="Maximum retries per run when the API or JSON parsing fails.",
    )
    parser.add_argument("--log-level", help="Override log level, e.g. INFO or DEBUG.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build prompts and validate discovery without calling any API.",
    )
    parser.add_argument(
        "--print-prompts",
        action="store_true",
        help="Print the generated prompts to the terminal.",
    )
    parser.add_argument(
        "--save-prompts",
        action="store_true",
        help="Save the generated prompts as .txt files next to the output CSV structure.",
    )
    return parser.parse_args()


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(message)s",
    )


def filter_projects(projects: list[ProjectContext], project_name: str | None) -> list[ProjectContext]:
    if not project_name:
        return projects
    filtered = [project for project in projects if project.name == project_name]
    if not filtered:
        raise ValueError(f"Project '{project_name}' was not found under systems/.")
    return filtered


def filter_prompt_templates(
    configured_templates: list[str],
    requested_templates: list[str] | None,
) -> list[str]:
    if not requested_templates:
        return configured_templates

    configured_set = set(configured_templates)
    invalid = [template for template in requested_templates if template not in configured_set]
    if invalid:
        raise ValueError(
            f"Unsupported prompt template(s): {', '.join(invalid)}. "
            f"Configured templates: {', '.join(configured_templates)}."
        )
    return requested_templates


def select_approaches(
    configured_approaches: list[str],
    requested_approaches: list[str] | None,
) -> list[str]:
    approaches = requested_approaches or configured_approaches
    invalid = [approach for approach in approaches if approach not in {"direct", "agent"}]
    if invalid:
        raise ValueError(f"Unsupported approach(es): {', '.join(invalid)}")
    return list(dict.fromkeys(approaches))


def select_models(
    config: AppConfig,
    provider_name: str | None,
    model_name: str | None,
) -> list[tuple[str, ProviderConfig, ModelConfig]]:
    selected: list[tuple[str, ProviderConfig, ModelConfig]] = []

    for current_provider_name, provider_config in config.providers.items():
        if provider_name and current_provider_name != provider_name:
            continue
        if not provider_config.enabled:
            continue
        for model_config in provider_config.models:
            if model_name and model_config.name != model_name:
                continue
            selected.append((current_provider_name, provider_config, model_config))

    if not selected:
        raise ValueError("No provider/model combination matched the requested filters.")
    return selected


def build_output_path(
    *,
    output_dir: Path,
    project_name: str,
    approach: str,
    provider_name: str,
    model_name: str,
    prompt_template: str,
    run_number: int,
) -> Path:
    safe_model_name = sanitize_path_fragment(model_name)
    return (
        output_dir
        / project_name
        / approach
        / provider_name
        / safe_model_name
        / prompt_template
        / f"run_{run_number}.csv"
    )


def build_prompt_path(
    *,
    output_dir: Path,
    project_name: str,
    approach: str,
    provider_name: str,
    model_name: str,
    prompt_template: str,
    run_number: int,
) -> Path:
    safe_model_name = sanitize_path_fragment(model_name)
    return (
        output_dir
        / project_name
        / approach
        / provider_name
        / safe_model_name
        / prompt_template
        / f"run_{run_number}.prompt.txt"
    )


def sanitize_path_fragment(value: str) -> str:
    sanitized = value.replace("/", "_").replace("\\", "_").replace(":", "_").strip()
    return sanitized or "model"


def print_prompt_preview(
    *,
    project_name: str,
    approach: str,
    provider_name: str,
    model_name: str,
    prompt_template: str,
    run_number: int,
    prompt: PromptPayload,
) -> None:
    separator = "=" * 80
    print(separator)
    print(
        f"PROJECT={project_name} | APPROACH={approach} | PROVIDER={provider_name} | "
        f"MODEL={model_name} | PROMPT={prompt_template} | RUN={run_number}"
    )
    print(separator)
    print(render_prompt_text(prompt))


def prompt_for_approach(
    *,
    approach: str,
    direct_prompt: PromptPayload,
    evidence: str,
) -> PromptPayload:
    if approach == "direct":
        return direct_prompt
    return PromptPayload(
        template_name=direct_prompt.template_name,
        system_prompt=(
            "Structured multi-agent workflow: domain analyst, structural analyst, architect, "
            "critic, and refiner. Exact prompts and intermediate outputs are in the trace JSONL."
        ),
        user_prompt=evidence,
    )


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    main()
