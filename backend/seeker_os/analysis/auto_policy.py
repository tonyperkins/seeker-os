"""Auto-analysis policy — close the analysis coverage gap on high scorers.

Diagnosis (2026-07): JD analysis was purely manual (the only trigger was
POST /api/jobs/{id}/analysis from the job detail UI), so high-scoring jobs
routinely reached the review queue with no verdict — and therefore no verdict
cap on their net score. This module adds:

  - select_unanalyzed_high_scorers(): the shared candidate query
  - resync_verdicts_from_analyses(): repair jobs whose analysis_verdict was
    lost (e.g. a DB restore that predated the denormalized columns) but that
    have a job_analyses row — no LLM call needed
  - run_auto_analysis(): analyze candidates up to the rate limit; called at
    the end of a pipeline run when the policy is enabled, and by the one-shot
    backfill endpoint

Policy knobs live in scoring_rubric.yml (`auto_analysis` section):
enabled (default false), min_score (null → post_threshold), max_per_run.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Callable

from seeker_os.config import ScoringConfig, Settings
from seeker_os.scoring.net_score import compute_net_score

logger = logging.getLogger(__name__)

# Effective score with the same fallback the UI and calibration report use.
_EFFECTIVE_SCORE_SQL = """
    CASE WHEN net_score IS NOT NULL THEN net_score
         WHEN research_adjusted_score IS NOT NULL THEN research_adjusted_score
         ELSE score END
"""


def resolve_min_score(scoring: ScoringConfig) -> float:
    min_score = scoring.auto_analysis.min_score
    return scoring.post_threshold if min_score is None else min_score


def select_unanalyzed_high_scorers(
    db: sqlite3.Connection,
    scoring: ScoringConfig,
    limit: int | None = None,
) -> list[sqlite3.Row]:
    """Jobs whose effective net score meets min_score and have no verdict.

    Requires a fetched JD (analyze_job's precondition) and no existing
    job_analyses row — jobs with an orphaned analysis row are handled by
    resync_verdicts_from_analyses() instead, without an LLM call.
    Highest scores first, so the rate limit spends budget where it matters.
    """
    excluded_statuses = scoring.auto_analysis.analysis_excluded_statuses or []
    excluded_placeholders = ",".join("?" for _ in excluded_statuses)
    status_clause = f" AND status NOT IN ({excluded_placeholders})" if excluded_statuses else ""
    query = f"""
        SELECT id, title, company, ({_EFFECTIVE_SCORE_SQL}) AS effective_score
        FROM jobs
        WHERE score IS NOT NULL
          AND analysis_verdict IS NULL
          AND jd_full IS NOT NULL AND jd_full != ''
          AND ({_EFFECTIVE_SCORE_SQL}) >= ?
          AND NOT EXISTS (SELECT 1 FROM job_analyses ja WHERE ja.job_id = jobs.id)
          {status_clause}
        ORDER BY effective_score DESC, id
    """
    params: list = [resolve_min_score(scoring), *excluded_statuses]
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)
    return db.execute(query, params).fetchall()


def count_unanalyzed_high_scorers(
    db: sqlite3.Connection, scoring: ScoringConfig, min_score: float | None = None
) -> int:
    """Count of scored jobs at/above min_score with no analysis verdict.

    Unlike the selection query this counts ALL verdict-less high scorers
    (including JD-less and orphaned-analysis rows) — it measures the coverage
    gap, not the actionable queue.
    """
    if min_score is None:
        min_score = resolve_min_score(scoring)
    excluded_statuses = scoring.auto_analysis.analysis_excluded_statuses or []
    excluded_placeholders = ",".join("?" for _ in excluded_statuses)
    status_clause = f" AND status NOT IN ({excluded_placeholders})" if excluded_statuses else ""
    row = db.execute(
        f"""
        SELECT COUNT(*) AS c FROM jobs
        WHERE score IS NOT NULL
          AND analysis_verdict IS NULL
          AND ({_EFFECTIVE_SCORE_SQL}) >= ?
          {status_clause}
        """,
        (min_score, *excluded_statuses),
    ).fetchone()
    return row["c"]


def resync_verdicts_from_analyses(
    db: sqlite3.Connection, scoring: ScoringConfig
) -> int:
    """Re-denormalize analysis_verdict + net_score from existing job_analyses rows.

    Repairs jobs where the denormalized columns were lost (observed after a
    production data sync: job_analyses rows intact, jobs.analysis_verdict
    NULL). Uses each job's latest analysis. Commits. Returns rows repaired.
    """
    rows = db.execute(
        """
        SELECT j.id AS job_id, j.score, j.research_delta, ja.verdict
        FROM jobs j
        JOIN job_analyses ja ON ja.job_id = j.id
        WHERE j.analysis_verdict IS NULL
          AND ja.verdict IS NOT NULL AND ja.verdict != ''
          AND ja.analyzed_at = (
              SELECT MAX(ja2.analyzed_at) FROM job_analyses ja2
              WHERE ja2.job_id = j.id
          )
        """
    ).fetchall()

    for row in rows:
        base = float(row["score"]) if row["score"] is not None else 0.0
        net = compute_net_score(
            base_score=base,
            research_delta=float(row["research_delta"] or 0.0),
            analysis_verdict=row["verdict"],
            verdict_caps=scoring.verdict_caps,
            max_score=float(scoring.max_score),
            min_score=float(scoring.min_score),
            unknown_verdict_cap=scoring.unknown_verdict_cap,
        )
        db.execute(
            "UPDATE jobs SET analysis_verdict = ?, net_score = ? WHERE id = ?",
            (row["verdict"], net, row["job_id"]),
        )
        logger.info(
            "Resynced analysis verdict for job %s from existing analysis: %s (net %.1f)",
            row["job_id"], row["verdict"], net,
        )
    if rows:
        db.commit()
    return len(rows)


def run_auto_analysis(
    settings: Settings,
    db: sqlite3.Connection,
    limit: int | None = None,
    analyze_fn: Callable[..., dict] | None = None,
) -> dict:
    """Analyze unanalyzed high-scorers up to the rate limit.

    limit overrides max_per_run when given. analyze_fn is injectable for
    tests; defaults to the real LLM-backed analyze_job. Per-job failures are
    logged and counted, never raised — one bad JD must not sink the run.

    Returns {"candidates", "analyzed", "failed", "job_ids", "errors"}.
    """
    scoring = settings.scoring
    if scoring is None:
        return {"candidates": 0, "analyzed": 0, "failed": 0, "job_ids": [], "errors": []}

    if analyze_fn is None:
        from seeker_os.analysis.jd_analyzer import analyze_job
        analyze_fn = analyze_job

    if limit is None:
        limit = scoring.auto_analysis.max_per_run

    candidates = select_unanalyzed_high_scorers(db, scoring, limit=limit)
    analyzed_ids: list[int] = []
    errors: list[str] = []

    for row in candidates:
        try:
            analyze_fn(settings=settings, job_id=row["id"])
            analyzed_ids.append(row["id"])
        except Exception as exc:
            logger.warning(
                "Auto-analysis failed for job %s (%r @ %s): %s",
                row["id"], row["title"], row["company"], exc,
            )
            errors.append(f"job {row['id']}: {exc}")

    return {
        "candidates": len(candidates),
        "analyzed": len(analyzed_ids),
        "failed": len(errors),
        "job_ids": analyzed_ids,
        "errors": errors,
    }
