"""Analytics API routes."""

from __future__ import annotations

from fastapi import APIRouter
from seeker_os.api.schemas import FunnelStats, ResponseRateStats
from seeker_os.database import get_connection

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/funnel", response_model=FunnelStats)
def get_funnel_stats():
    """Pipeline funnel stats — cumulative counts at each tier and by status.

    The funnel is: All Jobs → Tier 1 (Discovery) → Tier 2 (Filtering) → Scored.
    JD fetch is enrichment, not a funnel gate — shown as a separate metric.
    """
    db = get_connection()

    # Total
    total = db.execute("SELECT COUNT(*) as c FROM jobs").fetchone()["c"]

    # By status
    status_rows = db.execute(
        "SELECT status, COUNT(*) as c FROM jobs GROUP BY status"
    ).fetchall()
    by_status = {r["status"]: r["c"] for r in status_rows}

    # By tier (raw counts — jobs whose highest passed tier is N)
    tier_rows = db.execute(
        "SELECT tier_passed, COUNT(*) as c FROM jobs GROUP BY tier_passed"
    ).fetchall()
    by_tier = {r["tier_passed"]: r["c"] for r in tier_rows}

    # Cumulative funnel: jobs that reached AT LEAST each stage
    # Every job in the DB has tier_passed >= 1 (that's how it got inserted),
    # so "All Jobs" and "Discovery" are the same — we collapse them.
    # tier_passed >= 2 means passed hard filters
    # tier_passed >= 4 means scored (tier 3 = JD fetch is enrichment, not a gate)
    passed_t2 = db.execute("SELECT COUNT(*) as c FROM jobs WHERE tier_passed >= 2").fetchone()["c"]
    scored = db.execute("SELECT COUNT(*) as c FROM jobs WHERE tier_passed >= 4").fetchone()["c"]

    funnel = [
        {"tier": 1, "label": "Discovered", "count": total},
        {"tier": 2, "label": "Passed Filters", "count": passed_t2},
        {"tier": 4, "label": "Passed Scoring", "count": scored},
    ]

    # JD fetch stats — for jobs that passed tier 2 (the ones that need JD fetch)
    jd_fetch_rows = db.execute(
        """
        SELECT jd_fetch_status, COUNT(*) as c
        FROM jobs WHERE tier_passed >= 2
        GROUP BY jd_fetch_status
        """
    ).fetchall()
    jd_stats = {r["jd_fetch_status"]: r["c"] for r in jd_fetch_rows}
    jd_fetch_total = sum(jd_stats.values())
    jd_fetch_success = jd_stats.get("fetched", 0)
    jd_fetch_failed = jd_stats.get("failed", 0)
    jd_fetch_pending = jd_stats.get("pending", 0)

    # By ATS source
    ats_rows = db.execute(
        "SELECT ats_source, COUNT(*) as c FROM jobs WHERE ats_source IS NOT NULL GROUP BY ats_source ORDER BY c DESC"
    ).fetchall()
    by_ats = {r["ats_source"] or "unknown": r["c"] for r in ats_rows}

    # Rejection reasons
    reason_rows = db.execute(
        "SELECT reject_reason, COUNT(*) as c FROM jobs WHERE reject_reason IS NOT NULL AND reject_reason != '' GROUP BY reject_reason ORDER BY c DESC LIMIT 20"
    ).fetchall()
    rejection_reasons = {r["reject_reason"]: r["c"] for r in reason_rows}

    # Score distribution
    score_rows = db.execute(
        """
        SELECT
          CASE
            WHEN score IS NULL THEN 'unscored'
            WHEN score >= 8 THEN '8-10'
            WHEN score >= 6 THEN '6-8'
            WHEN score >= 4 THEN '4-6'
            WHEN score >= 2 THEN '2-4'
            ELSE '0-2'
          END as bucket,
          COUNT(*) as c
        FROM jobs GROUP BY bucket
        """
    ).fetchall()
    score_dist = {r["bucket"]: r["c"] for r in score_rows}

    db.close()

    return FunnelStats(
        total_jobs=total,
        discovered=by_status.get("discovered", 0),
        filtered=by_status.get("filtered", 0),
        jd_fetched=by_status.get("jd_fetched", 0),
        ready=by_status.get("ready", 0),
        rejected=by_status.get("rejected", 0),
        duplicate_flagged=by_status.get("duplicate_flagged", 0),
        capped=by_status.get("capped", 0),
        funnel=funnel,
        jd_fetch_total=jd_fetch_total,
        jd_fetch_success=jd_fetch_success,
        jd_fetch_failed=jd_fetch_failed,
        jd_fetch_pending=jd_fetch_pending,
        by_tier=by_tier,
        by_status=by_status,
        by_ats_source=by_ats,
        rejection_reasons=rejection_reasons,
        score_distribution=score_dist,
    )


@router.get("/response-rate", response_model=ResponseRateStats)
def get_response_rate():
    """Response rate stats (placeholder — application tracking is Phase 2+)."""
    return ResponseRateStats(
        total_applied=0,
        total_responded=0,
        response_rate=0.0,
        by_source={},
    )
