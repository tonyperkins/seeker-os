"""Jobs repository — DB access, row converters, and query builders."""

from __future__ import annotations

from datetime import UTC, datetime

from seeker_os.api.schemas import (
    ApplicationEvent,
    JobDetail,
    JobSummary,
    RecruiterContact,
    RecruiterSearchResult,
)
from seeker_os.database import json_decode
from seeker_os.events import (
    MANUAL_EVENT_TYPES,
    STALE_ACTIVITY_EVENTS,
    Actor,
    EventType,
    JobStatus,
    compute_stale_flag,
)

# ---------------------------------------------------------------------------
# Stale-flag computation
# ---------------------------------------------------------------------------

def get_stale_after_days() -> int:
    """Get stale_after_days from lifecycle config (default 14)."""
    try:
        from seeker_os.config import get_settings
        return get_settings().lifecycle.stale_after_days
    except Exception:
        return 14


def compute_stale(db, row, stale_after_days: int | None = None) -> tuple[bool, int | None]:
    """Compute stale flag for a job row."""
    if stale_after_days is None:
        stale_after_days = get_stale_after_days()
    return compute_stale_flag(db, row["id"], row["status"], stale_after_days)


def batch_compute_stale(
    db, rows, stale_after_days: int,
) -> dict[int, tuple[bool, int | None]]:
    """Batch-compute stale flags for a set of job rows in ONE query.

    Returns {job_id: (is_stale, days_since)} for applied/engaged jobs only.
    Jobs in other statuses are excluded (their stale flag is always (False, None)).
    """
    ae_ids = [
        r["id"] for r in rows
        if r["status"] in (JobStatus.APPLIED, JobStatus.ENGAGED)
    ]
    if not ae_ids:
        return {}

    placeholders = ",".join("?" * len(ae_ids))
    event_ph = ",".join("?" * len(STALE_ACTIVITY_EVENTS))
    stale_rows = db.execute(
        f"SELECT job_id, MAX(occurred_at) as last_activity "
        f"FROM application_events "
        f"WHERE job_id IN ({placeholders}) AND event_type IN ({event_ph}) "
        f"GROUP BY job_id",
        (*ae_ids, *STALE_ACTIVITY_EVENTS),
    ).fetchall()

    now = datetime.now(UTC)
    result: dict[int, tuple[bool, int | None]] = {}
    for sr in stale_rows:
        try:
            last_dt = datetime.fromisoformat(sr["last_activity"])
        except (ValueError, TypeError):
            continue
        delta = now - last_dt
        days_since = delta.days
        is_stale = days_since > stale_after_days
        result[sr["job_id"]] = (is_stale, days_since)

    for jid in ae_ids:
        if jid not in result:
            result[jid] = (False, None)

    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_iso(s: str) -> datetime | None:
    """Parse an ISO datetime string; return None on failure."""
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Row-to-model converters
# ---------------------------------------------------------------------------

def row_to_recruiter(row) -> RecruiterContact:
    return RecruiterContact(
        id=row["id"],
        recruiter_id=row["recruiter_id"],
        job_id=row["job_id"],
        name=row["name"],
        email=row["email"],
        phone=row["phone"],
        linkedin=row["linkedin"],
        agency=row["agency"],
        source=row["source"],
        contacted_at=row["contacted_at"],
        notes=row["notes"],
        created_at=row["created_at"] or "",
        updated_at=row["updated_at"] or "",
    )


def row_to_summary(
    row, db=None, *, stale_after_days: int | None = None,
    stale_result: tuple[bool, int | None] | None = None,
    indicator_flags: tuple[bool, bool, bool] | None = None,
    recruiter_flag: tuple[bool, str | None] | None = None,
) -> JobSummary:
    is_stale = False
    days_since = None
    if stale_result is not None:
        is_stale, days_since = stale_result
    elif db is not None:
        is_stale, days_since = compute_stale(db, row, stale_after_days=stale_after_days)
    has_analysis, has_research, has_resume = indicator_flags or (False, False, False)
    has_recruiter, recruiter_source = recruiter_flag or (False, None)
    return JobSummary(
        id=row["id"],
        title=row["title"] or "",
        company=row["company"] or "",
        score=row["score"],
        status=row["status"],
        tier_passed=row["tier_passed"],
        comp_min=row["comp_min"],
        comp_max=row["comp_max"],
        comp_source=row["comp_source"] if "comp_source" in row.keys() else None,
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
        reject_details=row["reject_details"] if "reject_details" in row.keys() else None,
        source_id=row["source_id"] or "",
        discovered_query=row["discovered_query"] or "",
        run_id=row["run_id"] if "run_id" in row.keys() else None,
        preference_rank=row["preference_rank"] if "preference_rank" in row.keys() else None,
        is_stale=is_stale,
        days_since_last_activity=days_since,
        has_analysis=has_analysis,
        has_research=has_research,
        has_resume=has_resume,
        analysis_verdict=row["analysis_verdict"] if "analysis_verdict" in row.keys() else None,
        net_score=row["net_score"] if "net_score" in row.keys() else None,
        ai_policy=row["ai_policy"] if "ai_policy" in row.keys() else None,
        score_modifiers=json_decode(row["score_modifiers"]) if "score_modifiers" in row.keys() and row["score_modifiers"] else {},
        score_reasons=json_decode(row["score_reasons"]) if "score_reasons" in row.keys() and row["score_reasons"] else [],
        has_recruiter=has_recruiter,
        recruiter_source=recruiter_source,
    )


def row_to_event(row) -> ApplicationEvent:
    return ApplicationEvent(
        id=row["id"],
        job_id=row["job_id"],
        event_type=row["event_type"],
        actor=row["actor"],
        occurred_at=row["occurred_at"],
        created_at=row["created_at"],
        metadata=json_decode(row["metadata"]) if row["metadata"] else None,
        note=row["note"],
        is_mutable=(
            bool(row["is_mutable"])
            if "is_mutable" in row.keys()
            else row["event_type"] in MANUAL_EVENT_TYPES
        ),
    )


def row_to_detail(row, db=None) -> JobDetail:
    events: list[ApplicationEvent] = []
    recruiters: list[RecruiterContact] = []
    is_stale = False
    days_since = None
    if db is not None:
        event_rows = db.execute(
            """
            SELECT e.*,
                   CASE
                     WHEN e.event_type IN ('note', 'call', 'email_sent', 'email_received', 'meeting', 'interview')
                      AND NOT EXISTS (
                          SELECT 1 FROM inbound_messages i WHERE i.confirmed_event_id = e.id
                      ) THEN 1 ELSE 0
                   END AS is_mutable
            FROM application_events e
            WHERE e.job_id = ?
            ORDER BY e.occurred_at ASC, e.id ASC
            """,
            (row["id"],),
        ).fetchall()
        events = [row_to_event(r) for r in event_rows]
        recruiter_rows = db.execute(
            """
            SELECT rjc.id, rjc.recruiter_id, rjc.job_id, rjc.source,
                   rjc.contacted_at, rjc.notes, rjc.created_at, rjc.updated_at,
                   r.name, r.email, r.phone, r.linkedin, r.agency
            FROM recruiter_job_contacts rjc
            JOIN recruiters r ON rjc.recruiter_id = r.id
            WHERE rjc.job_id = ? ORDER BY rjc.id ASC
            """,
            (row["id"],),
        ).fetchall()
        recruiters = [row_to_recruiter(r) for r in recruiter_rows]
        is_stale, days_since = compute_stale(db, row)
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
        comp_source=row["comp_source"] if "comp_source" in row.keys() else None,
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
        ai_policy=row["ai_policy"] if "ai_policy" in row.keys() else None,
        preference_rank=row["preference_rank"] if "preference_rank" in row.keys() else None,
        research_adjusted_score=row["research_adjusted_score"] if "research_adjusted_score" in row.keys() else None,
        research_delta=row["research_delta"] if "research_delta" in row.keys() else 0.0,
        analysis_verdict=row["analysis_verdict"] if "analysis_verdict" in row.keys() else None,
        analysis_delta=row["analysis_delta"] if "analysis_delta" in row.keys() else 0.0,
        net_score=row["net_score"] if "net_score" in row.keys() else None,
        filter_warnings=json_decode(row["filter_warnings"]) if "filter_warnings" in row.keys() and row["filter_warnings"] else [],
        overridden_at=row["overridden_at"] if "overridden_at" in row.keys() else None,
        override_note=row["override_note"] if "override_note" in row.keys() else None,
        original_reject_reason=row["original_reject_reason"] if "original_reject_reason" in row.keys() else None,
        events=events,
        recruiter_contacts=recruiters,
        is_stale=is_stale,
        days_since_last_activity=days_since,
    )


# ---------------------------------------------------------------------------
# Sort whitelist
# ---------------------------------------------------------------------------

JOB_SORT_EXPRESSIONS: dict[str, str] = {
    "score": "COALESCE(net_score, score)",
    "net_score": "COALESCE(net_score, score)",
    "status": "LOWER(COALESCE(status, ''))",
    "run_id": "LOWER(COALESCE(run_id, ''))",
    "title": "LOWER(COALESCE(title, ''))",
    "company": "LOWER(COALESCE(company, ''))",
    "comp": "COALESCE(comp_min, comp_max)",
    "location": "LOWER(COALESCE(location, ''))",
    "ats": "LOWER(COALESCE(ats_source, ''))",
    "preference": "COALESCE(preference_rank, 999999)",
}


# ---------------------------------------------------------------------------
# Recruiter SQL
# ---------------------------------------------------------------------------

RECRUITER_JOIN_SQL = """
    SELECT rjc.id, rjc.recruiter_id, rjc.job_id, rjc.source,
           rjc.contacted_at, rjc.notes, rjc.created_at, rjc.updated_at,
           r.name, r.email, r.phone, r.linkedin, r.agency
    FROM recruiter_job_contacts rjc
    JOIN recruiters r ON rjc.recruiter_id = r.id
"""


# ---------------------------------------------------------------------------
# Transition maps
# ---------------------------------------------------------------------------

TRANSITION_MAP: dict[str, tuple[str, str]] = {
    JobStatus.APPLIED: (EventType.APPLIED, Actor.CANDIDATE),
    JobStatus.COMPANY_REJECTED: (EventType.COMPANY_REJECTED, Actor.COMPANY),
    JobStatus.WITHDRAWN: (EventType.WITHDRAWN, Actor.CANDIDATE),
    JobStatus.ENGAGED: (EventType.ENGAGED, Actor.CANDIDATE),
    JobStatus.OFFER_ACCEPTED: (EventType.OFFER_ACCEPTED, Actor.CANDIDATE),
    JobStatus.OFFER_DECLINED: (EventType.OFFER_DECLINED, Actor.CANDIDATE),
}

VALID_TRANSITIONS: dict[str, frozenset[str]] = {
    JobStatus.APPLIED: frozenset({JobStatus.COMPANY_REJECTED, JobStatus.WITHDRAWN, JobStatus.ENGAGED}),
    JobStatus.ENGAGED: frozenset({
        JobStatus.OFFER_ACCEPTED, JobStatus.OFFER_DECLINED,
        JobStatus.COMPANY_REJECTED, JobStatus.WITHDRAWN,
    }),
}


# ---------------------------------------------------------------------------
# Query functions
# ---------------------------------------------------------------------------

def fetch_job_by_id(db, job_id: int):
    """Fetch a single job row by ID or return None."""
    return db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()


def fetch_job_events(db, job_id: int) -> list:
    """Fetch all events for a job ordered by occurred_at."""
    return db.execute(
        "SELECT * FROM application_events WHERE job_id = ? ORDER BY occurred_at ASC, id ASC",
        (job_id,),
    ).fetchall()


def fetch_recruiter_contacts_for_job(db, job_id: int) -> list:
    """Fetch all recruiter contacts for a job."""
    return db.execute(
        f"{RECRUITER_JOIN_SQL} WHERE rjc.job_id = ? ORDER BY rjc.id ASC",
        (job_id,),
    ).fetchall()


def batch_indicator_flags(db, job_ids: list[int]) -> tuple[set, set, set, dict[int, str | None]]:
    """Batch-compute analysis/research/resume/recruiter indicator flags.

    Returns (analysis_ids, research_ids, resume_ids, recruiter_map).
    """
    analysis_ids: set[int] = set()
    research_ids: set[int] = set()
    resume_ids: set[int] = set()
    recruiter_map: dict[int, str | None] = {}

    if not job_ids:
        return analysis_ids, research_ids, resume_ids, recruiter_map

    placeholders = ",".join("?" * len(job_ids))
    analysis_rows = db.execute(
        f"SELECT DISTINCT job_id FROM job_analyses WHERE job_id IN ({placeholders})",
        job_ids,
    ).fetchall()
    analysis_ids = {r["job_id"] for r in analysis_rows}

    research_rows = db.execute(
        f"""
        SELECT DISTINCT j.id AS job_id
        FROM jobs j
        INNER JOIN company_research cr ON cr.company_norm = j.company_norm
        WHERE j.id IN ({placeholders})
        """,
        job_ids,
    ).fetchall()
    research_ids = {r["job_id"] for r in research_rows}

    resume_rows = db.execute(
        f"SELECT DISTINCT job_id FROM resumes WHERE job_id IN ({placeholders})",
        job_ids,
    ).fetchall()
    resume_ids = {r["job_id"] for r in resume_rows}

    recruiter_rows = db.execute(
        f"SELECT job_id, source FROM recruiter_job_contacts WHERE job_id IN ({placeholders})",
        job_ids,
    ).fetchall()
    for r in recruiter_rows:
        if r["job_id"] not in recruiter_map:
            recruiter_map[r["job_id"]] = r["source"]

    return analysis_ids, research_ids, resume_ids, recruiter_map


def search_recruiters(db, q: str) -> list[RecruiterSearchResult]:
    """Search recruiters by name or email for autocomplete."""
    if not q.strip():
        return []
    pat = f"%{q.strip()}%"
    rows = db.execute(
        """
        SELECT r.id, r.name, r.email, r.phone, r.linkedin, r.agency,
               COUNT(rjc.id) AS job_count
        FROM recruiters r
        LEFT JOIN recruiter_job_contacts rjc ON rjc.recruiter_id = r.id
        WHERE r.name LIKE ? OR r.email LIKE ?
        GROUP BY r.id
        ORDER BY r.name ASC
        LIMIT 20
        """,
        (pat, pat),
    ).fetchall()
    return [
        RecruiterSearchResult(
            id=r["id"],
            name=r["name"],
            email=r["email"],
            phone=r["phone"],
            linkedin=r["linkedin"],
            agency=r["agency"],
            job_count=r["job_count"],
        )
        for r in rows
    ]


def list_no_reason_skips(db) -> list:
    """List skipped/rejected jobs whose most recent candidate skip/rejected event
    has no reason in its metadata.
    """
    from seeker_os.events import Actor, EventType
    rows = db.execute(
        """
        SELECT j.id, j.title, j.company, j.status,
               e.id AS event_id, e.event_type, e.occurred_at, e.metadata
        FROM jobs j
        JOIN application_events e ON e.job_id = j.id
        WHERE e.actor = ?
          AND e.event_type IN (?, ?)
          AND e.id = (
              SELECT MAX(e2.id) FROM application_events e2
              WHERE e2.job_id = j.id
                AND e2.actor = ?
                AND e2.event_type IN (?, ?)
          )
          AND (e.metadata IS NULL
               OR json_extract(e.metadata, '$.reason') IS NULL
               OR json_extract(e.metadata, '$.reason') = '')
        ORDER BY e.occurred_at DESC
        """,
        (
            Actor.CANDIDATE, EventType.SKIPPED, EventType.REJECTED,
            Actor.CANDIDATE, EventType.SKIPPED, EventType.REJECTED,
        ),
    ).fetchall()
    return rows
