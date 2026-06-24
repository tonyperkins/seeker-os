"""JD Analysis API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from seeker_os.api.schemas import JobAnalysisResponse
from seeker_os.analysis.jd_analyzer import analyze_job, get_latest_analysis

router = APIRouter(prefix="/api/jobs", tags=["jd-analysis"])


def _dict_to_response(data: dict) -> JobAnalysisResponse:
    """Convert a raw analysis dict to JobAnalysisResponse."""
    from seeker_os.api.schemas import (
        NamedGapSchema,
        HardBlockerSchema,
        RubricDimensionSchema,
        CompAssessmentSchema,
        PositioningSchema,
        CompanyFitSchema,
        TailoringSchema,
    )

    comp_data = data.get("comp") or {}
    pos_data = data.get("positioning") or {}
    fit_data = data.get("company_fit") or {}
    tail_data = data.get("tailoring") or {}

    return JobAnalysisResponse(
        id=data.get("id"),
        job_id=data.get("job_id", 0),
        provider=data.get("provider", ""),
        model=data.get("model", ""),
        input_tokens=data.get("input_tokens", 0),
        output_tokens=data.get("output_tokens", 0),
        latency_ms=data.get("latency_ms", 0),
        company=data.get("company", ""),
        title=data.get("title", ""),
        url=data.get("url", ""),
        analyzed_at=data.get("analyzed_at", ""),
        verdict=data.get("verdict", ""),
        weighted_score=data.get("weighted_score", 0.0),
        one_line=data.get("one_line", ""),
        named_gaps=[NamedGapSchema(**g) for g in data.get("named_gaps", [])],
        hard_blockers=[HardBlockerSchema(**b) for b in data.get("hard_blockers", [])],
        rubric_breakdown=[RubricDimensionSchema(**r) for r in data.get("rubric_breakdown", [])],
        bonuses_applied=data.get("bonuses_applied", []),
        penalties_applied=data.get("penalties_applied", []),
        comp=CompAssessmentSchema(**comp_data),
        positioning=PositioningSchema(**pos_data),
        company_fit=CompanyFitSchema(**fit_data),
        tailoring=TailoringSchema(**tail_data),
        red_flags=data.get("red_flags", []),
        confidence=data.get("confidence", 0.0),
    )


@router.get("/{job_id}/analysis", response_model=JobAnalysisResponse)
def get_analysis(job_id: int):
    """Get the latest cached JD analysis for a job."""
    data = get_latest_analysis(job_id)
    if not data:
        raise HTTPException(status_code=404, detail="No analysis found for this job")
    return _dict_to_response(data)


@router.post("/{job_id}/analysis", response_model=JobAnalysisResponse)
def run_analysis(job_id: int):
    """Run JD analysis for a job and cache the result."""
    from seeker_os.config import Settings

    settings = Settings()
    try:
        result = analyze_job(settings=settings, job_id=job_id)
        return _dict_to_response(result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {e}")
