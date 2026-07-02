"""Phase 2 regression test — Tier 3 commits per job (§2.5).

Previously Tier 3 committed once after the whole loop, so a crash mid-tier
rolled back every completed JD fetch. This test seeds two Tier-2 jobs, makes the
second one blow up during fetch, and asserts the first job's fetch is durably
committed (visible on a fresh connection) — and that the misleading CWD-relative
`data/checkpoint.json` is no longer written.

See ai-audit/REMEDIATION_PLAN_2026-07-02.md, Phase 2B.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

import seeker_os.pipeline.runner as runner
from seeker_os.config import Settings
from seeker_os.database import get_connection, run_migrations
from seeker_os.models import JDFetchResult


_JD = "Seeded JD body. " * 40


def _seed_job(db, url_hash: str, title: str) -> int:
    cur = db.execute(
        "INSERT INTO jobs (title, company, apply_url, url_hash, status, tier_passed, "
        "jd_fetch_status, discovered_at) "
        "VALUES (?, ?, ?, ?, 'filtered', 2, 'pending', '2026-07-02T00:00:00+00:00')",
        (title, "Phase2Tier3Co", f"https://example.com/{url_hash}", url_hash, ),
    )
    db.commit()
    return cur.lastrowid


@pytest.fixture(autouse=True)
def _cleanup():
    run_migrations()
    yield
    db = get_connection()
    try:
        rows = db.execute("SELECT id FROM jobs WHERE company = 'Phase2Tier3Co'").fetchall()
        if rows:
            csv = ",".join(str(r["id"]) for r in rows)
            for t in ("application_events", "dedup_registry"):
                db.execute(f"DELETE FROM {t} WHERE job_id IN ({csv})")
            db.execute(f"DELETE FROM jobs WHERE id IN ({csv})")
        db.execute("DELETE FROM pipeline_runs WHERE run_id LIKE '0702-%' AND jds_fetched IS NULL")
        db.commit()
    finally:
        db.close()


def test_completed_fetch_survives_crash_mid_tier(monkeypatch):
    db = get_connection()
    try:
        job_a = _seed_job(db, "phase2-tier3-a", "Job A")
        job_b = _seed_job(db, "phase2-tier3-b", "Job B")
    finally:
        db.close()

    def fake_fetch_jd(*, job_id, **kwargs):
        if job_id == job_b:
            raise RuntimeError("simulated crash during Tier 3")
        return JDFetchResult(job_id=job_id, jd_text=_JD, status="fetched", source_used="test")

    monkeypatch.setattr(runner, "fetch_jd", fake_fetch_jd)
    monkeypatch.setattr(runner, "check_content_duplicate",
                        lambda job_id, jd_text, db: SimpleNamespace(is_duplicate=False))
    monkeypatch.setattr(runner, "register_content_hash", lambda job_id, jd_text, db: None)

    checkpoint = Path("data/checkpoint.json")
    checkpoint_existed = checkpoint.exists()

    settings = Settings()
    with pytest.raises(RuntimeError, match="simulated crash"):
        runner.run_pipeline(settings, tiers=[3])

    # Fresh connection: Job A's fetch was committed before Job B crashed.
    db = get_connection()
    try:
        a = db.execute("SELECT status, tier_passed, jd_fetch_status FROM jobs WHERE id=?", (job_a,)).fetchone()
        b = db.execute("SELECT status, jd_fetch_status FROM jobs WHERE id=?", (job_b,)).fetchone()
    finally:
        db.close()

    assert a["status"] == "jd_fetched"
    assert a["tier_passed"] == 3
    assert a["jd_fetch_status"] == "fetched"
    # Job B never completed — still pending, so a re-run picks it up.
    assert b["status"] == "filtered"
    assert b["jd_fetch_status"] == "pending"

    # The removed checkpoint file must not be (re)created by the run.
    if not checkpoint_existed:
        assert not checkpoint.exists()
