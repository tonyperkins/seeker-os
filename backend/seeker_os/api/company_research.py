"""Company research API routes."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from seeker_os.api.schemas import CompanyResearchResponse, SourceRefSchema
from seeker_os.database import get_connection, json_decode, json_encode
from seeker_os.dedup.normalize import normalize_company
from seeker_os.research.company_research import research_company
from seeker_os.research.models import (
    CompanyResearchResult,
    FundingDossier,
    SentimentDossier,
    FitDossier,
)
from seeker_os.scoring.research_adjustment import (
    ResearchModifierRule,
    compute_research_adjustment,
)

router = APIRouter(prefix="/api/jobs", tags=["company-research"])


def _row_to_response(
    row,
    reused_from_cache: bool = False,
    dossier_age_days: int | None = None,
    adjustment: dict | None = None,
) -> CompanyResearchResponse:
    """Convert a DB row to CompanyResearchResponse."""
    from seeker_os.api.schemas import (
        WikipediaInfoSchema,
        FundingDossierSchema,
        SentimentDossierSchema,
        FitDossierSchema,
        VerdictFlagsSchema,
    )

    wiki_data = json_decode(row["wikipedia_data"]) if row["wikipedia_data"] else None
    funding_data = json_decode(row["funding_data"]) if row["funding_data"] else None
    sentiment_data = json_decode(row["sentiment_data"]) if row["sentiment_data"] else None
    fit_data = json_decode(row["fit_data"]) if "fit_data" in row.keys() and row["fit_data"] else None
    verdict_data = json_decode(row["verdict_flags"]) if "verdict_flags" in row.keys() and row["verdict_flags"] else None

    wiki = WikipediaInfoSchema(**wiki_data) if wiki_data else None
    funding = FundingDossierSchema(**funding_data) if funding_data else None
    sentiment = SentimentDossierSchema(**sentiment_data) if sentiment_data else None
    fit = FitDossierSchema(**fit_data) if fit_data else None
    verdict_flags = VerdictFlagsSchema(**verdict_data) if verdict_data else VerdictFlagsSchema()

    retrieval_sources_data = (
        json_decode(row["retrieval_sources"])
        if "retrieval_sources" in row.keys() and row["retrieval_sources"]
        else []
    )
    retrieval_snippets_data = (
        json_decode(row["retrieval_snippets_data"])
        if "retrieval_snippets_data" in row.keys() and row["retrieval_snippets_data"]
        else []
    )

    adj = adjustment or {}
    return CompanyResearchResponse(
        id=row["id"],
        job_id=row["job_id"],
        company_name=row["company_name"] or "",
        company_homepage=row["company_homepage"],
        wikipedia=wiki,
        overall_confidence=row["overall_confidence"] if "overall_confidence" in row.keys() else 0.0,
        summary=row["summary"] if "summary" in row.keys() else "",
        verdict_flags=verdict_flags,
        funding=funding,
        sentiment=sentiment,
        fit=fit,
        gaps=json_decode(row["gaps"]) if "gaps" in row.keys() and row["gaps"] else [],
        sources_used=json_decode(row["sources_used"]) or [],
        errors=json_decode(row["errors"]) or [],
        researched_at=row["researched_at"] or "",
        retrieval_used=bool(retrieval_sources_data),
        retrieval_sources=[SourceRefSchema(**s) for s in retrieval_sources_data] if retrieval_sources_data else [],
        retrieval_snippets=retrieval_snippets_data,
        reused_from_cache=reused_from_cache,
        dossier_age_days=dossier_age_days,
        research_adjusted_score=adj.get("research_adjusted_score"),
        research_delta=adj.get("research_delta", 0.0),
        research_breakdown=adj.get("research_breakdown", []),
        research_adjustment_applied=adj.get("research_adjustment_applied", False),
    )


def _reconstruct_dossier_from_row(row, confidence_floor: float = 0.3) -> CompanyResearchResult:
    """Reconstruct a minimal CompanyResearchResult from a DB row for adjustment computation."""
    funding = None
    sentiment = None
    fit = None

    funding_data = json_decode(row["funding_data"]) if row["funding_data"] else None
    if funding_data:
        funding = FundingDossier(**funding_data)

    sentiment_data = json_decode(row["sentiment_data"]) if row["sentiment_data"] else None
    if sentiment_data:
        sentiment = SentimentDossier(**sentiment_data)

    fit_data = json_decode(row["fit_data"]) if "fit_data" in row.keys() and row["fit_data"] else None
    if fit_data:
        fit = FitDossier(**fit_data)

    overall_confidence = row["overall_confidence"] if "overall_confidence" in row.keys() else 0.0
    retrieval_sources_data = (
        json_decode(row["retrieval_sources"])
        if "retrieval_sources" in row.keys() and row["retrieval_sources"]
        else []
    )

    return CompanyResearchResult(
        company_name=row["company_name"] or "",
        overall_confidence=overall_confidence,
        funding=funding,
        sentiment=sentiment,
        fit=fit,
        is_stub=overall_confidence < confidence_floor,
        retrieval_used=bool(retrieval_sources_data),
    )


def _apply_research_adjustment(db, job_id: int, dossier: CompanyResearchResult) -> dict | None:
    """Compute research-adjusted score and persist to the jobs table.

    Returns a dict with research_adjusted_score, research_delta,
    research_breakdown, research_adjustment_applied — or None if the
    job hasn't been scored yet (no base score to adjust).
    """
    job = db.execute("SELECT score FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not job or job["score"] is None:
        return None

    base_score = float(job["score"])

    try:
        from seeker_os.config import Settings
        settings = Settings()
        scoring = settings.scoring
    except Exception:
        return None

    if not scoring or not scoring.research_modifiers:
        return None

    rules = [
        ResearchModifierRule(
            factor=rm.factor,
            delta=rm.delta,
            confidence_threshold=rm.confidence_threshold,
            source_section=rm.source_section,
        )
        for rm in scoring.research_modifiers
    ]

    result = compute_research_adjustment(
        base_score=base_score,
        dossier=dossier,
        rules=rules,
        max_score=scoring.max_score,
        min_score=scoring.min_score,
    )

    breakdown_json = json_encode([
        item.model_dump() for item in result.breakdown
    ])

    # Recompute net_score since research_delta changed
    from seeker_os.scoring.net_score import compute_net_score
    job_row = db.execute(
        "SELECT analysis_verdict FROM jobs WHERE id = ?", (job_id,)
    ).fetchone()
    analysis_verdict = job_row["analysis_verdict"] if job_row else None
    verdict_caps = scoring.verdict_caps if scoring else {}
    net = compute_net_score(
        base_score=base_score,
        research_delta=result.research_delta,
        analysis_verdict=analysis_verdict,
        verdict_caps=verdict_caps,
        max_score=scoring.max_score if scoring else 10,
        min_score=scoring.min_score if scoring else 0,
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
            breakdown_json,
            net,
            datetime.now(timezone.utc).isoformat(),
            job_id,
        ),
    )
    db.commit()

    return {
        "research_adjusted_score": result.adjusted_score,
        "research_delta": result.research_delta,
        "research_breakdown": [item.model_dump() for item in result.breakdown],
        "research_adjustment_applied": result.applied,
        "net_score": net,
    }


def _find_fresh_dossier(db, company_norm: str, ttl_days: int):
    """Find a fresh (within TTL) dossier for a company. Returns row or None."""
    row = db.execute(
        "SELECT * FROM company_research WHERE company_norm = ? ORDER BY researched_at DESC LIMIT 1",
        (company_norm,),
    ).fetchone()
    if not row:
        return None, None
    # Check freshness
    researched_at = row["researched_at"] or ""
    age_days = None
    if researched_at:
        try:
            parsed = datetime.fromisoformat(researched_at.replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - parsed).days
        except (ValueError, TypeError):
            age_days = None
    if age_days is not None and age_days <= ttl_days:
        return row, age_days
    return None, age_days


@router.get("/{job_id}/company-research", response_model=CompanyResearchResponse)
def get_company_research(job_id: int):
    """Get cached company research for a job."""
    db = get_connection()
    try:
        job = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not job:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

        # Try by job_id first (backward compat)
        row = db.execute(
            "SELECT * FROM company_research WHERE job_id = ? ORDER BY researched_at DESC LIMIT 1",
            (job_id,),
        ).fetchone()

        # If not found by job_id, try by company_norm
        reused = False
        age_days = None
        if not row:
            company_norm = normalize_company(job["company"] or "")
            if company_norm:
                row = db.execute(
                    "SELECT * FROM company_research WHERE company_norm = ? ORDER BY researched_at DESC LIMIT 1",
                    (company_norm,),
                ).fetchone()
                if row:
                    reused = True
                    researched_at = row["researched_at"] or ""
                    if researched_at:
                        try:
                            parsed = datetime.fromisoformat(researched_at.replace("Z", "+00:00"))
                            age_days = (datetime.now(timezone.utc) - parsed).days
                        except (ValueError, TypeError):
                            pass

        if not row:
            raise HTTPException(status_code=404, detail="No company research found for this job")

        # Read existing adjusted score from jobs table (persisted by POST endpoint)
        adjustment = None
        job_row = db.execute(
            "SELECT research_adjusted_score, research_delta, research_breakdown FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        if job_row and job_row["research_adjusted_score"] is not None:
            adjustment = {
                "research_adjusted_score": job_row["research_adjusted_score"],
                "research_delta": job_row["research_delta"] if "research_delta" in job_row.keys() else 0.0,
                "research_breakdown": json_decode(job_row["research_breakdown"]) if "research_breakdown" in job_row.keys() and job_row["research_breakdown"] else [],
                "research_adjustment_applied": True,
            }

        return _row_to_response(row, reused_from_cache=reused, dossier_age_days=age_days, adjustment=adjustment)
    finally:
        db.close()


@router.post("/{job_id}/company-research", response_model=CompanyResearchResponse)
def run_company_research(job_id: int, force_refresh: bool = False):
    """Run company research for a job and cache the result.

    If a fresh (within TTL) dossier exists for the same company, reuses it
    instead of hitting Tavily again. Pass force_refresh=true to bypass cache.
    """
    db = get_connection()
    try:
        job = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not job:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

        company = job["company"] or ""
        if not company:
            raise HTTPException(status_code=400, detail="Job has no company name")

        company_homepage = job["company_homepage"] if "company_homepage" in job.keys() else None
        jd_full = job["jd_full"] if "jd_full" in job.keys() else None
        company_norm = normalize_company(company)

        # Check for fresh cached dossier by company_norm (unless force_refresh)
        ttl_days = 30
        try:
            from seeker_os.config import Settings
            settings = Settings()
            if settings.company_research:
                ttl_days = settings.company_research.research_ttl_days
        except Exception:
            pass

        if not force_refresh:
            cached_row, age_days = _find_fresh_dossier(db, company_norm, ttl_days)
            if cached_row:
                # Compute and persist research-adjusted score from cached dossier
                confidence_floor = 0.3
                try:
                    from seeker_os.config import Settings
                    s = Settings()
                    if s.company_research:
                        confidence_floor = s.company_research.confidence_floor
                except Exception:
                    pass
                dossier = _reconstruct_dossier_from_row(cached_row, confidence_floor)
                adjustment = _apply_research_adjustment(db, job_id, dossier)
                return _row_to_response(
                    cached_row, reused_from_cache=True, dossier_age_days=age_days,
                    adjustment=adjustment,
                )

        # Run fresh research
        result = research_company(
            company=company,
            company_homepage=company_homepage,
            jd_text=jd_full or "",
            force_refresh=force_refresh,
        )

        # Guard: don't persist a completely empty dossier (LLM failure with
        # no fallback data). This would shadow any previous good research row
        # since GET returns the most recent by job_id.
        if (result.overall_confidence == 0.0
                and result.funding is None
                and result.sentiment is None
                and result.fit is None
                and not result.summary):
            raise HTTPException(
                status_code=502,
                detail="Research completed but produced no usable data — LLM dossier generation may have failed. Check server logs.",
            )

        now = datetime.now(timezone.utc).isoformat()

        # Serialize sub-objects to JSON for storage
        wiki_json = json_encode(result.wikipedia.model_dump()) if result.wikipedia else None
        funding_json = json_encode(result.funding.model_dump()) if result.funding else None
        sentiment_json = json_encode(result.sentiment.model_dump()) if result.sentiment else None
        fit_json = json_encode(result.fit.model_dump()) if result.fit else None
        verdict_json = json_encode(result.verdict_flags.model_dump())
        gaps_json = json_encode(result.gaps)

        retrieval_sources_json = json_encode(
            [s.model_dump() for s in result.retrieval_sources]
        ) if result.retrieval_sources else None
        retrieval_snippets_json = json_encode(result.retrieval_snippets) if result.retrieval_snippets else None

        cursor = db.execute(
            """
            INSERT INTO company_research (
                job_id, company_name, company_homepage,
                wikipedia_data, funding_data, sentiment_data, fit_data,
                overall_confidence, summary, verdict_flags, gaps,
                sources_used, errors, researched_at, created_at,
                retrieval_sources, retrieval_snippets_data, company_norm
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id, company, company_homepage,
                wiki_json, funding_json, sentiment_json, fit_json,
                result.overall_confidence, result.summary, verdict_json, gaps_json,
                json_encode(result.sources_used),
                json_encode(result.errors),
                result.researched_at, now,
                retrieval_sources_json, retrieval_snippets_json,
                company_norm,
            ),
        )
        db.commit()

        research_id = cursor.lastrowid
        row = db.execute(
            "SELECT * FROM company_research WHERE id = ?", (research_id,)
        ).fetchone()

        # Compute and persist research-adjusted score from fresh dossier
        adjustment = _apply_research_adjustment(db, job_id, result)

        return _row_to_response(row, reused_from_cache=False, dossier_age_days=0, adjustment=adjustment)
    finally:
        db.close()
