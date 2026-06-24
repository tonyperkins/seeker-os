"""Anthropic provider — native Messages API."""

from __future__ import annotations

import time
from datetime import datetime, timezone

import anthropic

from seeker_os.llm.models import LLMRequest, LLMResponse, ModelInfo, ProviderHealth


class AnthropicProvider:
    """Direct Anthropic API provider using native Messages API.

    Docs: https://docs.anthropic.com/en/api/messages
    Models: https://docs.anthropic.com/en/api/models
    """

    def __init__(
        self,
        provider_id: str,
        api_key: str,
        base_url: str | None = None,
        label: str = "",
    ):
        self._id = provider_id
        self._type = "anthropic"
        self._label = label or provider_id
        self._client = anthropic.Anthropic(
            api_key=api_key,
            base_url=base_url,
        )

    @property
    def id(self) -> str:
        return self._id

    @property
    def type(self) -> str:
        return self._type

    def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate a completion using Anthropic's Messages API."""
        start = time.monotonic()

        kwargs: dict = {
            "model": request.model,
            "max_tokens": request.max_tokens or 4096,
            "system": request.system_prompt,
            "messages": [{"role": "user", "content": request.user_prompt}],
            "temperature": request.temperature,
        }

        response = self._client.messages.create(**kwargs)
        latency = int((time.monotonic() - start) * 1000)

        text = ""
        if response.content:
            text = "".join(block.text for block in response.content if hasattr(block, "text"))

        return LLMResponse(
            text=text,
            model=response.model,
            provider=self._id,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            latency_ms=latency,
            task=request.task,
        )

    def list_models(self) -> list[ModelInfo]:
        """Fetch available models from Anthropic's API."""
        now = datetime.now(timezone.utc).isoformat()
        response = self._client.models.list()
        models: list[ModelInfo] = []
        for m in response.data:
            models.append(ModelInfo(
                id=m.id,
                label=m.display_name or m.id,
                provider_id=self._id,
                context_window=getattr(m, "context_window", None),
                max_output=None,
                tags=[],
                source="auto",
                available=True,
                fetched_at=now,
            ))
        return models

    def test_connection(self) -> ProviderHealth:
        """Test connectivity by listing models."""
        start = time.monotonic()
        try:
            self._client.models.list(limit=1)
            latency = int((time.monotonic() - start) * 1000)
            return ProviderHealth(
                provider_id=self._id,
                healthy=True,
                message="Connection OK",
                latency_ms=latency,
                checked_at=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as e:
            return ProviderHealth(
                provider_id=self._id,
                healthy=False,
                message=str(e),
                latency_ms=int((time.monotonic() - start) * 1000),
                checked_at=datetime.now(timezone.utc).isoformat(),
            )
