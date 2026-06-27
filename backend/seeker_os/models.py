"""Pydantic v2 data models for Seeker OS.

All models use BaseModel (not dataclasses) for validation, serialization, and
consistent typing. See AGENTS.md § Data Conventions.
"""

from __future__ import annotations

from pydantic import BaseModel, field_validator


class JobCard(BaseModel):
    """Generic, source-agnostic job card.

    All source adapters normalize their data into this format. The pipeline
    downstream never sees source-specific fields.
    See docs/SOURCE_ADAPTERS.md for full design.
    """

    # Identity (source-specific, but normalized)
    source_id: str               # which adapter found this (e.g. 'hiring_cafe')
    source_job_id: str           # source-specific job ID (e.g. source___board___jobid)
    ats_source: str | None = None       # canonical ATS (greenhouse, ashby, lever, etc.)
    ats_board_token: str | None = None
    ats_job_id: str | None = None
    apply_url: str

    # Job details (normalized)
    title: str = ""
    core_title: str = ""         # normalized/core job title
    company: str = ""
    company_homepage: str | None = None
    location: str = ""
    workplace_type: str = ""     # Remote, On-Site, Hybrid
    workplace_countries: list[str] = []
    seniority_level: str | None = None
    commitment: list[str] = []
    comp_min: int | None = None
    comp_max: int | None = None
    comp_currency: str | None = None
    technical_tools: list[str] = []
    requirements_summary: str = ""
    date_posted: str             # ISO timestamp
    role_type: str | None = None
    is_pinned: bool = False

    # Metadata
    discovered_query: str        # which query slug found this
    detail_url: str | None = None  # source-specific detail page URL (e.g. hiring.cafe/job/{slug})

    @field_validator("comp_min", "comp_max", mode="before")
    @classmethod
    def _round_comp(cls, v):
        if v is None:
            return None
        return int(round(float(v)))


class SourcePage(BaseModel):
    """One page of results from a source adapter."""
    jobs: list[JobCard]
    total_count: int
    is_last_page: bool
    source: str                  # adapter ID


class SourceQuery(BaseModel):
    """A query to run against a source."""
    source_id: str = "hiring_cafe"
    slug: str
    label: str
    commitment: str = "full_time"
    max_pages: int = 1
    enabled: bool = True
    # search_query: raw search text (e.g. "senior sre remote"). When present,
    # adapters that support structured search (like hiring.cafe searchState) use
    # it instead of the slug. Falls back to slug-based URL when absent.
    search_query: str | None = None
    # posted_within_days: computed at runtime from last_run_at (not a static
    # config value). When set, the adapter requests only jobs posted within this
    # many days. None means no date filter (full pull).
    posted_within_days: int | None = None
    # Server-side filter hints (Phase 2). Populated by the pipeline runner from
    # FilterConfig. Each adapter maps these to its own server-side filter format.
    # Adapters that don't support a given filter simply ignore it. Server-side
    # filters are inclusive of null/missing values (jobs with no data for a field
    # still pass the filter), so these are safe pre-filters — Tier 2 remains the
    # authoritative filter.
    workplace_types: list[str] | None = None
    commitments: list[str] | None = None
    seniority_levels: list[str] | None = None
    role_types: list[str] | None = None


class FilterResult(BaseModel):
    """Result of applying Tier 2 hard filters to a job."""
    passed: bool
    reason: str = ""


class ScoreResult(BaseModel):
    """Result of scoring a job against the rubric."""
    score: float
    reasons: list[str] = []
    gaps: list[str] = []
    hard_reject: bool = False
    reject_reason: str | None = None
    # Research-adjusted scoring (Phase 3.2)
    research_adjusted_score: float | None = None
    research_delta: float = 0.0
    research_breakdown: list[dict] = []  # [{factor, delta, confidence, source_section}]


class DedupResult(BaseModel):
    """Result of checking a job for duplicates."""
    is_duplicate: bool
    layer: str = ""              # 'url_hash', 'composite', 'content_hash', 'fuzzy'
    matched_job_id: int | None = None
    confidence: str = ""         # 'exact', 'high', 'medium'


class JDFetchResult(BaseModel):
    """Result of fetching a full JD for a job."""
    job_id: int                  # Seeker OS job ID
    jd_text: str = ""
    status: str                  # fetched, failed, skipped
    source_used: str = ""
    error: str | None = None


class CrossRefResult(BaseModel):
    """Result of cross-referencing a job against the job-search repo."""
    matched: bool
    prior_status: str | None = None      # applied, rejected, closed, opportunities, found
    prior_date: str | None = None
    prior_score: float | None = None
    match_confidence: str = ""           # exact, high, fuzzy


class PipelineRunResult(BaseModel):
    """Summary of a pipeline run."""
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


class PipelineProgressEvent(BaseModel):
    """Progress event emitted during pipeline execution."""
    step: str  # "discovery", "filtering", "jd_fetch", "scoring", "ranking"
    step_label: str  # Human-readable label
    status: str  # "started", "in_progress", "completed"
    current: int = 0  # Current item being processed
    total: int = 0  # Total items to process
    detail: str = ""  # Extra info (e.g. "Fetching from hiring.cafe/jobs/sre...")
    # Running counts
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
