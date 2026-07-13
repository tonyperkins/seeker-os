"""Langfuse tracing sink — additive to the SQLite LLM ledger.

Mirrors the ledger's start_call()/finish_call() pattern at the ModelRouter
choke point. When disabled (default), the SDK is never imported and all
methods are no-ops. When enabled, traces are emitted to Langfuse via the
OTel-based Python SDK (v4 — validated against 4.14; `start_generation`/
`finish_generation` from the v2/early-v3 API do not exist on this client).

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
import threading
from typing import Any

logger = logging.getLogger(__name__)

_sink: LangfuseSink | None = None
_warned_init = False
_connection_ok = False
_warned_connection = False

# Suppress noisy OTel exporter retry/timeout logs — these fire on every
# failed span export and are not actionable. We surface connection issues
# via our own warning in init_sink() and the status endpoint instead.
logging.getLogger("opentelemetry.exporter.otlp.proto.http.trace_exporter").setLevel(
    logging.CRITICAL
)


class LangfuseSink:
    """Wraps a Langfuse SDK client for trace emission.

    Constructed by init_sink() only when enabled=True and keys are present.
    All methods swallow exceptions so the pipeline is never affected.

    start() opens a generation observation (so Langfuse records real
    durations); finish() updates it with the outcome and ends it. In-flight
    observations are keyed by call_id — generate() guarantees a finish() on
    every exit path, and shutdown() ends any orphans defensively.
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
        self._public_key = public_key
        self._base_url = base_url
        self._active: dict[str, Any] = {}
        self._lock = threading.Lock()
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
        """Open a generation observation, grouped into a trace by operation_id."""
        try:
            trace_context = None
            if operation_id:
                # Deterministic W3C trace id derived from the operation, so all
                # calls in one pipeline operation land in one Langfuse trace.
                trace_context = {
                    "trace_id": self._client.create_trace_id(seed=operation_id)
                }
            gen = self._client.start_observation(
                as_type="generation",
                name=prompt_name or task,
                trace_context=trace_context,
                input=(
                    {"system": system_prompt, "user": user_prompt}
                    if self._capture_content
                    else None
                ),
                metadata={
                    "operation_id": operation_id,
                    "call_id": call_id,
                    "task": task,
                },
                version=prompt_version or None,
            )
            with self._lock:
                self._active[call_id] = gen
        except Exception:
            logger.debug("langfuse_start_failed", exc_info=True)

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
        """Update the observation opened by start() with the outcome and end it."""
        try:
            with self._lock:
                gen = self._active.pop(call_id, None)
            if gen is None:
                return

            update_kwargs: dict[str, Any] = {
                "metadata": {
                    "operation_id": operation_id,
                    "call_id": call_id,
                    "task": task,
                    "provider": provider,
                    "route_reason": route_reason,
                    "stop_reason": getattr(response, "stop_reason", None),
                    "latency_ms": getattr(response, "latency_ms", None),
                },
                "usage_details": {
                    "input": getattr(response, "input_tokens", 0) or 0,
                    "output": getattr(response, "output_tokens", 0) or 0,
                },
            }
            if model:
                update_kwargs["model"] = model
            if self._capture_content and response is not None:
                update_kwargs["output"] = response.text
            if error is not None:
                update_kwargs["level"] = "ERROR"
                update_kwargs["status_message"] = str(error)

            gen.update(**update_kwargs)
            gen.end()
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
        # End any in-flight observations so they aren't dropped (spans that
        # are never ended are not exported).
        with self._lock:
            orphans = list(self._active.values())
            self._active.clear()
        for gen in orphans:
            try:
                gen.end()
            except Exception:
                logger.debug("langfuse_orphan_end_failed", exc_info=True)
        try:
            self._client.flush()
        except Exception:
            logger.debug("langfuse_shutdown_flush_failed", exc_info=True)
        try:
            self._client.shutdown()
        except Exception:
            logger.debug("langfuse_shutdown_failed", exc_info=True)
        # Shut down the OTel tracer provider that the Langfuse SDK created.
        # Without this, the background exporter thread persists as a global
        # singleton and keeps retrying against the old URL after a config
        # reload changes base_url.
        try:
            from opentelemetry.trace import get_tracer_provider
            provider = get_tracer_provider()
            if hasattr(provider, "shutdown"):
                provider.shutdown()
        except Exception:
            logger.debug("otel_provider_shutdown_failed", exc_info=True)
        # The SDK caches its resource manager (background workers, queues)
        # per public_key and shutdown() does NOT deregister it — a later
        # client with the same key would get back the dead instance, whose
        # flush() blocks forever on queues no worker drains. Deregister so
        # config-reload re-init gets a fresh, working client. (Private API;
        # verified against langfuse 4.14 — see test_langfuse_sink.py.)
        try:
            from langfuse._client.resource_manager import LangfuseResourceManager

            LangfuseResourceManager._instances.pop(self._public_key, None)
        except Exception:
            logger.debug("langfuse_deregister_failed", exc_info=True)


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
        _check_connection(lf.base_url, lf.public_key, lf.secret_key)
    except ImportError:
        if not _warned_init:
            logger.warning(
                "langfuse_sdk_not_installed: The 'langfuse' package is not installed. "
                "Install with: pip install 'langfuse>=4,<5'. Tracing is disabled."
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
            "connection_ok": False,
        }

    lf = obs.langfuse
    return {
        "enabled": lf.enabled,
        "initialized": _sink is not None,
        "base_url": lf.base_url,
        "capture_content": lf.capture_content,
        "keys_configured": bool(lf.public_key and lf.secret_key),
        "connection_ok": _connection_ok,
    }


def _check_connection(base_url: str, public_key: str, secret_key: str) -> None:
    """Best-effort health check against the Langfuse server.

    Logs a single clear warning if the server is unreachable or keys are
    invalid. Does not block — the sink still initializes and will retry
    on its own. The OTel exporter logs are suppressed so the user only
    sees this one message instead of repeated retry spam.
    """
    global _connection_ok, _warned_connection
    import urllib.request
    import urllib.error

    _connection_ok = False
    health_url = base_url.rstrip("/") + "/api/public/health"
    try:
        req = urllib.request.Request(health_url)
        req.add_header("Authorization", "Basic " + _basic_auth(public_key, secret_key))
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                _connection_ok = True
                _warned_connection = False
                logger.info("langfuse_connection_ok: %s", base_url)
            else:
                _warn_connection(base_url, f"HTTP {resp.status}")
    except urllib.error.HTTPError as exc:
        _warn_connection(base_url, f"HTTP {exc.code} — check API keys")
    except Exception as exc:
        _warn_connection(base_url, str(exc))


def _warn_connection(base_url: str, detail: str) -> None:
    """Log a one-time warning about Langfuse connection failure."""
    global _warned_connection
    if not _warned_connection:
        logger.warning(
            "langfuse_connection_failed: %s — %s. "
            "Tracing will retry in the background but traces may not appear. "
            "Check base_url and API keys. This warning will not repeat.",
            base_url, detail,
        )
        _warned_connection = True


def _basic_auth(public_key: str, secret_key: str) -> str:
    import base64
    creds = f"{public_key}:{secret_key}"
    return base64.b64encode(creds.encode()).decode()
