"""Tests for observability features — budget guard, SLO config, cost aggregation.

Covers #55: Budget-cap hard-stop path, cost aggregation accuracy for #54
endpoints, and SLO config validation. Test patterns follow
test_company_research.py (temp DB + monkeypatch get_connection).
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

import seeker_os.database as dbmod
from seeker_os.database import get_connection, run_migrations
from seeker_os.observability.budget_guard import (
    check_budget,
    record_call,
    get_usage,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """Create a temp SQLite DB and patch get_connection to use it."""
    path = tmp_path / "test_observability.db"
    run_migrations(path)

    _orig = dbmod.get_connection

    def _get_connection(_p=path):
        return _orig(_p)

    monkeypatch.setattr(dbmod, "get_connection", _get_connection)
    monkeypatch.setattr(
        "seeker_os.observability.budget_guard.get_connection", _get_connection
    )
    monkeypatch.setattr("seeker_os.api.analytics.get_connection", _get_connection)
    return path


# ---------------------------------------------------------------------------
# Budget guard tests
# ---------------------------------------------------------------------------


class TestBudgetGuard:
    def test_zero_caps_always_allowed(self, db):
        """A cap of 0 means unlimited — always returns True."""
        assert check_budget("tavily", daily_cap=0, monthly_cap=0) is True

    def test_daily_cap_not_exceeded(self, db):
        """Under the daily cap — should be allowed."""
        assert check_budget("tavily", daily_cap=5, monthly_cap=0) is True

    def test_daily_cap_exceeded(self, db):
        """At or over the daily cap — should be blocked."""
        for _ in range(3):
            record_call("tavily", "test query", "success")
        assert check_budget("tavily", daily_cap=3, monthly_cap=0) is False
        assert check_budget("tavily", daily_cap=2, monthly_cap=0) is False

    def test_monthly_cap_exceeded(self, db):
        """At or over the monthly cap — should be blocked."""
        for _ in range(5):
            record_call("tavily", "test query", "success")
        assert check_budget("tavily", daily_cap=0, monthly_cap=5) is False
        assert check_budget("tavily", daily_cap=0, monthly_cap=4) is False

    def test_daily_blocks_before_monthly(self, db):
        """Daily cap hits first even if monthly is higher."""
        for _ in range(2):
            record_call("tavily", "test query", "success")
        assert check_budget("tavily", daily_cap=2, monthly_cap=100) is False

    def test_different_adapter_independent(self, db):
        """Calls for one adapter don't count against another."""
        for _ in range(3):
            record_call("tavily", "query", "success")
        assert check_budget("serper", daily_cap=1, monthly_cap=0) is True

    def test_record_call_logs_failure_status(self, db):
        """record_call stores the status and error_message."""
        record_call("tavily", "query", "failed", error="timeout")
        conn = get_connection(db)
        try:
            row = conn.execute(
                "SELECT * FROM retrieval_calls WHERE adapter_type = 'tavily'"
            ).fetchone()
            assert row["status"] == "failed"
            assert row["error_message"] == "timeout"
        finally:
            conn.close()

    def test_get_usage_counts(self, db):
        """get_usage returns correct daily/monthly/error counts."""
        record_call("tavily", "q1", "success")
        record_call("tavily", "q2", "success")
        record_call("tavily", "q3", "failed", error="boom")

        usage = get_usage("tavily")
        assert usage["daily_count"] == 3
        assert usage["monthly_count"] == 3
        assert usage["daily_errors"] == 1


# ---------------------------------------------------------------------------
# SLO config validation tests
# ---------------------------------------------------------------------------


class TestSLOConfigValidation:
    def test_default_slo_config_loads(self):
        """Default SLOConfig loads with expected defaults."""
        from seeker_os.config import SLOConfig

        slo = SLOConfig()
        assert slo.analysis_latency_p95_ms == 30_000
        assert slo.pipeline_availability_target == 0.99
        assert slo.daily_spend_budget_usd == 5.0
        assert slo.slo_window_hours == 24

    def test_custom_slo_config_loads(self):
        """Custom values load correctly."""
        from seeker_os.config import SLOConfig

        slo = SLOConfig(
            analysis_latency_p95_ms=15_000,
            pipeline_availability_target=0.999,
            daily_spend_budget_usd=10.0,
            slo_window_hours=48,
        )
        assert slo.analysis_latency_p95_ms == 15_000
        assert slo.pipeline_availability_target == 0.999

    def test_observability_config_defaults(self):
        """ObservabilityConfig umbrella loads with all sub-configs."""
        from seeker_os.config import ObservabilityConfig

        obs = ObservabilityConfig()
        assert obs.langfuse.enabled is False
        assert obs.budget_caps.tavily_daily_cap == 0
        assert obs.slo.slo_window_hours == 24

    def test_langfuse_config_defaults(self):
        """LangfuseConfig defaults to disabled, metadata-only."""
        from seeker_os.config import LangfuseConfig

        lf = LangfuseConfig()
        assert lf.enabled is False
        assert lf.capture_content is False
        assert lf.base_url == "http://langfuse-web:3000"
        assert lf.public_key == ""
        assert lf.secret_key == ""

    def test_budget_caps_config_defaults(self):
        """BudgetCapsConfig defaults to unlimited (0)."""
        from seeker_os.config import BudgetCapsConfig

        caps = BudgetCapsConfig()
        assert caps.tavily_daily_cap == 0
        assert caps.tavily_monthly_cap == 0


# ---------------------------------------------------------------------------
# Cost aggregation accuracy tests (for #54 endpoints)
# ---------------------------------------------------------------------------


class TestCostAggregation:
    """Test the cost-summary and SLO endpoints against known ledger rows."""

    def _insert_llm_call(
        self, conn, *, call_id, task="jd_analysis", status="succeeded",
        provider="anthropic", model="claude-sonnet-5",
        input_tokens=100, output_tokens=20, latency_ms=1000,
        estimated_cost=0.005, operation_id="op-1",
        artifact_type=None, artifact_id=None,
    ):
        now = datetime.now(UTC).isoformat()
        conn.execute(
            """INSERT INTO llm_calls (
                call_id, operation_id, task, requested_provider, requested_model,
                actual_provider, actual_model, status, input_tokens, output_tokens,
                latency_ms, estimated_cost, started_at, completed_at,
                artifact_type, artifact_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                call_id, operation_id, task, provider, model,
                provider, model, status, input_tokens, output_tokens,
                latency_ms, estimated_cost, now, now,
                artifact_type, artifact_id,
            ),
        )
        conn.commit()

    def test_cost_summary_aggregation(self, db):
        """Cost-summary endpoint correctly aggregates total calls and cost."""
        from seeker_os.api.analytics import get_cost_summary

        conn = get_connection(db)
        self._insert_llm_call(conn, call_id="c1", task="jd_analysis",
                              estimated_cost=0.003)
        self._insert_llm_call(conn, call_id="c2", task="resume_generation",
                              estimated_cost=0.007)
        conn.close()

        result = get_cost_summary()
        assert result.total_calls == 2
        assert result.total_cost_usd == round(0.01, 6)

        task_keys = {b.key for b in result.by_task}
        assert "jd_analysis" in task_keys
        assert "resume_generation" in task_keys

    def test_cost_summary_by_task(self, db):
        """Cost-summary groups by task correctly."""
        from seeker_os.api.analytics import get_cost_summary

        conn = get_connection(db)
        self._insert_llm_call(conn, call_id="c1", task="jd_analysis",
                              estimated_cost=0.003)
        self._insert_llm_call(conn, call_id="c2", task="jd_analysis",
                              estimated_cost=0.002)
        self._insert_llm_call(conn, call_id="c3", task="resume_generation",
                              estimated_cost=0.01)
        conn.close()

        result = get_cost_summary()
        jd_bucket = next(b for b in result.by_task if b.key == "jd_analysis")
        assert jd_bucket.calls == 2
        assert jd_bucket.cost_usd == round(0.005, 6)

    def test_slo_status_latency(self, db):
        """SLO endpoint computes p95 latency from ledger rows."""
        from seeker_os.api.analytics import get_slo_status
        from seeker_os.config import get_settings

        # Patch get_settings to return known SLO config
        settings = type("S", (), {})()
        settings.observability = type("O", (), {})()
        settings.observability.slo = type("SLO", (), {})()
        settings.observability.slo.analysis_latency_p95_ms = 50_000
        settings.observability.slo.pipeline_availability_target = 0.99
        settings.observability.slo.daily_spend_budget_usd = 5.0
        settings.observability.slo.slo_window_hours = 24

        with patch("seeker_os.api.analytics.get_settings", return_value=settings):
            conn = get_connection(db)
            for i in range(20):
                self._insert_llm_call(
                    conn, call_id=f"c{i}", task="jd_analysis",
                    latency_ms=1000 + i * 100,
                    estimated_cost=0.001,
                )
            conn.close()

            result = get_slo_status()
            latency_metric = next(
                m for m in result.metrics if m.name == "analysis_latency_p95_ms"
            )
            assert latency_metric.actual > 0
            assert latency_metric.passing is True  # well under 50_000

    def test_slo_status_availability(self, db):
        """SLO endpoint computes pipeline availability from failed/succeeded calls."""
        from seeker_os.api.analytics import get_slo_status

        settings = type("S", (), {})()
        settings.observability = type("O", (), {})()
        settings.observability.slo = type("SLO", (), {})()
        settings.observability.slo.analysis_latency_p95_ms = 50_000
        settings.observability.slo.pipeline_availability_target = 0.99
        settings.observability.slo.daily_spend_budget_usd = 5.0
        settings.observability.slo.slo_window_hours = 24

        with patch("seeker_os.api.analytics.get_settings", return_value=settings):
            conn = get_connection(db)
            # 3 succeeded, 1 failed — all under the same operation_id
            self._insert_llm_call(conn, call_id="ok1", operation_id="op-a",
                                  status="succeeded")
            self._insert_llm_call(conn, call_id="ok2", operation_id="op-a",
                                  status="succeeded")
            self._insert_llm_call(conn, call_id="ok3", operation_id="op-b",
                                  status="succeeded")
            self._insert_llm_call(conn, call_id="fail1", operation_id="op-c",
                                  status="failed")
            conn.close()

            result = get_slo_status()
            avail_metric = next(
                m for m in result.metrics if m.name == "pipeline_availability"
            )
            # 3 ops total, 1 failed → 2/3 = 0.667
            assert avail_metric.actual == pytest.approx(2 / 3, rel=0.01)
            assert avail_metric.passing is False  # 0.667 < 0.99

    def test_slo_status_all_succeeded(self, db):
        """SLO availability is 1.0 when all operations succeed."""
        from seeker_os.api.analytics import get_slo_status

        settings = type("S", (), {})()
        settings.observability = type("O", (), {})()
        settings.observability.slo = type("SLO", (), {})()
        settings.observability.slo.analysis_latency_p95_ms = 50_000
        settings.observability.slo.pipeline_availability_target = 0.99
        settings.observability.slo.daily_spend_budget_usd = 5.0
        settings.observability.slo.slo_window_hours = 24

        with patch("seeker_os.api.analytics.get_settings", return_value=settings):
            conn = get_connection(db)
            self._insert_llm_call(conn, call_id="ok1", operation_id="op-a",
                                  status="succeeded")
            self._insert_llm_call(conn, call_id="ok2", operation_id="op-b",
                                  status="succeeded")
            conn.close()

            result = get_slo_status()
            avail_metric = next(
                m for m in result.metrics if m.name == "pipeline_availability"
            )
            assert avail_metric.actual == 1.0
            assert avail_metric.passing is True

    def test_budget_status_endpoint(self, db):
        """Budget-status endpoint returns correct counts and caps."""
        from seeker_os.api.analytics import get_budget_status
        from seeker_os.config import BudgetCapsConfig, ObservabilityConfig

        settings = type("S", (), {})()
        settings.observability = ObservabilityConfig(
            budget_caps=BudgetCapsConfig(tavily_daily_cap=10, tavily_monthly_cap=100)
        )

        record_call("tavily", "q1", "success")
        record_call("tavily", "q2", "success")
        record_call("tavily", "q3", "failed", error="timeout")

        with patch("seeker_os.api.analytics.get_settings", return_value=settings):
            result = get_budget_status()
            assert result.daily_count == 3
            assert result.daily_cap == 10
            assert result.daily_errors == 1
            assert result.daily_remaining == 7
