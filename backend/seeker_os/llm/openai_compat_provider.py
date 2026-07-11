"""OpenAI-compatible provider — works with any /v1/chat/completions endpoint.

Supports: OpenAI, Kilo, Ollama, vLLM, LiteLLN, and any OpenAI-compatible gateway.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

import httpx
from openai import OpenAI

from seeker_os.llm.models import LLMRequest, LLMResponse, ModelInfo, ProviderHealth, TruncationError

logger = logging.getLogger(__name__)


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
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
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
        logger.info(
            "llm_call provider=%s model=%s task=%s max_tokens=%s — sending request",
            self._id, request.model, request.task, request.max_tokens,
        )

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
        logger.info(
            "llm_call provider=%s model=%s task=%s — response received in %dms, finish=%s, tokens=%d",
            self._id, request.model, request.task, latency,
            response.choices[0].finish_reason if response.choices else "none",
            response.usage.completion_tokens if response.usage else 0,
        )

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
        """Fetch available models from the provider's /models endpoint.

        Uses a raw HTTP GET to capture non-standard fields (pricing, context_length,
        display name) that the OpenAI SDK strips out. Falls back to the SDK if the
        raw request fails.
        """
        now = datetime.now(UTC).isoformat()
        models = self._list_models_raw()
        if models is not None:
            return models

        # Fallback: use the SDK (no pricing data)
        logger.debug("Raw /models fetch failed for '%s', falling back to SDK", self._id)
        response = self._client.models.list()
        fallback: list[ModelInfo] = []
        for m in response.data:
            fallback.append(ModelInfo(
                id=m.id,
                label=m.id,
                provider_id=self._id,
                context_window=None,
                max_output=None,
                tags=[],
                source="auto",
                available=True,
                fetched_at=now,
            ))
        return fallback

    def _list_models_raw(self) -> list[ModelInfo] | None:
        """Raw HTTP GET to /models — captures pricing from Kilo/OpenRouter.

        Returns None if the request fails (caller falls back to SDK).
        """
        now = datetime.now(UTC).isoformat()
        headers = {"Authorization": f"Bearer {self._api_key}"}
        url = f"{self._base_url}/models"
        try:
            resp = httpx.get(url, headers=headers, timeout=30.0)
            resp.raise_for_status()
        except Exception as e:
            logger.debug("Raw /models fetch failed for '%s': %s", self._id, e)
            return None

        data = resp.json().get("data", [])
        models: list[ModelInfo] = []
        for m in data:
            model_id = m.get("id", "")
            if not model_id:
                continue

            # Parse pricing (per-token → per-million)
            pricing = m.get("pricing") or {}
            in_price = _parse_per_token_to_per_mtok(pricing.get("prompt"))
            out_price = _parse_per_token_to_per_mtok(pricing.get("completion"))

            # Some providers include context_length at top level or in top_provider
            ctx = m.get("context_length") or m.get("context_window")
            top_provider = m.get("top_provider") or {}
            if ctx is None:
                ctx = top_provider.get("context_length")
            max_out = top_provider.get("max_completion_tokens") or m.get("max_output")

            models.append(ModelInfo(
                id=model_id,
                label=m.get("name") or m.get("label") or model_id,
                provider_id=self._id,
                context_window=ctx,
                max_output=max_out,
                tags=[],
                source="auto",
                available=True,
                fetched_at=now,
                input_price_per_mtok=in_price,
                output_price_per_mtok=out_price,
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


def _parse_per_token_to_per_mtok(value: str | None) -> float | None:
    """Convert a per-token price string (e.g. '0.000005') to per-1M-tokens float.

    Kilo/OpenRouter return pricing as USD per token. We need USD per 1M tokens.
    Returns 0.0 for an explicit zero price (free — e.g. Ollama models).
    Returns None only for missing/unparseable values (no pricing data).
    """
    if value is None:
        return None
    try:
        per_token = float(value)
    except (ValueError, TypeError):
        return None
    if per_token == 0:
        return 0.0
    if per_token < 0:
        return None
    return round(per_token * 1_000_000, 4)
