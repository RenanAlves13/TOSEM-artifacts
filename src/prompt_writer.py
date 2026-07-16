from __future__ import annotations

from pathlib import Path

from .prompt_builder import PromptPayload


def render_prompt_text(prompt: PromptPayload) -> str:
    return (
        f"PROMPT TEMPLATE: {prompt.template_name}\n"
        "\n=== SYSTEM PROMPT ===\n"
        f"{prompt.system_prompt}\n"
        "\n=== USER PROMPT ===\n"
        f"{prompt.user_prompt}\n"
    )


def write_prompt_file(prompt_path: Path, prompt: PromptPayload) -> None:
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(render_prompt_text(prompt), encoding="utf-8")
