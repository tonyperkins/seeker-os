"""Langfuse sink — API-compatibility regression tests.

These run against the REAL installed langfuse SDK (no server — the OTel
exporter fails asynchronously, which is fine). The sink swallows every
exception by design, so a wrong SDK call degrades to silently emitting
nothing; the only way to catch that in CI is to assert the sink's
failure-path debug logs are never hit. #55 adds the fuller behavior suite
(canary PII test, mocked-client field assertions).
"""

import logging
import types

import pytest

from seeker_os.observability import langfuse_sink as sink_mod
from seeker_os.observability.langfuse_sink import (
    LangfuseSink,
    disable_sink,
    get_sink,
    init_sink,
)

pytest.importorskip("langfuse")

_FAILURE_MARKERS = (
    "langfuse_start_failed",
    "langfuse_finish_failed",
    "langfuse_shutdown_failed",
    "langfuse_shutdown_flush_failed",
    "langfuse_orphan_end_failed",
)


from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

@pytest.fixture(autouse=True)
def exporter(monkeypatch):
    """Route the SDK's OTel spans to a fresh in-memory exporter per test.

    Without this, flush/shutdown sit in the OTLP exporter's retry/backoff
    loop against the unreachable test host (minutes per test). Bonus: we can
    assert spans are actually exported — the regression this file exists for
    is a sink that silently exports nothing.
    """
    import langfuse as _lf

    real = _lf.Langfuse
    exp = InMemorySpanExporter()

    def patched(*args, **kwargs):
        kwargs.setdefault("span_exporter", exp)
        kwargs.setdefault("timeout", 1)
        return real(*args, **kwargs)

    monkeypatch.setattr(_lf, "Langfuse", patched)
    return exp


def _make_sink(capture_content=False):
    return LangfuseSink(
        public_key="pk-lf-test",
        secret_key="sk-lf-test",
        base_url="http://127.0.0.1:9",  # never contacted — in-memory exporter
        capture_content=capture_content,
        flush_interval_seconds=60.0,
    )


def _fake_response():
    return types.SimpleNamespace(
        text="output text",
        input_tokens=100,
        output_tokens=20,
        latency_ms=1234,
        stop_reason="end_turn",
    )


def _assert_no_failures(caplog):
    failures = [
        r.message for r in caplog.records
        if any(m in r.message for m in _FAILURE_MARKERS)
    ]
    assert not failures, f"sink hit silent-failure path(s): {failures}"


class TestSinkSdkCompatibility:
    """A wrong SDK call surfaces only as a debug log — assert none happen."""

    def test_start_finish_success_path(self, caplog, exporter):
        caplog.set_level(logging.DEBUG, logger=sink_mod.__name__)
        s = _make_sink()
        s.start(
            call_id="c1", task="jd_analysis", operation_id="op-1",
            system_prompt="sys", user_prompt="usr",
            prompt_name="jd_analysis", prompt_version="v2",
        )
        assert "c1" in s._active, "start() did not register an observation"
        s.finish(
            call_id="c1", task="jd_analysis", operation_id="op-1",
            system_prompt="sys", user_prompt="usr",
            response=_fake_response(), provider="anthropic",
            model="claude-sonnet-5", route_reason="task_or_tier_resolution",
        )
        assert s._active == {}, "finish() did not close the observation"
        _assert_no_failures(caplog)
        s.flush()
        spans = exporter.get_finished_spans()
        assert spans, "no spans exported — the sink is silently emitting nothing"
        assert any(sp.name == "jd_analysis" for sp in spans)
        s.shutdown()

    def test_error_path(self, caplog):
        caplog.set_level(logging.DEBUG, logger=sink_mod.__name__)
        s = _make_sink()
        s.start(
            call_id="c2", task="jd_analysis", operation_id="op-2",
            system_prompt="sys", user_prompt="usr",
        )
        s.finish(
            call_id="c2", task="jd_analysis", operation_id="op-2",
            system_prompt="sys", user_prompt="usr",
            error=RuntimeError("provider exploded"),
            provider="anthropic", model="claude-sonnet-5",
        )
        assert s._active == {}
        _assert_no_failures(caplog)
        s.shutdown()

    def test_capture_content_path(self, caplog):
        caplog.set_level(logging.DEBUG, logger=sink_mod.__name__)
        s = _make_sink(capture_content=True)
        s.start(
            call_id="c3", task="jd_analysis", operation_id="op-3",
            system_prompt="sys", user_prompt="usr",
        )
        s.finish(
            call_id="c3", task="jd_analysis", operation_id="op-3",
            system_prompt="sys", user_prompt="usr",
            response=_fake_response(), provider="anthropic", model="m",
        )
        _assert_no_failures(caplog)
        s.shutdown()

    def test_finish_without_start_is_noop(self, caplog):
        caplog.set_level(logging.DEBUG, logger=sink_mod.__name__)
        s = _make_sink()
        s.finish(
            call_id="never-started", task="t", operation_id=None,
            system_prompt="s", user_prompt="u", response=_fake_response(),
        )
        _assert_no_failures(caplog)
        s.shutdown()

    def test_shutdown_ends_orphans(self, caplog):
        caplog.set_level(logging.DEBUG, logger=sink_mod.__name__)
        s = _make_sink()
        s.start(call_id="orphan", task="t", operation_id="op-o",
                system_prompt="s", user_prompt="u")
        s.shutdown()
        assert s._active == {}
        _assert_no_failures(caplog)

    def test_shutdown_then_reinit(self, caplog):
        """The OTel re-init spike as a regression test."""
        caplog.set_level(logging.DEBUG, logger=sink_mod.__name__)
        s1 = _make_sink()
        s1.start(call_id="r1", task="t", operation_id="op-r",
                 system_prompt="s", user_prompt="u")
        s1.finish(call_id="r1", task="t", operation_id="op-r",
                  system_prompt="s", user_prompt="u", response=_fake_response())
        s1.shutdown()
        s2 = _make_sink()
        s2.start(call_id="r2", task="t", operation_id="op-r",
                 system_prompt="s", user_prompt="u")
        s2.finish(call_id="r2", task="t", operation_id="op-r",
                  system_prompt="s", user_prompt="u", response=_fake_response())
        s2.shutdown()
        _assert_no_failures(caplog)


class TestInitSink:
    def test_disabled_config_leaves_sink_none(self):
        settings = types.SimpleNamespace(
            observability=types.SimpleNamespace(
                langfuse=types.SimpleNamespace(
                    enabled=False, base_url="", public_key="", secret_key="",
                    capture_content=False, flush_interval_seconds=1.0,
                )
            )
        )
        init_sink(settings)
        assert get_sink() is None

    def test_enabled_without_keys_leaves_sink_none(self):
        settings = types.SimpleNamespace(
            observability=types.SimpleNamespace(
                langfuse=types.SimpleNamespace(
                    enabled=True, base_url="http://127.0.0.1:9",
                    public_key="", secret_key="",
                    capture_content=False, flush_interval_seconds=1.0,
                )
            )
        )
        init_sink(settings)
        assert get_sink() is None

    def test_enabled_with_keys_initializes_and_disable_clears(self):
        settings = types.SimpleNamespace(
            observability=types.SimpleNamespace(
                langfuse=types.SimpleNamespace(
                    enabled=True, base_url="http://127.0.0.1:9",
                    public_key="pk-lf-test", secret_key="sk-lf-test",
                    capture_content=False, flush_interval_seconds=60.0,
                )
            )
        )
        init_sink(settings)
        assert get_sink() is not None
        disable_sink()
        assert get_sink() is None
