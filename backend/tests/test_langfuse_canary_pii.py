"""Canary PII test — the epic's key privacy assertion.

A unique canary string is embedded in the system and user prompts. We then
inspect the OTel span attributes exported by the in-memory span exporter and
assert:

1. When capture_content=False: the canary appears in NO span attribute.
2. When capture_content=True: the canary appears in the input attribute.

This is the privacy gate: if a bug accidentally passes prompt content to the
SDK even when capture is disabled, this test catches it.
"""

import logging
import types

import pytest

from seeker_os.observability import langfuse_sink as sink_mod
from seeker_os.observability.langfuse_sink import LangfuseSink

import langfuse  # noqa: F401 — declared dependency, not optional

from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)


@pytest.fixture(autouse=True)
def exporter(monkeypatch):
    """Route the SDK's OTel spans to a fresh in-memory exporter per test."""
    import langfuse as _lf

    real = _lf.Langfuse
    exp = InMemorySpanExporter()

    def patched(*args, **kwargs):
        kwargs.setdefault("span_exporter", exp)
        kwargs.setdefault("timeout", 1)
        return real(*args, **kwargs)

    monkeypatch.setattr(_lf, "Langfuse", patched)
    return exp


_CANARY = "CANARY_PII_TOKEN_x9k2m7q4w"

_SYS_PROMPT = f"You are a helpful assistant. Secret: {_CANARY}"
_USER_PROMPT = f"Analyze this JD. Reference: {_CANARY}"


def _make_sink(capture_content: bool) -> LangfuseSink:
    return LangfuseSink(
        public_key="pk-lf-test",
        secret_key="sk-lf-test",
        base_url="http://127.0.0.1:9",
        capture_content=capture_content,
        flush_interval_seconds=60.0,
    )


def _fake_response():
    return types.SimpleNamespace(
        text=f"Output with {_CANARY}",
        input_tokens=100,
        output_tokens=20,
        latency_ms=1234,
        stop_reason="end_turn",
    )


def _all_span_values(exporter):
    """Flatten all span attribute values into a single list of strings."""
    values = []
    for sp in exporter.get_finished_spans():
        for v in sp.attributes.values():
            values.append(str(v))
    return values


class TestCanaryPII:
    """The privacy assertion: prompt content must not leak when capture is off."""

    def test_canary_absent_when_capture_disabled(self, exporter):
        """When capture_content=False, the canary must not appear in any span attribute."""
        caplog = logging.getLogger(sink_mod.__name__)
        s = _make_sink(capture_content=False)
        s.start(
            call_id="pii-off", task="jd_analysis", operation_id="op-pii",
            system_prompt=_SYS_PROMPT, user_prompt=_USER_PROMPT,
            prompt_name="jd_analysis", prompt_version="v1",
        )
        s.finish(
            call_id="pii-off", task="jd_analysis", operation_id="op-pii",
            system_prompt=_SYS_PROMPT, user_prompt=_USER_PROMPT,
            response=_fake_response(), provider="anthropic",
            model="claude-sonnet-5",
        )
        s.flush()
        s.shutdown()

        values = _all_span_values(exporter)
        for v in values:
            assert _CANARY not in v, (
                f"PII leak: canary string found in span attribute when "
                f"capture_content=False. Value: {v[:200]}"
            )

    def test_canary_present_when_capture_enabled(self, exporter):
        """When capture_content=True, the canary must appear in the input attribute."""
        s = _make_sink(capture_content=True)
        s.start(
            call_id="pii-on", task="jd_analysis", operation_id="op-pii",
            system_prompt=_SYS_PROMPT, user_prompt=_USER_PROMPT,
            prompt_name="jd_analysis", prompt_version="v1",
        )
        s.finish(
            call_id="pii-on", task="jd_analysis", operation_id="op-pii",
            system_prompt=_SYS_PROMPT, user_prompt=_USER_PROMPT,
            response=_fake_response(), provider="anthropic",
            model="claude-sonnet-5",
        )
        s.flush()
        s.shutdown()

        spans = exporter.get_finished_spans()
        assert spans, "no spans exported"

        # The canary must appear in at least one span attribute (the input)
        all_values = _all_span_values(exporter)
        assert any(_CANARY in v for v in all_values), (
            "canary string not found in any span attribute when "
            "capture_content=True — content capture is broken"
        )

        # Specifically, it should be in the input attribute
        input_attrs = [
            str(sp.attributes.get("langfuse.observation.input", ""))
            for sp in spans
            if "langfuse.observation.input" in sp.attributes
        ]
        assert input_attrs, "langfuse.observation.input attribute missing"
        assert any(_CANARY in v for v in input_attrs), (
            f"canary not in input attribute: {input_attrs}"
        )

    def test_output_absent_when_capture_disabled(self, exporter):
        """When capture_content=False, response text must not appear in span attributes."""
        s = _make_sink(capture_content=False)
        s.start(
            call_id="out-off", task="jd_analysis", operation_id="op-out",
            system_prompt="sys", user_prompt="usr",
        )
        s.finish(
            call_id="out-off", task="jd_analysis", operation_id="op-out",
            system_prompt="sys", user_prompt="usr",
            response=_fake_response(), provider="anthropic",
            model="claude-sonnet-5",
        )
        s.flush()
        s.shutdown()

        values = _all_span_values(exporter)
        # The response text contains the canary — it must not leak
        for v in values:
            assert _CANARY not in v, (
                f"Output leak: response text found in span attribute when "
                f"capture_content=False. Value: {v[:200]}"
            )

    def test_output_present_when_capture_enabled(self, exporter):
        """When capture_content=True, response text must appear in the output attribute."""
        s = _make_sink(capture_content=True)
        s.start(
            call_id="out-on", task="jd_analysis", operation_id="op-out",
            system_prompt="sys", user_prompt="usr",
        )
        s.finish(
            call_id="out-on", task="jd_analysis", operation_id="op-out",
            system_prompt="sys", user_prompt="usr",
            response=_fake_response(), provider="anthropic",
            model="claude-sonnet-5",
        )
        s.flush()
        s.shutdown()

        spans = exporter.get_finished_spans()
        assert spans, "no spans exported"

        output_attrs = [
            str(sp.attributes.get("langfuse.observation.output", ""))
            for sp in spans
            if "langfuse.observation.output" in sp.attributes
        ]
        assert output_attrs, "langfuse.observation.output attribute missing"
        assert any(_CANARY in v for v in output_attrs), (
            f"canary not in output attribute: {output_attrs}"
        )
