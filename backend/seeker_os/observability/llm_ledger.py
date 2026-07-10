"""Metadata-only SQLite ledger for LLM calls and quality evaluations."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from seeker_os.database import get_connection

logger = logging.getLogger(__name__)
SCHEMA_VERSION = "1"
_EPHEMERAL_KEY = secrets.token_bytes(32)
_warned_ephemeral = False


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _key() -> bytes:
    global _warned_ephemeral
    configured = os.environ.get("SEEKER_TELEMETRY_HMAC_KEY")
    if configured:
        return configured.encode("utf-8")
    if not _warned_ephemeral:
        logger.warning(
            "telemetry_hmac_key_ephemeral: SEEKER_TELEMETRY_HMAC_KEY is unset; "
            "prompt fingerprints will not be comparable across restarts"
        )
        _warned_ephemeral = True
    return _EPHEMERAL_KEY


def fingerprint(value: str) -> str:
    return hmac.new(_key(), value.encode("utf-8"), hashlib.sha256).hexdigest()


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def classify_error(exc: BaseException) -> str:
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    if "truncation" in name or "max_tokens" in message:
        return "truncated"
    if "timeout" in name or "timeout" in message:
        return "timeout"
    if "authentication" in name or "unauthorized" in message or "api key" in message:
        return "authentication"
    if "rate" in name or "429" in message:
        return "rate_limited"
    if "connection" in name or "transport" in name:
        return "transport"
    if isinstance(exc, (ValueError, RuntimeError)) and "provider" in message:
        return "routing_configuration"
    return "unknown"


def _pricing(settings: Any, provider: str | None, model: str | None) -> tuple[float | None, float | None]:
    if not provider or not model or not settings.providers:
        return None, None
    for item in settings.providers.providers:
        if item.id != provider:
            continue
        for configured_model in item.models:
            if configured_model.id == model:
                return configured_model.input_price_per_mtok, configured_model.output_price_per_mtok
    return None, None


def start_call(
    *,
    settings: Any,
    task: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_tokens: int | None,
    operation_id: str | None,
    parent_call_id: str | None,
    prompt_name: str | None,
    prompt_version: str | None,
    prompt_template: str | None,
    requested_provider: str | None = None,
    requested_model: str | None = None,
    route_reason: str | None = None,
) -> tuple[str, float]:
    call_id = str(uuid.uuid4())
    started = _now()
    db = get_connection()
    try:
        db.execute(
            """INSERT INTO llm_calls (
                call_id, operation_id, parent_call_id, task,
                requested_provider, requested_model, route_reason,
                temperature, max_tokens, status, prompt_name, prompt_version,
                prompt_template_digest, system_prompt_hmac, user_prompt_hmac,
                system_prompt_bytes, user_prompt_bytes, started_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'running', ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                call_id, operation_id, parent_call_id, task,
                requested_provider, requested_model, route_reason,
                temperature, max_tokens, prompt_name or task, prompt_version or "1",
                digest(prompt_template or system_prompt), fingerprint(system_prompt), fingerprint(user_prompt),
                len(system_prompt.encode("utf-8")), len(user_prompt.encode("utf-8")), started,
            ),
        )
        db.commit()
    finally:
        db.close()
    return call_id, time.monotonic()


def finish_call(
    call_id: str,
    *,
    settings: Any,
    started_monotonic: float,
    response: Any | None = None,
    error: BaseException | None = None,
    requested_provider: str | None = None,
    requested_model: str | None = None,
    route_reason: str | None = None,
) -> None:
    actual_provider = response.provider if response else None
    actual_model = response.model if response else None
    price_in, price_out = _pricing(settings, actual_provider or requested_provider, actual_model or requested_model)
    input_tokens = response.input_tokens if response else 0
    output_tokens = response.output_tokens if response else getattr(error, "output_tokens", 0)
    cost = (input_tokens * (price_in or 0) + output_tokens * (price_out or 0)) / 1_000_000
    status = "failed" if error else ("empty" if response is None or not response.text else "succeeded")
    error_type = classify_error(error) if error else ("empty_response" if status == "empty" else None)
    latency = response.latency_ms if response else int((time.monotonic() - started_monotonic) * 1000)
    db = get_connection()
    try:
        db.execute(
            """UPDATE llm_calls SET
                requested_provider = COALESCE(?, requested_provider),
                requested_model = COALESCE(?, requested_model), route_reason = COALESCE(?, route_reason),
                actual_provider = ?, actual_model = ?, status = ?, error_type = ?, stop_reason = ?,
                input_tokens = ?, output_tokens = ?, latency_ms = ?, input_price_per_mtok = ?,
                output_price_per_mtok = ?, estimated_cost = ?, completed_at = ?
            WHERE call_id = ?""",
            (
                requested_provider, requested_model, route_reason, actual_provider, actual_model,
                status, error_type, response.stop_reason if response else getattr(error, "stop_reason", None),
                input_tokens, output_tokens, latency, price_in, price_out, cost, _now(), call_id,
            ),
        )
        db.commit()
    finally:
        db.close()


def attach_artifact(operation_id: str, artifact_type: str, artifact_id: int) -> None:
    db = get_connection()
    try:
        db.execute(
            "UPDATE llm_calls SET artifact_type = ?, artifact_id = ? WHERE operation_id = ?",
            (artifact_type, artifact_id, operation_id),
        )
        db.execute(
            "UPDATE llm_evaluations SET artifact_type = ?, artifact_id = ? WHERE operation_id = ?",
            (artifact_type, artifact_id, operation_id),
        )
        db.commit()
    finally:
        db.close()


def record_evaluation(
    *,
    evaluator_name: str,
    evaluator_type: str,
    metric_name: str,
    passed: bool | None,
    operation_id: str | None = None,
    call_id: str | None = None,
    judge_call_id: str | None = None,
    evaluator_version: str = "1",
    label: str | None = None,
    score: float | None = None,
    explanation_redacted: str | None = None,
    details: dict[str, Any] | None = None,
    rubric_digest: str | None = None,
) -> str:
    evaluation_id = str(uuid.uuid4())
    db = get_connection()
    try:
        db.execute(
            """INSERT INTO llm_evaluations (
                evaluation_id, operation_id, call_id, judge_call_id, evaluator_name,
                evaluator_type, evaluator_version, metric_name, score, label, passed,
                explanation_redacted, details_json, rubric_digest, evaluated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                evaluation_id, operation_id, call_id, judge_call_id, evaluator_name,
                evaluator_type, evaluator_version, metric_name, score, label, passed,
                explanation_redacted, json.dumps(details or {}, sort_keys=True), rubric_digest, _now(),
            ),
        )
        db.commit()
    finally:
        db.close()
    return evaluation_id
