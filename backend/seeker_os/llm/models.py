"""LLM data models — request, response, and model info."""

from __future__ import annotations

from dataclasses import dataclass, field


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


@dataclass
class ProviderHealth:
    """Health check result for a provider."""
    provider_id: str
    healthy: bool
    message: str = ""
    latency_ms: int = 0
    checked_at: str = ""
