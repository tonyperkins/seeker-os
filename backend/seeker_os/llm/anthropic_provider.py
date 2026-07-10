"""Anthropic provider — native Messages API."""

from __future__ import annotations

import time
from datetime import UTC, datetime

import anthropic

from seeker_os.llm.models import LLMRequest, LLMResponse, ModelInfo, ProviderHealth, TruncationError


class AnthropicProvider:
    """Direct Anthropic API provider using native Messages API.

    Uses a standard API key (sk-ant-...) for authentication.

    Docs: https://docs.anthropic.com/en/api/messages
    Models: https://docs.anthropic.com/en/api/models
    """

    def __init__(
        self,
        provider_id: str,
        api_key: str = "",
        base_url: str | None = None,
        label: str = "",
        **_extra: object,
    ):
        self._id = provider_id
        self._type = "anthropic"
        self._label = label or provider_id
        self._client = anthropic.Anthropic(
            api_key=api_key or None,
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
        }

        # Only include temperature if explicitly set (some models reject it)
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature

        try:
            response = self._client.messages.create(**kwargs)
        except Exception as e:
            # If temperature is rejected, retry without it
            if "temperature" in str(e).lower() and "deprecated" in str(e).lower():
                kwargs.pop("temperature", None)
                response = self._client.messages.create(**kwargs)
            else:
                raise
        latency = int((time.monotonic() - start) * 1000)

        text = ""
        if response.content:
            text = "".join(block.text for block in response.content if hasattr(block, "text"))

        stop_reason = response.stop_reason or ""

        # Detect truncation: Anthropic uses "max_tokens" as the stop_reason
        if stop_reason in ("max_tokens", "length"):
            raise TruncationError(
                task=request.task,
                model=response.model,
                requested_max_tokens=request.max_tokens,
                output_tokens=response.usage.output_tokens,
                stop_reason=stop_reason,
            )

        return LLMResponse(
            text=text,
            model=response.model,
            provider=self._id,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            latency_ms=latency,
            task=request.task,
            stop_reason=stop_reason,
        )

    def list_models(self) -> list[ModelInfo]:
        """Fetch available models from Anthropic's API."""
        now = datetime.now(UTC).isoformat()
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
                checked_at=datetime.now(UTC).isoformat(),
            )
        except Exception as e:
            return ProviderHealth(
                provider_id=self._id,
                healthy=False,
                message=str(e),
                latency_ms=int((time.monotonic() - start) * 1000),
                checked_at=datetime.now(UTC).isoformat(),
            )
