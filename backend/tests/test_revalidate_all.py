"""Tests for revalidate_all — the full-gate revalidation orchestrator.

All tests operate on a tmp copy of the DB seeded with resume 66's data.
The production seeker.db is never touched.

Happy path: resume 66 (stored with stale FAIL from the retired integer
page gate) should flip to PASS after revalidation with the current
height-based page gate and ATS parse gate.

Failure case: a resume with a genuine high-severity violation should
remain FAIL after revalidation.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from seeker_os.config import get_settings
from seeker_os.database import get_connection as real_get_connection
from seeker_os.database import run_migrations
from seeker_os.validation import revalidate_all


def _seed_tmp_db(tmp_path: Path) -> Path:
    """Create a tmp DB, run migrations, and seed it with resume 66's data
    copied from the real seeker.db. Returns the tmp DB path."""
    db_path = tmp_path / "test_revalidate.db"
    run_migrations(db_path)

    # Read resume 66 from the real DB
    real_db = real_get_connection()
    try:
        resume = real_db.execute(
            "SELECT * FROM resumes WHERE id = 66"
        ).fetchone()
        if resume is None:
            pytest.skip("Resume 66 not found in real DB")

        # Read the job row (needed for FK constraint)
        job = real_db.execute(
            "SELECT * FROM jobs WHERE id = ?", (resume["job_id"],)
        ).fetchone()

        # Read audit evals for resume 66
        evals = real_db.execute(
            "SELECT * FROM llm_evaluations WHERE artifact_type = 'resume' AND artifact_id = 66"
        ).fetchall()
    finally:
        real_db.close()

    # Insert into tmp DB
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Insert a minimal job row to satisfy the FK constraint on resumes.job_id
    if job:
        conn.execute(
            "INSERT INTO jobs (id, title, company, status) VALUES (?, ?, ?, ?)",
            (job["id"], job["title"], job["company"], job["status"]),
        )

    # Insert resume row with stale FAIL (simulating original state)
    conn.execute(
        """INSERT INTO resumes (
            id, job_id, resume_text, master_resume_path, provider, model,
            validation_passed, validation_violations, validation_checked_at,
            generated_at, markdown_path
        ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)""",
        (
            resume["id"],
            resume["job_id"],
            resume["resume_text"],
            resume["master_resume_path"],
            resume["provider"],
            resume["model"],
            json.dumps([{
                "rule_id": "page_count_exceeded",
                "description": "Resume exceeds 3-page limit",
                "violation": "Resume is 4 pages (limit: 3)",
                "severity": "high",
                "matched_text": "4 pages",
            }]),
            resume["validation_checked_at"],
            resume["generated_at"],
            resume["markdown_path"],
        ),
    )

    # Copy audit evals (bullet_selection, competency_selection, etc.)
    for e in evals:
        conn.execute(
            """INSERT INTO llm_evaluations (
                evaluation_id, operation_id, call_id, judge_call_id,
                artifact_type, artifact_id, evaluator_name, evaluator_type,
                evaluator_version, metric_name, score, label, passed,
                explanation_redacted, details_json, rubric_digest, evaluated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                e["evaluation_id"], e["operation_id"], e["call_id"], e["judge_call_id"],
                e["artifact_type"], e["artifact_id"], e["evaluator_name"], e["evaluator_type"],
                e["evaluator_version"], e["metric_name"], e["score"], e["label"], e["passed"],
                e["explanation_redacted"], e["details_json"], e["rubric_digest"], e["evaluated_at"],
            ),
        )

    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Create a tmp DB seeded with resume 66's data and patch all DB access
    to use it instead of the real seeker.db."""
    import seeker_os.database as dbmod

    db_path = _seed_tmp_db(tmp_path)

    _orig_get_connection = dbmod.get_connection

    def _temp_get_connection(_db_path=db_path):
        return _orig_get_connection(_db_path)

    monkeypatch.setattr(dbmod, "_db_path", lambda: db_path)
    monkeypatch.setattr(dbmod, "get_connection", _temp_get_connection)

    return db_path


@pytest.fixture
def settings():
    return get_settings()


class TestRevalidateAll:
    """Tests for the revalidate_all orchestrator."""

    def test_resume_66_flips_to_pass(self, isolated_db, settings):
        """Resume 66 is seeded with stale FAIL (retired integer page gate).
        Revalidation with current gates should flip it to PASS."""
        db = real_get_connection(isolated_db)
        try:
            # Verify precondition: seeded as FAIL
            before = db.execute(
                "SELECT validation_passed FROM resumes WHERE id = 66"
            ).fetchone()
            assert before["validation_passed"] == 0, "Precondition: seeded resume should be FAIL"

            # Run revalidation
            result = revalidate_all(66, settings)

            # Should pass
            assert result.passed, f"Expected PASS, got violations: {[v.rule_id for v in result.violations]}"

            # Verify DB was updated
            after = db.execute(
                "SELECT validation_passed FROM resumes WHERE id = 66"
            ).fetchone()
            assert after["validation_passed"] == 1, "DB should show PASS after revalidation"

            # Verify revalidation eval was recorded with previous verdict
            reval_eval = db.execute(
                "SELECT details_json FROM llm_evaluations WHERE artifact_type = 'resume' AND artifact_id = 66 AND metric_name = 'revalidation' ORDER BY evaluated_at DESC LIMIT 1"
            ).fetchone()
            assert reval_eval is not None, "revalidation eval should be recorded"
            d = json.loads(reval_eval["details_json"])
            assert d["previous_passed"] == 0, "Previous verdict should be FAIL (stale page gate)"
            assert "page_count_exceeded" in [v["rule_id"] for v in d["previous_violations"]]
            assert "accuracy" in d["gates_run"]
            assert "page_count" in d["gates_run"]
            assert "ats_parse" in d["gates_run"]
            assert d["traceability_rerun"] is False
        finally:
            db.close()

    def test_revalidation_records_previous_violations(self, isolated_db, settings):
        """The revalidation eval should include the previous violations for audit trail."""
        db = real_get_connection(isolated_db)
        try:
            # Run revalidation first
            revalidate_all(66, settings)

            reval_eval = db.execute(
                "SELECT details_json FROM llm_evaluations WHERE artifact_type = 'resume' AND artifact_id = 66 AND metric_name = 'revalidation' ORDER BY evaluated_at DESC LIMIT 1"
            ).fetchone()
            assert reval_eval is not None
            d = json.loads(reval_eval["details_json"])
            assert "previous_violations" in d
            assert isinstance(d["previous_violations"], list)
            assert len(d["previous_violations"]) > 0, "Previous FAIL should have violations"
            assert d["previous_passed"] == 0
        finally:
            db.close()

    def test_nonexistent_resume_raises(self, isolated_db, settings):
        """Revalidating a non-existent resume should raise ValueError."""
        with pytest.raises(ValueError, match="not found"):
            revalidate_all(99999, settings)

    def test_revalidation_idempotent(self, isolated_db, settings):
        """Running revalidation twice should produce the same result."""
        result1 = revalidate_all(66, settings)
        result2 = revalidate_all(66, settings)
        assert result1.passed == result2.passed
        assert len(result1.violations) == len(result2.violations)

    def test_revalidation_still_fails_on_genuine_violation(self, isolated_db, settings):
        """A resume with a genuine high-severity violation should remain FAIL.

        We insert a copy of resume 66's text with 'Rust' added (a forbidden
        technology, high severity) into the tmp DB, revalidate, and confirm
        it fails.
        """
        db = real_get_connection(isolated_db)
        try:
            r = db.execute("SELECT resume_text, master_resume_path, job_id FROM resumes WHERE id = 66").fetchone()
            corrupted_text = r["resume_text"] + "\n\nBuilt a high-throughput data pipeline in Rust.\n"

            now = datetime.now(UTC).isoformat()
            db.execute(
                """INSERT INTO resumes (job_id, resume_text, master_resume_path, provider, model,
                   validation_passed, validation_violations, validation_checked_at, generated_at, markdown_path)
                   VALUES (?, ?, ?, 'test', 'test-model', 1, '[]', ?, ?, '/tmp/test_revalidation.md')""",
                (r["job_id"], corrupted_text, r["master_resume_path"], now, now),
            )
            db.commit()
            test_resume_id = db.execute("SELECT last_insert_rowid() as id").fetchone()["id"]
            db.close()

            result = revalidate_all(test_resume_id, settings)

            assert not result.passed, \
                f"Expected FAIL, but passed. Violations: {[v.rule_id for v in result.violations]}"
            assert any(v.rule_id == "forbidden_technologies" for v in result.violations), \
                f"Expected forbidden_technologies, got: {[v.rule_id for v in result.violations]}"

            # Verify DB shows FAIL
            db = real_get_connection(isolated_db)
            after = db.execute(
                "SELECT validation_passed FROM resumes WHERE id = ?", (test_resume_id,)
            ).fetchone()
            assert after["validation_passed"] == 0

            # Verify revalidation eval recorded the previous (fake-pass) verdict
            reval_eval = db.execute(
                "SELECT details_json FROM llm_evaluations WHERE artifact_type = 'resume' AND artifact_id = ? AND metric_name = 'revalidation' ORDER BY evaluated_at DESC LIMIT 1",
                (test_resume_id,),
            ).fetchone()
            assert reval_eval is not None
            d = json.loads(reval_eval["details_json"])
            assert d["previous_passed"] == 1, "Previous verdict should be the fake-pass we inserted"
        finally:
            db.close()
