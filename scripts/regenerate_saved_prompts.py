"""Rebuild saved prompts and recorded prompt payloads from the English overlays."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import load_app_config
from src.main import prompt_for_approach
from src.prompt_builder import build_evidence_context, build_prompt
from src.prompt_writer import write_prompt_file
from src.project_loader import discover_projects
from src.requirements_loader import load_requirements
from src.static_analysis_loader import load_static_analysis


def main() -> None:
    config = load_app_config(ROOT / "config.yaml")
    projects = discover_projects(
        ROOT / "systems",
        ROOT / "analysis-results/static-analysis",
        config.experiment.analysis_extensions,
    )
    project_data = {}
    for project in projects:
        requirements = load_requirements(project.requirements_csv)
        static_analysis = load_static_analysis(project.static_analysis_dir, project.static_analysis_files)
        project_data[project.name] = (requirements, static_analysis)

    updated_prompts = 0
    updated_traces = 0
    for prompt_path in (ROOT / "outputs").rglob("*.prompt.txt"):
        relative = prompt_path.relative_to(ROOT / "outputs")
        project_name, approach, *_middle, template_name, _filename = relative.parts
        requirements, static_analysis = project_data[project_name]
        direct_prompt = build_prompt(
            project_name=project_name,
            requirements=requirements,
            static_analysis=static_analysis,
            template_name=template_name,
            limits=config.experiment.prompt_limits,
        )
        evidence = build_evidence_context(
            project_name=project_name,
            requirements=requirements,
            static_analysis=static_analysis,
            limits=config.experiment.prompt_limits,
        )
        prompt = prompt_for_approach(
            approach=approach,
            direct_prompt=direct_prompt,
            evidence=evidence,
        )
        write_prompt_file(prompt_path, prompt)
        updated_prompts += 1

        trace_path = prompt_path.with_name(prompt_path.name.replace(".prompt.txt", ".trace.jsonl"))
        if trace_path.exists() and replace_trace_evidence(trace_path, project_name, evidence):
            updated_traces += 1

    # Two legacy DeepSeek prompt exports predate the ``*.prompt.txt`` naming
    # convention and must remain aligned with the rebuilt artifacts.
    for template_name, filename in (
        ("zero_shot", "tnt - deepseek - zs.txt"),
        ("few_shot", "tnt - deepseek - fs.txt"),
    ):
        prompt_path = (
            ROOT
            / "outputs/TNTConcept/direct/deepseek/deepseek-chat"
            / template_name
            / filename
        )
        if not prompt_path.exists():
            continue
        requirements, static_analysis = project_data["TNTConcept"]
        prompt = build_prompt(
            project_name="TNTConcept",
            requirements=requirements,
            static_analysis=static_analysis,
            template_name=template_name,
            limits=config.experiment.prompt_limits,
        )
        write_prompt_file(prompt_path, prompt)
        updated_prompts += 1

    for template_name in ("zero_shot", "few_shot"):
        trace_path = (
            ROOT
            / "outputs/TNTConcept/direct/deepseek/deepseek-chat"
            / template_name
            / "run_1.trace.jsonl"
        )
        requirements, static_analysis = project_data["TNTConcept"]
        evidence = build_evidence_context(
            project_name="TNTConcept",
            requirements=requirements,
            static_analysis=static_analysis,
            limits=config.experiment.prompt_limits,
        )
        if trace_path.exists() and replace_trace_evidence(trace_path, "TNTConcept", evidence):
            updated_traces += 1

    print(f"Regenerated {updated_prompts} prompt files and updated {updated_traces} trace files.")


def replace_trace_evidence(trace_path: Path, project_name: str, evidence: str) -> bool:
    marker = f"Project name: {project_name}\n\nSystem requirements:"
    changed = False
    updated_lines = []
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        user_prompt = event.get("user_prompt")
        if isinstance(user_prompt, str):
            start = user_prompt.find(marker)
            if start >= 0:
                event["user_prompt"] = user_prompt[:start] + evidence
                changed = True
        updated_lines.append(json.dumps(event, ensure_ascii=False, sort_keys=True))
    if changed:
        trace_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")
    return changed


if __name__ == "__main__":
    main()
