"""Settings management — loads all YAML configs, .env, and validates them.

Config loading order:
1. Load .env file (via python-dotenv) at startup, before any config parsing
2. YAML config files are loaded and parsed
3. ${ENV_VAR} references in YAML are resolved against os.environ
4. Path values (e.g. ~/projects/job-search) are expanded
5. Pydantic models validate the final merged config; validation errors are fatal
"""

from __future__ import annotations

import os
import re
import threading
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"


def expand_path(value: str) -> str:
    """Expand ~ and relative paths. Relative paths resolve against project root."""
    if not value:
        return value
    p = Path(value).expanduser()
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return str(p)


# ---------------------------------------------------------------------------
# Env var resolution
# ---------------------------------------------------------------------------

_ENV_VAR_PATTERN = re.compile(r"\$\{(\w+)\}")


def resolve_env_vars(value: Any) -> Any:
    """Recursively resolve ${VAR_NAME} references in a data structure."""
    if isinstance(value, str):
        def _replace(m: re.Match) -> str:
            var_name = m.group(1)
            return os.environ.get(var_name, m.group(0))  # leave as-is if not found
        return _ENV_VAR_PATTERN.sub(_replace, value)
    if isinstance(value, dict):
        return {k: resolve_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_env_vars(v) for v in value]
    return value


# Credential-like field names that should only hold ${VAR} references
_CREDENTIAL_FIELD_NAMES = {"api_key", "token", "secret", "password", "apikey"}
# Safe field names that may hold a non-${VAR} value (e.g. a file path)
_SAFE_CREDENTIAL_FIELDS = {"token_path"}


def _check_unresolved_env_refs(data: Any, filename: str) -> None:
    """Warn about ${VAR} references that did not resolve (env var unset).

    Does not fail; does not log any value. Only names the missing var
    and the config file it appeared in.
    """
    import warnings

    def _walk(obj: Any, path: str = "") -> None:
        if isinstance(obj, str):
            for m in _ENV_VAR_PATTERN.finditer(obj):
                var_name = m.group(1)
                if os.environ.get(var_name) is None:
                    field_hint = path.split(".")[-1] if path else "value"
                    warnings.warn(
                        f"{var_name} unset — referenced in {filename}"
                        f" (field: {field_hint})."
                        f" Feature gated by this var will be disabled.",
                        stacklevel=2,
                    )
        elif isinstance(obj, dict):
            for k, v in obj.items():
                _walk(v, f"{path}.{k}" if path else k)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                _walk(v, f"{path}[{i}]")

    _walk(data)


def _check_literal_secrets(data: Any, filename: str) -> None:
    """Warn if a credential-like field holds a literal value instead of a ${VAR} reference.

    Catches hand-edit mistakes: a key/token/secret/password field that contains
    a raw value instead of an env var reference. The UI path already does the
    right thing; this guards against manual edits to committed configs.

    Does not print the value. Does not fail.
    """
    import warnings

    def _walk(obj: Any, path: str = "") -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                field_path = f"{path}.{k}" if path else k
                if (
                    k.lower() in _CREDENTIAL_FIELD_NAMES
                    and field_path.split(".")[-1].lower() not in _SAFE_CREDENTIAL_FIELDS
                    and isinstance(v, str)
                    and v
                    and not v.startswith("${")
                ):
                    warnings.warn(
                        f"Literal value in credential field '{k}' in {filename}."
                        f" Secrets in committed configs must be ${{VAR}} references."
                        f" Put the literal in .env instead.",
                        stacklevel=2,
                    )
                _walk(v, field_path)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                _walk(v, f"{path}[{i}]")

    _walk(data)


# ---------------------------------------------------------------------------
# Pydantic config models
# ---------------------------------------------------------------------------

class UserIdentity(BaseModel):
    name: str
    email: str
    location: str


class ContactInfo(BaseModel):
    """Structured contact info extracted from resume or entered manually."""
    name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    urls: dict[str, str] = {}  # {"github": "...", "linkedin": "...", "portfolio": "...", "other": "..."}


class LocationPrefs(BaseModel):
    # Required — no silent default. User must explicitly choose whether to
    # filter for remote-only jobs.
    remote_only: bool
    accepted_cities: list[str] = []
    accepted_states: list[str] = []
    rejected_cities: list[str] = []


class CompPrefs(BaseModel):
    floor: int
    target: int
    stretch: int


class ExperiencePrefs(BaseModel):
    years: int
    anchor_phrase: str


class EmploymentPrefs(BaseModel):
    commitment: str
    reject_commitments: list[str] = []
    # Required — no silent default. User must explicitly choose their target
    # role type (e.g. "Individual Contributor", "Manager", or "" for no filter).
    role_type: str
    reject_role_types: list[str] = []


class ResumePrefs(BaseModel):
    master_path: str
    accuracy_rules_path: str
    output_dir: str
    contact_urls: list[str] = []

    @field_validator("master_path", "output_dir", "accuracy_rules_path")
    @classmethod
    def _expand(cls, v: str) -> str:
        return expand_path(v)


class CrossReferencePrefs(BaseModel):
    repo_path: str
    auto_pull: bool = True

    @field_validator("repo_path")
    @classmethod
    def _expand(cls, v: str) -> str:
        return expand_path(v)


class HardReject(BaseModel):
    reason: str
    pattern: str
    unless_pattern: str | None = None


class ProfileConfig(BaseModel):
    user: UserIdentity
    location: LocationPrefs
    comp: CompPrefs
    experience: ExperiencePrefs
    employment: EmploymentPrefs
    blacklist: list[str] = []
    defense_blocklist: list[str] = []
    resume: ResumePrefs
    cross_reference: CrossReferencePrefs
    hard_rejects: list[HardReject] = []
    # NEW: structured contact info (extracted from resume or manual entry)
    contact: ContactInfo = ContactInfo()
    # NEW: free-form instructions that guide scoring and resume generation
    instructions: str = ""


class BaseScoreRule(BaseModel):
    pattern: str | None = None
    score: float
    label: str
    check: str | None = None  # for jd_infra_role type rules
    patterns: list[str] | None = None  # configurable patterns for jd_infra_role check


class ModifierRule(BaseModel):
    signal: str
    pattern: str | None = None
    points: float | None = None  # required for non-dynamic check types; validator enforces
    check: str
    requires: str | None = None
    unless: str | None = None
    threshold: int | None = None
    threshold_min: int | None = None
    threshold_max: int | None = None
    requires_comp_below: int | None = None
    requires_comp_at_least: int | None = None
    patterns: list[str] | None = None  # for domain_mismatch check: off-domain term regexes
    min_distinct_hits: int = 3  # for domain_mismatch check: distinct pattern matches needed to fire
    # never_claim_density check: scaled penalty for never-claim tech density in JD
    points_per_hit: float | None = None  # e.g. -0.5 per distinct never-claim tech
    max_penalty: float | None = None  # clamp on scaled penalty, e.g. -2.5
    primary_stack_penalty: float | None = None  # applied instead of scaled when a never-claim term is in the title or heavily mentioned
    primary_stack_min_mentions: int = 3  # JD mention count threshold for primary_stack_penalty
    density_exclude: list[str] | None = None  # never-claim terms to skip in density count (scoring-layer only; identity list unchanged)

    # Check types that compute penalty dynamically (points not required)
    _DYNAMIC_PENALTY_CHECKS: frozenset[str] = frozenset({"never_claim_density"})

    @model_validator(mode="after")
    def _validate_points_required(self) -> ModifierRule:
        """Fail loud if points is missing on a non-dynamic check type."""
        if self.points is None and self.check not in self._DYNAMIC_PENALTY_CHECKS:
            raise ValueError(
                f"Modifier '{self.signal}' (check={self.check}) is missing required 'points' field. "
                f"Only check types {sorted(self._DYNAMIC_PENALTY_CHECKS)} may omit points."
            )
        return self


class FreshnessConfig(BaseModel):
    boost_days: int = 7
    neutral_days: int = 14
    penalty_days: int = 30
    hard_filter_days: int = 30


class ResearchModifierConfig(BaseModel):
    """A single research-adjustment rule from scoring_rubric.yml."""
    factor: str
    delta: float
    confidence_threshold: float = 0.5
    source_section: str  # "funding" | "sentiment" | "fit"
    # Optional cutoffs for headcount-based factors (right_size_company, large_company_confirmed)
    headcount_max: int | None = None
    headcount_min: int | None = None
    # Optional: name of a base-modifier signal to suppress when this research factor fires
    # (e.g. "large_enterprise" — compensates the JD-text penalty already baked into base_score)
    suppresses: str | None = None


class CalibrationConfig(BaseModel):
    """Scoring calibration report settings (scoring_rubric.yml `calibration` section).

    Thresholds of None resolve to the rubric's post_threshold at report time:
    "high" (false-positive floor) defaults to >= post_threshold, "low"
    (false-negative ceiling) defaults to < post_threshold.
    """
    bucket_width: float = Field(default=1.0, gt=0)
    high_score_threshold: float | None = None
    low_score_threshold: float | None = None


class AutoAnalysisConfig(BaseModel):
    """Auto-analysis policy (scoring_rubric.yml `auto_analysis` section).

    When enabled, jobs whose effective net score meets min_score and have no
    analysis verdict are analyzed automatically at the end of a pipeline run.
    Disabled by default — analysis stays manual/on-demand unless opted in.
    """
    enabled: bool = False
    min_score: float | None = None  # None → post_threshold at policy-eval time
    max_per_run: int = Field(default=10, ge=1)
    # Statuses considered decided-dead — excluded from analysis coverage
    # (high_score_unanalyzed metric and auto-analysis candidate selection).
    # Analyzing already-rejected jobs wastes LLM spend.
    analysis_excluded_statuses: list[str] = ["rejected", "company_rejected"]


class ScoringConfig(BaseModel):
    post_threshold: float = 6.0
    per_company_cap: int = 3
    max_score: int = 10
    min_score: int = 0
    base_scores: list[BaseScoreRule] = []
    positive_modifiers: list[ModifierRule] = []
    negative_modifiers: list[ModifierRule] = []
    freshness: FreshnessConfig = FreshnessConfig()
    research_modifiers: list[ResearchModifierConfig] = []
    verdict_caps: dict[str, float | None] = {}
    unknown_verdict_cap: float | None = None  # cap for unrecognized verdicts; defaults to CONDITIONAL cap if present
    calibration: CalibrationConfig = CalibrationConfig()
    auto_analysis: AutoAnalysisConfig = AutoAnalysisConfig()

    # Comp provenance: values above this are implausible regardless of source.
    # For parsed/none → treated as comp-unknown (no floor clear, no bonus).
    # For structured/manual → flagged/logged but still trusted (data error, not
    #   a parse artifact — the user should investigate).
    comp_sanity_max: int = 10_000_000
    # Provenance values that earn full trust (comp_target bonus, floor clearing).
    trusted_comp_sources: list[str] = ["structured", "manual"]

    # Evidence gate: minimum JD character length to score (shorter JDs are
    # rejected as insufficient evidence). Configurable per rubric.
    min_jd_length: int = 500

    # Location fallback patterns: if the location field is empty but the JD
    # text matches any of these patterns, the evidence gate passes (the job is
    # clearly remote or US-based). Uses re.search with IGNORECASE.
    # Also used by the location_only modifier to detect remote-job bypass.
    location_fallback_patterns: list[str] = ["remote", "united states", r"\bus\b"]

    # Metadata extraction: max characters of JD text sent to the LLM for
    # structured-field extraction (company, comp, seniority, etc.).
    metadata_max_jd_chars: int = 8000


class FilterConfig(BaseModel):
    # Required — no silent defaults. User must explicitly choose whether to
    # filter for remote-only and US-only jobs.
    remote_only: bool
    us_only: bool
    seniority_floor: list[str] = []
    seniority_reject: list[str] = []
    seniority_unknown_passes: bool = True
    # NEW: if title contains any of these, pass regardless of seniority_level tag
    seniority_title_override: list[str] = []
    # comp_floor is NOT here — it lives in profile.comp.floor (canonical source).
    # comp_floor_margin_pct applies a tolerance below profile.comp.floor.
    comp_floor_margin_pct: int = 0
    # NEW: if True, jobs with no comp data pass; if False, they're rejected
    comp_unknown_passes: bool = True
    # Comp provenance: values above this are implausible regardless of source.
    # In the filter, an implausible comp_max from any source is treated as
    # comp-unknown (does not clear the floor). Prevents the 130000000 misfire
    # from clearing the comp floor.
    comp_sanity_max: int = 10_000_000
    freshness_days: int = 30
    commitment_required: str = "Full Time"
    # NEW: locations to exclude even if us_only passes (states or cities)
    location_exclude: list[str] = []
    # NEW: cities where hybrid jobs are allowed even when remote_only=true
    hybrid_accepted_cities: list[str] = []
    # NEW: if True, only pass jobs that offer visa sponsorship
    visa_sponsorship_required: bool = False
    # Junior-level title patterns for title-based fallback when seniority_level
    # is None and seniority_unknown_passes is False. Configurable so users
    # targeting junior roles can empty or adjust this list.
    junior_title_patterns: list[str] = ["junior", "entry", "associate", "intern", "new grad", "early career"]


class TitleFilters(BaseModel):
    positive: list[str] = []
    negative: list[str] = []


class FiltersConfig(BaseModel):
    filters: FilterConfig
    title_filters: TitleFilters


class SourceConfig(BaseModel):
    id: str
    type: str
    label: str = ""
    enabled: bool = True
    base_url: str | None = None
    request_delay_seconds: float = 3.0
    jd_fetch_delay_seconds: float = 2.0
    user_agent: str = "Mozilla/5.0"
    cache_ttl_hours: int = 6
    max_retries: int = 3
    timeout_seconds: int = 15
    browser_fallback: bool = True
    source_map: dict[str, str] = {}


class SourcesConfig(BaseModel):
    sources: list[SourceConfig] = []


class QueryConfig(BaseModel):
    source_id: str = "hiring_cafe"
    slug: str
    label: str
    commitment: str = "full_time"
    max_pages: int = 1
    enabled: bool = True
    # search_query: raw search text (e.g. "senior sre remote"). When present,
    # the adapter builds a structured search URL (hiring.cafe searchState) instead
    # of the slug-based URL. Falls back to slug when absent (backward compat).
    search_query: str | None = None


class QueriesConfig(BaseModel):
    queries: list[QueryConfig] = []


class ProviderModel(BaseModel):
    id: str
    label: str = ""
    context_window: int | None = None
    max_output: int | None = None
    tags: list[str] = []
    # Pricing per 1M tokens (USD) — used for spend estimation
    input_price_per_mtok: float | None = None
    output_price_per_mtok: float | None = None


class ProviderConfig(BaseModel):
    id: str
    type: str  # 'anthropic' or 'openai_compatible'
    label: str = ""
    api_key: str | None = None
    base_url: str | None = None
    enabled: bool = True
    auto_fetch_models: bool = False
    models: list[ProviderModel] = []


class TierMapping(BaseModel):
    provider: str
    model: str


class TaskOverride(BaseModel):
    tier: str
    provider: str | None = None
    model: str | None = None
    max_tokens: int | None = None


class ProvidersConfig(BaseModel):
    providers: list[ProviderConfig] = []
    tiers: dict[str, TierMapping] = {}
    tasks: dict[str, TaskOverride] = {}
    # Auto-fetched pricing cache staleness threshold (days). When the cached
    # pricing data is older than this, pricing_stale=True in the spend report.
    pricing_stale_after_days: int = 30


# ---------------------------------------------------------------------------
# Identity rules models
# ---------------------------------------------------------------------------

class HonestQualifier(BaseModel):
    skill: str
    framing: str


class ExperienceAnchor(BaseModel):
    phrase: str = ""
    applies_to: str = ""
    disallowed_variants: list[str] = []


class IdentityConfig(BaseModel):
    positioning: str = ""
    work_eligibility: str = ""
    experience_anchor: ExperienceAnchor = ExperienceAnchor()
    honest_qualifiers: list[HonestQualifier] = []
    never_claim: list[str] = []


# ---------------------------------------------------------------------------
# Channel rules models
# ---------------------------------------------------------------------------

class ContentTieringConfig(BaseModel):
    target_pages: int = 2
    recent_years: int = 10
    mid_years: int = 20
    mid_max_bullets: int = 3
    old_max_bullets: int = 1


class ChannelConfig(BaseModel):
    require_visible_urls: bool = False
    format_hints: str = ""
    ai_generation_default: str = "allowed"
    content_tiering: ContentTieringConfig | None = None


class ChannelRulesConfig(BaseModel):
    resume: ChannelConfig = ChannelConfig()
    cover_letter: ChannelConfig = ChannelConfig()
    application_answer: ChannelConfig = ChannelConfig()
    analysis: ChannelConfig = ChannelConfig()


# ---------------------------------------------------------------------------
# Company research config models
# ---------------------------------------------------------------------------

class WikipediaConfig(BaseModel):
    enabled: bool = True
    language: str = "en"
    timeout_seconds: int = 10


class WikidataConfig(BaseModel):
    enabled: bool = True
    timeout_seconds: int = 10


class LLMDossierConfig(BaseModel):
    enabled: bool = True
    task: str = "company_dossier_generation"
    temperature: float = 0.3


class RetrievalProviderConfig(BaseModel):
    """Retrieval adapter configuration — provider type and credentials."""
    type: str = ""
    api_key: str = ""
    max_results: int = 5
    timeout_seconds: int = 15
    funding_query_template: str = "{company} funding round investors valuation"
    sentiment_query_template: str = "{company} employee reviews sentiment glassdoor culture"
    retrieval_cache_ttl_days: int = 7


class FitPreferencesConfig(BaseModel):
    """User-configurable fit preferences injected into the company dossier prompt.

    These are personal preferences, not product behavior. They tell the LLM
    what company characteristics the candidate is looking for so the fit
    section of the dossier is tailored to the individual.
    """
    preferred_size_bucket: str = ""
    preferred_stage: str = ""
    remote_policy: str = ""
    ic_vs_mgmt: str = ""
    clearance_ok: bool = True
    notes: str = ""


class LifecycleConfig(BaseModel):
    """Config for application lifecycle — stale flag threshold.

    Loaded from profile.yml under the 'lifecycle' key. If absent, defaults apply.
    """
    stale_after_days: int = 14


class CompanyResearchConfig(BaseModel):
    """Config for company_research.yml — controls research flow and thresholds."""
    wikipedia: WikipediaConfig = WikipediaConfig()
    wikidata: WikidataConfig = WikidataConfig()
    llm_dossier: LLMDossierConfig = LLMDossierConfig()
    retrieval: RetrievalProviderConfig = RetrievalProviderConfig()

    # HTTP User-Agent for Wikipedia/Wikidata requests (their robot policy requires one).
    # No personal handles — use a generic product identifier.
    user_agent: str = "SeekerOS/0.1 (product; contact: admin@example.com)"

    # Thresholds (Phase 3)
    confidence_floor: float = 0.3
    staleness_months: int = 18
    source_trust_order: list[str] = []

    # Phase 3 retrieval disambiguation: confidence floor for mismatch cases.
    # When Wikidata P856 doesn't match the company domain (wrong entity),
    # section confidence is clamped to this value via min(). Must be below
    # the research modifier confidence_threshold (typically 0.5) so
    # confidence-gated modifiers don't fire on wrong-entity research.
    mismatch_confidence: float = 0.2

    # Research TTL: reuse cached dossier within this many days (default ~30)
    research_ttl_days: int = 30

    # User-configurable fit preferences (injected into dossier prompt)
    fit_preferences: FitPreferencesConfig = FitPreferencesConfig()


class SkipReason(BaseModel):
    """A single structured skip/reject reason from skip_reasons.yml."""
    key: str
    label: str = ""
    hint: str = ""
    free_text: bool = False


class SkipReasonsConfig(BaseModel):
    """Config for skip_reasons.yml — structured reason choices for skip/reject."""
    skip_reasons: list[SkipReason] = []


# ---------------------------------------------------------------------------
# Observability models (Langfuse, budget caps, SLOs)
# ---------------------------------------------------------------------------

class LangfuseConfig(BaseModel):
    """Langfuse tracing configuration.

    Two modes: disabled (default, zero overhead) and external (URL + keys —
    covers the vendored stack, Langfuse Cloud, and any self-hosted instance).
    """
    enabled: bool = False
    base_url: str = "http://langfuse-web:3000"
    public_key: str = ""
    secret_key: str = ""
    capture_content: bool = False
    flush_interval_seconds: float = 1.0


class BudgetCapsConfig(BaseModel):
    """Daily/monthly caps for paid retrieval calls (Tavily).

    When a cap is exceeded, the retrieval adapter returns empty results and
    logs a WARNING. Set to 0 for unlimited (no cap).
    """
    tavily_daily_cap: int = 0
    tavily_monthly_cap: int = 0


class SLOConfig(BaseModel):
    """SLO targets for pipeline health indicators.

    All thresholds read from config — never hardcoded. Values are used by
    the /api/analytics/slo-status endpoint to compare actuals vs targets.

    Pipeline availability: fraction of distinct operation_ids over the SLO
    window whose LLM calls all completed without error (computed from ledger
    error rows). Window is in hours.
    """
    analysis_latency_p95_ms: int = 30_000
    pipeline_availability_target: float = 0.99
    daily_spend_budget_usd: float = 5.0
    slo_window_hours: int = 24


class ObservabilityConfig(BaseModel):
    """Umbrella config for observability.yml — Langfuse, budget caps, SLOs."""
    langfuse: LangfuseConfig = LangfuseConfig()
    budget_caps: BudgetCapsConfig = BudgetCapsConfig()
    slo: SLOConfig = SLOConfig()


# ---------------------------------------------------------------------------
# Settings — top-level config container
# ---------------------------------------------------------------------------

class Settings:
    """Loads and holds all configuration. Singleton-like — create once at startup."""

    def __init__(self, config_dir: Path | None = None):
        load_dotenv(PROJECT_ROOT / ".env")
        self.config_dir = config_dir if config_dir is not None else CONFIG_DIR

        self.profile: ProfileConfig | None = None
        self.scoring: ScoringConfig | None = None
        self.filters: FiltersConfig | None = None
        self.sources: SourcesConfig | None = None
        self.queries: QueriesConfig | None = None
        self.providers: ProvidersConfig | None = None
        self.identity: IdentityConfig | None = None
        self.channel_rules: ChannelRulesConfig | None = None
        self.company_research: CompanyResearchConfig | None = None
        self.skip_reasons: SkipReasonsConfig | None = None
        self.lifecycle: LifecycleConfig = LifecycleConfig()
        self.observability: ObservabilityConfig = ObservabilityConfig()

        self._load_all()

    def _load_yaml(self, filename: str) -> dict | None:
        path = self.config_dir / filename
        if not path.exists():
            return None
        with open(path) as f:
            data = yaml.safe_load(f)
        if data is None:
            return None
        # Warn about unresolved ${VAR} refs before resolution (so we can see the refs)
        _check_unresolved_env_refs(data, filename)
        # Warn about literal secrets in credential-like fields
        _check_literal_secrets(data, filename)
        return resolve_env_vars(data)

    def _load_all(self):
        self._load_live_configs()

    def _load_live_configs(self):
        """Load the user's config files."""
        # sources.yml and filters.yml can be committed (no personal data)
        if (self.config_dir / "sources.yml").exists():
            self.sources = SourcesConfig(**self._load_yaml("sources.yml"))

        if (self.config_dir / "filters.yml").exists():
            self.filters = FiltersConfig(**self._load_yaml("filters.yml"))

        # Personal configs (gitignored)
        if (self.config_dir / "profile.yml").exists():
            profile_data = self._load_yaml("profile.yml")
            self.profile = ProfileConfig(**profile_data)
            # Lifecycle config lives under 'lifecycle' key in profile.yml
            if profile_data and "lifecycle" in profile_data:
                self.lifecycle = LifecycleConfig(**profile_data["lifecycle"])

        if (self.config_dir / "scoring_rubric.yml").exists():
            scoring_data = self._load_yaml("scoring_rubric.yml")
            # YAML has top-level 'scoring' key; unwrap it
            if "scoring" in scoring_data:
                scoring_data = scoring_data["scoring"]
            self.scoring = ScoringConfig(**scoring_data)

        if (self.config_dir / "queries.yml").exists():
            self.queries = QueriesConfig(**self._load_yaml("queries.yml"))

        if (self.config_dir / "providers.yml").exists():
            self.providers = ProvidersConfig(**self._load_yaml("providers.yml"))

        if (self.config_dir / "identity_rules.yml").exists():
            data = self._load_yaml("identity_rules.yml")
            if data and "identity" in data:
                self.identity = IdentityConfig(**data["identity"])

        if (self.config_dir / "channel_rules.yml").exists():
            data = self._load_yaml("channel_rules.yml")
            if data and "channels" in data:
                self.channel_rules = ChannelRulesConfig(**data["channels"])

        if (self.config_dir / "company_research.yml").exists():
            data = self._load_yaml("company_research.yml")
            if data:
                self.company_research = CompanyResearchConfig(**data)

        if (self.config_dir / "skip_reasons.yml").exists():
            data = self._load_yaml("skip_reasons.yml")
            if data:
                self.skip_reasons = SkipReasonsConfig(**data)

        if (self.config_dir / "observability.yml").exists():
            data = self._load_yaml("observability.yml")
            if data:
                self.observability = ObservabilityConfig(**data)

    def load_blacklist(self) -> list[str]:
        """Load blacklist.txt (flat list, one company per line)."""
        path = self.config_dir / "blacklist.txt"
        if not path.exists():
            return []
        companies = []
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                companies.append(line.lower())
        return companies


# ---------------------------------------------------------------------------
# Cached settings access — avoids re-parsing 7 YAML files on every call
# ---------------------------------------------------------------------------

_settings_cache: Settings | None = None
_settings_cache_key: tuple[object, Path] | None = None
_settings_lock = threading.Lock()


def get_settings(config_dir: Path | None = None) -> Settings:
    """Return a cached Settings instance.

    The first call constructs Settings (loads all YAML from disk). Subsequent
    calls return the same instance. Thread-safe.

    Use invalidate_settings_cache() after writing config files (e.g. via
    config_writer) so the next call re-reads from disk.
    """
    global _settings_cache, _settings_cache_key
    effective_config_dir = Path(
        config_dir if config_dir is not None else CONFIG_DIR
    )
    # Include the constructor identity so tests or embedders that replace the
    # Settings factory do not receive an instance created by the old factory.
    cache_key = (Settings, effective_config_dir)
    if _settings_cache is not None and _settings_cache_key == cache_key:
        return _settings_cache
    with _settings_lock:
        if _settings_cache is not None and _settings_cache_key == cache_key:
            return _settings_cache
        # Preserve the no-argument construction path for callers/tests that
        # provide a Settings-compatible factory without a config_dir keyword.
        _settings_cache = Settings() if config_dir is None else Settings(config_dir=config_dir)
        _settings_cache_key = cache_key
        return _settings_cache


def invalidate_settings_cache() -> None:
    """Clear the cached Settings instance.

    Call this after writing to YAML config files (e.g. via config_writer,
    api/models.py provider updates, api/company_research_settings.py key
    rotation) so the next get_settings() call re-reads from disk.
    """
    global _settings_cache, _settings_cache_key
    with _settings_lock:
        _settings_cache = None
        _settings_cache_key = None
