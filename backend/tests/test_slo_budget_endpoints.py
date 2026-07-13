"""SLO and budget status endpoint tests."""

import types
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

import seeker_os.database as dbmod
from seeker_os.api.app import app
from seeker_os.config import (
    BudgetCapsConfig,
    ObservabilityConfig,
    SLOConfig,
)
from seeker_os.database import get_connection, run_migrations
from seeker_os.observability import budget_guard


def _make_settings(
    slo: SLOConfig | None = None,
    caps: BudgetCapsConfig | None = None,
):
    return types.SimpleNamespace(
        observability=ObservabilityConfig(
            slo=slo or SLOConfig(),
            budget_caps=caps or BudgetCapsConfig(),
        ),
    )


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient wired to a temp DB with patched settings."""
    db_path = tmp_path / "slo_test.db"
    run_migrations(db_path)

    monkeypatch.setattr(dbmod, "_db_path", lambda: db_path)

    def _temp_get_connection(_db_path=None):
        return get_connection(db_path)

    monkeypatch.setattr(dbmod, "get_connection", _temp_get_connection)
    monkeypatch.setattr(budget_guard, "get_connection", _temp_get_connection)

    # Patch get_connection in analytics module too (it imports directly)
    import seeker_os.api.analytics as analytics_mod
    monkeypatch.setattr(analytics_mod, "get_connection", _temp_get_connection)

    # Patch get_settings to return our test config
    test_settings = _make_settings()
    monkeypatch.setattr(analytics_mod, "get_settings", lambda: test_settings)

    return TestClient(app)


def _insert_llm_call(
    db_path,
    task="jd_analysis",
    status="succeeded",
    latency_ms=1000,
    operation_id="op-1",
    cost=0.01,
):
    """Insert a row into llm_calls for SLO testing."""
    now = datetime.now(UTC).isoformat()
    conn = get_connection(db_path)
    try:
        conn.execute(
            """INSERT INTO llm_calls (
                call_id, task, status, latency_ms, operation_id,
                input_tokens, output_tokens, estimated_cost, started_at, completed_at
            ) VALUES (?, ?, ?, ?, ?, 0, 0, ?, ?, ?)""",
            (f"call-{task}-{latency_ms}-{operation_id}-{cost}", task, status, latency_ms, operation_id, cost, now, now),
        )
        conn.commit()
    finally:
        conn.close()


class TestSLOStatus:
    def test_slo_status_empty_db(self, client):
        """SLO endpoint returns defaults when no data."""
        r = client.get("/api/analytics/slo-status")
        assert r.status_code == 200
        data = r.json()
        assert data["window_hours"] == 24
        assert data["daily_spend_usd"] == 0.0
        assert data["daily_spend_budget_usd"] == 5.0
        assert len(data["metrics"]) == 2

        # With no data, latency is 0 (passes), availability is 1.0 (passes)
        for m in data["metrics"]:
            assert m["passing"] is True

    def test_slo_latency_metric(self, client, tmp_path):
        """Latency p95 is computed from jd_analysis calls."""
        db_path = tmp_path / "slo_test.db"
        # Insert calls with varying latency
        for lat in [100, 200, 300, 400, 500]:
            _insert_llm_call(db_path, latency_ms=lat, operation_id="op-lat")

        r = client.get("/api/analytics/slo-status")
        assert r.status_code == 200
        data = r.json()

        latency_metric = next(
            m for m in data["metrics"] if m["name"] == "analysis_latency_p95_ms"
        )
        # p95 of [100,200,300,400,500] with 5 items: idx = int(5*0.95)=4 → 500
        assert latency_metric["actual"] == 500.0
        assert latency_metric["target"] == 30000.0
        assert latency_metric["passing"] is True

    def test_slo_availability_metric(self, client, tmp_path):
        """Availability = fraction of operations with no failures."""
        db_path = tmp_path / "slo_test.db"
        # 3 operations: 2 clean, 1 with a failure
        _insert_llm_call(db_path, operation_id="op-good-1")
        _insert_llm_call(db_path, operation_id="op-good-2")
        _insert_llm_call(db_path, operation_id="op-bad", status="failed")

        r = client.get("/api/analytics/slo-status")
        assert r.status_code == 200
        data = r.json()

        avail = next(
            m for m in data["metrics"] if m["name"] == "pipeline_availability"
        )
        # 2 out of 3 operations have no failures → 0.667
        assert avail["actual"] == pytest.approx(2 / 3, abs=0.01)
        assert avail["passing"] is False  # 0.667 < 0.99 target

    def test_slo_daily_spend(self, client, tmp_path):
        """Daily spend is summed from estimated_cost."""
        db_path = tmp_path / "slo_test.db"
        _insert_llm_call(db_path, cost=1.50, operation_id="op-spend-1")
        _insert_llm_call(db_path, cost=2.00, operation_id="op-spend-2")

        r = client.get("/api/analytics/slo-status")
        assert r.status_code == 200
        data = r.json()
        assert data["daily_spend_usd"] == pytest.approx(3.50, abs=0.01)


class TestBudgetStatus:
    def test_budget_status_empty(self, client):
        """Budget endpoint returns zeros when no calls recorded."""
        r = client.get("/api/analytics/budget-status")
        assert r.status_code == 200
        data = r.json()
        assert data["adapter_type"] == "tavily"
        assert data["daily_count"] == 0
        assert data["monthly_count"] == 0
        assert data["daily_errors"] == 0
        assert data["daily_cap"] == 0
        assert data["monthly_cap"] == 0

    def test_budget_status_with_calls(self, client, tmp_path):
        """Budget endpoint reflects recorded calls."""
        budget_guard.record_call("tavily", "q1", "succeeded")
        budget_guard.record_call("tavily", "q2", "failed", "timeout")

        r = client.get("/api/analytics/budget-status")
        assert r.status_code == 200
        data = r.json()
        assert data["daily_count"] == 2
        assert data["monthly_count"] == 2
        assert data["daily_errors"] == 1

    def test_budget_status_with_caps(self, client, tmp_path, monkeypatch):
        """Budget endpoint shows remaining when caps are set."""
        budget_guard.record_call("tavily", "q1", "succeeded")

        import seeker_os.api.analytics as analytics_mod
        test_settings = _make_settings(caps=BudgetCapsConfig(
            tavily_daily_cap=10, tavily_monthly_cap=100,
        ))
        monkeypatch.setattr(analytics_mod, "get_settings", lambda: test_settings)

        r = client.get("/api/analytics/budget-status")
        assert r.status_code == 200
        data = r.json()
        assert data["daily_cap"] == 10
        assert data["monthly_cap"] == 100
        assert data["daily_remaining"] == 9
        assert data["monthly_remaining"] == 99

    def test_budget_status_unlimited_caps(self, client):
        """When caps are 0 (unlimited), remaining is null."""
        r = client.get("/api/analytics/budget-status")
        assert r.status_code == 200
        data = r.json()
        assert data["daily_remaining"] is None
        assert data["monthly_remaining"] is None
