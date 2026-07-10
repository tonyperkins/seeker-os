"""Scoring calibration analytics — how well do rubric scores predict decisions?

Joins the jobs table (score, research_adjusted_score, net_score,
analysis_verdict) against the application_events log to derive the user's
actual decision per job:

    applied  — a candidate 'applied' event exists
    skipped  — a candidate 'skipped' or 'rejected' event exists (no apply)
    ignored  — no candidate decision recorded

The event log is authoritative for decisions — job status is not consulted,
because status 'rejected' is also written by the pipeline (scored_rejected),
which is not a user decision.

All thresholds and the bucket width are config-driven (scoring_rubric.yml
`calibration` section) — no hardcoded values here.
See docs/SCORING_RUBRIC.md § Calibration Report.
"""

from __future__ import annotations

import math
import sqlite3

from seeker_os.config import ScoringConfig
from seeker_os.database import json_decode
from seeker_os.events import Actor, EventType

DECISION_APPLIED = "applied"
DECISION_SKIPPED = "skipped"
DECISION_IGNORED = "ignored"

# Candidate event types that mean "decided not to pursue"
_SKIP_EVENT_TYPES = (EventType.SKIPPED, EventType.REJECTED)


def derive_decisions(db: sqlite3.Connection) -> dict[int, dict]:
    """Derive the user's decision per job from the event log.

    Returns {job_id: {"decision": applied|skipped, "reason": str|None}}.
    Jobs absent from the map have no recorded decision (ignored).
    An apply always wins over a skip regardless of event order — a job the
    user skipped and later applied to counts as applied.
    """
    rows = db.execute(
        """
        SELECT job_id, event_type, metadata
        FROM application_events
        WHERE actor = ?
          AND event_type IN (?, ?, ?)
        ORDER BY occurred_at
        """,
        (Actor.CANDIDATE, EventType.APPLIED, *_SKIP_EVENT_TYPES),
    ).fetchall()

    decisions: dict[int, dict] = {}
    for row in rows:
        job_id = row["job_id"]
        entry = decisions.setdefault(job_id, {"decision": None, "reason": None})
        if row["event_type"] == EventType.APPLIED:
            entry["decision"] = DECISION_APPLIED
        elif entry["decision"] != DECISION_APPLIED:
            entry["decision"] = DECISION_SKIPPED
            metadata = json_decode(row["metadata"]) or {}
            entry["reason"] = metadata.get("reason")
    return decisions


def _effective_net(row: sqlite3.Row) -> float | None:
    """Net score with fallback — mirrors the UI: net → research-adjusted → base."""
    for col in ("net_score", "research_adjusted_score", "score"):
        if row[col] is not None:
            return row[col]
    return None


def _base_score_label(row: sqlite3.Row) -> str | None:
    """Extract the fired base-score pattern label from score_reasons.

    The scoring engine writes the base entry first, as "Base: <label> (<score>)".
    """
    reasons = json_decode(row["score_reasons"]) or []
    for reason in reasons:
        if isinstance(reason, str) and reason.startswith("Base: "):
            return reason[len("Base: "):]
    return None


def _split_modifiers(row: sqlite3.Row) -> tuple[dict[str, float], dict[str, float]]:
    """Split jobs.score_modifiers (signal → realized points) by sign."""
    fired = json_decode(row["score_modifiers"]) or {}
    positive = {s: p for s, p in fired.items() if p >= 0}
    negative = {s: p for s, p in fired.items() if p < 0}
    return positive, negative


def _miss_entry(row: sqlite3.Row, net: float, decision: str, reason: str | None) -> dict:
    """Build one inspectable miss-list entry."""
    positive, negative = _split_modifiers(row)
    return {
        "job_id": row["id"],
        "title": row["title"],
        "company": row["company"],
        "net_score": net,
        "base_score": row["score"],
        "research_adjusted_score": row["research_adjusted_score"],
        "analysis_verdict": row["analysis_verdict"],
        "decision": decision,
        "decision_reason": reason,
        "base_score_label": _base_score_label(row),
        "positive_modifiers": positive,
        "negative_modifiers": negative,
        "research_factors": json_decode(row["research_breakdown"]) or [],
    }


def _bucket_index(net: float, width: float) -> int:
    # Epsilon guards float artifacts (e.g. 6.0 / 1.0 landing in the 5–6 bucket)
    return math.floor(net / width + 1e-9)


def _format_edge(value: float) -> str:
    return f"{value:g}"


def build_calibration_report(
    db: sqlite3.Connection,
    rubric: ScoringConfig,
    bucket_width: float | None = None,
) -> dict:
    """Build the full calibration report.

    bucket_width overrides the config value when given (must be > 0).
    Only scored jobs (effective net score not null) participate; the count of
    unscored jobs is reported separately.
    """
    if bucket_width is None:
        bucket_width = rubric.calibration.bucket_width
    if bucket_width <= 0:
        raise ValueError(f"bucket_width must be > 0, got {bucket_width}")

    high_threshold = rubric.calibration.high_score_threshold
    if high_threshold is None:
        high_threshold = rubric.post_threshold
    low_threshold = rubric.calibration.low_score_threshold
    if low_threshold is None:
        low_threshold = rubric.post_threshold

    decisions = derive_decisions(db)

    excluded_statuses = rubric.auto_analysis.analysis_excluded_statuses or []
    job_rows = db.execute(
        """
        SELECT id, title, company, score, research_adjusted_score, net_score,
               analysis_verdict, score_reasons, score_modifiers, research_breakdown,
               status
        FROM jobs
        """
    ).fetchall()

    # --- Pass over jobs: bucket counts, miss lists, modifier tallies ---------
    bucket_counts: dict[int, dict[str, int]] = {}
    false_positives: list[dict] = []
    false_negatives: list[dict] = []
    modifier_tallies: dict[str, dict[str, int]] = {}
    unscored = 0
    high_score_unanalyzed = 0
    totals = {DECISION_APPLIED: 0, DECISION_SKIPPED: 0, DECISION_IGNORED: 0}

    for row in job_rows:
        entry = decisions.get(row["id"])
        decision = entry["decision"] if entry else DECISION_IGNORED
        reason = entry["reason"] if entry else None

        net = _effective_net(row)
        if net is None:
            unscored += 1
            continue

        totals[decision] += 1

        # Coverage gap: a high scorer with no verdict has no verdict cap on its
        # net score — the same jobs the auto_analysis policy targets.
        # Decided-dead statuses (rejected, company_rejected) are excluded —
        # analyzing already-rejected jobs wastes LLM spend.
        if (
            net >= high_threshold
            and row["analysis_verdict"] is None
            and row["status"] not in excluded_statuses
        ):
            high_score_unanalyzed += 1

        idx = _bucket_index(net, bucket_width)
        counts = bucket_counts.setdefault(
            idx, {DECISION_APPLIED: 0, DECISION_SKIPPED: 0, DECISION_IGNORED: 0}
        )
        counts[decision] += 1

        if decision == DECISION_SKIPPED and net >= high_threshold:
            false_positives.append(_miss_entry(row, net, decision, reason))
        elif decision == DECISION_APPLIED and net < low_threshold:
            false_negatives.append(_miss_entry(row, net, decision, reason))

        fired = json_decode(row["score_modifiers"]) or {}
        for signal in fired:
            tally = modifier_tallies.setdefault(
                signal,
                {DECISION_APPLIED: 0, DECISION_SKIPPED: 0, DECISION_IGNORED: 0},
            )
            tally[decision] += 1

    # --- Bucket table (contiguous range, including empty in-between buckets) -
    buckets: list[dict] = []
    if bucket_counts:
        for idx in range(min(bucket_counts), max(bucket_counts) + 1):
            counts = bucket_counts.get(
                idx, {DECISION_APPLIED: 0, DECISION_SKIPPED: 0, DECISION_IGNORED: 0}
            )
            total = sum(counts.values())
            lo, hi = idx * bucket_width, (idx + 1) * bucket_width
            buckets.append({
                "bucket": f"{_format_edge(lo)}–{_format_edge(hi)}",
                "min_score": lo,
                "max_score": hi,
                "total": total,
                "applied": counts[DECISION_APPLIED],
                "skipped": counts[DECISION_SKIPPED],
                "ignored": counts[DECISION_IGNORED],
                "applied_pct": counts[DECISION_APPLIED] / total * 100 if total else 0.0,
                "skipped_pct": counts[DECISION_SKIPPED] / total * 100 if total else 0.0,
                "ignored_pct": counts[DECISION_IGNORED] / total * 100 if total else 0.0,
            })

    # --- Per-modifier precision ----------------------------------------------
    rubric_signals = [m.signal for m in rubric.positive_modifiers] + [
        m.signal for m in rubric.negative_modifiers
    ]
    # Rubric order first, then data-only signals (fired historically, since
    # renamed or removed from the rubric) so they stay inspectable.
    ordered_signals = [s for s in rubric_signals if s in modifier_tallies]
    ordered_signals += sorted(s for s in modifier_tallies if s not in rubric_signals)

    # Base apply rate across all scored jobs. A broad modifier that fires on
    # nearly everything converges toward this rate — lift (precision /
    # base_rate) is the meaningful read, not absolute precision.
    total_scored = sum(totals.values())
    base_rate = totals[DECISION_APPLIED] / total_scored if total_scored else 0.0

    modifier_precision: list[dict] = []
    for signal in ordered_signals:
        tally = modifier_tallies[signal]
        fired_count = sum(tally.values())
        decided = tally[DECISION_APPLIED] + tally[DECISION_SKIPPED]
        precision = tally[DECISION_APPLIED] / fired_count if fired_count else 0.0
        modifier_precision.append({
            "signal": signal,
            "in_rubric": signal in rubric_signals,
            "fired": fired_count,
            "applied": tally[DECISION_APPLIED],
            "skipped": tally[DECISION_SKIPPED],
            "ignored": tally[DECISION_IGNORED],
            "precision": precision,
            "decided_precision": (
                tally[DECISION_APPLIED] / decided if decided else None
            ),
            "lift": precision / base_rate if base_rate else None,
        })

    false_positives.sort(key=lambda m: m["net_score"], reverse=True)
    false_negatives.sort(key=lambda m: m["net_score"])

    # --- Skip reason summary -------------------------------------------------
    # Count how many skipped decisions have each reason (and how many have none).
    skip_reason_summary: dict[str, int] = {}
    skip_no_reason = 0
    for entry in decisions.values():
        if entry["decision"] == DECISION_SKIPPED:
            reason = entry["reason"]
            if reason:
                skip_reason_summary[reason] = skip_reason_summary.get(reason, 0) + 1
            else:
                skip_no_reason += 1

    return {
        "bucket_width": bucket_width,
        "high_score_threshold": high_threshold,
        "low_score_threshold": low_threshold,
        "total_scored": total_scored,
        "total_unscored": unscored,
        "high_score_unanalyzed": high_score_unanalyzed,
        "base_apply_rate": base_rate,
        "total_applied": totals[DECISION_APPLIED],
        "total_skipped": totals[DECISION_SKIPPED],
        "total_ignored": totals[DECISION_IGNORED],
        "skip_reason_summary": skip_reason_summary,
        "skip_no_reason": skip_no_reason,
        "buckets": buckets,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "modifier_precision": modifier_precision,
    }
