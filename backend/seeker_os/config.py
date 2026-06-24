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


# ---------------------------------------------------------------------------
# Pydantic config models
# ---------------------------------------------------------------------------

class UserIdentity(BaseModel):
    name: str
    email: str
    location: str


class LocationPrefs(BaseModel):
    remote_only: bool = True
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
    role_type: str = "Individual Contributor"
    reject_role_types: list[str] = []


class ResumePrefs(BaseModel):
    master_path: str
    accuracy_rules_path: str
    output_dir: str
    contact_urls: list[str] = []

    @field_validator("master_path", "output_dir")
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
    resume: ResumePrefs
    cross_reference: CrossReferencePrefs
    hard_rejects: list[HardReject] = []


class BaseScoreRule(BaseModel):
    pattern: str | None = None
    score: float
    label: str
    check: str | None = None  # for jd_infra_role type rules


class ModifierRule(BaseModel):
    signal: str
    pattern: str | None = None
    points: float
    check: str
    requires: str | None = None
    unless: str | None = None
    threshold: int | None = None
    threshold_min: int | None = None
    threshold_max: int | None = None
    requires_comp_below: int | None = None
    requires_comp_at_least: int | None = None


class FreshnessConfig(BaseModel):
    boost_days: int = 7
    neutral_days: int = 14
    penalty_days: int = 30
    hard_filter_days: int = 30


class ScoringConfig(BaseModel):
    post_threshold: float = 6.0
    per_company_cap: int = 3
    max_score: int = 10
    min_score: int = 0
    base_scores: list[BaseScoreRule] = []
    positive_modifiers: list[ModifierRule] = []
    negative_modifiers: list[ModifierRule] = []
    freshness: FreshnessConfig = FreshnessConfig()


class FilterConfig(BaseModel):
    remote_only: bool = True
    us_only: bool = True
    seniority_floor: list[str] = []
    seniority_reject: list[str] = []
    seniority_unknown_passes: bool = True
    comp_floor: int = 150000
    freshness_days: int = 30
    commitment_required: str = "Full Time"


class TitleFilters(BaseModel):
    positive: list[str] = []
    negative: list[str] = []


class FiltersConfig(BaseModel):
    filters: FilterConfig
    title_filters: TitleFilters

    @model_validator(mode="after")
    def _check_comp_floor(self) -> "FiltersConfig":
        # This is checked against profile.comp.floor at load time in Settings
        return self


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


class QueriesConfig(BaseModel):
    queries: list[QueryConfig] = []


class ProviderModel(BaseModel):
    id: str
    label: str = ""
    context_window: int | None = None
    max_output: int | None = None
    tags: list[str] = []


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


class ProvidersConfig(BaseModel):
    providers: list[ProviderConfig] = []
    tiers: dict[str, TierMapping] = {}
    tasks: dict[str, TaskOverride] = {}


# ---------------------------------------------------------------------------
# Settings — top-level config container
# ---------------------------------------------------------------------------

class Settings:
    """Loads and holds all configuration. Singleton-like — create once at startup."""

    def __init__(self, config_dir: Path | None = None):
        self.config_dir = config_dir or CONFIG_DIR
        load_dotenv(PROJECT_ROOT / ".env")

        self.profile: ProfileConfig | None = None
        self.scoring: ScoringConfig | None = None
        self.filters: FiltersConfig | None = None
        self.sources: SourcesConfig | None = None
        self.queries: QueriesConfig | None = None
        self.providers: ProvidersConfig | None = None

        self._load_all()

    def _load_yaml(self, filename: str) -> dict | None:
        path = self.config_dir / filename
        if not path.exists():
            return None
        with open(path) as f:
            data = yaml.safe_load(f)
        return resolve_env_vars(data)

    def _load_all(self):
        # sources.yml and filters.yml can be committed (no personal data)
        if (self.config_dir / "sources.yml").exists():
            self.sources = SourcesConfig(**self._load_yaml("sources.yml"))

        if (self.config_dir / "filters.yml").exists():
            self.filters = FiltersConfig(**self._load_yaml("filters.yml"))

        # Personal configs (gitignored)
        if (self.config_dir / "profile.yml").exists():
            self.profile = ProfileConfig(**self._load_yaml("profile.yml"))

        if (self.config_dir / "scoring_rubric.yml").exists():
            self.scoring = ScoringConfig(**self._load_yaml("scoring_rubric.yml"))

        if (self.config_dir / "queries.yml").exists():
            self.queries = QueriesConfig(**self._load_yaml("queries.yml"))

        if (self.config_dir / "providers.yml").exists():
            self.providers = ProvidersConfig(**self._load_yaml("providers.yml"))

        # Cross-validate comp_floor between filters and profile
        if self.filters and self.profile:
            ff = self.filters.filters.comp_floor
            pf = self.profile.comp.floor
            if ff != pf:
                import warnings
                warnings.warn(
                    f"filters.yml comp_floor ({ff}) != profile.yml comp.floor ({pf}). "
                    "These should match. profile.comp.floor is canonical."
                )

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
