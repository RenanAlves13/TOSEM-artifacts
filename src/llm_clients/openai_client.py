from __future__ import annotations

import logging
import os
from typing import Any

from openai import OpenAI

from ..config import ModelConfig, ProviderConfig


LOGGER = logging.getLogger("microservice-decomposition")


class OpenAIClient:
    def __init__(self, provider_config: ProviderConfig) -> None:
        self.provider_config = provider_config
        api_key = os.getenv(provider_config.api_key_env)
        if not api_key:
            raise RuntimeError(
                f"Missing API key in environment variable {provider_config.api_key_env}."
            )
        self.client = OpenAI(api_key=api_key, base_url=provider_config.base_url)
        self.use_responses_api = provider_config.base_url in (None, "")

    def generate(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        model_config: ModelConfig,
    ) -> str:
        if self.use_responses_api:
            return self._generate_with_responses(
                system_prompt=system_prompt,
                messages=messages,
                model_config=model_config,
            )
        return self._generate_with_chat(
            system_prompt=system_prompt,
            messages=messages,
            model_config=model_config,
        )

    def _generate_with_responses(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        model_config: ModelConfig,
    ) -> str:
        request = {
            "model": model_config.name,
            "instructions": system_prompt,
            "input": [build_responses_input_message(item) for item in messages],
            "timeout": model_config.timeout_seconds,
        }
        if model_config.max_tokens is not None:
            request["max_output_tokens"] = model_config.max_tokens
        if should_send_temperature(model_config.name, model_config.temperature):
            request["temperature"] = model_config.temperature

        try:
            response = self.client.responses.create(**request)
        except Exception as exc:  # noqa: BLE001
            if should_omit_temperature(exc) and "temperature" in request:
                LOGGER.warning(
                    "Retrying OpenAI request for model %s without temperature due to API compatibility warning.",
                    model_config.name,
                )
                request.pop("temperature", None)
                response = self.client.responses.create(**request)
            else:
                raise

        return extract_openai_response_text(response)

    def _generate_with_chat(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        model_config: ModelConfig,
    ) -> str:
        request = {
            "model": model_config.name,
            "timeout": model_config.timeout_seconds,
            "messages": [
                {"role": "system", "content": system_prompt},
                *messages,
            ],
        }
        if model_config.max_tokens is not None:
            request["max_tokens"] = model_config.max_tokens
        if should_send_temperature(model_config.name, model_config.temperature):
            request["temperature"] = model_config.temperature

        try:
            response = self.client.chat.completions.create(**request)
        except Exception as exc:  # noqa: BLE001
            if should_omit_temperature(exc) and "temperature" in request:
                LOGGER.warning(
                    "Retrying chat-completions request for model %s without temperature due to API compatibility warning.",
                    model_config.name,
                )
                request.pop("temperature", None)
                response = self.client.chat.completions.create(**request)
            else:
                raise
        return extract_openai_chat_text(response)


def extract_openai_chat_text(response: Any) -> str:
    content = response.choices[0].message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        fragments: list[str] = []
        for item in content:
            text = getattr(item, "text", None)
            if text:
                fragments.append(text)
        return "\n".join(fragments).strip()
    return str(content)


def extract_openai_response_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    fragments: list[str] = []
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            text = getattr(content, "text", None)
            if text:
                fragments.append(text)

    if fragments:
        return "\n".join(fragments).strip()
    return str(response)


def build_responses_input_message(message: dict[str, str]) -> dict[str, Any]:
    role = message["role"]
    content = message["content"]

    if role == "assistant":
        content_type = "output_text"
    else:
        content_type = "input_text"

    return {
        "role": role,
        "content": [{"type": content_type, "text": content}],
    }


def should_omit_temperature(exc: Exception) -> bool:
    message = str(exc).lower()
    return "temperature" in message and any(
        token in message
        for token in ("deprecated", "unsupported", "not allowed", "invalid_request_error")
    )


def should_send_temperature(model_name: str, temperature: float | None) -> bool:
    if temperature is None:
        return False

    normalized = model_name.strip().lower()

    # Newer GPT-5-class models can reject the temperature parameter entirely.
    if normalized.startswith("gpt-5"):
        return False

    return True
