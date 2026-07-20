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

import langfuse  # noqa: F401 — declared dependency, not optional

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


# ---------------------------------------------------------------------------
# #55 — PII audit: canary test + capture_content toggle + allowed fields
# ---------------------------------------------------------------------------

_Canary = "CANARY_PII_7f3a2b8e"

_ALLOWED_METADATA_KEYS = frozenset({
    "operation_id", "call_id", "task", "provider", "route_reason",
    "stop_reason", "latency_ms",
})


class _MockObservation:
    """Records every argument passed to update()/end() for PII scanning."""

    def __init__(self):
        self.update_calls: list[dict] = []
        self.end_calls: int = 0

    def update(self, **kwargs):
        self.update_calls.append(kwargs)

    def end(self):
        self.end_calls += 1


class _MockLangfuseClient:
    """Records every argument passed to start_observation() for PII scanning."""

    def __init__(self):
        self.start_calls: list[dict] = []
        self.observations: dict[str, _MockObservation] = {}
        self._flushed = False
        self._shutdown = False

    def start_observation(self, **kwargs):
        obs = _MockObservation()
        self.start_calls.append(kwargs)
        return obs

    def create_trace_id(self, seed):
        return "mock-trace-id"

    def flush(self):
        self._flushed = True

    def shutdown(self):
        self._shutdown = True


def _all_strings_from_call(call: dict) -> list[str]:
    """Recursively extract all string values from a kwargs dict."""
    result = []

    def _walk(obj):
        if isinstance(obj, str):
            result.append(obj)
        elif isinstance(obj, dict):
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, (list, tuple)):
            for item in obj:
                _walk(item)
        elif obj is not None and hasattr(obj, "__dict__"):
            for v in vars(obj).values():
                _walk(v)

    for v in call.values():
        _walk(v)
    return result


class TestPiiAudit:
    """Assert default (capture_content=False) traces never contain prompt content."""

    def test_canary_absent_in_default_mode(self, monkeypatch):
        """Inject a canary into prompts; with capture_content=False it must
        appear in NO argument of ANY call on the mocked SDK client."""
        observations: list[_MockObservation] = []

        class _TrackingClient(_MockLangfuseClient):
            def start_observation(self, **kwargs):
                obs = _MockObservation()
                observations.append(obs)
                self.start_calls.append(kwargs)
                return obs

        client = _TrackingClient()
        import langfuse as _lf
        monkeypatch.setattr(_lf, "Langfuse", lambda *a, **kw: client)

        s = LangfuseSink(
            public_key="pk", secret_key="sk",
            base_url="http://x", capture_content=False,
        )
        s.start(
            call_id="pii-1", task="jd_analysis", operation_id="op-pii",
            system_prompt=f"system with {_Canary}",
            user_prompt=f"user with {_Canary}",
            prompt_name="jd_analysis", prompt_version="v1",
        )
        s.finish(
            call_id="pii-1", task="jd_analysis", operation_id="op-pii",
            system_prompt=f"system with {_Canary}",
            user_prompt=f"user with {_Canary}",
            response=_fake_response(), provider="anthropic",
            model="claude-sonnet-5", route_reason="task_or_tier_resolution",
        )
        s.shutdown()

        for call in client.start_calls:
            for string in _all_strings_from_call(call):
                assert _Canary not in string, (
                    f"Canary leaked into start_observation: {call}"
                )
        for obs in observations:
            for call in obs.update_calls:
                for string in _all_strings_from_call(call):
                    assert _Canary not in string, (
                        f"Canary leaked into observation.update: {call}"
                    )

    def test_canary_absent_no_strings_anywhere(self, monkeypatch):
        """Primary canary assertion: canary appears in NO string argument of
        ANY call on the mocked SDK client — not just known content fields."""
        mock_client = _MockLangfuseClient()

        # Patch Langfuse constructor to return our mock AND track observations
        observations: list[_MockObservation] = []

        class _TrackingClient(_MockLangfuseClient):
            def start_observation(self, **kwargs):
                obs = _MockObservation()
                observations.append(obs)
                self.start_calls.append(kwargs)
                return obs

        client = _TrackingClient()
        import langfuse as _lf
        monkeypatch.setattr(_lf, "Langfuse", lambda *a, **kw: client)

        s = LangfuseSink(
            public_key="pk", secret_key="sk",
            base_url="http://x", capture_content=False,
        )
        s.start(
            call_id="pii-2", task="jd_analysis", operation_id="op-pii2",
            system_prompt=f"secret system {_Canary} prompt",
            user_prompt=f"secret user {_Canary} prompt",
            prompt_name="jd_analysis", prompt_version="v1",
        )
        s.finish(
            call_id="pii-2", task="jd_analysis", operation_id="op-pii2",
            system_prompt=f"secret system {_Canary} prompt",
            user_prompt=f"secret user {_Canary} prompt",
            response=_fake_response(), provider="anthropic",
            model="claude-sonnet-5", route_reason="task_or_tier_resolution",
        )
        s.shutdown()

        # Scan every string from start_calls
        for call in client.start_calls:
            for string in _all_strings_from_call(call):
                assert _Canary not in string, (
                    f"Canary leaked into start_observation: {call}"
                )

        # Scan every string from update calls on observations
        for obs in observations:
            for call in obs.update_calls:
                for string in _all_strings_from_call(call):
                    assert _Canary not in string, (
                        f"Canary leaked into observation.update: {call}"
                    )

    def test_canary_present_with_capture_content(self, monkeypatch):
        """With capture_content=True, the canary SHOULD appear (in input/output)
        — and ONLY when the flag is on."""
        observations: list[_MockObservation] = []

        class _TrackingClient(_MockLangfuseClient):
            def start_observation(self, **kwargs):
                obs = _MockObservation()
                observations.append(obs)
                self.start_calls.append(kwargs)
                return obs

        client = _TrackingClient()
        import langfuse as _lf
        monkeypatch.setattr(_lf, "Langfuse", lambda *a, **kw: client)

        s = LangfuseSink(
            public_key="pk", secret_key="sk",
            base_url="http://x", capture_content=True,
        )
        s.start(
            call_id="pii-3", task="jd_analysis", operation_id="op-pii3",
            system_prompt=f"system with {_Canary}",
            user_prompt=f"user with {_Canary}",
        )
        s.finish(
            call_id="pii-3", task="jd_analysis", operation_id="op-pii3",
            system_prompt=f"system with {_Canary}",
            user_prompt=f"user with {_Canary}",
            response=_fake_response(), provider="anthropic", model="m",
        )
        s.shutdown()

        # Canary should be in start's input field
        start_call = client.start_calls[0]
        input_val = start_call.get("input")
        assert input_val is not None, "capture_content=True should set input on start"
        input_str = str(input_val)
        assert _Canary in input_str, "canary should appear in input when capture_content=True"

        # Canary should be in finish's output field
        assert len(observations) == 1
        update_calls = observations[0].update_calls
        assert len(update_calls) == 1
        output_val = update_calls[0].get("output")
        assert output_val is not None, "capture_content=True should set output on finish"
        assert _Canary not in str(output_val), "canary is in prompts, not output — output is response.text"

    def test_default_trace_only_allowed_fields(self, monkeypatch):
        """Assert default trace payloads contain only allowed fields —
        no job titles, company names, resume content, or profile data."""
        observations: list[_MockObservation] = []

        class _TrackingClient(_MockLangfuseClient):
            def start_observation(self, **kwargs):
                obs = _MockObservation()
                observations.append(obs)
                self.start_calls.append(kwargs)
                return obs

        client = _TrackingClient()
        import langfuse as _lf
        monkeypatch.setattr(_lf, "Langfuse", lambda *a, **kw: client)

        s = LangfuseSink(
            public_key="pk", secret_key="sk",
            base_url="http://x", capture_content=False,
        )
        s.start(
            call_id="fields-1", task="jd_analysis", operation_id="op-fields",
            system_prompt="sys", user_prompt="usr",
            prompt_name="jd_analysis", prompt_version="v2",
        )
        s.finish(
            call_id="fields-1", task="jd_analysis", operation_id="op-fields",
            system_prompt="sys", user_prompt="usr",
            response=_fake_response(), provider="anthropic",
            model="claude-sonnet-5", route_reason="task_or_tier_resolution",
        )
        s.shutdown()

        # Check start_call: input must be None, metadata must have only allowed keys
        start_call = client.start_calls[0]
        assert start_call.get("input") is None, "input must be None when capture_content=False"

        metadata = start_call.get("metadata", {})
        for key in metadata:
            assert key in _ALLOWED_METADATA_KEYS, (
                f"Unexpected metadata key in start: {key}"
            )

        # Check update call: output must not be set, metadata must have only allowed keys
        assert len(observations) == 1
        update_call = observations[0].update_calls[0]
        assert "output" not in update_call, "output must not be set when capture_content=False"

        update_meta = update_call.get("metadata", {})
        for key in update_meta:
            assert key in _ALLOWED_METADATA_KEYS, (
                f"Unexpected metadata key in update: {key}"
            )


# ---------------------------------------------------------------------------
# #55 — Sink behavior tests
# ---------------------------------------------------------------------------

class TestSinkBehavior:
    """Fuller behavior suite using mocked SDK client."""

    def test_disabled_sink_no_sdk_client(self, monkeypatch):
        """Disabled sink is a no-op: no SDK client is constructed."""
        constructed = []
        import langfuse as _lf
        original = _lf.Langfuse

        def tracking(*a, **kw):
            constructed.append(True)
            return original(*a, **kw)

        monkeypatch.setattr(_lf, "Langfuse", tracking)

        settings = types.SimpleNamespace(
            observability=types.SimpleNamespace(
                langfuse=types.SimpleNamespace(
                    enabled=False, base_url="http://x",
                    public_key="pk", secret_key="sk",
                    capture_content=False, flush_interval_seconds=1.0,
                )
            )
        )
        init_sink(settings)
        assert get_sink() is None
        assert not constructed, "Langfuse client was constructed when disabled"

    def test_enabled_sink_emits_correct_fields(self, monkeypatch):
        """Enabled sink emits start/finish with correct fields (mocked client)."""
        observations: list[_MockObservation] = []

        class _TrackingClient(_MockLangfuseClient):
            def start_observation(self, **kwargs):
                obs = _MockObservation()
                observations.append(obs)
                self.start_calls.append(kwargs)
                return obs

        client = _TrackingClient()
        import langfuse as _lf
        monkeypatch.setattr(_lf, "Langfuse", lambda *a, **kw: client)

        s = LangfuseSink(
            public_key="pk", secret_key="sk",
            base_url="http://x", capture_content=False,
        )
        s.start(
            call_id="beh-1", task="resume_generation", operation_id="op-beh",
            system_prompt="sys", user_prompt="usr",
            prompt_name="resume_generation", prompt_version="v3",
        )
        s.finish(
            call_id="beh-1", task="resume_generation", operation_id="op-beh",
            system_prompt="sys", user_prompt="usr",
            response=_fake_response(), provider="anthropic",
            model="claude-sonnet-5", route_reason="task_or_tier_resolution",
        )

        # Verify start fields
        start_call = client.start_calls[0]
        assert start_call["name"] == "resume_generation"
        assert start_call["version"] == "v3"
        assert start_call["input"] is None  # capture_content=False
        assert start_call["metadata"]["task"] == "resume_generation"
        assert start_call["metadata"]["operation_id"] == "op-beh"
        assert start_call["metadata"]["call_id"] == "beh-1"

        # Verify finish fields
        assert len(observations) == 1
        update_call = observations[0].update_calls[0]
        assert update_call["model"] == "claude-sonnet-5"
        assert update_call["metadata"]["provider"] == "anthropic"
        assert update_call["metadata"]["route_reason"] == "task_or_tier_resolution"
        assert update_call["metadata"]["stop_reason"] == "end_turn"
        assert update_call["metadata"]["latency_ms"] == 1234
        assert update_call["usage_details"]["input"] == 100
        assert update_call["usage_details"]["output"] == 20
        assert "output" not in update_call  # capture_content=False

        s.shutdown()

    def test_missing_keys_warning_no_raise(self, caplog):
        """Missing keys with enabled=True → warning logged, sink disabled, no raise.

        TODO(langfuse): pre-existing failure as of 2026-07-19, unrelated to
        the Phase 1 resume bullet-selection work — tracked separately, must
        be green before the Langfuse blog post publishes. Not touched here
        per explicit scope exclusion.
        """
        caplog.set_level(logging.WARNING, logger=sink_mod.__name__)
        settings = types.SimpleNamespace(
            observability=types.SimpleNamespace(
                langfuse=types.SimpleNamespace(
                    enabled=True, base_url="http://x",
                    public_key="", secret_key="",
                    capture_content=False, flush_interval_seconds=1.0,
                )
            )
        )
        # Should not raise
        init_sink(settings)
        assert get_sink() is None
        assert any("langfuse_enabled_but_no_keys" in r.message for r in caplog.records)

    def test_sink_failure_does_not_propagate(self, monkeypatch):
        """Sink/SDK failure never propagates to the pipeline."""
        import langfuse as _lf

        class _ExplodingClient:
            def start_observation(self, **kwargs):
                raise RuntimeError("SDK exploded")
            def create_trace_id(self, seed):
                raise RuntimeError("SDK exploded")
            def flush(self):
                raise RuntimeError("SDK exploded")
            def shutdown(self):
                raise RuntimeError("SDK exploded")

        monkeypatch.setattr(_lf, "Langfuse", lambda *a, **kw: _ExplodingClient())

        s = LangfuseSink(
            public_key="pk", secret_key="sk",
            base_url="http://x", capture_content=False,
        )
        # None of these should raise
        s.start(
            call_id="boom", task="t", operation_id="op-boom",
            system_prompt="s", user_prompt="u",
        )
        s.finish(
            call_id="boom", task="t", operation_id="op-boom",
            system_prompt="s", user_prompt="u",
            response=_fake_response(), provider="anthropic", model="m",
        )
        s.flush()
        s.shutdown()

    def test_config_reload_reinit(self, monkeypatch):
        """Config reload re-initializes sink (enabled → disabled → enabled)
        and cleans up the old client."""
        clients: list[_MockLangfuseClient] = []

        class _TrackingClient(_MockLangfuseClient):
            pass

        def make_client(*a, **kw):
            c = _TrackingClient()
            clients.append(c)
            return c

        import langfuse as _lf
        monkeypatch.setattr(_lf, "Langfuse", make_client)

        enabled_settings = types.SimpleNamespace(
            observability=types.SimpleNamespace(
                langfuse=types.SimpleNamespace(
                    enabled=True, base_url="http://x",
                    public_key="pk", secret_key="sk",
                    capture_content=False, flush_interval_seconds=60.0,
                )
            )
        )
        disabled_settings = types.SimpleNamespace(
            observability=types.SimpleNamespace(
                langfuse=types.SimpleNamespace(
                    enabled=False, base_url="http://x",
                    public_key="pk", secret_key="sk",
                    capture_content=False, flush_interval_seconds=60.0,
                )
            )
        )

        # 1. Enable
        init_sink(enabled_settings)
        sink1 = get_sink()
        assert sink1 is not None
        assert len(clients) == 1

        # 2. Disable
        init_sink(disabled_settings)
        assert get_sink() is None
        assert clients[0]._shutdown, "old client was not shut down"

        # 3. Re-enable
        init_sink(enabled_settings)
        sink3 = get_sink()
        assert sink3 is not None
        assert len(clients) == 2, "a new client should be constructed on re-enable"
        assert clients[1] is not clients[0], "must be a different client instance"

        # Cleanup
        disable_sink()


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
