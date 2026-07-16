from __future__ import annotations

import logging
import os

from anthropic import Anthropic

from ..config import ModelConfig, ProviderConfig


LOGGER = logging.getLogger("microservice-decomposition")


class AnthropicClient:
    def __init__(self, provider_config: ProviderConfig) -> None:
        self.provider_config = provider_config
        api_key = os.getenv(provider_config.api_key_env)
        if not api_key:
            raise RuntimeError(
                f"Missing API key in environment variable {provider_config.api_key_env}."
            )
        self.api_key = api_key

    def generate(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        model_config: ModelConfig,
    ) -> str:
        client = Anthropic(
            api_key=self.api_key,
            base_url=self.provider_config.base_url,
            timeout=model_config.timeout_seconds,
        )
        request = {
            "model": model_config.name,
            "system": system_prompt,
            "messages": [{"role": item["role"], "content": item["content"]} for item in messages],
            "max_tokens": model_config.max_tokens or 3500,
        }
        if model_config.temperature is not None:
            request["temperature"] = model_config.temperature

        try:
            response = client.messages.create(**request)
        except Exception as exc:  # noqa: BLE001
            if should_omit_temperature(exc) and "temperature" in request:
                LOGGER.warning(
                    "Retrying Anthropic request for model %s without temperature due to API compatibility warning.",
                    model_config.name,
                )
                request.pop("temperature", None)
                response = client.messages.create(**request)
            else:
                raise
        fragments = [block.text for block in response.content if getattr(block, "type", "") == "text"]
        return "\n".join(fragments).strip()


def should_omit_temperature(exc: Exception) -> bool:
    message = str(exc).lower()
    return "temperature" in message and any(
        token in message
        for token in ("deprecated", "unsupported", "not allowed", "invalid_request_error")
    )
