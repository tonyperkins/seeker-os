"""LLM provider protocol — the abstract interface all providers implement."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from seeker_os.llm.models import LLMRequest, LLMResponse, ModelInfo, ProviderHealth


@runtime_checkable
class LLMProvider(Protocol):
    """Abstract LLM provider interface.

    All providers (Anthropic, OpenAI-compatible, etc.) implement this.
    The rest of the code never knows which provider it's using.
    """

    @property
    def id(self) -> str: ...

    @property
    def type(self) -> str: ...
        # 'anthropic' or 'openai_compatible'

    def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate a completion for the given request."""
        ...

    def list_models(self) -> list[ModelInfo]:
        """Fetch available models from the provider's API."""
        ...

    def test_connection(self) -> ProviderHealth:
        """Test connectivity to the provider."""
        ...
