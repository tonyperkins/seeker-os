"""API schemas — Pydantic models for API request/response.

These are separate from the internal models in models.py because:
- API schemas are typed for JSON serialization (camelCase, optional fields)
- Internal models are typed for pipeline logic (snake_case, required fields)
- The API layer converts between them
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

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
    comp_source: str | None = None
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
    reject_details: str | None = None
    source_id: str = ""
    discovered_query: str = ""
    run_id: str | None = None

    # Derived recruiter indicator (computed from recruiter_contacts table)
    has_recruiter: bool = False
    recruiter_source: str | None = None

    # Derived stale flag (computed, never stored)
    is_stale: bool = False
    days_since_last_activity: int | None = None

    # Derived indicator flags (computed from related tables, never stored)
    has_analysis: bool = False
    has_research: bool = False
    has_resume: bool = False
    analysis_verdict: str | None = None
    net_score: float | None = None
    ai_policy: str | None = None
    score_modifiers: dict[str, float] = {}
    score_reasons: list[str] = []

    @field_validator("comp_min", "comp_max", mode="before")
    @classmethod
    def _round_comp(cls, v):
        if v is None:
            return None
        return int(round(float(v)))


class PaginatedJobsResponse(BaseModel):
    """A stable, typed page of jobs returned by ``GET /api/jobs``."""

    jobs: list[JobSummary]
    total: int


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
    comp_source: str | None = None
    technical_tools: list[str] = []
    requirements_summary: str = ""
    date_posted: str = ""
    role_type: str | None = None

    @field_validator("comp_min", "comp_max", mode="before")
    @classmethod
    def _round_comp(cls, v):
        if v is None:
            return None
        return int(round(float(v)))

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
    ai_policy: str | None = None

    # Research-adjusted scoring (Phase 3.2)
    research_adjusted_score: float | None = None
    research_delta: float = 0.0

    # AI analysis verdict + delta (shown as modifier card)
    analysis_verdict: str | None = None
    analysis_delta: float = 0.0

    # Net score (composite: base + research_delta, capped by verdict)
    net_score: float | None = None

    # Manual job metadata + override audit
    filter_warnings: list[str] = []
    overridden_at: str | None = None
    override_note: str | None = None
    original_reject_reason: str | None = None

    # Application lifecycle events timeline
    events: list[ApplicationEvent] = []

    # Recruiter contacts (one-to-many — supports multiple recruiters per job)
    recruiter_contacts: list[RecruiterContact] = []

    # Derived stale flag (computed, never stored)
    is_stale: bool = False
    days_since_last_activity: int | None = None


class JobCreate(BaseModel):
    """POST /api/jobs — manually add a job.

    Either a URL or jd_text (or both) must be provided. When only jd_text is
    given (e.g. a recruiter emailed a JD with no link), the job is created
    directly from the pasted text with a synthetic URL for dedup purposes.
    All other fields are optional (user may provide known details; the
    backend fills gaps from JD fetch when possible).
    If jd_text is provided, JD fetch is skipped.
    """
    url: str = ""
    title: str = ""
    company: str = ""
    location: str = ""
    workplace_type: str = ""
    seniority_level: str | None = None
    comp_min: int | None = None
    comp_max: int | None = None
    comp_currency: str | None = None
    company_homepage: str | None = None
    jd_text: str | None = None  # paste-JD path — skip fetch when provided
    force: bool = False  # bypass soft-duplicate check (content hash match)
    # Recruiter contact info (creates a recruiter_contacts record on job creation)
    recruiter_name: str | None = None
    recruiter_email: str | None = None
    recruiter_phone: str | None = None
    recruiter_linkedin: str | None = None
    recruiter_agency: str | None = None
    recruiter_source: str | None = None
    recruiter_contacted_at: str | None = None  # ISO datetime when recruiter reached out

    @model_validator(mode="after")
    def _require_url_or_jd(self):
        if not self.url.strip() and not (self.jd_text and self.jd_text.strip()):
            raise ValueError("Either url or jd_text must be provided")
        return self

    @field_validator("comp_min", "comp_max", mode="before")
    @classmethod
    def _round_comp(cls, v):
        if v is None:
            return None
        return int(round(float(v)))


class JobCreateResponse(BaseModel):
    """Response from POST /api/jobs.

    status is one of:
    - 'created': job inserted and scored successfully
    - 'already_exists': url_hash matched an existing job — existing_job_id set
    - 'fetch_failed': JD fetch from URL failed — no job inserted; frontend
      should prompt user to paste JD and re-submit with jd_text
    - 'possible_duplicate': content hash matched an existing job — NO insert;
      existing_job_id and existing_summary set. Frontend should ask user to
      confirm and re-submit with force=true to insert anyway.
    - 'likely_duplicate': content hash matched but force=true — job was
      inserted (warning only); existing_job_id set
    """
    status: str
    job: JobDetail | None = None
    existing_job_id: int | None = None
    existing_summary: str | None = None
    fetch_error: str | None = None
    filter_warnings: list[str] = []


class JobOverride(BaseModel):
    """POST /api/jobs/{id}/override — override a rejection with audit trail."""
    note: str | None = None
    target_status: str = "ready"  # 'ready' or 'interested'


class JobUpdate(BaseModel):
    """PATCH /api/jobs/{id} — partial update."""
    status: str | None = None
    notes: str | None = None
    is_pinned: bool | None = None
    ai_policy: str | None = None
    # Editable job details
    title: str | None = None
    company: str | None = None
    location: str | None = None
    workplace_type: str | None = None
    seniority_level: str | None = None
    role_type: str | None = None
    comp_min: int | None = None
    comp_max: int | None = None
    comp_currency: str | None = None
    company_homepage: str | None = None
    apply_url: str | None = None
    jd_full: str | None = None

    @field_validator("comp_min", "comp_max", mode="before")
    @classmethod
    def _round_comp(cls, v):
        if v is None:
            return None
        return int(round(float(v)))


class RecruiterContact(BaseModel):
    """Recruiter contact read model — joins recruiter entity + association fields."""
    id: int                   # recruiter_job_contacts.id (association PK)
    recruiter_id: int         # recruiters.id (entity PK)
    job_id: int
    # Entity fields (from recruiters table)
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    linkedin: str | None = None
    agency: str | None = None
    # Association fields (from recruiter_job_contacts table)
    source: str | None = None
    contacted_at: str | None = None
    notes: str | None = None
    created_at: str = ""
    updated_at: str = ""


class RecruiterContactCreate(BaseModel):
    """POST /api/jobs/{id}/recruiters — link or create a recruiter for a job.

    If recruiter_id is provided, links an existing recruiter (ignores inline
    entity fields). Otherwise creates a new recruiter from inline fields.
    Upserts on UNIQUE(recruiter_id, job_id): if the pair already exists,
    updates source/notes; does NOT overwrite contacted_at.
    """
    recruiter_id: int | None = None
    # Inline entity fields (used when recruiter_id is None)
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    linkedin: str | None = None
    agency: str | None = None
    # Association fields
    source: str | None = None
    contacted_at: str | None = None
    notes: str | None = None


class RecruiterEntityUpdate(BaseModel):
    """PATCH /api/recruiters/{id} — update recruiter entity (affects all associations)."""
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    linkedin: str | None = None
    agency: str | None = None


class RecruiterAssociationUpdate(BaseModel):
    """PATCH /api/jobs/recruiters/{id} — update association fields only.

    source and notes are editable. contacted_at is write-once (set on create,
    never overwritten) and is NOT accepted here.
    """
    source: str | None = None
    notes: str | None = None


class RecruiterSearchResult(BaseModel):
    """GET /api/recruiters/search — autocomplete result."""
    id: int
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    linkedin: str | None = None
    agency: str | None = None
    job_count: int = 0


class JobReject(BaseModel):
    """POST /api/jobs/{id}/reject."""
    reason: str
    details: str | None = None  # free-text feedback on why the job was rejected


class JobSkip(BaseModel):
    """POST /api/jobs/{id}/skip."""
    reason: str | None = None
    details: str | None = None


class SkipReasonAnnotate(BaseModel):
    """POST /api/jobs/{id}/annotate-skip — add a reason to an existing skip/rejected event."""
    reason: str
    details: str | None = None


class SkipReasonOption(BaseModel):
    """A single skip reason option for the UI."""
    key: str
    label: str = ""
    hint: str = ""
    free_text: bool = False


class NoReasonSkip(BaseModel):
    """A skipped/rejected job with no reason in its event metadata."""
    job_id: int
    title: str | None = None
    company: str | None = None
    status: str
    event_id: int
    event_type: str
    occurred_at: str


class MessageResponse(BaseModel):
    """Generic message response."""
    message: str


class LangfuseStatusResponse(BaseModel):
    """Status of the Langfuse tracing sink."""
    enabled: bool = False
    initialized: bool = False
    base_url: str = ""
    capture_content: bool = False
    keys_configured: bool = False


class RefilterRescoreRequest(BaseModel):
    """POST /api/jobs/refilter-rescore."""
    job_ids: list[int] | None = None
    run_id: str | None = None


class RefilterRescoreResult(BaseModel):
    """Result of a refilter&rescore operation."""
    job_id: int
    status: str
    score: float | None = None
    net_score: float | None = None
    previous_score: float | None = None
    previous_status: str | None = None
    score_changed: bool = False
    status_changed: bool = False
    filter_passed: bool
    filter_reason: str | None = None
    research_applied: bool = False
    analysis_verdict: str | None = None


# ---------------------------------------------------------------------------
# Application Event schemas
# ---------------------------------------------------------------------------

class ApplicationEvent(BaseModel):
    """An event in the job application lifecycle (read model).

    job_id is None for global events (notes/calls not tied to a job).
    """
    id: int
    job_id: int | None = None
    event_type: str
    actor: str
    occurred_at: str
    created_at: str
    metadata: dict | None = None
    note: str | None = None


class ApplicationEventCreate(BaseModel):
    """Payload for creating an event.

    occurred_at is editable (defaults to server now). created_at is NOT
    settable — it is always server-set and never appears in this model.
    """
    event_type: str
    actor: str = "candidate"
    occurred_at: str | None = None
    metadata: dict | None = None
    note: str | None = None


class GlobalEventCreate(BaseModel):
    """POST /api/events — manual event, optionally tied to a job.

    Only manual event types (note, call, email_sent, email_received, meeting,
    interview) are accepted; lifecycle events must go through their own
    endpoints so status and event stay in sync.
    """
    event_type: str
    job_id: int | None = None
    actor: str = "candidate"
    occurred_at: str | None = None
    metadata: dict | None = None
    note: str | None = None


class EventUpdate(BaseModel):
    """PATCH /api/events/{id} — edit a manual event. All fields optional.

    Only manual event types may be edited; event_type may only change to
    another manual type. metadata/note set to null explicitly are cleared.
    """
    event_type: str | None = None
    occurred_at: str | None = None
    metadata: dict | None = None
    note: str | None = None


class ActivityEvent(ApplicationEvent):
    """Event enriched with job context for the global activity feed."""
    job_title: str | None = None
    job_company: str | None = None


class PostApplyTransition(BaseModel):
    """POST /api/jobs/{id}/transition — post-apply status transition.

    For: company_rejected, withdrawn, engaged, offer_accepted, offer_declined.
    Each maps to a specific event_type + actor; the API enforces valid transitions.
    """
    target_status: str
    occurred_at: str | None = None
    note: str | None = None
    metadata: dict | None = None


class EngagedEventCreate(BaseModel):
    """POST /api/jobs/{id}/engaged-events — log an engaged sub-lifecycle event.

    Does NOT change status. event_type must be one of the EngagedEventType values.
    """
    event_type: str
    occurred_at: str | None = None
    note: str | None = None
    metadata: dict | None = None


class CleanStartCreate(BaseModel):
    """POST /api/jobs/{id}/clean-start — enter a job directly at a post-apply status.

    Sets status directly (applied, engaged, company_rejected, withdrawn,
    offer_accepted, offer_declined, rejected) with a backdated event.
    Skips the pre-apply funnel entirely.

    When entering at engaged or company_rejected, an optional applied_occurred_at
    may be supplied to record a backdated 'applied' event first (complete funnel
    history). If omitted, the job stands at engaged/rejected with no applied event.
    """
    target_status: str
    occurred_at: str | None = None
    applied_occurred_at: str | None = None
    note: str | None = None
    metadata: dict | None = None


# ---------------------------------------------------------------------------
# Pipeline schemas
# ---------------------------------------------------------------------------

class PipelineRunRequest(BaseModel):
    """POST /api/pipeline/run."""
    tiers: list[int] | None = None
    queries: list[str] | None = None
    dry_run: bool = False
    force_full_pull: bool = False


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
    search_query: str | None = None


class QueryCreate(BaseModel):
    """POST /api/queries."""
    source_id: str = "hiring_cafe"
    slug: str
    label: str
    commitment: str = "full_time"
    max_pages: int = 1
    enabled: bool = True
    search_query: str | None = None


class QueryUpdate(BaseModel):
    """PATCH /api/queries/{id}."""
    label: str | None = None
    commitment: str | None = None
    max_pages: int | None = None
    enabled: bool | None = None
    search_query: str | None = None
    clear_search_query: bool = False


# ---------------------------------------------------------------------------
# Settings schemas
# ---------------------------------------------------------------------------

class SettingsResponse(BaseModel):
    """GET /api/settings — returns all config."""
    filters: dict | None = None
    scoring: dict | None = None
    sources: dict | None = None
    profile_loaded: bool = False
    profile_configured: bool = False
    queries_count: int = 0
    skip_reasons: list[SkipReasonOption] = []


class SettingUpdate(BaseModel):
    """PATCH /api/settings/{key}."""
    value: str


# ---------------------------------------------------------------------------
# Profile & Filter schemas (editable via settings UI)
# ---------------------------------------------------------------------------

class ContactInfoSchema(BaseModel):
    name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    urls: dict[str, str] = {}


class ProfileResponse(BaseModel):
    """GET /api/profile — full profile config."""
    user: dict
    contact: ContactInfoSchema = ContactInfoSchema()
    location: dict
    comp: dict
    experience: dict
    employment: dict
    blacklist: list[str] = []
    resume: dict
    cross_reference: dict
    hard_rejects: list[dict] = []
    instructions: str = ""


class ProfileUpdate(BaseModel):
    """PUT /api/profile — update profile config."""
    user: dict | None = None
    contact: ContactInfoSchema | None = None
    location: dict | None = None
    comp: dict | None = None
    experience: dict | None = None
    employment: dict | None = None
    blacklist: list[str] | None = None
    resume: dict | None = None
    cross_reference: dict | None = None
    hard_rejects: list[dict] | None = None
    instructions: str | None = None


class FiltersResponse(BaseModel):
    """GET /api/filters — filter config + title filters."""
    filters: dict
    title_filters: dict


class FiltersUpdate(BaseModel):
    """PUT /api/filters — update filter config."""
    filters: dict | None = None
    title_filters: dict | None = None


class AccuracyRule(BaseModel):
    """A single accuracy rule for resume validation."""
    id: str
    description: str = ""
    type: str  # disallowed_phrases, forbidden_technologies, required_phrases, experience_anchor, education_omission
    severity: str = "medium"  # high or medium
    phrases: list[str] | None = None
    technologies: list[str] | None = None
    patterns: list[str] | None = None


class AccuracyRulesResponse(BaseModel):
    """GET /api/accuracy-rules — all accuracy rules."""
    rules: list[AccuracyRule]


class AccuracyRulesUpdate(BaseModel):
    """PUT /api/accuracy-rules — replace all accuracy rules."""
    rules: list[AccuracyRule]


class ResumeParseResult(BaseModel):
    """POST /api/resumes/parse — extracted data from resume."""
    contact: ContactInfoSchema = ContactInfoSchema()
    experience_years: int | None = None
    current_title: str = ""
    key_skills: list[str] = []
    suggested_title_positive: list[str] = []
    suggested_comp_floor: int | None = None
    summary: str = ""


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


class MovementEvent(BaseModel):
    """A single status-transition event in the movement feed."""
    job_id: int
    job_title: str = ""
    company: str = ""
    event_type: str = ""
    from_status: str | None = None
    to_status: str = ""
    occurred_at: str = ""
    actor: str = ""
    note: str | None = None


class MovementReport(BaseModel):
    """GET /api/analytics/movement."""
    events: list[MovementEvent] = []
    total: int = 0
    rejection_count: int = 0
    rejection_breakdown: dict[str, int] = {}


class AgingBucket(BaseModel):
    """Aging stats for jobs in a given status."""
    status: str
    count: int = 0
    avg_days: float = 0.0
    max_days: int = 0
    stale_count: int = 0


class AgingReport(BaseModel):
    """GET /api/analytics/aging."""
    buckets: list[AgingBucket] = []
    stale_after_days: int = 14


class VerdictDistribution(BaseModel):
    """Verdict distribution entry."""
    verdict: str
    count: int = 0
    pct: float = 0.0


class SignalQualityReport(BaseModel):
    """GET /api/analytics/signal-quality."""
    total_analyzed: int = 0
    verdicts: list[VerdictDistribution] = []
    apply_rate: float = 0.0
    skip_rate: float = 0.0
    false_positive_pct: float = 0.0
    false_negative_pct: float = 0.0
    calibration_available: bool = False
    partial: bool = False
    warnings: list[str] = Field(default_factory=list)


class SpendByTask(BaseModel):
    """Token usage and cost for a single task type."""
    task: str
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost: float = 0.0


class SpendByModel(BaseModel):
    """Token usage and cost for a single provider+model."""
    provider: str
    model: str
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost: float = 0.0
    input_price_per_mtok: float | None = None
    output_price_per_mtok: float | None = None
    pricing_source: str = ""  # "yaml", "auto", "yaml+auto", or ""
    pricing_fetched_at: str | None = None  # ISO timestamp for auto-fetched pricing


class PricingRouteComparison(BaseModel):
    """Price difference for the same underlying model across routes."""
    model: str  # underlying model id (without provider prefix)
    routes: list[dict] = []  # [{provider, input_price, output_price}]
    variance_pct: float = 0.0  # max variance between routes


class SpendReport(BaseModel):
    """GET /api/analytics/spend."""
    total_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_estimated_cost: float = 0.0
    pricing_configured: bool = False
    by_task: list[SpendByTask] = []
    by_model: list[SpendByModel] = []
    cost_per_ready: float | None = None
    cost_per_applied: float | None = None
    pricing_fetched_at: str | None = None  # oldest auto-fetched pricing timestamp
    pricing_stale: bool = False  # true if any auto-fetched pricing is older than threshold
    pricing_stale_after_days: int = 30  # configured threshold
    route_pricing: list[PricingRouteComparison] = []  # cross-route price differences
    partial: bool = False
    warnings: list[str] = Field(default_factory=list)


class ObservabilityOperation(BaseModel):
    operation_id: str
    started_at: str
    completed_at: str | None = None
    status: str
    calls: int = 0
    estimated_cost: float = 0.0
    validation_passed: bool | None = None
    artifact_type: str | None = None
    artifact_id: int | None = None
    job_id: int | None = None
    job_title: str | None = None
    company: str | None = None
    task: str = ""
    grouped: bool = True
    model: str | None = None
    total_tokens: int = 0
    latency_ms: int = 0


class ObservabilitySummary(BaseModel):
    total_calls: int = 0
    total_estimated_cost: float = 0.0
    failed_calls: int = 0
    truncated_calls: int = 0
    validation_pass_rate: float | None = None
    unsupported_claims: int = 0
    overstated_claims: int = 0
    cost_per_passing_resume: float | None = None
    historical_data_incomplete: bool = True
    available_tasks: list[str] = Field(default_factory=list)
    recent_operations: list[ObservabilityOperation] = Field(default_factory=list)


class ObservabilityTaskSummary(BaseModel):
    task: str = ""
    calls: int = 0
    estimated_cost: float = 0.0
    failed_calls: int = 0
    truncated_calls: int = 0
    avg_latency_ms: int = 0
    total_tokens: int = 0
    models_used: list[str] = Field(default_factory=list)
    validation_pass_rate: float | None = None
    unsupported_claims: int = 0
    overstated_claims: int = 0
    cost_per_passing_resume: float | None = None


class ObservabilityCall(BaseModel):
    call_id: str
    parent_call_id: str | None = None
    task: str
    provider: str | None = None
    model: str | None = None
    status: str
    error_type: str | None = None
    stop_reason: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    prompt_name: str | None = None
    prompt_version: str | None = None
    route_reason: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    estimated_cost: float = 0.0
    started_at: str


class ObservabilityEvaluation(BaseModel):
    evaluation_id: str
    evaluator_name: str
    evaluator_type: str = ""
    evaluator_version: str = ""
    metric_name: str
    score: float | None = None
    label: str | None = None
    passed: bool | None = None
    evaluated_at: str


class ObservabilityOperationDetail(BaseModel):
    operation_id: str
    artifact_type: str | None = None
    artifact_id: int | None = None
    job_id: int | None = None
    job_title: str | None = None
    company: str | None = None
    calls: list[ObservabilityCall] = Field(default_factory=list)
    evaluations: list[ObservabilityEvaluation] = Field(default_factory=list)


class AnalysisBackfillRequest(BaseModel):
    """POST /api/jobs/analysis/backfill body."""
    limit: int | None = Field(default=None, ge=1)  # None → auto_analysis.max_per_run


class AnalysisBackfillResponse(BaseModel):
    """POST /api/jobs/analysis/backfill result."""
    resynced: int = 0            # verdicts re-denormalized from existing analyses (no LLM)
    candidates: int = 0          # jobs selected for LLM analysis this batch
    analyzed: int = 0
    failed: int = 0
    job_ids: list[int] = []
    errors: list[str] = []
    remaining_unanalyzed: int = 0  # high-scorers still without a verdict after this batch


class ScoreBucket(BaseModel):
    """One net-score bucket in the calibration report."""
    bucket: str                  # display label, e.g. "6–7"
    min_score: float             # inclusive lower edge
    max_score: float             # exclusive upper edge
    total: int = 0
    applied: int = 0
    skipped: int = 0
    ignored: int = 0
    applied_pct: float = 0.0
    skipped_pct: float = 0.0
    ignored_pct: float = 0.0


class CalibrationMiss(BaseModel):
    """A scoring miss — high-score-but-skipped or low-score-but-applied job.

    Carries the full fired-signal breakdown so the cause is inspectable.
    """
    job_id: int
    title: str | None = None
    company: str | None = None
    net_score: float
    base_score: float | None = None
    research_adjusted_score: float | None = None
    analysis_verdict: str | None = None
    decision: str                # applied | skipped
    decision_reason: str | None = None
    base_score_label: str | None = None        # fired base-score pattern label
    positive_modifiers: dict[str, float] = {}  # signal → realized points (>= 0)
    negative_modifiers: dict[str, float] = {}  # signal → realized points (< 0)
    research_factors: list[dict] = []          # [{factor, delta, confidence, source_section}]


class ModifierPrecision(BaseModel):
    """Empirical precision of one rubric signal — of jobs where it fired, how many were applied to."""
    signal: str
    in_rubric: bool = True       # False = fired historically but no longer in the rubric
    fired: int = 0
    applied: int = 0
    skipped: int = 0
    ignored: int = 0
    precision: float = 0.0                     # applied / fired
    decided_precision: float | None = None     # applied / (applied + skipped); None if no decisions
    lift: float | None = None                  # precision / base_apply_rate; None if base rate is 0


class CalibrationReport(BaseModel):
    """GET /api/analytics/calibration."""
    bucket_width: float
    high_score_threshold: float  # false positives: skipped with net >= this
    low_score_threshold: float   # false negatives: applied with net < this
    total_scored: int = 0
    total_unscored: int = 0      # jobs with no score at all (excluded from the report)
    high_score_unanalyzed: int = 0  # net >= high threshold but no analysis verdict (uncapped scores)
    base_apply_rate: float = 0.0 # total_applied / total_scored — reference point for modifier lift
    total_applied: int = 0
    total_skipped: int = 0
    total_ignored: int = 0
    skip_reason_summary: dict[str, int] = {}   # reason key → count
    skip_no_reason: int = 0                    # skipped with no reason in metadata
    buckets: list[ScoreBucket] = []
    false_positives: list[CalibrationMiss] = []
    false_negatives: list[CalibrationMiss] = []
    modifier_precision: list[ModifierPrecision] = []


# ---------------------------------------------------------------------------
# Generic
# ---------------------------------------------------------------------------

class ErrorResponse(BaseModel):
    detail: str


# ---------------------------------------------------------------------------
# Company Research schemas
# ---------------------------------------------------------------------------

class WikipediaInfoSchema(BaseModel):
    """Company info from Wikipedia."""
    title: str = ""
    description: str = ""
    extract: str = ""
    url: str | None = None
    thumbnail: str | None = None


class SourceRefSchema(BaseModel):
    """A source URL with retrieval date."""
    url: str = ""
    retrieved: str = ""


class LayoffEventSchema(BaseModel):
    """A single layoff event."""
    date: str | None = None
    pct: float | None = None
    count: int | None = None
    source: str | None = None


class LastRoundSchema(BaseModel):
    """Most recent funding round."""
    type: str | None = None
    amount_usd: int | None = None
    date: str | None = None
    lead_investors: list[str] = []


class FundingDossierSchema(BaseModel):
    """Funding / company stage section of the dossier."""
    founded: int | None = None
    hq: str | None = None
    public: bool = False
    stage: str | None = None
    total_raised_usd: int | None = None
    valuation_usd: int | None = None
    last_round: LastRoundSchema | None = None
    headcount: str | None = None

    @field_validator("headcount", mode="before")
    @classmethod
    def _coerce_headcount(cls, v):
        if isinstance(v, int):
            return str(v)
        return v

    headcount_trend: str | None = None
    layoffs: list[LayoffEventSchema] = []
    financial_health: str | None = None
    confidence: float = 0.0
    sources: list[SourceRefSchema] = []
    stripped_count: int = 0


class SentimentThemeSchema(BaseModel):
    """A recurring positive or negative theme in employee sentiment."""
    theme: str = ""
    frequency: str = "low"
    paraphrase: str = ""
    source: str = ""
    age_months: int | None = None


class SentimentDossierSchema(BaseModel):
    """Employee sentiment section of the dossier."""
    overall_rating_estimate: float | None = None
    rating_scale: str = "out of 5"
    ceo_approval_pct: float | None = None
    recommend_pct: float | None = None
    positives: list[SentimentThemeSchema] = []
    negatives: list[SentimentThemeSchema] = []
    staleness_warning: str | None = None
    confidence: float = 0.0
    sources: list[SourceRefSchema] = []
    stripped_count: int = 0


class FitDossierSchema(BaseModel):
    """Fit signals section of the dossier."""
    remote_policy: str | None = None
    remote_walkback: str | None = None
    size_bucket: str | None = None
    ic_vs_mgmt_culture: str | None = None
    comp_band: str | None = None
    clearance_required: bool = False
    confidence: float = 0.0
    sources: list[SourceRefSchema] = []
    stripped_count: int = 0


class VerdictFlagsSchema(BaseModel):
    """Green / red / watch flags for the company."""
    green: list[str] = []
    red: list[str] = []
    watch: list[str] = []


class CompanyResearchResponse(BaseModel):
    """Company research result."""
    id: int | None = None
    triggered_by_job_id: int | None = None
    company_name: str
    company_homepage: str | None = None
    wikipedia: WikipediaInfoSchema | None = None
    overall_confidence: float = 0.0
    summary: str = ""
    verdict_flags: VerdictFlagsSchema = VerdictFlagsSchema()
    funding: FundingDossierSchema | None = None
    sentiment: SentimentDossierSchema | None = None
    fit: FitDossierSchema | None = None
    gaps: list[str] = []
    sources_used: list[str] = []
    errors: list[str] = []
    researched_at: str = ""
    verification_state: str = "unverified"
    retrieval_used: bool = False
    retrieval_sources: list[SourceRefSchema] = []
    retrieval_snippets: list[dict] = []
    reused_from_cache: bool = False
    dossier_age_days: int | None = None
    # Research-adjusted scoring (Phase 3.2)
    research_adjusted_score: float | None = None
    research_delta: float = 0.0
    research_breakdown: list[dict] = []
    research_adjustment_applied: bool = False


# ---------------------------------------------------------------------------
# JD Analysis schemas
# ---------------------------------------------------------------------------

class NamedGapSchema(BaseModel):
    """A single named gap between JD requirements and candidate profile."""
    area: str = ""
    jd_requires: str = ""
    candidate_actual: str = ""
    severity: str = "low"


class HardBlockerSchema(BaseModel):
    """A hard blocker that prevents applying regardless of score."""
    type: str = ""
    detail: str = ""


class RubricDimensionSchema(BaseModel):
    """A single rubric dimension score breakdown."""
    dimension: str = ""
    weight: float = 0.0
    raw: float = 0.0
    weighted: float = 0.0
    note: str = ""


class CompAssessmentSchema(BaseModel):
    """Compensation assessment against floor."""
    posted: str | float | None = None
    meets_floor: bool | None = None
    note: str = ""

    @field_validator("meets_floor", mode="before")
    @classmethod
    def _coerce_meets_floor(cls, v):
        if v is None or isinstance(v, bool):
            return v
        if isinstance(v, str):
            v_lower = v.strip().lower()
            if v_lower in ("true", "yes", "1"):
                return True
            if v_lower in ("false", "no", "0"):
                return False
            return None
        return bool(v)


class PositioningSchema(BaseModel):
    """Positioning alignment assessment."""
    aligned: bool = True
    note: str = ""


class CompanyFitSchema(BaseModel):
    """Company fit assessment."""
    size_bucket: str | None = None
    stage: str | None = None
    remote_policy: str | None = None
    note: str = ""


class TailoringSchema(BaseModel):
    """Tailoring guidance for resume generation."""
    lead_with: list[str] = []
    reframe_summary: str = ""
    do_not_claim: list[str] = []


class JobAnalysisResponse(BaseModel):
    """Full JD analysis result — returned by the analysis agent."""
    id: int | None = None
    job_id: int
    # LLM metadata
    provider: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    # Analysis fields (from LLM output schema)
    company: str = ""
    title: str = ""
    url: str = ""
    analyzed_at: str = ""
    verdict: str = ""
    weighted_score: float = 0.0
    one_line: str = ""
    named_gaps: list[NamedGapSchema] = []
    hard_blockers: list[HardBlockerSchema] = []
    rubric_breakdown: list[RubricDimensionSchema] = []
    bonuses_applied: list[str] = []
    penalties_applied: list[str] = []
    comp: CompAssessmentSchema = CompAssessmentSchema()
    positioning: PositioningSchema = PositioningSchema()
    company_fit: CompanyFitSchema = CompanyFitSchema()
    tailoring: TailoringSchema = TailoringSchema()
    red_flags: list[str] = []
    confidence: float = 0.0
