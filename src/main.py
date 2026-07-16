from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path

from .config import AppConfig, ModelConfig, ProviderConfig, load_app_config
from .csv_writer import write_microservices_csv
from .llm_clients import build_client
from .metadata_writer import MetadataWriter
from .project_loader import ProjectContext, discover_projects
from .prompt_builder import PromptPayload, build_prompt, build_repair_prompt
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
    selected_models = select_models(config, args.provider, args.model)

    metadata_writer = MetadataWriter(output_dir / "metadata.csv")
    run_count = args.runs or config.experiment.default_runs
    max_attempts = args.max_attempts or config.experiment.max_attempts

    LOGGER.info(
        "Starting experiment with %s project(s), %s model target(s), %s prompt template(s), runs=%s",
        len(projects),
        len(selected_models),
        len(prompt_templates),
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

                for run_number in range(1, run_count + 1):
                    output_path = build_output_path(
                        output_dir=output_dir,
                        project_name=project.name,
                        provider_name=provider_name,
                        model_name=model_config.name,
                        prompt_template=prompt_template,
                        run_number=run_number,
                    )
                    prompt_path = build_prompt_path(
                        output_dir=output_dir,
                        project_name=project.name,
                        provider_name=provider_name,
                        model_name=model_config.name,
                        prompt_template=prompt_template,
                        run_number=run_number,
                    )
                    timestamp = utc_now()

                    LOGGER.info(
                        "Project=%s | Provider=%s | Model=%s | Prompt=%s | Run=%s",
                        project.name,
                        provider_name,
                        model_config.name,
                        prompt_template,
                        run_number,
                    )

                    if args.print_prompts:
                        print_prompt_preview(
                            project_name=project.name,
                            provider_name=provider_name,
                            model_name=model_config.name,
                            prompt_template=prompt_template,
                            run_number=run_number,
                            prompt=prompt,
                        )

                    if args.save_prompts:
                        write_prompt_file(prompt_path, prompt)
                        LOGGER.info("Saved prompt file: %s", prompt_path.as_posix())

                    if args.dry_run:
                        LOGGER.info(
                            "Dry-run enabled. Prompt built for %s (%s/%s).",
                            project.name,
                            provider_name,
                            prompt_template,
                        )
                        metadata_writer.append_row(
                            project_name=project.name,
                            provider=provider_name,
                            model=model_config.name,
                            prompt_template=prompt_template,
                            run_number=run_number,
                            output_path="",
                            timestamp=timestamp,
                            status="dry_run",
                            error="",
                        )
                        continue

                    try:
                        assert client is not None
                        proposal = execute_generation(
                            client=client,
                            prompt=prompt,
                            model_config=model_config,
                            max_attempts=max_attempts,
                        )
                        write_microservices_csv(
                            output_path=output_path,
                            proposal=proposal,
                            empty_communication_value=config.experiment.empty_communication_value,
                        )
                        metadata_writer.append_row(
                            project_name=project.name,
                            provider=provider_name,
                            model=model_config.name,
                            prompt_template=prompt_template,
                            run_number=run_number,
                            output_path=output_path.as_posix(),
                            timestamp=timestamp,
                            status="success",
                            error="",
                        )
                        LOGGER.info("Generated file: %s", output_path.as_posix())
                    except Exception as exc:  # noqa: BLE001
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
                            provider=provider_name,
                            model=model_config.name,
                            prompt_template=prompt_template,
                            run_number=run_number,
                            output_path="",
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
) -> MicroserviceProposal:
    conversation = [{"role": "user", "content": prompt.user_prompt}]
    last_error = "No attempts performed."

    for attempt in range(1, max_attempts + 1):
        LOGGER.info("  API attempt %s/%s", attempt, max_attempts)
        try:
            raw_response = client.generate(
                system_prompt=prompt.system_prompt,
                messages=conversation,
                model_config=model_config,
            )
        except Exception as exc:  # noqa: BLE001
            last_error = f"API error: {exc}"
            LOGGER.warning("  API error on attempt %s: %s", attempt, exc)
            continue

        try:
            return parse_model_response(raw_response)
        except ParseFailure as exc:
            last_error = str(exc)
            LOGGER.warning("  Parsing failed on attempt %s: %s", attempt, exc)
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
    provider_name: str,
    model_name: str,
    prompt_template: str,
    run_number: int,
) -> Path:
    safe_model_name = sanitize_path_fragment(model_name)
    return (
        output_dir
        / project_name
        / provider_name
        / safe_model_name
        / prompt_template
        / f"run_{run_number}.csv"
    )


def build_prompt_path(
    *,
    output_dir: Path,
    project_name: str,
    provider_name: str,
    model_name: str,
    prompt_template: str,
    run_number: int,
) -> Path:
    safe_model_name = sanitize_path_fragment(model_name)
    return (
        output_dir
        / project_name
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
    provider_name: str,
    model_name: str,
    prompt_template: str,
    run_number: int,
    prompt: PromptPayload,
) -> None:
    separator = "=" * 80
    print(separator)
    print(
        f"PROJECT={project_name} | PROVIDER={provider_name} | "
        f"MODEL={model_name} | PROMPT={prompt_template} | RUN={run_number}"
    )
    print(separator)
    print(render_prompt_text(prompt))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    main()
