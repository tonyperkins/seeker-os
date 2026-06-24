"""API schemas — Pydantic models for API request/response.

These are separate from the internal models in models.py because:
- API schemas are typed for JSON serialization (camelCase, optional fields)
- Internal models are typed for pipeline logic (snake_case, required fields)
- The API layer converts between them
"""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Job schemas
# ---------------------------------------------------------------------------

class JobSummary(BaseModel):
    """Job summary for list views."""
    id: int
    title: str
    company: str
    score: float | None = None
    status: str
    tier_passed: int
    comp_min: int | None = None
    comp_max: int | None = None
    location: str = ""
    workplace_type: str = ""
    seniority_level: str | None = None
    date_posted: str = ""
    discovered_at: str = ""
    apply_url: str = ""
    ats_source: str | None = None
    cross_ref_status: str | None = None
    is_pinned: bool = False
    reject_reason: str | None = None


class JobDetail(BaseModel):
    """Full job detail."""
    id: int
    title: str
    core_title: str
    company: str
    company_homepage: str | None = None
    location: str
    workplace_type: str
    workplace_countries: list[str] = []
    seniority_level: str | None = None
    commitment: list[str] = []
    comp_min: int | None = None
    comp_max: int | None = None
    comp_currency: str | None = None
    technical_tools: list[str] = []
    requirements_summary: str = ""
    date_posted: str = ""
    role_type: str | None = None

    # Pipeline
    status: str
    tier_passed: int
    score: float | None = None
    score_reasons: list[str] = []
    score_gaps: list[str] = []
    reject_reason: str | None = None
    reject_details: str | None = None

    # JD
    jd_full: str = ""
    jd_fetch_status: str = "pending"

    # Metadata
    source_id: str = ""
    ats_source: str | None = None
    ats_board_token: str | None = None
    ats_job_id: str | None = None
    apply_url: str = ""
    discovered_query: str = ""
    discovered_at: str = ""
    updated_at: str = ""

    # Dedup
    content_hash: str | None = None

    # Cross-ref
    cross_ref_status: str | None = None
    cross_ref_date: str | None = None
    cross_ref_score: float | None = None

    is_pinned: bool = False


class JobUpdate(BaseModel):
    """PATCH /api/jobs/{id} — partial update."""
    status: str | None = None
    notes: str | None = None
    is_pinned: bool | None = None


class JobReject(BaseModel):
    """POST /api/jobs/{id}/reject."""
    reason: str
    details: str | None = None  # free-text feedback on why the job was rejected


class JobSnooze(BaseModel):
    """POST /api/jobs/{id}/snooze."""
    days: int = 7


# ---------------------------------------------------------------------------
# Pipeline schemas
# ---------------------------------------------------------------------------

class PipelineRunRequest(BaseModel):
    """POST /api/pipeline/run."""
    tiers: list[int] | None = None
    queries: list[str] | None = None
    dry_run: bool = False


class PipelineRunSummary(BaseModel):
    """Pipeline run result."""
    run_id: str
    cards_fetched: int = 0
    cards_new: int = 0
    duplicates_skipped: int = 0
    tier2_passed: int = 0
    tier2_rejected: int = 0
    tier3_fetched: int = 0
    tier3_failed: int = 0
    tier4_scored: int = 0
    tier4_rejected: int = 0
    tier4_hard_rejected: int = 0
    tier5_ready: int = 0
    tier5_capped: int = 0
    cross_ref_matches: int = 0
    rejection_reasons: dict[str, int] = {}


class PipelineRunRecord(BaseModel):
    """A pipeline run from the DB."""
    id: int
    run_id: str
    started_at: str
    completed_at: str | None = None
    cards_fetched: int = 0
    cards_new: int = 0
    cards_survived_tier2: int = 0
    jds_fetched: int = 0
    jobs_scored: int = 0
    jobs_ready: int = 0
    status: str = ""


# ---------------------------------------------------------------------------
# Query schemas
# ---------------------------------------------------------------------------

class QuerySummary(BaseModel):
    """Search query for list views."""
    id: int | None = None
    source_id: str = "hiring_cafe"
    slug: str
    label: str
    commitment: str = "full_time"
    max_pages: int = 1
    enabled: bool = True
    last_run_at: str | None = None


class QueryCreate(BaseModel):
    """POST /api/queries."""
    source_id: str = "hiring_cafe"
    slug: str
    label: str
    commitment: str = "full_time"
    max_pages: int = 1
    enabled: bool = True


class QueryUpdate(BaseModel):
    """PATCH /api/queries/{id}."""
    label: str | None = None
    commitment: str | None = None
    max_pages: int | None = None
    enabled: bool | None = None


# ---------------------------------------------------------------------------
# Settings schemas
# ---------------------------------------------------------------------------

class SettingsResponse(BaseModel):
    """GET /api/settings — returns all config."""
    filters: dict | None = None
    scoring: dict | None = None
    sources: dict | None = None
    profile_loaded: bool = False
    queries_count: int = 0


class SettingUpdate(BaseModel):
    """PATCH /api/settings/{key}."""
    value: str


# ---------------------------------------------------------------------------
# Analytics schemas
# ---------------------------------------------------------------------------

class FunnelStats(BaseModel):
    """GET /api/analytics/funnel."""
    total_jobs: int = 0
    discovered: int = 0
    filtered: int = 0
    jd_fetched: int = 0
    ready: int = 0
    rejected: int = 0
    duplicate_flagged: int = 0
    capped: int = 0
    # Cumulative funnel: jobs that reached AT LEAST this tier
    funnel: list[dict] = []  # [{tier: 1, label: "Discovery", count: 142}, ...]
    # JD fetch stats (enrichment, not a funnel gate)
    jd_fetch_total: int = 0  # jobs that passed tier 2 and need JD fetch
    jd_fetch_success: int = 0
    jd_fetch_failed: int = 0
    jd_fetch_pending: int = 0
    by_tier: dict[int, int] = {}  # raw tier_passed counts (kept for compatibility)
    by_status: dict[str, int] = {}
    by_ats_source: dict[str, int] = {}
    rejection_reasons: dict[str, int] = {}
    score_distribution: dict[str, int] = {}


class ResponseRateStats(BaseModel):
    """GET /api/analytics/response-rate."""
    total_applied: int = 0
    total_responded: int = 0
    response_rate: float = 0.0
    by_source: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Generic
# ---------------------------------------------------------------------------

class MessageResponse(BaseModel):
    message: str


class ErrorResponse(BaseModel):
    detail: str
