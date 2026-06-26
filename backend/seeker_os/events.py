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

    _ALL = frozenset({
        DISCOVERED, FILTER_PASSED, FILTER_REJECTED, JD_FETCHED,
        JD_FETCH_FAILED, JD_FETCH_RETRY, DUPLICATE_FLAGGED,
        SCORED_READY, SCORED_REJECTED, CAPPED, MANUAL_CREATED,
        STATUS_CHANGED, REJECTED, SKIPPED, OVERRIDDEN, RESUME_GENERATED,
    })


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_occurred_at(
    db: sqlite3.Connection, job_id: int, occurred_at: str
) -> None:
    """Soft validation: reject future dates and dates before job discovery.

    Raises ValueError with a clear message — callers should catch and return
    as a 422 in API context.
    """
    try:
        occurred_dt = datetime.fromisoformat(occurred_at)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid occurred_at format: {occurred_at}") from exc

    now = datetime.now(timezone.utc)
    if occurred_dt > now:
        raise ValueError(f"occurred_at cannot be in the future: {occurred_at}")

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
) -> int:
    """The ONLY way events are written.

    occurred_at defaults to now; created_at is always server now().
    event_type must be a known EventType constant (warns loudly on unknown).
    actor must be one of Actor.CANDIDATE | Actor.COMPANY | Actor.SYSTEM.
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
        _validate_occurred_at(db, job_id, occurred_at)

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
) -> int:
    """Change a job's status AND record the matching event in the same transaction.

    This is the ONLY way a status change should happen — it guarantees the
    event log gets a row. Does NOT commit — the caller controls the transaction.

    extra_sets: additional column=value pairs to include in the UPDATE
    (e.g. {"tier_passed": 4, "score": 8.5}).

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
        )
    except Exception:
        db.rollback()
        raise

    return event_id
