"""Langfuse tracing sink — additive to the SQLite LLM ledger.

Mirrors the ledger's start_call()/finish_call() pattern at the ModelRouter
choke point. When disabled (default), the SDK is never imported and all
methods are no-ops. When enabled, traces are emitted to Langfuse via the
v3 Python SDK (OTel-based).

Design constraints (see #53):
- The langfuse import is lazy — inside the enabled-guarded init, never at
  module level — so disabled mode never imports the SDK.
- start()/finish() mirror the ledger's explicit-call style, not the SDK's
  context-manager style, because generate() has three exit paths that the
  ledger already handles with explicit calls.
- All failure modes degrade silently: the SQLite ledger is never affected.
- operation_id is the correlation key — no job_id parameter on generate().
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_sink: LangfuseSink | None = None
_warned_init = False


class LangfuseSink:
    """Wraps a Langfuse v3 SDK client for trace emission.

    Constructed by init_sink() only when enabled=True and keys are present.
    All methods swallow exceptions so the pipeline is never affected.
    """

    def __init__(
        self,
        *,
        public_key: str,
        secret_key: str,
        base_url: str,
        capture_content: bool = False,
        flush_interval_seconds: float = 1.0,
    ):
        from langfuse import Langfuse

        self._capture_content = capture_content
        self._client = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=base_url,
            flush_interval=flush_interval_seconds,
        )

    def start(
        self,
        *,
        call_id: str,
        task: str,
        operation_id: str | None,
        system_prompt: str,
        user_prompt: str,
        prompt_name: str | None = None,
        prompt_version: str | None = None,
    ) -> None:
        """Record the start of an LLM generation.

        We don't create a trace at start — the v3 SDK's start_generation()
        is called at finish with the full payload. This keeps start lightweight
        and avoids half-created traces on routing failures.
        """
        # No-op: trace is emitted at finish with complete data.
        # This mirrors the ledger's start_call (which writes a DB row) but
        # Langfuse traces are better emitted as complete events.

    def finish(
        self,
        *,
        call_id: str,
        task: str,
        operation_id: str | None,
        system_prompt: str,
        user_prompt: str,
        response: Any | None = None,
        error: BaseException | None = None,
        provider: str | None = None,
        model: str | None = None,
        route_reason: str | None = None,
        prompt_name: str | None = None,
        prompt_version: str | None = None,
        started_monotonic: float = 0.0,
    ) -> None:
        """Record the completion (or failure) of an LLM generation."""
        try:
            latency_ms = (
                response.latency_ms if response and response.latency_ms
                else int((time.monotonic() - started_monotonic) * 1000) if started_monotonic
                else 0
            )
            input_tokens = response.input_tokens if response else 0
            output_tokens = response.output_tokens if response else getattr(error, "output_tokens", 0)
            stop_reason = response.stop_reason if response else getattr(error, "stop_reason", None)
            status = "error" if error else ("succeeded" if response and response.text else "empty")

            metadata: dict[str, Any] = {
                "operation_id": operation_id,
                "route_reason": route_reason,
                "call_id": call_id,
            }

            # Build the generation payload
            gen_kwargs: dict[str, Any] = {
                "name": prompt_name or task,
                "model": model or "",
                "metadata": metadata,
                "input": (
                    {"system": system_prompt, "user": user_prompt}
                    if self._capture_content
                    else None
                ),
                "output": response.text if response and self._capture_content else None,
                "usage": {
                    "input": input_tokens,
                    "output": output_tokens,
                    "unit": "TOKENS",
                },
                "level": "ERROR" if error else "DEFAULT",
            }

            if prompt_version:
                gen_kwargs["version"] = prompt_version

            if error:
                gen_kwargs["status_message"] = str(error)

            self._client.start_generation(
                trace_id=operation_id or call_id,
                **gen_kwargs,
            )
            self._client.finish_generation(
                generation=None,  # let SDK handle the generation object internally
            )
        except Exception:
            logger.debug("langfuse_finish_failed", exc_info=True)

    def flush(self) -> None:
        """Flush pending traces to the Langfuse server."""
        try:
            self._client.flush()
        except Exception:
            logger.debug("langfuse_flush_failed", exc_info=True)

    def shutdown(self) -> None:
        """Shut down the SDK client, flushing pending traces."""
        try:
            self._client.flush()
        except Exception:
            logger.debug("langfuse_shutdown_flush_failed", exc_info=True)
        try:
            self._client.shutdown()
        except Exception:
            logger.debug("langfuse_shutdown_failed", exc_info=True)


def init_sink(settings: Any) -> None:
    """Initialize the global Langfuse sink from observability config.

    If already initialized, the old client is shut down first (best-effort).
    When disabled or misconfigured, the sink remains None (no-op).
    """
    global _sink, _warned_init

    # Shut down existing sink if any
    if _sink is not None:
        _sink.shutdown()
        _sink = None

    obs = getattr(settings, "observability", None)
    if not obs:
        return

    lf = obs.langfuse
    if not lf.enabled:
        return

    if not lf.public_key or not lf.secret_key:
        if not _warned_init:
            logger.warning(
                "langfuse_enabled_but_no_keys: Langfuse is enabled in config "
                "but LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY are not set. "
                "Create keys in the Langfuse UI (Project Settings → API Keys) "
                "and add them to .env. Tracing is disabled until keys are provided."
            )
            _warned_init = True
        return

    try:
        _sink = LangfuseSink(
            public_key=lf.public_key,
            secret_key=lf.secret_key,
            base_url=lf.base_url,
            capture_content=lf.capture_content,
            flush_interval_seconds=lf.flush_interval_seconds,
        )
        _warned_init = False
        logger.info(
            "langfuse_sink_initialized: base_url=%s, capture_content=%s",
            lf.base_url, lf.capture_content,
        )
    except ImportError:
        if not _warned_init:
            logger.warning(
                "langfuse_sdk_not_installed: The 'langfuse' package is not installed. "
                "Install with: pip install langfuse>=3. Tracing is disabled."
            )
            _warned_init = True
    except Exception:
        if not _warned_init:
            logger.warning("langfuse_init_failed: sink disabled", exc_info=True)
            _warned_init = True


def disable_sink() -> None:
    """Disable the sink and shut down the existing client (best-effort).

    Used when toggling enabled→false via config reload. Disabling always
    works without restart — it just sets the sink to None after a
    best-effort shutdown on the old client.
    """
    global _sink
    if _sink is not None:
        _sink.shutdown()
        _sink = None
    logger.info("langfuse_sink_disabled")


def get_sink() -> LangfuseSink | None:
    """Return the active sink, or None if disabled/uninitialized."""
    return _sink


def get_status() -> dict:
    """Return status info for the /api/analytics/langfuse-status endpoint."""
    from seeker_os.config import get_settings

    settings = get_settings()
    obs = getattr(settings, "observability", None)
    if not obs:
        return {
            "enabled": False,
            "initialized": False,
            "base_url": "",
            "capture_content": False,
            "keys_configured": False,
        }

    lf = obs.langfuse
    return {
        "enabled": lf.enabled,
        "initialized": _sink is not None,
        "base_url": lf.base_url,
        "capture_content": lf.capture_content,
        "keys_configured": bool(lf.public_key and lf.secret_key),
    }
