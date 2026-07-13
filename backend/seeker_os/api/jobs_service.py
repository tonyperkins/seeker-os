"""Jobs service — business logic for job creation, transitions, and refilter/rescore."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from seeker_os.api.jobs_repo import (
    row_to_detail,
)
from seeker_os.api.schemas import (
    JobCreate,
    JobCreateResponse,
    RefilterRescoreResult,
)
from seeker_os.database import get_connection, json_decode, json_encode
from seeker_os.events import (
    Actor,
    EventType,
    JobStatus,
    record_event,
    transition_status,
)


def try_apply_research_adjustment(db, job_id: int, company: str) -> None:
    """Check for a cached company dossier and apply research adjustment if available.

    Reuses the same compute_research_adjustment path as the pipeline and the
    company-research API endpoint. This is a cache-hit-only check — it does
    NOT trigger new research. If no cached dossier exists, this is a no-op.
    """
    if not company:
        return

    from seeker_os.api.company_research import _find_fresh_dossier, _reconstruct_dossier_from_row
    from seeker_os.dedup.normalize import normalize_company
    from seeker_os.scoring.research_adjustment import (
        ResearchModifierRule,
        compute_research_adjustment,
    )

    company_norm = normalize_company(company)
    if not company_norm:
        return

    try:
        from seeker_os.config import get_settings
        settings = get_settings()
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

    job = db.execute("SELECT score, score_modifiers FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not job or job["score"] is None:
        return

    import json
    base_modifiers: dict[str, float] = json.loads(job["score_modifiers"]) if job["score_modifiers"] else {}

    rules = [
        ResearchModifierRule(
            factor=rm.factor,
            delta=rm.delta,
            confidence_threshold=rm.confidence_threshold,
            source_section=rm.source_section,
            headcount_max=rm.headcount_max,
            headcount_min=rm.headcount_min,
            suppresses=rm.suppresses,
        )
        for rm in settings.scoring.research_modifiers
    ]

    result = compute_research_adjustment(
        base_score=float(job["score"]),
        dossier=dossier,
        rules=rules,
        max_score=settings.scoring.max_score,
        min_score=settings.scoring.min_score,
        base_modifiers=base_modifiers,
    )

    from seeker_os.scoring.net_score import compute_net_score
    job_row = db.execute(
        "SELECT analysis_verdict FROM jobs WHERE id = ?", (job_id,)
    ).fetchone()
    analysis_verdict = job_row["analysis_verdict"] if job_row else None
    verdict_caps = settings.scoring.verdict_caps if settings.scoring else {}
    unknown_verdict_cap = settings.scoring.unknown_verdict_cap if settings.scoring else None
    net = compute_net_score(
        base_score=float(job["score"]),
        research_delta=result.research_delta,
        analysis_verdict=analysis_verdict,
        verdict_caps=verdict_caps,
        max_score=settings.scoring.max_score,
        min_score=settings.scoring.min_score,
        unknown_verdict_cap=unknown_verdict_cap,
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
            datetime.now(UTC).isoformat(),
            job_id,
        ),
    )


def create_job_service(body: JobCreate) -> JobCreateResponse:
    """Manually add a job — validate-then-insert flow.

    1. Compute url_hash, check dedup layer 1 (url_hash). If match → already_exists.
    2. If jd_text provided (paste-JD path), use it directly. Otherwise attempt
       fetch_jd from the URL. If fetch fails → return fetch_failed (no insert).
    3. After JD is available, check content hash dedup (layer 3). If match and
       force=False → return possible_duplicate (NO insert). If force=True →
       proceed with insert (likely_duplicate warning).
    4. Insert complete job with JD, run hard filters as informational metadata
       (manual jobs bypass filter rejection), run scoring, and
       apply research adjustment from cached company dossier if available.
    5. Manual jobs always land in 'ready' regardless of score.
    """
    import hashlib as _hashlib

    from seeker_os.config import get_settings
    from seeker_os.dedup.layers import check_content_duplicate, register_content_hash, url_hash
    from seeker_os.dedup.normalize import normalize_company, normalize_title
    from seeker_os.discovery.ats_fetch import _strip_html as _strip_html_safe
    from seeker_os.discovery.ats_fetch import fetch_greenhouse_job, fetch_jd, parse_greenhouse_url
    from seeker_os.filtering.hard_filters import apply_filters
    from seeker_os.models import JobCard
    from seeker_os.scoring.engine import score_job
    if body.url.strip():
        effective_url = body.url.strip()
    else:
        jd_hash = _hashlib.sha256(body.jd_text.strip().encode()).hexdigest()[:16]
        effective_url = f"manual://jd-paste/{jd_hash}"
    uh = url_hash(effective_url)

    db = get_connection()
    try:
        existing = db.execute("SELECT id FROM jobs WHERE url_hash = ?", (uh,)).fetchone()
        if existing:
            return JobCreateResponse(status="already_exists", existing_job_id=existing["id"])

        gh_title = None
        gh_location = None
        gh_comp_min = None
        gh_comp_max = None
        gh_comp_source = None
        gh_workplace_type = None
        ats_source = None
        ats_board_token = None
        ats_job_id = None

        if body.jd_text and body.jd_text.strip():
            jd_text = body.jd_text.strip()
        else:
            settings = get_settings()
            user_agent = "Mozilla/5.0"
            if settings.sources:
                for src in settings.sources.sources:
                    if src.enabled:
                        user_agent = src.user_agent
                        break

            gh_parsed = parse_greenhouse_url(effective_url)
            gh_data = None
            if gh_parsed:
                gh_board, gh_job_id = gh_parsed
                try:
                    gh_data = fetch_greenhouse_job(gh_board, gh_job_id, user_agent)
                    content = gh_data.get("content", "") or gh_data.get("first_content", "")
                    jd_text = _strip_html_safe(content) if content else ""
                    if not jd_text or len(jd_text) < 100:
                        gh_data = None
                    else:
                        gh_title = gh_data.get("title")
                        loc_obj = gh_data.get("location", {})
                        if isinstance(loc_obj, dict):
                            gh_location = loc_obj.get("name", "")
                        elif isinstance(loc_obj, str):
                            gh_location = loc_obj

                        comp = gh_data.get("compensation")
                        if comp and isinstance(comp, dict):
                            ranges = comp.get("salary_ranges", [])
                            if ranges:
                                first = ranges[0]
                                gh_comp_min = first.get("min")
                                gh_comp_max = first.get("max")
                                gh_comp_source = "structured"

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

                        ats_source = "greenhouse"
                        ats_board_token = gh_board
                        ats_job_id = gh_job_id
                except Exception:
                    gh_data = None

            if not gh_data:
                jd_result = fetch_jd(
                    job_id=0,
                    ats_source=ats_source,
                    ats_board_token=ats_board_token,
                    ats_job_id=ats_job_id,
                    apply_url=effective_url,
                    user_agent=user_agent,
                    delay=0,
                )
                if jd_result.status != "fetched" or not jd_result.jd_text or len(jd_result.jd_text) < 100:
                    return JobCreateResponse(
                        status="fetch_failed",
                        fetch_error=jd_result.error or "JD fetch returned insufficient content",
                    )
                jd_text = jd_result.jd_text

        content_dedup = check_content_duplicate(0, jd_text, db)
        likely_dup_id = None
        if content_dedup.is_duplicate:
            if not body.force:
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
            likely_dup_id = content_dedup.matched_job_id

        now = datetime.now(UTC).isoformat()
        source_job_id = f"manual___{uh[:12]}"

        settings = get_settings()
        if settings.sources:
            for src in settings.sources.sources:
                if src.enabled and src.source_map:
                    break

        if settings.providers:
            from seeker_os.analysis.metadata_extractor import extract_metadata_from_jd
            metadata_op_id = str(uuid.uuid4())
            extracted = extract_metadata_from_jd(
                jd_text=jd_text,
                title=body.title or gh_title or "",
                location=body.location or gh_location or "",
                settings=settings,
                operation_id=metadata_op_id,
            )
            if not gh_workplace_type and not body.workplace_type:
                gh_workplace_type = extracted.workplace_type
            if not gh_comp_min and not body.comp_min:
                gh_comp_min = extracted.comp_min
                if extracted.comp_min is not None:
                    gh_comp_source = "parsed"
            if not gh_comp_max and not body.comp_max:
                gh_comp_max = extracted.comp_max
                if extracted.comp_max is not None:
                    gh_comp_source = "parsed"
            if not body.seniority_level:
                body_seniority_extracted = extracted.seniority_level
            else:
                body_seniority_extracted = None
            gh_role_type = extracted.role_type
            gh_commitment = extracted.commitment
            gh_countries = extracted.countries or []
            gh_company = extracted.company
            gh_title = gh_title or extracted.title
            gh_location = gh_location or extracted.location
            if extracted.jd_text and len(extracted.jd_text) >= 200 and not (body.jd_text and body.jd_text.strip()):
                jd_text = extracted.jd_text
        else:
            body_seniority_extracted = None
            gh_role_type = None
            gh_commitment = None
            gh_countries = []
            gh_company = None

        if not gh_company and not body.company and gh_parsed:
            gh_company = gh_parsed[0].replace("-", " ").replace("_", " ").title()

        eff_title = body.title or gh_title or ""
        eff_company = body.company or gh_company or ""
        eff_location = body.location or gh_location or ""
        eff_workplace = body.workplace_type or gh_workplace_type or ""
        eff_comp_min = body.comp_min if body.comp_min is not None else gh_comp_min
        eff_comp_max = body.comp_max if body.comp_max is not None else gh_comp_max
        if body.comp_min is not None or body.comp_max is not None:
            eff_comp_source = "manual"
        elif gh_comp_source is not None:
            eff_comp_source = gh_comp_source
        else:
            eff_comp_source = "none"
        eff_seniority = body.seniority_level or body_seniority_extracted
        eff_role_type = gh_role_type
        eff_commitment = gh_commitment
        eff_countries = gh_countries

        card = JobCard(
            source_id="manual",
            source_job_id=source_job_id,
            apply_url=effective_url,
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
            comp_source=eff_comp_source,
            date_posted=now,
            discovered_query="manual",
        )

        filter_warnings: list[str] = []
        if settings.profile and settings.filters:
            from seeker_os.config import TitleFilters as _TF
            manual_title_filters = _TF(positive=[], negative=[])
            filter_result = apply_filters(
                card, settings.profile, settings.filters.filters, manual_title_filters,
            )
            if not filter_result.passed:
                filter_warnings.append(filter_result.reason)

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
            comp_source=eff_comp_source,
            never_claim=settings.identity.never_claim if settings.identity else None,
        )

        cursor = db.execute(
            """
            INSERT INTO jobs (
                source_id, source_job_id, ats_source, ats_board_token, ats_job_id,
                apply_url, url_hash,
                title, core_title, company, company_homepage,
                location, workplace_type, workplace_countries, seniority_level,
                commitment, comp_min, comp_max, comp_currency, comp_source,
                technical_tools, requirements_summary, date_posted, role_type,
                status, tier_passed, score, score_reasons, score_gaps, score_modifiers,
                jd_full, jd_fetch_status,
                discovered_at, discovered_query, updated_at, is_pinned,
                filter_warnings
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ready', 4, ?, ?, ?, ?, ?, 'fetched', ?, 'manual', ?, 0, ?)
            """,
            (
                "manual", source_job_id,
                ats_source, ats_board_token, ats_job_id,
                effective_url, uh,
                eff_title, eff_title, eff_company, body.company_homepage,
                eff_location, eff_workplace, json_encode(eff_countries), eff_seniority,
                json_encode([eff_commitment] if eff_commitment else []), eff_comp_min, eff_comp_max, body.comp_currency, eff_comp_source,
                json_encode([]), "", now, eff_role_type,
                score_result.score,
                json_encode(score_result.reasons),
                json_encode(score_result.gaps),
                json_encode(score_result.fired_modifiers),
                jd_text,
                now, now,
                json_encode(filter_warnings) if filter_warnings else None,
            ),
        )
        job_id = cursor.lastrowid

        # Link metadata extraction LLM calls to the job for observability
        if settings.providers:
            try:
                from seeker_os.observability.llm_ledger import attach_artifact
                attach_artifact(metadata_op_id, "job", int(job_id), db=db)
            except Exception:
                logging.getLogger(__name__).exception(
                    "llm_artifact_link_failed", extra={"operation_id": metadata_op_id}
                )

        db.execute(
            "UPDATE jobs SET title_norm=?, company_norm=? WHERE id=?",
            (normalize_title(eff_title), normalize_company(eff_company), job_id),
        )
        register_content_hash(job_id, jd_text, db)

        try_apply_research_adjustment(db, job_id, eff_company)

        record_event(
            db, job_id, EventType.MANUAL_CREATED, Actor.CANDIDATE,
            metadata={"score": score_result.score},
        )

        if any([body.recruiter_name, body.recruiter_email, body.recruiter_phone,
                body.recruiter_linkedin, body.recruiter_agency, body.recruiter_source]):
            now_rc = datetime.now(UTC).isoformat()
            cursor_rc = db.execute(
                """
                INSERT INTO recruiters (name, email, phone, linkedin, agency, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (body.recruiter_name, body.recruiter_email, body.recruiter_phone,
                 body.recruiter_linkedin, body.recruiter_agency, now_rc, now_rc),
            )
            recruiter_entity_id = cursor_rc.lastrowid
            db.execute(
                """
                INSERT INTO recruiter_job_contacts
                    (recruiter_id, job_id, source, contacted_at, notes, created_at, updated_at)
                VALUES (?, ?, ?, ?, NULL, ?, ?)
                """,
                (recruiter_entity_id, job_id, body.recruiter_source,
                 body.recruiter_contacted_at, now_rc, now_rc),
            )
            record_event(
                db, job_id, EventType.RECRUITER_CONTACT, Actor.COMPANY,
                metadata={
                    "name": body.recruiter_name,
                    "source": body.recruiter_source,
                    "agency": body.recruiter_agency,
                },
                occurred_at=body.recruiter_contacted_at,
                allow_before_discovery=True,
            )

        db.commit()

        row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        response_status = "likely_duplicate" if likely_dup_id else "created"
        return JobCreateResponse(
            status=response_status,
            job=row_to_detail(row, db=db),
            existing_job_id=likely_dup_id,
            filter_warnings=filter_warnings,
        )
    finally:
        db.close()


def refilter_rescore_job(db, row, settings) -> RefilterRescoreResult:
    """Re-run filter + score on an existing job, factoring in analysis + research.

    Does NOT trigger new analysis or research — only uses existing data.
    Preserves decision statuses (skipped, interested, applied, engaged, etc.)
    — those jobs are only rescored, not refiltered. System statuses (ready,
    rejected) are re-evaluated.
    """
    from seeker_os.filtering.hard_filters import apply_filters
    from seeker_os.models import JobCard
    from seeker_os.scoring.engine import score_job
    from seeker_os.scoring.net_score import compute_net_score

    job_id = row["id"]
    preserve_status = row["status"] in JobStatus._RESCORE_PRESERVED_STATUSES

    if not preserve_status and row["status"] == "rejected":
        last_rejection = db.execute(
            """
            SELECT actor FROM application_events
            WHERE job_id = ? AND event_type IN (?, ?)
            ORDER BY id DESC LIMIT 1
            """,
            (job_id, EventType.REJECTED, EventType.FILTER_REJECTED),
        ).fetchone()
        if last_rejection and last_rejection["actor"] == Actor.CANDIDATE:
            preserve_status = True

    previous_score = row["score"] if "score" in row.keys() and row["score"] is not None else None
    previous_status = row["status"]

    card = JobCard(
        source_id=row["source_id"] or "",
        source_job_id=row["source_job_id"] or "",
        ats_source=row["ats_source"],
        ats_board_token=row["ats_board_token"],
        ats_job_id=row["ats_job_id"],
        apply_url=row["apply_url"] or "",
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
        comp_source=row["comp_source"] if "comp_source" in row.keys() else "none",
        technical_tools=json_decode(row["technical_tools"]) or [],
        requirements_summary=row["requirements_summary"] or "",
        date_posted=row["date_posted"] or "",
        role_type=row["role_type"],
        is_pinned=bool(row["is_pinned"]),
        discovered_query=row["discovered_query"] or "",
    )

    # Recompute filter_warnings for manual jobs (informational, empty title
    # filters — same approach as create_job_service).  For non-manual jobs,
    # clear any stale warnings.
    new_filter_warnings: list[str] = []
    if (row["source_id"] or "") == "manual" and settings.profile and settings.filters:
        from seeker_os.config import TitleFilters as _TF
        manual_title_filters = _TF(positive=[], negative=[])
        info_result = apply_filters(
            card, settings.profile, settings.filters.filters, manual_title_filters,
        )
        if not info_result.passed:
            new_filter_warnings.append(info_result.reason)
    filter_warnings_json = json_encode(new_filter_warnings) if new_filter_warnings else None

    filter_passed = True
    if not preserve_status:
        filter_result = apply_filters(
            card, settings.profile, settings.filters.filters, settings.filters.title_filters,
        )
        filter_passed = filter_result.passed

        if not filter_passed:
            if row["status"] != "rejected":
                transition_status(
                    db, job_id, "rejected", EventType.FILTER_REJECTED, Actor.SYSTEM,
                    extra_sets={
                        "reject_reason": filter_result.reason,
                        "tier_passed": 0,
                        "filter_warnings": filter_warnings_json,
                    },
                    metadata={"reason": filter_result.reason, "refilter": True},
                )
            else:
                record_event(
                    db, job_id, EventType.REFILTER_RESCORED, Actor.SYSTEM,
                    metadata={"refilter": True, "filter_reason": filter_result.reason},
                )
            return RefilterRescoreResult(
                job_id=job_id,
                status="rejected",
                previous_score=previous_score,
                previous_status=previous_status,
                status_changed=previous_status != "rejected",
                filter_passed=False,
                filter_reason=filter_result.reason,
            )

    score_result = score_job(
        title=row["title"] or "",
        jd_text=row["jd_full"] or "",
        location=row["location"] or "",
        company=row["company"] or "",
        rubric=settings.scoring,
        profile=settings.profile,
        comp_min=row["comp_min"],
        comp_max=row["comp_max"],
        workplace_type=row["workplace_type"],
        seniority_level=row["seniority_level"],
        comp_source=row["comp_source"] if "comp_source" in row.keys() else "none",
        never_claim=settings.identity.never_claim if settings.identity else None,
    )

    now = datetime.now(UTC).isoformat()

    new_status = row["status"]
    if not preserve_status:
        if score_result.hard_reject:
            new_status = "rejected"
        elif score_result.score >= settings.scoring.post_threshold:
            new_status = "ready"
        else:
            new_status = "rejected"

    extra_sets = {
        "score": score_result.score,
        "score_reasons": json_encode(score_result.reasons),
        "score_gaps": json_encode(score_result.gaps),
        "score_modifiers": json_encode(score_result.fired_modifiers),
        "filter_warnings": filter_warnings_json,
    }
    if not preserve_status:
        if score_result.hard_reject:
            extra_sets["reject_reason"] = score_result.reject_reason
        elif score_result.score < settings.scoring.post_threshold:
            extra_sets["reject_reason"] = "score below threshold"
        extra_sets["tier_passed"] = 4 if new_status == "ready" else row["tier_passed"]

    analysis_verdict = row["analysis_verdict"] if "analysis_verdict" in row.keys() else None
    research_applied = False
    research_delta = 0.0

    company = row["company"] or ""
    if company:
        try:
            try_apply_research_adjustment(db, job_id, company)
            updated = db.execute(
                "SELECT research_delta, research_adjusted_score FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if updated and updated["research_delta"]:
                research_delta = float(updated["research_delta"])
                research_applied = True
        except Exception:
            pass

    net = compute_net_score(
        base_score=score_result.score,
        research_delta=research_delta,
        analysis_verdict=analysis_verdict,
        verdict_caps=settings.scoring.verdict_caps,
        max_score=settings.scoring.max_score,
        min_score=settings.scoring.min_score,
        unknown_verdict_cap=settings.scoring.unknown_verdict_cap,
    )
    extra_sets["net_score"] = net
    extra_sets["updated_at"] = now

    score_changed = (previous_score is None) or (abs(score_result.score - previous_score) > 0.01)
    status_changed = new_status != previous_status

    if not preserve_status and status_changed:
        if new_status == "ready":
            transition_status(
                db, job_id, "ready", EventType.SCORED_READY, Actor.SYSTEM,
                extra_sets=extra_sets,
                metadata={"refilter_rescore": True, "previous_score": previous_score},
            )
        else:
            transition_status(
                db, job_id, "rejected", EventType.SCORED_REJECTED, Actor.SYSTEM,
                extra_sets=extra_sets,
                metadata={"refilter_rescore": True, "previous_score": previous_score},
            )
    else:
        db.execute(
            f"UPDATE jobs SET {', '.join(f'{k} = ?' for k in extra_sets)} WHERE id = ?",
            (*extra_sets.values(), job_id),
        )
        record_event(
            db, job_id, EventType.REFILTER_RESCORED, Actor.SYSTEM,
            metadata={
                "refilter_rescore": True,
                "previous_score": previous_score,
                "new_score": score_result.score,
                "net_score": net,
                "score_changed": score_changed,
                "research_applied": research_applied,
                "analysis_verdict": analysis_verdict,
            },
        )

    return RefilterRescoreResult(
        job_id=job_id,
        status=new_status,
        score=score_result.score,
        net_score=net,
        previous_score=previous_score,
        previous_status=previous_status,
        score_changed=score_changed,
        status_changed=status_changed,
        filter_passed=True,
        research_applied=research_applied,
        analysis_verdict=analysis_verdict,
    )
