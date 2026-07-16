from __future__ import annotations

from ..config import ProviderConfig
from .anthropic_client import AnthropicClient
from .deepseek_client import DeepSeekClient
from .openai_client import OpenAIClient


def build_client(provider_name: str, provider_config: ProviderConfig):
    normalized = provider_name.lower()
    if normalized == "openai":
        return OpenAIClient(provider_config)
    if normalized == "anthropic":
        return AnthropicClient(provider_config)
    if normalized == "deepseek":
        return DeepSeekClient(provider_config)
    raise ValueError(f"Unsupported provider: {provider_name}")
