"""Application lifecycle events — append-only event log.

Every status change routes through transition_status() which updates the job's
status AND appends an event row in the same transaction. record_event() is the
ONLY way events are written.

Actors (closed vocabulary):
    candidate  — the user (job seeker) initiated this change
    company    — the employer initiated this change (L2+: company rejections, etc.)
    system     — the pipeline / automated process did this, not a person

Event types (closed vocabulary — use EventType constants, not raw strings):
    discovered           — job inserted by pipeline
    filter_passed        — passed tier 2 filters
    filter_rejected      — failed tier 2 filters
    jd_fetched           — JD successfully fetched
    jd_fetch_failed      — JD fetch failed
    jd_fetch_retry       — retrying previously failed JD fetch
    duplicate_flagged    — content hash dedup match
    scored_ready         — passed scoring threshold
    scored_rejected      — failed scoring (hard reject or below threshold)
    capped               — per-company cap exceeded
    manual_created       — job manually added by candidate
    status_changed       — generic PATCH status change
    rejected             — manual reject with reason
    skipped              — manual skip
    overridden           — rejection overridden
    resume_generated     — resume generated, status → interested
    applied              — candidate submitted application
    company_rejected     — company rejected (post-apply)
    withdrawn            — candidate withdrew (post-apply)
    engaged              — moved to engaged sub-lifecycle
    offer_accepted       — offer accepted
    offer_declined       — offer declined
    interview            — interview scheduled (engaged sub-event)
    challenge_assigned   — take-home challenge assigned (engaged sub-event)
    challenge_submitted  — challenge submitted (engaged sub-event)
    offer_received       — offer received (engaged sub-event)
    offer_countered      — offer countered (engaged sub-event)
    followup_sent        — follow-up sent (engaged sub-event, resets staleness)
    contact_received     — company contact received (engaged sub-event, resets staleness)
"""

from __future__ import annotations

import json
import re
import sqlite3
import warnings
from datetime import datetime, timezone
from typing import Any

_VALID_COLUMN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


# ---------------------------------------------------------------------------
# Closed vocabularies
# ---------------------------------------------------------------------------

class Actor:
    """Who initiated the event. Exactly three values — no others allowed."""
    CANDIDATE = "candidate"
    COMPANY = "company"
    SYSTEM = "system"

    _ALL = frozenset({CANDIDATE, COMPANY, SYSTEM})


class EventType:
    """Closed catalog of event types. Use these constants, not raw strings."""
    DISCOVERED = "discovered"
    FILTER_PASSED = "filter_passed"
    FILTER_REJECTED = "filter_rejected"
    JD_FETCHED = "jd_fetched"
    JD_FETCH_FAILED = "jd_fetch_failed"
    JD_FETCH_RETRY = "jd_fetch_retry"
    DUPLICATE_FLAGGED = "duplicate_flagged"
    SCORED_READY = "scored_ready"
    SCORED_REJECTED = "scored_rejected"
    CAPPED = "capped"
    MANUAL_CREATED = "manual_created"
    STATUS_CHANGED = "status_changed"
    REJECTED = "rejected"
    SKIPPED = "skipped"
    OVERRIDDEN = "overridden"
    RESUME_GENERATED = "resume_generated"
    APPLIED = "applied"
    COMPANY_REJECTED = "company_rejected"
    WITHDRAWN = "withdrawn"
    ENGAGED = "engaged"
    OFFER_ACCEPTED = "offer_accepted"
    OFFER_DECLINED = "offer_declined"
    INTERVIEW = "interview"
    CHALLENGE_ASSIGNED = "challenge_assigned"
    CHALLENGE_SUBMITTED = "challenge_submitted"
    OFFER_RECEIVED = "offer_received"
    OFFER_COUNTERED = "offer_countered"
    FOLLOWUP_SENT = "followup_sent"
    CONTACT_RECEIVED = "contact_received"
    REFILTER_RESCORED = "refilter_rescored"

    _ALL = frozenset({
        DISCOVERED, FILTER_PASSED, FILTER_REJECTED, JD_FETCHED,
        JD_FETCH_FAILED, JD_FETCH_RETRY, DUPLICATE_FLAGGED,
        SCORED_READY, SCORED_REJECTED, CAPPED, MANUAL_CREATED,
        STATUS_CHANGED, REJECTED, SKIPPED, OVERRIDDEN, RESUME_GENERATED,
        APPLIED, COMPANY_REJECTED, WITHDRAWN, ENGAGED,
        OFFER_ACCEPTED, OFFER_DECLINED,
        INTERVIEW, CHALLENGE_ASSIGNED, CHALLENGE_SUBMITTED,
        OFFER_RECEIVED, OFFER_COUNTERED, FOLLOWUP_SENT, CONTACT_RECEIVED,
        REFILTER_RESCORED,
    })


class JobStatus:
    """Closed catalog of job statuses. Use these constants, not raw strings."""
    DISCOVERED = "discovered"
    FILTERED = "filtered"
    JD_FETCHED = "jd_fetched"
    DUPLICATE_FLAGGED = "duplicate_flagged"
    READY = "ready"
    REVIEWING = "reviewing"
    INTERESTED = "interested"
    APPLIED = "applied"
    ENGAGED = "engaged"
    COMPANY_REJECTED = "company_rejected"
    WITHDRAWN = "withdrawn"
    OFFER_ACCEPTED = "offer_accepted"
    OFFER_DECLINED = "offer_declined"
    REJECTED = "rejected"
    SKIPPED = "skipped"
    CAPPED = "capped"

    _ALL = frozenset({
        DISCOVERED, FILTERED, JD_FETCHED, DUPLICATE_FLAGGED,
        READY, REVIEWING, INTERESTED, APPLIED, ENGAGED,
        COMPANY_REJECTED, WITHDRAWN, OFFER_ACCEPTED, OFFER_DECLINED,
        REJECTED, SKIPPED, CAPPED,
    })

    _POST_APPLY = frozenset({APPLIED, ENGAGED, COMPANY_REJECTED, WITHDRAWN, OFFER_ACCEPTED, OFFER_DECLINED})
    _TERMINAL = frozenset({COMPANY_REJECTED, WITHDRAWN, OFFER_ACCEPTED, OFFER_DECLINED, REJECTED, SKIPPED, CAPPED})


class EngagedEventType:
    """Engaged sub-lifecycle event types — these do NOT change status."""
    INTERVIEW = EventType.INTERVIEW
    CHALLENGE_ASSIGNED = EventType.CHALLENGE_ASSIGNED
    CHALLENGE_SUBMITTED = EventType.CHALLENGE_SUBMITTED
    OFFER_RECEIVED = EventType.OFFER_RECEIVED
    OFFER_COUNTERED = EventType.OFFER_COUNTERED
    FOLLOWUP_SENT = EventType.FOLLOWUP_SENT
    CONTACT_RECEIVED = EventType.CONTACT_RECEIVED

    _ALL = frozenset({
        EventType.INTERVIEW, EventType.CHALLENGE_ASSIGNED,
        EventType.CHALLENGE_SUBMITTED, EventType.OFFER_RECEIVED,
        EventType.OFFER_COUNTERED, EventType.FOLLOWUP_SENT,
        EventType.CONTACT_RECEIVED,
    })


STALE_ACTIVITY_EVENTS: frozenset[str] = frozenset({
    EventType.APPLIED,
    EventType.ENGAGED,
    EventType.INTERVIEW,
    EventType.CHALLENGE_ASSIGNED,
    EventType.CHALLENGE_SUBMITTED,
    EventType.OFFER_RECEIVED,
    EventType.OFFER_COUNTERED,
    EventType.FOLLOWUP_SENT,
    EventType.CONTACT_RECEIVED,
})
"""Allowlist of event types that count as "application activity" for stale-flag
purposes. Only these events reset the staleness clock for applied/engaged jobs.

Terminal-status events (company_rejected, withdrawn, offer_accepted,
offer_declined) are excluded — the status guard already short-circuits before
stale computes. manual_created/discovered are excluded — they are about job
creation, not application activity.

New event types default to NOT resetting staleness unless explicitly added here.
"""


def compute_stale_flag(
    db: sqlite3.Connection, job_id: int, status: str, stale_after_days: int
) -> tuple[bool, int | None]:
    """Compute derived stale flag — NOT stored, NOT an event.

    A job is stale if status ∈ {applied, engaged} AND the most recent event's
    occurred_at is older than stale_after_days.

    Returns (is_stale, days_since_last_activity).
    """
    if status not in (JobStatus.APPLIED, JobStatus.ENGAGED):
        return False, None

    row = db.execute(
        f"SELECT occurred_at FROM application_events "
        f"WHERE job_id = ? AND event_type IN ({','.join('?' * len(STALE_ACTIVITY_EVENTS))}) "
        f"ORDER BY occurred_at DESC LIMIT 1",
        (job_id, *STALE_ACTIVITY_EVENTS),
    ).fetchone()
    if not row or not row["occurred_at"]:
        return False, None

    try:
        last_dt = datetime.fromisoformat(row["occurred_at"])
    except (ValueError, TypeError):
        return False, None

    now = datetime.now(timezone.utc)
    delta = now - last_dt
    days_since = delta.days
    is_stale = days_since > stale_after_days
    return is_stale, days_since


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_occurred_at(
    db: sqlite3.Connection, job_id: int, occurred_at: str,
    *, allow_before_discovery: bool = False,
) -> None:
    """Soft validation: reject future dates and dates before job discovery.

    Raises ValueError with a clear message — callers should catch and return
    as a 422 in API context.

    If allow_before_discovery is True, the discovery-date floor check is
    skipped (used by the clean-start path where the user is backdating an
    event that happened before the job was added to Seeker OS).
    """
    try:
        occurred_dt = datetime.fromisoformat(occurred_at)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid occurred_at format: {occurred_at}") from exc

    now = datetime.now(timezone.utc)
    if occurred_dt > now:
        raise ValueError(f"occurred_at cannot be in the future: {occurred_at}")

    if allow_before_discovery:
        return

    row = db.execute(
        "SELECT discovered_at FROM jobs WHERE id = ?", (job_id,)
    ).fetchone()
    if row and row["discovered_at"]:
        try:
            discovered_dt = datetime.fromisoformat(row["discovered_at"])
        except (ValueError, TypeError):
            return
        if occurred_dt < discovered_dt:
            raise ValueError(
                f"occurred_at cannot be before job discovery "
                f"({row['discovered_at']}): {occurred_at}"
            )


def record_event(
    db: sqlite3.Connection,
    job_id: int,
    event_type: str,
    actor: str,
    *,
    metadata: dict | None = None,
    occurred_at: str | None = None,
    note: str | None = None,
    allow_before_discovery: bool = False,
) -> int:
    """The ONLY way events are written.

    occurred_at defaults to now; created_at is always server now().
    event_type must be a known EventType constant (warns loudly on unknown).
    actor must be one of Actor.CANDIDATE | Actor.COMPANY | Actor.SYSTEM.
    If allow_before_discovery is True, occurred_at may predate the job's
    discovered_at (used by the clean-start path).
    Returns the event ID.
    """
    if event_type not in EventType._ALL:
        warnings.warn(
            f"Unknown event_type '{event_type}' — not in EventType catalog. "
            f"Known types: {sorted(EventType._ALL)}",
            stacklevel=2,
        )
    if actor not in Actor._ALL:
        raise ValueError(
            f"Invalid actor '{actor}' — must be one of: "
            f"{', '.join(sorted(Actor._ALL))}"
        )

    now = _utc_now_iso()
    if occurred_at is None:
        occurred_at = now
    else:
        _validate_occurred_at(db, job_id, occurred_at, allow_before_discovery=allow_before_discovery)

    cursor = db.execute(
        """INSERT INTO application_events
           (job_id, event_type, actor, occurred_at, created_at, metadata, note)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            job_id,
            event_type,
            actor,
            occurred_at,
            now,
            json.dumps(metadata) if metadata else None,
            note,
        ),
    )
    return cursor.lastrowid


def transition_status(
    db: sqlite3.Connection,
    job_id: int,
    new_status: str,
    event_type: str,
    actor: str,
    *,
    metadata: dict | None = None,
    occurred_at: str | None = None,
    note: str | None = None,
    extra_sets: dict[str, Any] | None = None,
    allow_before_discovery: bool = False,
) -> int:
    """Change a job's status AND record the matching event in the same transaction.

    This is the ONLY way a status change should happen — it guarantees the
    event log gets a row. Does NOT commit — the caller controls the transaction.

    extra_sets: additional column=value pairs to include in the UPDATE
    (e.g. {"tier_passed": 4, "score": 8.5}).

    If allow_before_discovery is True, occurred_at may predate the job's
    discovered_at (used by the clean-start path).

    Returns the event ID.
    """
    now = _utc_now_iso()

    set_parts = ["status = ?", "updated_at = ?"]
    set_values: list[Any] = [new_status, now]

    if extra_sets:
        for col, val in extra_sets.items():
            if not _VALID_COLUMN.match(col):
                raise ValueError(f"Invalid column name in extra_sets: {col}")
            set_parts.append(f"{col} = ?")
            set_values.append(val)

    set_values.append(job_id)

    db.execute(
        f"UPDATE jobs SET {', '.join(set_parts)} WHERE id = ?",
        set_values,
    )

    try:
        event_id = record_event(
            db=db,
            job_id=job_id,
            event_type=event_type,
            actor=actor,
            metadata=metadata,
            occurred_at=occurred_at,
            note=note,
            allow_before_discovery=allow_before_discovery,
        )
    except Exception:
        db.rollback()
        raise

    return event_id
