"""Budget guard tests — check_budget, record_call, get_usage, cap enforcement."""

import pytest

import seeker_os.database as dbmod
from seeker_os.database import get_connection, run_migrations
from seeker_os.observability import budget_guard


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """Create a temp DB and patch budget_guard to use it."""
    db_path = tmp_path / "budget_test.db"
    run_migrations(db_path)

    monkeypatch.setattr(dbmod, "_db_path", lambda: db_path)

    def _temp_get_connection(_db_path=None):
        return get_connection(db_path)

    monkeypatch.setattr(budget_guard, "get_connection", _temp_get_connection)
    return db_path


class TestCheckBudget:
    def test_zero_caps_always_allowed(self, db):
        """Cap of 0 means unlimited — always True."""
        assert budget_guard.check_budget("tavily", 0, 0) is True

    def test_within_budget_allowed(self, db):
        """Under the cap — should be allowed."""
        for _ in range(3):
            budget_guard.record_call("tavily", "test query", "succeeded")
        assert budget_guard.check_budget("tavily", 10, 100) is True

    def test_daily_cap_exceeded(self, db):
        """At the daily cap — should be blocked."""
        for _ in range(5):
            budget_guard.record_call("tavily", "test query", "succeeded")
        assert budget_guard.check_budget("tavily", 5, 0) is False

    def test_daily_cap_not_exceeded_at_boundary(self, db):
        """One below the cap — should still be allowed."""
        for _ in range(4):
            budget_guard.record_call("tavily", "test query", "succeeded")
        assert budget_guard.check_budget("tavily", 5, 0) is True

    def test_monthly_cap_exceeded(self, db):
        """At the monthly cap — should be blocked even if daily is fine."""
        for _ in range(10):
            budget_guard.record_call("tavily", "test query", "succeeded")
        assert budget_guard.check_budget("tavily", 100, 10) is False

    def test_daily_zero_monthly_enforced(self, db):
        """Daily cap 0 (unlimited) but monthly cap enforced."""
        for _ in range(3):
            budget_guard.record_call("tavily", "test query", "succeeded")
        assert budget_guard.check_budget("tavily", 0, 3) is False
        assert budget_guard.check_budget("tavily", 0, 4) is True

    def test_different_adapter_types_independent(self, db):
        """Calls for one adapter don't count against another."""
        for _ in range(5):
            budget_guard.record_call("tavily", "test query", "succeeded")
        assert budget_guard.check_budget("tavily", 5, 0) is False
        assert budget_guard.check_budget("serper", 5, 0) is True


class TestRecordCall:
    def test_records_successful_call(self, db):
        budget_guard.record_call("tavily", "query1", "succeeded")
        conn = get_connection(db)
        try:
            row = conn.execute(
                "SELECT * FROM retrieval_calls WHERE query = 'query1'"
            ).fetchone()
            assert row is not None
            assert row["adapter_type"] == "tavily"
            assert row["status"] == "succeeded"
            assert row["error_message"] is None
            assert row["called_at"] is not None
        finally:
            conn.close()

    def test_records_failed_call_with_error(self, db):
        budget_guard.record_call("tavily", "query2", "failed", "API timeout")
        conn = get_connection(db)
        try:
            row = conn.execute(
                "SELECT * FROM retrieval_calls WHERE query = 'query2'"
            ).fetchone()
            assert row is not None
            assert row["status"] == "failed"
            assert row["error_message"] == "API timeout"
        finally:
            conn.close()

    def test_record_call_swallows_db_errors(self, db, monkeypatch):
        """record_call should not raise even if the DB is unavailable."""
        def bad_conn():
            raise RuntimeError("DB unavailable")
        monkeypatch.setattr(budget_guard, "get_connection", bad_conn)
        # Should not raise
        budget_guard.record_call("tavily", "query", "succeeded")


class TestGetUsage:
    def test_empty_usage(self, db):
        usage = budget_guard.get_usage("tavily")
        assert usage["adapter_type"] == "tavily"
        assert usage["daily_count"] == 0
        assert usage["monthly_count"] == 0
        assert usage["daily_errors"] == 0

    def test_usage_counts_correctly(self, db):
        budget_guard.record_call("tavily", "q1", "succeeded")
        budget_guard.record_call("tavily", "q2", "succeeded")
        budget_guard.record_call("tavily", "q3", "failed", "timeout")

        usage = budget_guard.get_usage("tavily")
        assert usage["daily_count"] == 3
        assert usage["monthly_count"] == 3
        assert usage["daily_errors"] == 1

    def test_usage_filtered_by_adapter(self, db):
        budget_guard.record_call("tavily", "q1", "succeeded")
        budget_guard.record_call("serper", "q2", "succeeded")

        tavily = budget_guard.get_usage("tavily")
        assert tavily["daily_count"] == 1

        serper = budget_guard.get_usage("serper")
        assert serper["daily_count"] == 1
