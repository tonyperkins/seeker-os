"""Global events API — manual activity log (notes, calls, emails, meetings).

Job-scoped event reads/creates also live at /api/jobs/{id}/events; this router
adds the global feed (including events with no job), creation of manual events
optionally untied to a job, and the only mutation surface for events.

Mutation policy: only MANUAL_EVENT_TYPES rows may be edited or deleted. Every
other event type is written by the pipeline or a status transition and stays
append-only — calibration and funnel analytics read those as ground truth.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query

from seeker_os.api.schemas import (
    ActivityEvent,
    EventUpdate,
    GlobalEventCreate,
    MessageResponse,
)
from seeker_os.database import get_connection, json_decode
from seeker_os.events import (
    MANUAL_EVENT_TYPES,
    _validate_occurred_at,
    record_event,
)

router = APIRouter(prefix="/api/events", tags=["events"])

_SELECT_ENRICHED = """
    SELECT e.*, j.title AS job_title, j.company AS job_company,
           CASE
             WHEN e.event_type IN ('note', 'call', 'email_sent', 'email_received', 'meeting', 'interview')
              AND NOT EXISTS (
                  SELECT 1 FROM inbound_messages i WHERE i.confirmed_event_id = e.id
              ) THEN 1 ELSE 0
           END AS is_mutable
    FROM application_events e
    LEFT JOIN jobs j ON j.id = e.job_id
"""


def _row_to_activity(row) -> ActivityEvent:
    return ActivityEvent(
        id=row["id"],
        job_id=row["job_id"],
        event_type=row["event_type"],
        actor=row["actor"],
        occurred_at=row["occurred_at"],
        created_at=row["created_at"],
        metadata=json_decode(row["metadata"]) if row["metadata"] else None,
        note=row["note"],
        job_title=row["job_title"],
        job_company=row["job_company"],
        is_mutable=bool(row["is_mutable"]),
    )


def _fetch_enriched(db, event_id: int):
    return db.execute(
        f"{_SELECT_ENRICHED} WHERE e.id = ?", (event_id,)
    ).fetchone()


@router.get("", response_model=list[ActivityEvent])
def list_events(
    event_type: str | None = Query(None, description="Comma-separated event types"),
    job_id: int | None = Query(None, description="Filter to one job's events"),
    scope: str | None = Query(
        None, description="'global' = only events with no job attached"
    ),
    manual_only: bool = Query(False, description="Only manual event types"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Global activity feed — newest first, job context joined in."""
    where: list[str] = []
    params: list = []

    if event_type:
        types = [t.strip() for t in event_type.split(",") if t.strip()]
        if types:
            where.append(f"e.event_type IN ({','.join('?' * len(types))})")
            params.extend(types)
    if job_id is not None:
        where.append("e.job_id = ?")
        params.append(job_id)
    if scope == "global":
        where.append("e.job_id IS NULL")
    if manual_only:
        where.append(
            f"e.event_type IN ({','.join('?' * len(MANUAL_EVENT_TYPES))})"
        )
        params.extend(sorted(MANUAL_EVENT_TYPES))

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    db = get_connection()
    try:
        rows = db.execute(
            f"{_SELECT_ENRICHED} {where_sql} "
            "ORDER BY e.occurred_at DESC, e.id DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        return [_row_to_activity(r) for r in rows]
    finally:
        db.close()


@router.post("", response_model=ActivityEvent)
def create_manual_event(body: GlobalEventCreate):
    """Record a manual event, optionally tied to a job (job_id null = general note)."""
    if body.event_type not in MANUAL_EVENT_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"event_type must be a manual type: "
                   f"{', '.join(sorted(MANUAL_EVENT_TYPES))}. Lifecycle events "
                   f"go through the job status endpoints.",
        )

    db = get_connection()
    try:
        if body.job_id is not None:
            row = db.execute(
                "SELECT id FROM jobs WHERE id = ?", (body.job_id,)
            ).fetchone()
            if not row:
                raise HTTPException(
                    status_code=404, detail=f"Job {body.job_id} not found"
                )

        try:
            event_id = record_event(
                db=db,
                job_id=body.job_id,
                event_type=body.event_type,
                actor=body.actor,
                metadata=body.metadata,
                occurred_at=body.occurred_at,
                note=body.note,
                # A note about a call that predates adding the job is legitimate.
                allow_before_discovery=True,
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

        db.commit()
        return _row_to_activity(_fetch_enriched(db, event_id))
    finally:
        db.close()


def _get_mutable_event(db, event_id: int):
    """Fetch an event row, 404 if missing, 403 if not a manual type."""
    row = db.execute(
        "SELECT * FROM application_events WHERE id = ?", (event_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Event {event_id} not found")
    if row["event_type"] not in MANUAL_EVENT_TYPES:
        raise HTTPException(
            status_code=403,
            detail=f"Event type '{row['event_type']}' is append-only — only "
                   f"manual events ({', '.join(sorted(MANUAL_EVENT_TYPES))}) "
                   f"can be modified.",
        )
    inbound = db.execute(
        "SELECT 1 FROM inbound_messages WHERE confirmed_event_id = ?", (event_id,)
    ).fetchone()
    if inbound:
        raise HTTPException(
            status_code=403,
            detail="This event was confirmed from Gmail and is append-only.",
        )
    return row


@router.patch("/{event_id}", response_model=ActivityEvent)
def update_manual_event(event_id: int, body: EventUpdate):
    """Edit a manual event. System/lifecycle events are immutable."""
    db = get_connection()
    try:
        row = _get_mutable_event(db, event_id)
        fields = body.model_dump(exclude_unset=True)
        if not fields:
            return _row_to_activity(_fetch_enriched(db, event_id))

        if "event_type" in fields and fields["event_type"] not in MANUAL_EVENT_TYPES:
            raise HTTPException(
                status_code=422,
                detail=f"event_type may only change to another manual type: "
                       f"{', '.join(sorted(MANUAL_EVENT_TYPES))}",
            )
        if "occurred_at" in fields and fields["occurred_at"] is not None:
            try:
                _validate_occurred_at(
                    db, row["job_id"], fields["occurred_at"],
                    allow_before_discovery=True,
                )
            except ValueError as e:
                raise HTTPException(status_code=422, detail=str(e))

        sets, params = [], []
        for col in ("event_type", "occurred_at", "note"):
            if col in fields:
                sets.append(f"{col} = ?")
                params.append(fields[col])
        if "metadata" in fields:
            sets.append("metadata = ?")
            params.append(json.dumps(fields["metadata"]) if fields["metadata"] else None)

        db.execute(
            f"UPDATE application_events SET {', '.join(sets)} WHERE id = ?",
            (*params, event_id),
        )
        db.commit()
        return _row_to_activity(_fetch_enriched(db, event_id))
    finally:
        db.close()


@router.delete("/{event_id}", response_model=MessageResponse)
def delete_manual_event(event_id: int):
    """Delete a manual event. System/lifecycle events are immutable."""
    db = get_connection()
    try:
        _get_mutable_event(db, event_id)
        db.execute("DELETE FROM application_events WHERE id = ?", (event_id,))
        db.commit()
        return MessageResponse(message=f"Event {event_id} deleted")
    finally:
        db.close()
