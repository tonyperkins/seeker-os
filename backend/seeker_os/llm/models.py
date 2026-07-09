"""LLM data models — request, response, and model info."""

from __future__ import annotations

from dataclasses import dataclass, field


class TruncationError(Exception):
    """Raised when an LLM response hit the max_tokens ceiling (stop_reason == length).

    This is distinct from a parse error — the output was cut off before completion.
    The fix is to raise max_tokens or route to a higher-capacity model, not to fix
    the prompt or parser.
    """

    def __init__(
        self,
        task: str,
        model: str,
        requested_max_tokens: int | None,
        output_tokens: int,
        stop_reason: str,
    ):
        self.task = task
        self.model = model
        self.requested_max_tokens = requested_max_tokens
        self.output_tokens = output_tokens
        self.stop_reason = stop_reason
        super().__init__(
            f"LLM response for task '{task}' was truncated (stop_reason='{stop_reason}'). "
            f"Requested max_tokens={requested_max_tokens}, produced {output_tokens} output tokens. "
            f"Model: {model}. "
            f"Fix: increase max_tokens for this task in config, or route to a higher-capacity model."
        )


@dataclass
class LLMRequest:
    """A request to an LLM provider."""
    system_prompt: str
    user_prompt: str
    model: str
    temperature: float = 0.7
    max_tokens: int | None = None
    stream: bool = False
    task: str = ""  # for logging/tracing


@dataclass
class LLMResponse:
    """A response from an LLM provider."""
    text: str
    model: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    task: str = ""
    stop_reason: str = ""  # "stop", "length", "max_tokens", etc.


@dataclass
class ModelInfo:
    """Information about a model available from a provider."""
    id: str
    label: str
    provider_id: str
    context_window: int | None = None
    max_output: int | None = None
    tags: list[str] = field(default_factory=list)
    source: str = "manual"  # 'manual' (in config) or 'auto' (fetched)
    available: bool = True
    fetched_at: str | None = None  # ISO timestamp when last fetched
    # Pricing per 1M tokens (USD) — populated from provider API when available
    # (Kilo, OpenRouter). Falls back to YAML config in providers.yml.
    input_price_per_mtok: float | None = None
    output_price_per_mtok: float | None = None


@dataclass
class ProviderHealth:
    """Health check result for a provider."""
    provider_id: str
    healthy: bool
    message: str = ""
    latency_ms: int = 0
    checked_at: str = ""
