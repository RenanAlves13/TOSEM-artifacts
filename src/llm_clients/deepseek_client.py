from __future__ import annotations

from ..config import ProviderConfig
from .openai_client import OpenAIClient


class DeepSeekClient(OpenAIClient):
    def __init__(self, provider_config: ProviderConfig) -> None:
        super().__init__(provider_config)
        self.use_responses_api = False
