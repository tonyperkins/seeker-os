"""Jobs API routes."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from seeker_os.api.schemas import (
    JobSummary, JobDetail, JobUpdate, JobReject, MessageResponse,
)
from seeker_os.database import get_connection, json_decode

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _row_to_summary(row) -> JobSummary:
    return JobSummary(
        id=row["id"],
        title=row["title"] or "",
        company=row["company"] or "",
        score=row["score"],
        status=row["status"],
        tier_passed=row["tier_passed"],
        comp_min=row["comp_min"],
        comp_max=row["comp_max"],
        location=row["location"] or "",
        workplace_type=row["workplace_type"] or "",
        seniority_level=row["seniority_level"],
        date_posted=row["date_posted"] or "",
        discovered_at=row["discovered_at"] or "",
        apply_url=row["apply_url"] or "",
        ats_source=row["ats_source"],
        cross_ref_status=row["cross_ref_status"],
        is_pinned=bool(row["is_pinned"]),
        reject_reason=row["reject_reason"],
    )


def _row_to_detail(row) -> JobDetail:
    return JobDetail(
        id=row["id"],
        title=row["title"] or "",
        core_title=row["core_title"] or "",
        company=row["company"] or "",
        company_homepage=row["company_homepage"],
        location=row["location"] or "",
        workplace_type=row["workplace_type"] or "",
        workplace_countries=json_decode(row["workplace_countries"]) or [],
        seniority_level=row["seniority_level"],
        commitment=json_decode(row["commitment"]) or [],
        comp_min=row["comp_min"],
        comp_max=row["comp_max"],
        comp_currency=row["comp_currency"],
        technical_tools=json_decode(row["technical_tools"]) or [],
        requirements_summary=row["requirements_summary"] or "",
        date_posted=row["date_posted"] or "",
        role_type=row["role_type"],
        status=row["status"],
        tier_passed=row["tier_passed"],
        score=row["score"],
        score_reasons=json_decode(row["score_reasons"]) or [],
        score_gaps=json_decode(row["score_gaps"]) or [],
        reject_reason=row["reject_reason"],
        reject_details=row["reject_details"] if "reject_details" in row.keys() else None,
        jd_full=row["jd_full"] or "",
        jd_fetch_status=row["jd_fetch_status"] or "pending",
        source_id=row["source_id"] or "",
        ats_source=row["ats_source"],
        ats_board_token=row["ats_board_token"],
        ats_job_id=row["ats_job_id"],
        apply_url=row["apply_url"] or "",
        discovered_query=row["discovered_query"] or "",
        discovered_at=row["discovered_at"] or "",
        updated_at=row["updated_at"] or "",
        content_hash=row["content_hash"],
        cross_ref_status=row["cross_ref_status"],
        cross_ref_date=row["cross_ref_date"],
        cross_ref_score=row["cross_ref_score"],
        is_pinned=bool(row["is_pinned"]),
    )


@router.get("", response_model=list[JobSummary])
def list_jobs(
    status: str | None = Query(None, description="Filter by status"),
    min_score: float | None = Query(None, description="Minimum score"),
    company: str | None = Query(None, description="Filter by company (substring)"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List jobs with optional filters."""
    db = get_connection()
    try:
        query = "SELECT * FROM jobs WHERE 1=1"
        params: list = []

        if status:
            query += " AND status = ?"
            params.append(status)
        if min_score is not None:
            query += " AND score >= ?"
            params.append(min_score)
        if company:
            query += " AND company LIKE ?"
            params.append(f"%{company}%")

        query += " ORDER BY"
        if status == "ready":
            query += " score DESC,"
        query += " discovered_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = db.execute(query, params).fetchall()
        return [_row_to_summary(r) for r in rows]
    finally:
        db.close()


@router.get("/{job_id}", response_model=JobDetail)
def get_job(job_id: int):
    """Get full job detail."""
    db = get_connection()
    try:
        row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        return _row_to_detail(row)
    finally:
        db.close()


@router.patch("/{job_id}", response_model=MessageResponse)
def update_job(job_id: int, update: JobUpdate):
    """Update job status, notes, or pinned state."""
    db = get_connection()
    try:
        row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

        now = datetime.now(timezone.utc).isoformat()
        if update.status is not None:
            db.execute("UPDATE jobs SET status=?, updated_at=? WHERE id=?", (update.status, now, job_id))
        if update.is_pinned is not None:
            db.execute("UPDATE jobs SET is_pinned=?, updated_at=? WHERE id=?", (update.is_pinned, now, job_id))
        db.commit()
        return MessageResponse(message=f"Job {job_id} updated")
    finally:
        db.close()


@router.post("/{job_id}/reject", response_model=MessageResponse)
def reject_job(job_id: int, body: JobReject):
    """Reject a job with a reason."""
    db = get_connection()
    try:
        row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "UPDATE jobs SET status='rejected', reject_reason=?, reject_details=?, updated_at=? WHERE id=?",
            (body.reason, body.details, now, job_id),
        )
        db.commit()
        return MessageResponse(message=f"Job {job_id} rejected: {body.reason}")
    finally:
        db.close()


@router.post("/{job_id}/skip", response_model=MessageResponse)
def skip_job(job_id: int):
    """Skip a job — removes it from the active queue (sets status to 'skipped')."""
    db = get_connection()
    try:
        row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "UPDATE jobs SET status='skipped', reject_reason=NULL, updated_at=? WHERE id=?",
            (now, job_id),
        )
        db.commit()
        return MessageResponse(message=f"Job {job_id} skipped")
    finally:
        db.close()


@router.get("/{job_id}/cross-ref", response_model=dict)
def check_cross_ref(job_id: int):
    """Check a job against the job-search repo."""
    from seeker_os.config import Settings
    from seeker_os.crossref.jobsearch_repo import check_cross_reference

    db = get_connection()
    try:
        row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

        settings = Settings()
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
