"""OpenAI-compatible provider — works with any /v1/chat/completions endpoint.

Supports: OpenAI, Kilo, Ollama, vLLM, LiteLLN, and any OpenAI-compatible gateway.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from openai import OpenAI

from seeker_os.llm.models import LLMRequest, LLMResponse, ModelInfo, ProviderHealth, TruncationError


class OpenAICompatProvider:
    """OpenAI-compatible provider (Kilo, Ollama, vLLM, etc.).

    Uses the OpenAI Python SDK with a custom base_url.
    """

    def __init__(
        self,
        provider_id: str,
        api_key: str,
        base_url: str,
        label: str = "",
    ):
        self._id = provider_id
        self._type = "openai_compatible"
        self._label = label or provider_id
        self._client = OpenAI(
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
        """Generate a completion using OpenAI Chat Completions API."""
        start = time.monotonic()

        kwargs: dict = {
            "model": request.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            "temperature": request.temperature,
        }
        if request.max_tokens:
            kwargs["max_tokens"] = request.max_tokens

        response = self._client.chat.completions.create(**kwargs)
        latency = int((time.monotonic() - start) * 1000)

        text = ""
        finish_reason = ""
        if response.choices:
            choice = response.choices[0]
            if choice.message.content:
                text = choice.message.content
            finish_reason = choice.finish_reason or ""

        input_tokens = 0
        output_tokens = 0
        if response.usage:
            input_tokens = response.usage.prompt_tokens or 0
            output_tokens = response.usage.completion_tokens or 0

        # Detect truncation: finish_reason "length" means the model hit max_tokens
        if finish_reason in ("length", "max_tokens"):
            raise TruncationError(
                task=request.task,
                model=response.model or request.model,
                requested_max_tokens=request.max_tokens,
                output_tokens=output_tokens,
                stop_reason=finish_reason,
            )

        return LLMResponse(
            text=text,
            model=response.model or request.model,
            provider=self._id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency,
            task=request.task,
            stop_reason=finish_reason,
        )

    def list_models(self) -> list[ModelInfo]:
        """Fetch available models from the provider's /models endpoint."""
        now = datetime.now(timezone.utc).isoformat()
        response = self._client.models.list()
        models: list[ModelInfo] = []
        for m in response.data:
            models.append(ModelInfo(
                id=m.id,
                label=m.id,  # OpenAI-compatible endpoints usually don't have display names
                provider_id=self._id,
                context_window=None,
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
            self._client.models.list()
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
