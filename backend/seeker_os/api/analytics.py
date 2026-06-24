"""Analytics API routes."""

from __future__ import annotations

from fastapi import APIRouter
from seeker_os.api.schemas import FunnelStats, ResponseRateStats
from seeker_os.database import get_connection

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/funnel", response_model=FunnelStats)
def get_funnel_stats():
    """Pipeline funnel stats — counts at each tier and by status."""
    db = get_connection()

    # Total
    total = db.execute("SELECT COUNT(*) as c FROM jobs").fetchone()["c"]

    # By status
    status_rows = db.execute(
        "SELECT status, COUNT(*) as c FROM jobs GROUP BY status"
    ).fetchall()
    by_status = {r["status"]: r["c"] for r in status_rows}

    # By tier
    tier_rows = db.execute(
        "SELECT tier_passed, COUNT(*) as c FROM jobs GROUP BY tier_passed"
    ).fetchall()
    by_tier = {r["tier_passed"]: r["c"] for r in tier_rows}

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
