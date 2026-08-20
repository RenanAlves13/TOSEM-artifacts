from __future__ import annotations

from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field


DEFAULT_CONFIG_PATH = Path("config.yaml")


class ModelConfig(BaseModel):
    name: str
    temperature: float | None = 0.2
    max_tokens: int | None = 3500
    timeout_seconds: int = 120


class ProviderConfig(BaseModel):
    enabled: bool = True
    api_key_env: str
    base_url: str | None = None
    models: list[ModelConfig] = Field(default_factory=list)


class PromptLimits(BaseModel):
    requirements_rows: int = 80
    static_rows: int = 20
    max_section_chars: int = 18000
    text_preview_chars: int = 2000


class AgentConfig(BaseModel):
    max_refinement_rounds: int = Field(default=2, ge=1, le=10)


class ExperimentConfig(BaseModel):
    prompt_templates: list[str] = Field(default_factory=lambda: ["zero_shot", "few_shot"])
    approaches: list[str] = Field(default_factory=lambda: ["direct"])
    default_runs: int = 1
    max_attempts: int = 3
    empty_communication_value: str = ""
    analysis_extensions: list[str] = Field(
        default_factory=lambda: [".csv", ".json", ".txt", ".md"]
    )
    prompt_limits: PromptLimits = Field(default_factory=PromptLimits)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    log_level: str = "INFO"


class AppConfig(BaseModel):
    experiment: ExperimentConfig = Field(default_factory=ExperimentConfig)
    providers: dict[str, ProviderConfig]


def load_app_config(config_path: str | Path | None = None) -> AppConfig:
    load_dotenv()

    path = Path(config_path or DEFAULT_CONFIG_PATH)
    if not path.exists():
        raise FileNotFoundError(
            f"Could not find configuration file at {path}. "
            "Create config.yaml or pass --config."
        )

    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return AppConfig.model_validate(payload)
