"""Tests for the privacy-safe local LLM observability ledger."""

from __future__ import annotations

from types import SimpleNamespace

from seeker_os.config import ProviderConfig, ProviderModel, ProvidersConfig
from seeker_os.database import get_connection, run_migrations
from seeker_os.llm.models import LLMResponse
from seeker_os.observability import llm_ledger


def _settings() -> SimpleNamespace:
    return SimpleNamespace(providers=ProvidersConfig(
        providers=[ProviderConfig(
            id="test-provider", type="anthropic", models=[ProviderModel(
                id="test-model", input_price_per_mtok=2.0, output_price_per_mtok=8.0,
            )],
        )],
    ))


def _use_temp_ledger(monkeypatch, tmp_path):
    path = tmp_path / "observability.db"
    run_migrations(path)
    monkeypatch.setattr(llm_ledger, "get_connection", lambda: get_connection(path))
    return path


def test_call_ledger_is_metadata_only_and_uses_call_time_pricing(monkeypatch, tmp_path):
    path = _use_temp_ledger(monkeypatch, tmp_path)
    settings = _settings()
    call_id, started = llm_ledger.start_call(
        settings=settings, task="resume_generation_standard",
        system_prompt="SYSTEM SECRET CANARY", user_prompt="RESUME PII CANARY",
        temperature=0.2, max_tokens=1000, operation_id="operation-1",
        parent_call_id=None, prompt_name="resume_generation", prompt_version="1",
        prompt_template="template {resume}",
    )
    llm_ledger.finish_call(
        call_id, settings=settings, started_monotonic=started,
        requested_provider="test-provider", requested_model="test-model",
        response=LLMResponse(
            text="COMPLETION CANARY", provider="test-provider", model="test-model",
            input_tokens=100, output_tokens=50, latency_ms=20, stop_reason="stop",
        ),
    )

    db = get_connection(path)
    row = db.execute("SELECT * FROM llm_calls WHERE call_id = ?", (call_id,)).fetchone()
    serialized = " ".join(str(value) for value in row)
    assert "SYSTEM SECRET CANARY" not in serialized
    assert "RESUME PII CANARY" not in serialized
    assert "COMPLETION CANARY" not in serialized
    assert row["status"] == "succeeded"
    assert row["estimated_cost"] == (100 * 2.0 + 50 * 8.0) / 1_000_000

    settings.providers.providers[0].models[0].input_price_per_mtok = 999
    unchanged = db.execute("SELECT estimated_cost FROM llm_calls WHERE call_id = ?", (call_id,)).fetchone()[0]
    assert unchanged == row["estimated_cost"]
    db.close()


def test_failure_and_evaluation_are_queryable(monkeypatch, tmp_path):
    path = _use_temp_ledger(monkeypatch, tmp_path)
    settings = _settings()
    call_id, started = llm_ledger.start_call(
        settings=settings, task="accuracy_validation", system_prompt="sys", user_prompt="user",
        temperature=0, max_tokens=100, operation_id="operation-2", parent_call_id=None,
        prompt_name="judge", prompt_version="1", prompt_template="judge template",
    )
    llm_ledger.finish_call(
        call_id, settings=settings, started_monotonic=started,
        error=TimeoutError("provider timeout"), requested_provider="test-provider",
        requested_model="test-model",
    )
    evaluation_id = llm_ledger.record_evaluation(
        operation_id="operation-2", call_id=call_id, evaluator_name="claim_traceability",
        evaluator_type="model", metric_name="claim_traceability", passed=False,
        label="unsupported", details={"claim_fingerprint": "opaque"},
    )

    db = get_connection(path)
    call = db.execute("SELECT status, error_type FROM llm_calls WHERE call_id = ?", (call_id,)).fetchone()
    evaluation = db.execute(
        "SELECT label, passed FROM llm_evaluations WHERE evaluation_id = ?", (evaluation_id,)
    ).fetchone()
    assert tuple(call) == ("failed", "timeout")
    assert tuple(evaluation) == ("unsupported", 0)
    db.close()
