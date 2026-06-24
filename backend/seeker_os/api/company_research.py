"""Company research API routes."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from seeker_os.api.schemas import CompanyResearchResponse
from seeker_os.database import get_connection, json_decode, json_encode
from seeker_os.research.company_research import research_company

router = APIRouter(prefix="/api/jobs", tags=["company-research"])


def _row_to_response(row) -> CompanyResearchResponse:
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
    )


@router.get("/{job_id}/company-research", response_model=CompanyResearchResponse)
def get_company_research(job_id: int):
    """Get cached company research for a job."""
    db = get_connection()
    try:
        job = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not job:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

        row = db.execute(
            "SELECT * FROM company_research WHERE job_id = ? ORDER BY researched_at DESC LIMIT 1",
            (job_id,),
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="No company research found for this job")

        return _row_to_response(row)
    finally:
        db.close()


@router.post("/{job_id}/company-research", response_model=CompanyResearchResponse)
def run_company_research(job_id: int):
    """Run company research for a job and cache the result."""
    db = get_connection()
    try:
        job = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not job:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

        company = job["company"] or ""
        if not company:
            raise HTTPException(status_code=400, detail="Job has no company name")

        company_homepage = job["company_homepage"] if "company_homepage" in job.keys() else None

        result = research_company(
            company=company,
            company_homepage=company_homepage,
        )

        now = datetime.now(timezone.utc).isoformat()

        # Serialize sub-objects to JSON for storage
        wiki_json = json_encode(result.wikipedia.model_dump()) if result.wikipedia else None
        funding_json = json_encode(result.funding.model_dump()) if result.funding else None
        sentiment_json = json_encode(result.sentiment.model_dump()) if result.sentiment else None
        fit_json = json_encode(result.fit.model_dump()) if result.fit else None
        verdict_json = json_encode(result.verdict_flags.model_dump())
        gaps_json = json_encode(result.gaps)

        cursor = db.execute(
            """
            INSERT INTO company_research (
                job_id, company_name, company_homepage,
                wikipedia_data, funding_data, sentiment_data, fit_data,
                overall_confidence, summary, verdict_flags, gaps,
                sources_used, errors, researched_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id, company, company_homepage,
                wiki_json, funding_json, sentiment_json, fit_json,
                result.overall_confidence, result.summary, verdict_json, gaps_json,
                json_encode(result.sources_used),
                json_encode(result.errors),
                result.researched_at, now,
            ),
        )
        db.commit()

        research_id = cursor.lastrowid
        row = db.execute(
            "SELECT * FROM company_research WHERE id = ?", (research_id,)
        ).fetchone()

        return _row_to_response(row)
    finally:
        db.close()
