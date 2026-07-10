"""Jobs API routes — thin handlers delegating to jobs_repo and jobs_service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from seeker_os.api.jobs_repo import (
    JOB_SORT_EXPRESSIONS,
    RECRUITER_JOIN_SQL,
    TRANSITION_MAP,
    VALID_TRANSITIONS,
    batch_compute_stale,
    batch_indicator_flags,
    compute_stale,
    fetch_job_by_id,
    fetch_job_events,
    get_stale_after_days,
    list_no_reason_skips,
    parse_iso,
    row_to_detail,
    row_to_event,
    row_to_recruiter,
    row_to_summary,
    search_recruiters,
)
from seeker_os.api.jobs_service import (
    create_job_service,
    refilter_rescore_job,
    try_apply_research_adjustment,
)
from seeker_os.api.schemas import (
    ApplicationEvent,
    ApplicationEventCreate,
    CleanStartCreate,
    EngagedEventCreate,
    JobCreate,
    JobCreateResponse,
    JobDetail,
    JobOverride,
    JobReject,
    JobSkip,
    JobUpdate,
    MessageResponse,
    NoReasonSkip,
    PaginatedJobsResponse,
    PostApplyTransition,
    RecruiterAssociationUpdate,
    RecruiterContact,
    RecruiterContactCreate,
    RecruiterEntityUpdate,
    RecruiterSearchResult,
    RefilterRescoreRequest,
    RefilterRescoreResult,
    SkipReasonAnnotate,
)
from seeker_os.database import get_connection, json_decode, json_encode
from seeker_os.events import (
    Actor,
    EngagedEventType,
    EventType,
    JobStatus,
    record_event,
    transition_status,
)

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

# Backward-compat re-exports for tests that import from this module
_refilter_rescore_job = refilter_rescore_job
_try_apply_research_adjustment = try_apply_research_adjustment
_compute_stale = compute_stale
_batch_compute_stale = batch_compute_stale
_get_stale_after_days = get_stale_after_days
_parse_iso = parse_iso
_row_to_summary = row_to_summary
_row_to_detail = row_to_detail
_row_to_event = row_to_event
_row_to_recruiter = row_to_recruiter
_JOB_SORT_EXPRESSIONS = JOB_SORT_EXPRESSIONS
_RECRUITER_JOIN_SQL = RECRUITER_JOIN_SQL
_TRANSITION_MAP = TRANSITION_MAP
_VALID_TRANSITIONS = VALID_TRANSITIONS


@router.get("", response_model=PaginatedJobsResponse)
def list_jobs(
    status: str | None = Query(None, description="Filter by status"),
    min_score: float | None = Query(None, description="Minimum score"),
    min_tier: int | None = Query(None, description="Minimum tier_passed (e.g. 4 for scored)"),
    company: str | None = Query(None, description="Filter by company (substring)"),
    search: str | None = Query(None, description="Free-text search across title, company, location, reject_reason, discovered_query, recruiter name"),
    source: str | None = Query(None, description="Filter by source_id (e.g. 'manual', 'hiring_cafe')"),
    run_id: str | None = Query(None, description="Filter by pipeline run_id"),
    verdict: str | None = Query(None, description="Filter by AI analysis verdict (APPLY, CONDITIONAL, MONITOR, SKIP)"),
    exclude_status: str | None = Query(None, description="Comma-separated statuses to exclude (e.g. 'rejected,skipped')"),
    recruiter_source: str | None = Query(None, description="Filter by recruiter contact source (e.g. 'LinkedIn', 'email')"),
    has_recruiter: bool | None = Query(None, description="Filter to jobs with (true) or without (false) recruiter contacts"),
    sort_by: Literal["score", "net_score", "status", "run_id", "title", "company", "comp", "location", "ats"] | None = Query(
        None,
        description="Sort field. Defaults to net_score for ready jobs and score otherwise.",
    ),
    order: Literal["asc", "desc"] = Query("desc", description="Sort direction."),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List jobs with optional filters."""
    db = get_connection()
    try:
        query = "SELECT * FROM jobs WHERE 1=1"
        params: list = []

        if status:
            statuses = [s.strip() for s in status.split(",") if s.strip()]
            if len(statuses) == 1:
                query += " AND status = ?"
                params.append(statuses[0])
            elif len(statuses) > 1:
                placeholders = ",".join("?" for _ in statuses)
                query += f" AND status IN ({placeholders})"
                params.extend(statuses)
        if exclude_status:
            excluded = [s.strip() for s in exclude_status.split(",") if s.strip()]
            if excluded:
                placeholders = ",".join("?" for _ in excluded)
                query += f" AND status NOT IN ({placeholders})"
                params.extend(excluded)
        if min_tier is not None:
            query += " AND tier_passed >= ?"
            params.append(min_tier)
        if min_score is not None:
            query += " AND score >= ?"
            params.append(min_score)
        if company:
            query += " AND company LIKE ?"
            params.append(f"%{company}%")
        if search:
            query += " AND (title LIKE ? OR company LIKE ? OR location LIKE ? OR reject_reason LIKE ? OR discovered_query LIKE ? OR run_id LIKE ? OR id IN (SELECT rjc.job_id FROM recruiter_job_contacts rjc JOIN recruiters r ON rjc.recruiter_id = r.id WHERE r.name LIKE ?))"
            pat = f"%{search}%"
            params.extend([pat, pat, pat, pat, pat, pat, pat])
        if source:
            query += " AND source_id = ?"
            params.append(source)
        if run_id:
            query += " AND run_id LIKE ?"
            params.append(f"%{run_id}%")
        if verdict:
            query += " AND analysis_verdict = ?"
            params.append(verdict)
        if recruiter_source:
            query += " AND id IN (SELECT job_id FROM recruiter_job_contacts WHERE source = ?)"
            params.append(recruiter_source)
        if has_recruiter is not None:
            if has_recruiter:
                query += " AND id IN (SELECT job_id FROM recruiter_job_contacts)"
            else:
                query += " AND id NOT IN (SELECT job_id FROM recruiter_job_contacts)"

        count_query = query.replace("SELECT *", "SELECT COUNT(*) as total", 1)
        total = db.execute(count_query, params).fetchone()["total"]

        effective_sort = sort_by or ("net_score" if status == "ready" else "score")
        sort_expression = JOB_SORT_EXPRESSIONS[effective_sort]
        direction = "ASC" if order == "asc" else "DESC"
        query += f" ORDER BY {sort_expression} {direction}, discovered_at DESC, id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = db.execute(query, params).fetchall()

        stale_after_days = get_stale_after_days()
        stale_map = batch_compute_stale(db, rows, stale_after_days)

        job_ids = [r["id"] for r in rows]
        analysis_ids, research_ids, resume_ids, recruiter_map = batch_indicator_flags(db, job_ids)

        jobs = [
            row_to_summary(
                r, db=db, stale_after_days=stale_after_days,
                stale_result=stale_map.get(r["id"]),
                indicator_flags=(
                    r["id"] in analysis_ids,
                    r["id"] in research_ids,
                    r["id"] in resume_ids,
                ),
                recruiter_flag=(
                    r["id"] in recruiter_map,
                    recruiter_map.get(r["id"]),
                ),
            )
            for r in rows
        ]
        return PaginatedJobsResponse(jobs=jobs, total=total)
    finally:
        db.close()


@router.post("", response_model=JobCreateResponse)
def create_job(body: JobCreate):
    """Manually add a job."""
    return create_job_service(body)


@router.post("/{job_id}/override", response_model=MessageResponse)
def override_job(job_id: int, body: JobOverride):
    """Override a rejected job — auditable, not a silent status flip."""
    db = get_connection()
    try:
        row = fetch_job_by_id(db, job_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

        if row["status"] != "rejected":
            raise HTTPException(status_code=400, detail=f"Job {job_id} is not rejected (status={row['status']})")

        valid_targets = {"ready", "interested"}
        if body.target_status not in valid_targets:
            raise HTTPException(status_code=422, detail=f"target_status must be one of: {', '.join(valid_targets)}")

        now = datetime.now(UTC).isoformat()
        original_reason = row["reject_reason"]

        transition_status(
            db, job_id, body.target_status, EventType.OVERRIDDEN, Actor.CANDIDATE,
            extra_sets={
                "overridden_at": now,
                "override_note": body.note,
                "original_reject_reason": original_reason,
            },
            metadata={"from": "rejected", "to": body.target_status, "note": body.note},
        )
        db.commit()
        return MessageResponse(message=f"Job {job_id} overridden to '{body.target_status}'")
    finally:
        db.close()


@router.get("/{job_id}", response_model=JobDetail)
def get_job(job_id: int):
    """Get full job detail."""
    db = get_connection()
    try:
        row = fetch_job_by_id(db, job_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        return row_to_detail(row, db=db)
    finally:
        db.close()


@router.patch("/{job_id}", response_model=MessageResponse)
def update_job(job_id: int, update: JobUpdate):
    """Update job status, notes, pinned state, or editable job details."""
    db = get_connection()
    try:
        row = fetch_job_by_id(db, job_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

        now = datetime.now(UTC).isoformat()
        if update.status is not None:
            old_status = row["status"]
            try:
                transition_status(
                    db, job_id, update.status, EventType.STATUS_CHANGED, Actor.CANDIDATE,
                    metadata={"from": old_status, "to": update.status},
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        if update.is_pinned is not None:
            db.execute("UPDATE jobs SET is_pinned=?, updated_at=? WHERE id=?", (update.is_pinned, now, job_id))
        if update.ai_policy is not None:
            valid_policies = {"allowed", "draft_only", "forbidden"}
            if update.ai_policy not in valid_policies:
                raise HTTPException(status_code=422, detail=f"ai_policy must be one of: {', '.join(valid_policies)}")
            db.execute("UPDATE jobs SET ai_policy=?, updated_at=? WHERE id=?", (update.ai_policy, now, job_id))

        detail_fields = {
            "title": update.title,
            "company": update.company,
            "location": update.location,
            "workplace_type": update.workplace_type,
            "seniority_level": update.seniority_level,
            "role_type": update.role_type,
            "comp_min": update.comp_min,
            "comp_max": update.comp_max,
            "comp_currency": update.comp_currency,
            "company_homepage": update.company_homepage,
            "apply_url": update.apply_url,
            "jd_full": update.jd_full,
        }
        updates = {k: v for k, v in detail_fields.items() if v is not None}
        if updates:
            set_clauses = ", ".join(f"{k}=?" for k in updates)
            params = list(updates.values()) + [now, job_id]
            db.execute(f"UPDATE jobs SET {set_clauses}, updated_at=? WHERE id=?", params)

        db.commit()
        return MessageResponse(message=f"Job {job_id} updated")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Recruiter contact CRUD
# ---------------------------------------------------------------------------

@router.post("/{job_id}/recruiters", response_model=RecruiterContact)
def add_recruiter(job_id: int, body: RecruiterContactCreate):
    """Add a recruiter contact to a job."""
    db = get_connection()
    try:
        row = db.execute("SELECT id FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

        now = datetime.now(UTC).isoformat()

        if body.recruiter_id is not None:
            recruiter_id = body.recruiter_id
            exists = db.execute(
                "SELECT id FROM recruiters WHERE id = ?", (recruiter_id,)
            ).fetchone()
            if not exists:
                raise HTTPException(
                    status_code=404,
                    detail=f"Recruiter {recruiter_id} not found",
                )
        else:
            cursor = db.execute(
                """
                INSERT INTO recruiters (name, email, phone, linkedin, agency, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (body.name, body.email, body.phone, body.linkedin,
                 body.agency, now, now),
            )
            recruiter_id = cursor.lastrowid

        existing = db.execute(
            "SELECT id FROM recruiter_job_contacts WHERE recruiter_id = ? AND job_id = ?",
            (recruiter_id, job_id),
        ).fetchone()
        is_new_association = existing is None

        cursor = db.execute(
            """
            INSERT INTO recruiter_job_contacts
                (recruiter_id, job_id, source, contacted_at, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(recruiter_id, job_id) DO UPDATE SET
                source = COALESCE(excluded.source, recruiter_job_contacts.source),
                notes = COALESCE(excluded.notes, recruiter_job_contacts.notes),
                updated_at = excluded.updated_at
            """,
            (recruiter_id, job_id, body.source, body.contacted_at,
             body.notes, now, now),
        )
        assoc_row = db.execute(
            "SELECT id FROM recruiter_job_contacts WHERE recruiter_id = ? AND job_id = ?",
            (recruiter_id, job_id),
        ).fetchone()
        association_id = assoc_row["id"]

        if is_new_association:
            recruiter_row = db.execute(
                "SELECT name, agency FROM recruiters WHERE id = ?", (recruiter_id,)
            ).fetchone()
            record_event(
                db, job_id, EventType.RECRUITER_CONTACT, Actor.COMPANY,
                metadata={
                    "name": recruiter_row["name"] if recruiter_row else None,
                    "source": body.source,
                    "agency": recruiter_row["agency"] if recruiter_row else None,
                },
                occurred_at=body.contacted_at,
                allow_before_discovery=True,
            )

        db.commit()
        rc_row = db.execute(
            f"{RECRUITER_JOIN_SQL} WHERE rjc.id = ?",
            (association_id,),
        ).fetchone()
        return row_to_recruiter(rc_row)
    finally:
        db.close()


@router.patch("/recruiters/{recruiter_id}", response_model=RecruiterContact)
def update_recruiter_entity(recruiter_id: int, body: RecruiterEntityUpdate):
    """Update a recruiter entity (affects all associations)."""
    db = get_connection()
    try:
        row = db.execute(
            "SELECT id FROM recruiters WHERE id = ?", (recruiter_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Recruiter {recruiter_id} not found")

        now = datetime.now(UTC).isoformat()
        fields = {
            "name": body.name,
            "email": body.email,
            "phone": body.phone,
            "linkedin": body.linkedin,
            "agency": body.agency,
        }
        updates = {k: v for k, v in fields.items() if v is not None}
        if updates:
            set_clauses = ", ".join(f"{k}=?" for k in updates)
            params = list(updates.values()) + [now, recruiter_id]
            db.execute(
                f"UPDATE recruiters SET {set_clauses}, updated_at=? WHERE id=?",
                params,
            )

        db.commit()
        rc_row = db.execute(
            f"{RECRUITER_JOIN_SQL} WHERE rjc.recruiter_id = ? ORDER BY rjc.id ASC LIMIT 1",
            (recruiter_id,),
        ).fetchone()
        if not rc_row:
            r = db.execute("SELECT * FROM recruiters WHERE id = ?", (recruiter_id,)).fetchone()
            return RecruiterContact(
                id=0, recruiter_id=r["id"], job_id=0,
                name=r["name"], email=r["email"], phone=r["phone"],
                linkedin=r["linkedin"], agency=r["agency"],
                source=None, contacted_at=None, notes=None,
                created_at=r["created_at"] or "", updated_at=r["updated_at"] or "",
            )
        return row_to_recruiter(rc_row)
    finally:
        db.close()


@router.patch("/recruiters/association/{association_id}", response_model=RecruiterContact)
def update_recruiter_association(association_id: int, body: RecruiterAssociationUpdate):
    """Update association fields (source, notes only)."""
    db = get_connection()
    try:
        row = db.execute(
            "SELECT id FROM recruiter_job_contacts WHERE id = ?", (association_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Recruiter association {association_id} not found")

        now = datetime.now(UTC).isoformat()
        fields = {
            "source": body.source,
            "notes": body.notes,
        }
        updates = {k: v for k, v in fields.items() if v is not None}
        if updates:
            set_clauses = ", ".join(f"{k}=?" for k in updates)
            params = list(updates.values()) + [now, association_id]
            db.execute(
                f"UPDATE recruiter_job_contacts SET {set_clauses}, updated_at=? WHERE id=?",
                params,
            )

        db.commit()
        rc_row = db.execute(
            f"{RECRUITER_JOIN_SQL} WHERE rjc.id = ?",
            (association_id,),
        ).fetchone()
        return row_to_recruiter(rc_row)
    finally:
        db.close()


@router.delete("/recruiters/association/{association_id}", response_model=MessageResponse)
def delete_recruiter_association(association_id: int):
    """Delete a recruiter-job association (does NOT delete the recruiter entity)."""
    db = get_connection()
    try:
        row = db.execute(
            "SELECT id FROM recruiter_job_contacts WHERE id = ?", (association_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Recruiter association {association_id} not found")

        db.execute("DELETE FROM recruiter_job_contacts WHERE id = ?", (association_id,))
        db.commit()
        return MessageResponse(message=f"Recruiter association {association_id} deleted")
    finally:
        db.close()


@router.get("/recruiters/search", response_model=list[RecruiterSearchResult])
def search_recruiters_route(q: str = Query("", description="Search by name or email")):
    """Search recruiters by name or email for autocomplete picker."""
    db = get_connection()
    try:
        return search_recruiters(db, q)
    finally:
        db.close()


@router.post("/{job_id}/reject", response_model=MessageResponse)
def reject_job(job_id: int, body: JobReject):
    """Reject a job with a reason."""
    db = get_connection()
    try:
        row = fetch_job_by_id(db, job_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

        transition_status(
            db, job_id, "rejected", EventType.REJECTED, Actor.CANDIDATE,
            extra_sets={"reject_reason": body.reason, "reject_details": body.details},
            metadata={"reason": body.reason, "details": body.details},
        )
        db.commit()
        return MessageResponse(message=f"Job {job_id} rejected: {body.reason}")
    finally:
        db.close()


@router.post("/{job_id}/skip", response_model=MessageResponse)
def skip_job(job_id: int, body: JobSkip | None = None):
    """Skip a job — removes it from the active queue."""
    db = get_connection()
    try:
        row = fetch_job_by_id(db, job_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

        metadata = None
        extra_sets = {"reject_reason": None}
        if body and body.reason:
            metadata = {"reason": body.reason}
            if body.details:
                metadata["details"] = body.details
            extra_sets["reject_reason"] = body.reason

        transition_status(
            db, job_id, "skipped", EventType.SKIPPED, Actor.CANDIDATE,
            extra_sets=extra_sets,
            metadata=metadata,
        )
        db.commit()
        return MessageResponse(message=f"Job {job_id} skipped")
    finally:
        db.close()


@router.get("/skipped/no-reason", response_model=list[NoReasonSkip])
def list_no_reason_skips_route():
    """List skipped/rejected jobs whose most recent candidate skip/rejected event
    has no reason in its metadata.
    """
    db = get_connection()
    try:
        rows = list_no_reason_skips(db)
        return [
            NoReasonSkip(
                job_id=r["id"],
                title=r["title"],
                company=r["company"],
                status=r["status"],
                event_id=r["event_id"],
                event_type=r["event_type"],
                occurred_at=r["occurred_at"],
            )
            for r in rows
        ]
    finally:
        db.close()


@router.post("/{job_id}/annotate-skip", response_model=MessageResponse)
def annotate_skip(job_id: int, body: SkipReasonAnnotate):
    """Add a reason to the most recent candidate skip/rejected event for a job."""
    db = get_connection()
    try:
        row = fetch_job_by_id(db, job_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

        event_row = db.execute(
            """
            SELECT id, metadata FROM application_events
            WHERE job_id = ? AND actor = ? AND event_type IN (?, ?)
            ORDER BY id DESC LIMIT 1
            """,
            (job_id, Actor.CANDIDATE, EventType.SKIPPED, EventType.REJECTED),
        ).fetchone()
        if not event_row:
            raise HTTPException(
                status_code=404,
                detail=f"No skip/rejected event found for job {job_id}",
            )

        metadata = json_decode(event_row["metadata"]) or {}
        metadata["reason"] = body.reason
        if body.details:
            metadata["details"] = body.details

        db.execute(
            "UPDATE application_events SET metadata = ? WHERE id = ?",
            (json_encode(metadata), event_row["id"]),
        )
        db.execute(
            "UPDATE jobs SET reject_reason = ? WHERE id = ?",
            (body.reason, job_id),
        )
        db.commit()
        return MessageResponse(message=f"Job {job_id} skip reason annotated: {body.reason}")
    finally:
        db.close()


@router.post("/{job_id}/apply", response_model=MessageResponse)
def apply_to_job(job_id: int):
    """Mark a job as applied — records an APPLIED event with CANDIDATE actor."""
    db = get_connection()
    try:
        row = fetch_job_by_id(db, job_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

        current = row["status"]
        if current == JobStatus.APPLIED:
            raise HTTPException(status_code=409, detail=f"Job {job_id} is already marked applied")

        transition_status(
            db, job_id, JobStatus.APPLIED, EventType.APPLIED, Actor.CANDIDATE,
        )
        db.commit()
        return MessageResponse(message=f"Job {job_id} marked as applied")
    finally:
        db.close()


@router.get("/{job_id}/events", response_model=list[ApplicationEvent])
def get_job_events(job_id: int):
    """Get a job's event timeline ordered by occurred_at."""
    db = get_connection()
    try:
        row = db.execute("SELECT id FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

        rows = fetch_job_events(db, job_id)
        return [row_to_event(r) for r in rows]
    finally:
        db.close()


@router.post("/{job_id}/events", response_model=ApplicationEvent)
def create_event(job_id: int, body: ApplicationEventCreate):
    """Add an event to a job's timeline."""
    db = get_connection()
    try:
        row = db.execute("SELECT id FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

        try:
            event_id = record_event(
                db=db,
                job_id=job_id,
                event_type=body.event_type,
                actor=body.actor,
                metadata=body.metadata,
                occurred_at=body.occurred_at,
                note=body.note,
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

        db.commit()

        event_row = db.execute(
            "SELECT * FROM application_events WHERE id = ?", (event_id,)
        ).fetchone()
        return row_to_event(event_row)
    finally:
        db.close()


@router.delete("/{job_id}", response_model=MessageResponse)
def delete_job(job_id: int):
    """Delete a job and all dependent records."""
    db = get_connection()
    try:
        row = db.execute("SELECT id FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

        for table in ("dedup_registry", "resumes",
                       "job_analyses",
                       "application_events"):
            db.execute(f"DELETE FROM {table} WHERE job_id = ?", (job_id,))

        db.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        db.commit()
        return MessageResponse(message=f"Job {job_id} deleted")
    finally:
        db.close()


@router.get("/{job_id}/cross-ref", response_model=dict)
def check_cross_ref(job_id: int):
    """Check a job against the job-search repo."""
    from seeker_os.config import get_settings
    from seeker_os.crossref.jobsearch_repo import check_cross_reference

    db = get_connection()
    try:
        row = fetch_job_by_id(db, job_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

        settings = get_settings()
        if not settings.profile:
            raise HTTPException(status_code=400, detail="Profile config not loaded")

        result = check_cross_reference(
            title=row["title"] or "",
            company=row["company"] or "",
            repo_path=settings.profile.cross_reference.repo_path,
        )
        return result.model_dump()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Post-apply lifecycle endpoints (L2)
# ---------------------------------------------------------------------------

@router.post("/{job_id}/transition", response_model=MessageResponse)
def post_apply_transition(job_id: int, body: PostApplyTransition):
    """Post-apply status transition via the L1 central write path."""
    db = get_connection()
    try:
        row = fetch_job_by_id(db, job_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

        current = row["status"]
        target = body.target_status

        if target not in TRANSITION_MAP:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid target_status '{target}'. Must be one of: {', '.join(sorted(TRANSITION_MAP))}",
            )

        allowed = VALID_TRANSITIONS.get(current, frozenset())
        if target not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot transition from '{current}' to '{target}'. "
                       f"Allowed from '{current}': {', '.join(sorted(allowed)) or 'none'}",
            )

        event_type, actor = TRANSITION_MAP[target]
        transition_status(
            db, job_id, target, event_type, actor,
            metadata=body.metadata,
            occurred_at=body.occurred_at,
            note=body.note,
        )
        db.commit()
        return MessageResponse(message=f"Job {job_id} transitioned to '{target}'")
    finally:
        db.close()


@router.post("/{job_id}/engaged-events", response_model=ApplicationEvent)
def log_engaged_event(job_id: int, body: EngagedEventCreate):
    """Log an engaged sub-lifecycle event WITHOUT changing status."""
    db = get_connection()
    try:
        row = fetch_job_by_id(db, job_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

        if row["status"] != JobStatus.ENGAGED:
            raise HTTPException(
                status_code=400,
                detail=f"Engaged events can only be logged when status='engaged' (current: '{row['status']}')",
            )

        if body.event_type not in EngagedEventType._ALL:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid engaged event_type '{body.event_type}'. Must be one of: {', '.join(sorted(EngagedEventType._ALL))}",
            )

        try:
            event_id = record_event(
                db=db,
                job_id=job_id,
                event_type=body.event_type,
                actor=Actor.CANDIDATE,
                metadata=body.metadata,
                occurred_at=body.occurred_at,
                note=body.note,
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

        db.commit()

        event_row = db.execute(
            "SELECT * FROM application_events WHERE id = ?", (event_id,)
        ).fetchone()
        return row_to_event(event_row)
    finally:
        db.close()


@router.post("/{job_id}/clean-start", response_model=MessageResponse)
def clean_start(job_id: int, body: CleanStartCreate):
    """Enter a job directly at a post-apply status with a backdated event."""
    db = get_connection()
    try:
        row = fetch_job_by_id(db, job_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

        target = body.target_status
        clean_start_statuses = {
            JobStatus.APPLIED, JobStatus.ENGAGED,
            JobStatus.COMPANY_REJECTED, JobStatus.WITHDRAWN,
            JobStatus.OFFER_ACCEPTED, JobStatus.OFFER_DECLINED,
            JobStatus.REJECTED,
        }
        if target not in clean_start_statuses:
            raise HTTPException(
                status_code=422,
                detail=f"clean-start target_status must be one of: {', '.join(sorted(clean_start_statuses))}",
            )

        event_type, actor = TRANSITION_MAP.get(
            target, (EventType.STATUS_CHANGED, Actor.CANDIDATE),
        )

        now_iso = datetime.now(UTC).isoformat()
        target_occurred_at = body.occurred_at or now_iso

        implies_application = target in (JobStatus.ENGAGED, JobStatus.COMPANY_REJECTED)
        if implies_application and body.applied_occurred_at:
            applied_dt = parse_iso(body.applied_occurred_at)
            if applied_dt is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"Invalid applied_occurred_at format: {body.applied_occurred_at}",
                )
            now = datetime.now(UTC)
            if applied_dt > now:
                raise HTTPException(
                    status_code=422,
                    detail=f"applied_occurred_at cannot be in the future: {body.applied_occurred_at}",
                )
            target_dt = parse_iso(target_occurred_at)
            if target_dt and applied_dt > target_dt:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"applied_occurred_at ({body.applied_occurred_at}) cannot be "
                        f"later than the {target} event's occurred_at ({target_occurred_at})"
                    ),
                )

            try:
                record_event(
                    db=db,
                    job_id=job_id,
                    event_type=EventType.APPLIED,
                    actor=Actor.CANDIDATE,
                    occurred_at=body.applied_occurred_at,
                    allow_before_discovery=True,
                )
            except ValueError as e:
                raise HTTPException(status_code=422, detail=str(e))

        transition_status(
            db, job_id, target, event_type, actor,
            occurred_at=body.occurred_at,
            note=body.note,
            metadata=body.metadata or {"clean_start": True},
            allow_before_discovery=True,
        )
        db.commit()
        return MessageResponse(message=f"Job {job_id} clean-started to '{target}'")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Refilter & Rescore
# ---------------------------------------------------------------------------

@router.post("/refilter-rescore", response_model=list[RefilterRescoreResult])
def refilter_rescore(body: RefilterRescoreRequest):
    """Refilter & rescore existing jobs with current config."""
    from seeker_os.config import get_settings

    settings = get_settings()
    if not settings.profile or not settings.scoring or not settings.filters:
        raise HTTPException(status_code=500, detail="Config not loaded")

    db = get_connection()
    try:
        if body.job_ids:
            placeholders = ",".join("?" * len(body.job_ids))
            rows = db.execute(
                f"SELECT * FROM jobs WHERE id IN ({placeholders})",
                body.job_ids,
            ).fetchall()
        elif body.run_id:
            rows = db.execute(
                "SELECT * FROM jobs WHERE run_id = ?",
                (body.run_id,),
            ).fetchall()
        else:
            raise HTTPException(
                status_code=400,
                detail="Provide either job_ids or run_id",
            )

        results = []
        for row in rows:
            try:
                result = refilter_rescore_job(db, row, settings)
                results.append(result)
            except Exception as e:
                results.append(RefilterRescoreResult(
                    job_id=row["id"],
                    status=row["status"],
                    filter_passed=False,
                    filter_reason=f"Error: {e}",
                ))

        db.commit()
        return results
    finally:
        db.close()
