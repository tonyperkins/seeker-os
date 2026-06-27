"""Jobs API routes."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from seeker_os.api.schemas import (
    JobSummary, JobDetail, JobUpdate, JobReject, JobCreate, JobCreateResponse,
    JobOverride, MessageResponse, ApplicationEvent, ApplicationEventCreate,
    PostApplyTransition, EngagedEventCreate, CleanStartCreate,
)
from seeker_os.database import get_connection, json_decode, json_encode
from seeker_os.events import (
    record_event, transition_status, EventType, Actor,
    JobStatus, EngagedEventType, compute_stale_flag,
    STALE_ACTIVITY_EVENTS,
)

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _get_stale_after_days() -> int:
    """Get stale_after_days from lifecycle config (default 14)."""
    try:
        from seeker_os.config import get_settings
        return get_settings().lifecycle.stale_after_days
    except Exception:
        return 14


def _compute_stale(db, row, stale_after_days: int | None = None) -> tuple[bool, int | None]:
    """Compute stale flag for a job row."""
    if stale_after_days is None:
        stale_after_days = _get_stale_after_days()
    return compute_stale_flag(db, row["id"], row["status"], stale_after_days)


def _batch_compute_stale(
    db, rows, stale_after_days: int,
) -> dict[int, tuple[bool, int | None]]:
    """Batch-compute stale flags for a set of job rows in ONE query.

    Returns {job_id: (is_stale, days_since)} for applied/engaged jobs only.
    Jobs in other statuses are excluded (their stale flag is always (False, None)).
    """
    from datetime import datetime as _dt, timezone as _tz

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

    now = _dt.now(_tz.utc)
    result: dict[int, tuple[bool, int | None]] = {}
    for sr in stale_rows:
        try:
            last_dt = _dt.fromisoformat(sr["last_activity"])
        except (ValueError, TypeError):
            continue
        delta = now - last_dt
        days_since = delta.days
        is_stale = days_since > stale_after_days
        result[sr["job_id"]] = (is_stale, days_since)

    # Jobs in applied/engaged with no activity events → not stale (no activity to be stale about)
    for jid in ae_ids:
        if jid not in result:
            result[jid] = (False, None)

    return result


def _parse_iso(s: str) -> datetime | None:
    """Parse an ISO datetime string; return None on failure."""
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _try_apply_research_adjustment(db, job_id: int, company: str) -> None:
    """Check for a cached company dossier and apply research adjustment if available.

    Reuses the same compute_research_adjustment path as the pipeline and the
    company-research API endpoint. This is a cache-hit-only check — it does
    NOT trigger new research. If no cached dossier exists, this is a no-op.
    """
    if not company:
        return

    from seeker_os.dedup.normalize import normalize_company
    from seeker_os.scoring.research_adjustment import (
        ResearchModifierRule,
        compute_research_adjustment,
    )
    from seeker_os.api.company_research import _reconstruct_dossier_from_row, _find_fresh_dossier

    company_norm = normalize_company(company)
    if not company_norm:
        return

    try:
        from seeker_os.config import Settings
        settings = Settings()
        if not settings.scoring or not settings.scoring.research_modifiers:
            return
        ttl_days = settings.company_research.research_ttl_days if settings.company_research else 30
        confidence_floor = settings.company_research.confidence_floor if settings.company_research else 0.3
    except Exception:
        return

    cached_row, _ = _find_fresh_dossier(db, company_norm, ttl_days)
    if not cached_row:
        return

    dossier = _reconstruct_dossier_from_row(cached_row, confidence_floor)

    # Check that the job has a base score to adjust
    job = db.execute("SELECT score FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not job or job["score"] is None:
        return

    rules = [
        ResearchModifierRule(
            factor=rm.factor,
            delta=rm.delta,
            confidence_threshold=rm.confidence_threshold,
            source_section=rm.source_section,
        )
        for rm in settings.scoring.research_modifiers
    ]

    result = compute_research_adjustment(
        base_score=float(job["score"]),
        dossier=dossier,
        rules=rules,
        max_score=settings.scoring.max_score,
        min_score=settings.scoring.min_score,
    )

    # Recompute net_score since research_delta changed
    from seeker_os.scoring.net_score import compute_net_score
    job_row = db.execute(
        "SELECT analysis_verdict FROM jobs WHERE id = ?", (job_id,)
    ).fetchone()
    analysis_verdict = job_row["analysis_verdict"] if job_row else None
    verdict_caps = settings.scoring.verdict_caps if settings.scoring else {}
    net = compute_net_score(
        base_score=float(job["score"]),
        research_delta=result.research_delta,
        analysis_verdict=analysis_verdict,
        verdict_caps=verdict_caps,
        max_score=settings.scoring.max_score,
        min_score=settings.scoring.min_score,
    )

    db.execute(
        """UPDATE jobs
           SET research_adjusted_score = ?,
               research_delta = ?,
               research_breakdown = ?,
               net_score = ?,
               updated_at = ?
           WHERE id = ?""",
        (
            result.adjusted_score,
            result.research_delta,
            json_encode([item.model_dump() for item in result.breakdown]),
            net,
            datetime.now(timezone.utc).isoformat(),
            job_id,
        ),
    )


def _row_to_summary(
    row, db=None, *, stale_after_days: int | None = None,
    stale_result: tuple[bool, int | None] | None = None,
    indicator_flags: tuple[bool, bool, bool] | None = None,
) -> JobSummary:
    is_stale = False
    days_since = None
    if stale_result is not None:
        is_stale, days_since = stale_result
    elif db is not None:
        is_stale, days_since = _compute_stale(db, row, stale_after_days=stale_after_days)
    has_analysis, has_research, has_resume = indicator_flags or (False, False, False)
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
        reject_details=row["reject_details"] if "reject_details" in row.keys() else None,
        source_id=row["source_id"] or "",
        discovered_query=row["discovered_query"] or "",
        run_id=row["run_id"] if "run_id" in row.keys() else None,
        is_stale=is_stale,
        days_since_last_activity=days_since,
        has_analysis=has_analysis,
        has_research=has_research,
        has_resume=has_resume,
        analysis_verdict=row["analysis_verdict"] if "analysis_verdict" in row.keys() else None,
    )


def _row_to_event(row) -> ApplicationEvent:
    return ApplicationEvent(
        id=row["id"],
        job_id=row["job_id"],
        event_type=row["event_type"],
        actor=row["actor"],
        occurred_at=row["occurred_at"],
        created_at=row["created_at"],
        metadata=json_decode(row["metadata"]) if row["metadata"] else None,
        note=row["note"],
    )


def _row_to_detail(row, db=None) -> JobDetail:
    events: list[ApplicationEvent] = []
    is_stale = False
    days_since = None
    if db is not None:
        event_rows = db.execute(
            "SELECT * FROM application_events WHERE job_id = ? ORDER BY occurred_at ASC, id ASC",
            (row["id"],),
        ).fetchall()
        events = [_row_to_event(r) for r in event_rows]
        is_stale, days_since = _compute_stale(db, row)
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
        ai_policy=row["ai_policy"] if "ai_policy" in row.keys() else None,
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
        is_stale=is_stale,
        days_since_last_activity=days_since,
    )


@router.get("", response_model=list[JobSummary])
def list_jobs(
    status: str | None = Query(None, description="Filter by status"),
    min_score: float | None = Query(None, description="Minimum score"),
    min_tier: int | None = Query(None, description="Minimum tier_passed (e.g. 4 for scored)"),
    company: str | None = Query(None, description="Filter by company (substring)"),
    search: str | None = Query(None, description="Free-text search across title, company, location, reject_reason, discovered_query"),
    source: str | None = Query(None, description="Filter by source_id (e.g. 'manual', 'hiring_cafe')"),
    run_id: str | None = Query(None, description="Filter by pipeline run_id"),
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
            query += " AND (title LIKE ? OR company LIKE ? OR location LIKE ? OR reject_reason LIKE ? OR discovered_query LIKE ? OR run_id LIKE ?)"
            pat = f"%{search}%"
            params.extend([pat, pat, pat, pat, pat, pat])
        if source:
            query += " AND source_id = ?"
            params.append(source)
        if run_id:
            query += " AND run_id LIKE ?"
            params.append(f"%{run_id}%")

        query += " ORDER BY"
        if status == "ready":
            query += " score DESC,"
        query += " discovered_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = db.execute(query, params).fetchall()

        # Batch stale-flag computation: one aggregate query for all applied/engaged jobs
        stale_after_days = _get_stale_after_days()
        stale_map = _batch_compute_stale(db, rows, stale_after_days)

        # Batch indicator-flag computation: one query per table for all job IDs
        job_ids = [r["id"] for r in rows]
        analysis_ids = set()
        research_ids = set()
        resume_ids = set()
        if job_ids:
            placeholders = ",".join("?" * len(job_ids))
            analysis_rows = db.execute(
                f"SELECT DISTINCT job_id FROM job_analyses WHERE job_id IN ({placeholders})",
                job_ids,
            ).fetchall()
            analysis_ids = {r["job_id"] for r in analysis_rows}
            research_rows = db.execute(
                f"SELECT DISTINCT job_id FROM company_research WHERE job_id IN ({placeholders})",
                job_ids,
            ).fetchall()
            research_ids = {r["job_id"] for r in research_rows}
            resume_rows = db.execute(
                f"SELECT DISTINCT job_id FROM resumes WHERE job_id IN ({placeholders})",
                job_ids,
            ).fetchall()
            resume_ids = {r["job_id"] for r in resume_rows}

        return [
            _row_to_summary(
                r, db=db, stale_after_days=stale_after_days,
                stale_result=stale_map.get(r["id"]),
                indicator_flags=(
                    r["id"] in analysis_ids,
                    r["id"] in research_ids,
                    r["id"] in resume_ids,
                ),
            )
            for r in rows
        ]
    finally:
        db.close()


@router.post("", response_model=JobCreateResponse)
def create_job(body: JobCreate):
    """Manually add a job.

    Flow (validate-then-insert — no partial records):
    1. Compute url_hash, check dedup layer 1 (url_hash). If match → already_exists.
    2. If jd_text provided (paste-JD path), use it directly. Otherwise attempt
       fetch_jd from the URL. If fetch fails → return fetch_failed (no insert).
    3. After JD is available, check content hash dedup (layer 3). If match and
       force=False → return possible_duplicate (NO insert). If force=True →
       proceed with insert (likely_duplicate warning).
    4. Insert complete job with JD, run hard filters as informational metadata
       (manual jobs bypass filter rejection — DECISION 1), run scoring, and
       apply research adjustment from cached company dossier if available.
    5. Manual jobs always land in 'ready' regardless of score — the user
       decides (DECISION 1).
    """
    from seeker_os.dedup.layers import url_hash, check_content_duplicate, register_content_hash
    from seeker_os.dedup.normalize import normalize_title, normalize_company
    from seeker_os.discovery.ats_fetch import fetch_jd, parse_greenhouse_url, fetch_greenhouse_job, _strip_html as _strip_html_safe
    from seeker_os.filtering.hard_filters import apply_filters
    from seeker_os.scoring.engine import score_job
    from seeker_os.models import JobCard
    from seeker_os.config import Settings

    uh = url_hash(body.url)

    db = get_connection()
    try:
        # Step 1: Dedup layer 1 — url_hash
        existing = db.execute("SELECT id FROM jobs WHERE url_hash = ?", (uh,)).fetchone()
        if existing:
            return JobCreateResponse(status="already_exists", existing_job_id=existing["id"])

        # Step 2: Get JD text
        # Structured metadata extracted from ATS API (if available)
        gh_title = None
        gh_location = None
        gh_comp_min = None
        gh_comp_max = None
        gh_workplace_type = None
        ats_source = None
        ats_board_token = None
        ats_job_id = None

        if body.jd_text and body.jd_text.strip():
            jd_text = body.jd_text.strip()
        else:
            # Attempt fetch from URL
            settings = Settings()
            user_agent = "Mozilla/5.0"
            if settings.sources:
                for src in settings.sources.sources:
                    if src.enabled:
                        user_agent = src.user_agent
                        break

            # Try Greenhouse API first for structured metadata
            gh_parsed = parse_greenhouse_url(body.url)
            gh_data = None
            if gh_parsed:
                gh_board, gh_job_id = gh_parsed
                try:
                    gh_data = fetch_greenhouse_job(gh_board, gh_job_id, user_agent)
                    # Extract JD text
                    content = gh_data.get("content", "") or gh_data.get("first_content", "")
                    jd_text = _strip_html_safe(content) if content else ""
                    if not jd_text or len(jd_text) < 100:
                        # Fall through to generic fetch_jd
                        gh_data = None
                    else:
                        # Extract structured metadata
                        gh_title = gh_data.get("title")
                        loc_obj = gh_data.get("location", {})
                        if isinstance(loc_obj, dict):
                            gh_location = loc_obj.get("name", "")
                        elif isinstance(loc_obj, str):
                            gh_location = loc_obj

                        # Compensation
                        comp = gh_data.get("compensation")
                        if comp and isinstance(comp, dict):
                            ranges = comp.get("salary_ranges", [])
                            if ranges:
                                first = ranges[0]
                                gh_comp_min = first.get("min")
                                gh_comp_max = first.get("max")

                        # Metadata fields (custom ATS fields)
                        metadata = gh_data.get("metadata", [])
                        if isinstance(metadata, list):
                            for m in metadata:
                                if not isinstance(m, dict):
                                    continue
                                name = (m.get("name") or "").lower()
                                value = m.get("value")
                                if not value:
                                    continue
                                value_str = str(value).strip()
                                if "remote" in name or "workplace" in name:
                                    if "remote" in value_str.lower():
                                        gh_workplace_type = "Remote"
                                    elif "hybrid" in value_str.lower():
                                        gh_workplace_type = "Hybrid"
                                    elif "onsite" in value_str.lower() or "on-site" in value_str.lower() or "office" in value_str.lower():
                                        gh_workplace_type = "On-Site"

                        # Set ats_source for the INSERT and fallback fetch
                        ats_source = "greenhouse"
                        ats_board_token = gh_board
                        ats_job_id = gh_job_id
                except Exception:
                    gh_data = None

            # If Greenhouse API didn't work, fall back to generic fetch_jd
            if not gh_data:
                jd_result = fetch_jd(
                    job_id=0,  # no job yet — validate-then-insert
                    ats_source=ats_source,
                    ats_board_token=ats_board_token,
                    ats_job_id=ats_job_id,
                    apply_url=body.url,
                    user_agent=user_agent,
                    delay=0,  # no delay for manual single fetch
                )
                if jd_result.status != "fetched" or not jd_result.jd_text or len(jd_result.jd_text) < 100:
                    return JobCreateResponse(
                        status="fetch_failed",
                        fetch_error=jd_result.error or "JD fetch returned insufficient content",
                    )
                jd_text = jd_result.jd_text

        # Step 3: Content hash dedup check (ask before inserting — D3)
        content_dedup = check_content_duplicate(0, jd_text, db)
        # check_content_duplicate queries by job_id != 0, which matches all existing
        likely_dup_id = None
        if content_dedup.is_duplicate:
            if not body.force:
                # Soft match — ask the user before inserting
                ex_row = db.execute(
                    "SELECT title, company FROM jobs WHERE id = ?",
                    (content_dedup.matched_job_id,),
                ).fetchone()
                ex_title = ex_row["title"] if ex_row else "Unknown"
                ex_company = ex_row["company"] if ex_row else "Unknown"
                return JobCreateResponse(
                    status="possible_duplicate",
                    existing_job_id=content_dedup.matched_job_id,
                    existing_summary=f"{ex_title} at {ex_company}",
                )
            # force=True — proceed with insert, flag as likely_duplicate
            likely_dup_id = content_dedup.matched_job_id

        # Step 4: Insert complete job
        now = datetime.now(timezone.utc).isoformat()
        source_job_id = f"manual___{uh[:12]}"

        settings = Settings()
        source_map = {}
        if settings.sources:
            for src in settings.sources.sources:
                if src.enabled and src.source_map:
                    source_map = src.source_map
                    break

        # LLM fallback: extract structured metadata from JD text when ATS API
        # didn't provide it. Uses the light tier for low cost/latency.
        if settings.providers:
            from seeker_os.analysis.metadata_extractor import extract_metadata_from_jd
            extracted = extract_metadata_from_jd(
                jd_text=jd_text,
                title=body.title or gh_title or "",
                location=body.location or gh_location or "",
                settings=settings,
            )
            if not gh_workplace_type and not body.workplace_type:
                gh_workplace_type = extracted.workplace_type
            if not gh_comp_min and not body.comp_min:
                gh_comp_min = extracted.comp_min
            if not gh_comp_max and not body.comp_max:
                gh_comp_max = extracted.comp_max
            if not body.seniority_level:
                body_seniority_extracted = extracted.seniority_level
            else:
                body_seniority_extracted = None
            gh_role_type = extracted.role_type
            gh_commitment = extracted.commitment
            gh_countries = extracted.countries or []
            gh_company = extracted.company
        else:
            body_seniority_extracted = None
            gh_role_type = None
            gh_commitment = None
            gh_countries = []
            gh_company = None

        # Fallback: infer company from Greenhouse board token (e.g. "chainguard" → "Chainguard")
        if not gh_company and not body.company and gh_parsed:
            gh_company = gh_parsed[0].replace("-", " ").replace("_", " ").title()

        # Use Greenhouse metadata as fallback when user didn't provide values
        eff_title = body.title or gh_title or ""
        eff_company = body.company or gh_company or ""
        eff_location = body.location or gh_location or ""
        eff_workplace = body.workplace_type or gh_workplace_type or ""
        eff_comp_min = body.comp_min if body.comp_min is not None else gh_comp_min
        eff_comp_max = body.comp_max if body.comp_max is not None else gh_comp_max
        eff_seniority = body.seniority_level or body_seniority_extracted
        eff_role_type = gh_role_type
        eff_commitment = gh_commitment
        eff_countries = gh_countries

        # Build JobCard for filter check
        card = JobCard(
            source_id="manual",
            source_job_id=source_job_id,
            apply_url=body.url,
            title=eff_title,
            core_title=eff_title,
            company=eff_company,
            company_homepage=body.company_homepage,
            location=eff_location,
            workplace_type=eff_workplace,
            seniority_level=eff_seniority,
            comp_min=eff_comp_min,
            comp_max=eff_comp_max,
            comp_currency=body.comp_currency,
            date_posted=now,
            discovered_query="manual",
        )

        # Run hard filters as informational metadata (DECISION 1: bypass, record warnings)
        # Skip title pattern filter for manual jobs — the user explicitly chose to add
        # this job, so title matching is irrelevant. Pass empty title filters so the
        # title check passes through and remaining filters (comp, blacklist, etc.) can
        # still run and collect meaningful warnings.
        filter_warnings: list[str] = []
        if settings.profile and settings.filters:
            from seeker_os.config import TitleFilters as _TF
            manual_title_filters = _TF(positive=[], negative=[])
            filter_result = apply_filters(
                card, settings.profile, settings.filters.filters, manual_title_filters,
            )
            if not filter_result.passed:
                filter_warnings.append(filter_result.reason)

        # Run scoring (same entry point as pipeline)
        score_result = score_job(
            title=eff_title,
            jd_text=jd_text,
            location=eff_location,
            company=eff_company,
            rubric=settings.scoring,
            profile=settings.profile,
            comp_min=eff_comp_min,
            comp_max=eff_comp_max,
            workplace_type=eff_workplace,
            seniority_level=eff_seniority,
        )

        # Insert — manual jobs always go to 'ready' (DECISION 1)
        cursor = db.execute(
            """
            INSERT INTO jobs (
                source_id, source_job_id, ats_source, ats_board_token, ats_job_id,
                apply_url, url_hash,
                title, core_title, company, company_homepage,
                location, workplace_type, workplace_countries, seniority_level,
                commitment, comp_min, comp_max, comp_currency,
                technical_tools, requirements_summary, date_posted, role_type,
                status, tier_passed, score, score_reasons, score_gaps,
                jd_full, jd_fetch_status,
                discovered_at, discovered_query, updated_at, is_pinned,
                filter_warnings
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ready', 4, ?, ?, ?, ?, 'fetched', ?, 'manual', ?, 0, ?)
            """,
            (
                "manual", source_job_id,
                ats_source, ats_board_token, ats_job_id,
                body.url, uh,
                eff_title, eff_title, eff_company, body.company_homepage,
                eff_location, eff_workplace, json_encode(eff_countries), eff_seniority,
                json_encode([eff_commitment] if eff_commitment else []), eff_comp_min, eff_comp_max, body.comp_currency,
                json_encode([]), "", now, eff_role_type,
                score_result.score,
                json_encode(score_result.reasons),
                json_encode(score_result.gaps),
                jd_text,
                now, now,
                json_encode(filter_warnings) if filter_warnings else None,
            ),
        )
        job_id = cursor.lastrowid

        # Register dedup keys
        db.execute(
            "UPDATE jobs SET title_norm=?, company_norm=? WHERE id=?",
            (normalize_title(eff_title), normalize_company(eff_company), job_id),
        )
        register_content_hash(job_id, jd_text, db)

        # Apply research adjustment from cached company dossier (if any)
        _try_apply_research_adjustment(db, job_id, eff_company)

        # Record the manual_created event
        record_event(
            db, job_id, EventType.MANUAL_CREATED, Actor.CANDIDATE,
            metadata={"score": score_result.score},
        )

        db.commit()

        row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        response_status = "likely_duplicate" if likely_dup_id else "created"
        return JobCreateResponse(
            status=response_status,
            job=_row_to_detail(row, db=db),
            existing_job_id=likely_dup_id,
            filter_warnings=filter_warnings,
        )
    finally:
        db.close()


@router.post("/{job_id}/override", response_model=MessageResponse)
def override_job(job_id: int, body: JobOverride):
    """Override a rejected job — auditable, not a silent status flip.

    Records overridden_at, override_note, and preserves the original reject_reason
    in original_reject_reason. Sets status to target_status (default 'ready').
    The score and all other signals remain visible — this layers on top, never
    overwrites (DECISION 4).
    """
    db = get_connection()
    try:
        row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

        if row["status"] != "rejected":
            raise HTTPException(status_code=400, detail=f"Job {job_id} is not rejected (status={row['status']})")

        valid_targets = {"ready", "interested"}
        if body.target_status not in valid_targets:
            raise HTTPException(status_code=422, detail=f"target_status must be one of: {', '.join(valid_targets)}")

        now = datetime.now(timezone.utc).isoformat()
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
        row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        return _row_to_detail(row, db=db)
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
            old_status = row["status"]
            transition_status(
                db, job_id, update.status, EventType.STATUS_CHANGED, Actor.CANDIDATE,
                metadata={"from": old_status, "to": update.status},
            )
        if update.is_pinned is not None:
            db.execute("UPDATE jobs SET is_pinned=?, updated_at=? WHERE id=?", (update.is_pinned, now, job_id))
        if update.ai_policy is not None:
            valid_policies = {"allowed", "draft_only", "forbidden"}
            if update.ai_policy not in valid_policies:
                raise HTTPException(status_code=422, detail=f"ai_policy must be one of: {', '.join(valid_policies)}")
            db.execute("UPDATE jobs SET ai_policy=?, updated_at=? WHERE id=?", (update.ai_policy, now, job_id))
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
def skip_job(job_id: int):
    """Skip a job — removes it from the active queue (sets status to 'skipped')."""
    db = get_connection()
    try:
        row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

        transition_status(
            db, job_id, "skipped", EventType.SKIPPED, Actor.CANDIDATE,
            extra_sets={"reject_reason": None},
        )
        db.commit()
        return MessageResponse(message=f"Job {job_id} skipped")
    finally:
        db.close()


@router.post("/{job_id}/apply", response_model=MessageResponse)
def apply_to_job(job_id: int):
    """Mark a job as applied — records an APPLIED event with CANDIDATE actor."""
    db = get_connection()
    try:
        row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
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

        rows = db.execute(
            "SELECT * FROM application_events WHERE job_id = ? ORDER BY occurred_at ASC, id ASC",
            (job_id,),
        ).fetchall()
        return [_row_to_event(r) for r in rows]
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
        return _row_to_event(event_row)
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

        for table in ("dedup_registry", "resumes", "company_research",
                       "job_analyses", "cover_letters", "application_answers",
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


# ---------------------------------------------------------------------------
# Post-apply lifecycle endpoints (L2)
# ---------------------------------------------------------------------------

_TRANSITION_MAP: dict[str, tuple[str, str]] = {
    JobStatus.APPLIED: (EventType.APPLIED, Actor.CANDIDATE),
    JobStatus.COMPANY_REJECTED: (EventType.COMPANY_REJECTED, Actor.COMPANY),
    JobStatus.WITHDRAWN: (EventType.WITHDRAWN, Actor.CANDIDATE),
    JobStatus.ENGAGED: (EventType.ENGAGED, Actor.CANDIDATE),
    JobStatus.OFFER_ACCEPTED: (EventType.OFFER_ACCEPTED, Actor.CANDIDATE),
    JobStatus.OFFER_DECLINED: (EventType.OFFER_DECLINED, Actor.CANDIDATE),
}

_VALID_TRANSITIONS: dict[str, frozenset[str]] = {
    JobStatus.APPLIED: frozenset({JobStatus.COMPANY_REJECTED, JobStatus.WITHDRAWN, JobStatus.ENGAGED}),
    JobStatus.ENGAGED: frozenset({
        JobStatus.OFFER_ACCEPTED, JobStatus.OFFER_DECLINED,
        JobStatus.COMPANY_REJECTED, JobStatus.WITHDRAWN,
    }),
}


@router.post("/{job_id}/transition", response_model=MessageResponse)
def post_apply_transition(job_id: int, body: PostApplyTransition):
    """Post-apply status transition via the L1 central write path.

    Valid transitions:
      applied → {company_rejected | withdrawn | engaged}
      engaged → {offer_accepted | offer_declined | company_rejected | withdrawn}
    """
    db = get_connection()
    try:
        row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

        current = row["status"]
        target = body.target_status

        if target not in _TRANSITION_MAP:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid target_status '{target}'. Must be one of: {', '.join(sorted(_TRANSITION_MAP))}",
            )

        allowed = _VALID_TRANSITIONS.get(current, frozenset())
        if target not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot transition from '{current}' to '{target}'. "
                       f"Allowed from '{current}': {', '.join(sorted(allowed)) or 'none'}",
            )

        event_type, actor = _TRANSITION_MAP[target]
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
    """Log an engaged sub-lifecycle event WITHOUT changing status.

    event_type must be one of the EngagedEventType values.
    followup_sent and contact_received reset the staleness clock (they are
    recent activity — the stale flag recomputes on next read).
    """
    db = get_connection()
    try:
        row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
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
        return _row_to_event(event_row)
    finally:
        db.close()


@router.post("/{job_id}/clean-start", response_model=MessageResponse)
def clean_start(job_id: int, body: CleanStartCreate):
    """Enter a job directly at a post-apply status with a backdated event.

    Sets status directly (applied, engaged, company_rejected, withdrawn,
    offer_accepted, offer_declined, rejected) WITHOUT walking the pre-apply
    funnel. The event's occurred_at is the supplied (possibly past) date;
    created_at is always server now().

    When entering at engaged or company_rejected, an optional applied_occurred_at
    may be supplied to record a backdated 'applied' event first (complete funnel
    history). If omitted, the job stands at engaged/rejected with no applied event.

    This is the "I already applied/engaged/got rejected" clean-start path.
    """
    db = get_connection()
    try:
        row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
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

        event_type, actor = _TRANSITION_MAP.get(
            target, (EventType.STATUS_CHANGED, Actor.CANDIDATE),
        )

        # Resolve the target event's occurred_at (default now)
        now_iso = datetime.now(timezone.utc).isoformat()
        target_occurred_at = body.occurred_at or now_iso

        # If entering at engaged or company_rejected with an optional applied date,
        # record a backdated 'applied' event first.
        implies_application = target in (JobStatus.ENGAGED, JobStatus.COMPANY_REJECTED)
        if implies_application and body.applied_occurred_at:
            applied_dt = _parse_iso(body.applied_occurred_at)
            if applied_dt is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"Invalid applied_occurred_at format: {body.applied_occurred_at}",
                )
            now = datetime.now(timezone.utc)
            if applied_dt > now:
                raise HTTPException(
                    status_code=422,
                    detail=f"applied_occurred_at cannot be in the future: {body.applied_occurred_at}",
                )
            target_dt = _parse_iso(target_occurred_at)
            if target_dt and applied_dt > target_dt:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"applied_occurred_at ({body.applied_occurred_at}) cannot be "
                        f"later than the {target} event's occurred_at ({target_occurred_at})"
                    ),
                )

            # Record the backdated applied event (no status change — we go straight
            # to the target status in the transition below)
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
