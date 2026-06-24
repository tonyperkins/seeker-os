# Phase 1 Spec — Core Pipeline (CLI)

**Goal:** End-to-end pipeline that discovers jobs from hiring.cafe, filters them,
fetches full JDs for survivors, scores against a config-driven rubric, and outputs a
ranked report. CLI-only — no web UI.

**Definition of Done:** Running `python -m seeker_os.main run` produces a
ranked report of scored jobs, with all data persisted to SQLite, dedup working across
runs, and cross-reference against the job-search repo. (`seeker_os.pipeline.runner`
is the importable module; `seeker_os.main` is the CLI entry point.)

---

## 1. Project Setup

### 1.1 Directory Structure (Phase 1 only)

```
seeker-os/
├── backend/
│   ├── pyproject.toml
│   ├── seeker_os/
│   │   ├── __init__.py
│   │   ├── main.py                # CLI entry point
│   │   ├── config.py              # Settings management
│   │   ├── database.py            # SQLite connection + migrations
│   │   ├── models.py              # Pydantic v2 models (BaseModel, not dataclasses)
│   │   │
│   │   ├── discovery/
│   │   │   ├── __init__.py
│   │   │   ├── engine.py          # Discovery engine: iterates sources × queries
│   │   │   ├── ats_fetch.py       # Tier 3: JD fetch from ATS APIs/URLs
│   │   │   ├── cache.py           # Disk cache for HTTP responses
│   │   │   └── sources/
│   │   │       ├── __init__.py
│   │   │       ├── base.py        # SourceAdapter protocol, SourcePage, SourceQuery
│   │   │       ├── hiring_cafe.py # hiring.cafe adapter (one of N possible sources)
│   │   │       └── registry.py    # Adapter registry (type → class mapping)
│   │   │
│   │   ├── filtering/
│   │   │   ├── __init__.py
│   │   │   ├── hard_filters.py    # Tier 2: structured-field hard filters
│   │   │   └── title_patterns.py  # Title matching (positive/negative)
│   │   │
│   │   ├── scoring/
│   │   │   ├── __init__.py
│   │   │   └── engine.py          # Tier 4: score_job() — the rubric
│   │   │
│   │   ├── dedup/
│   │   │   ├── __init__.py
│   │   │   ├── normalize.py       # Title/company normalization
│   │   │   └── layers.py          # 4-layer dedup pipeline
│   │   │
│   │   ├── crossref/
│   │   │   ├── __init__.py
│   │   │   └── jobsearch_repo.py  # git pull + scan applied/rejected/closed
│   │   │
│   │   └── pipeline/
│   │       ├── __init__.py
│   │       └── runner.py          # Tier 1→5 orchestration
│   │
│   │   # NOTE: llm/ module is NOT created in Phase 1.
│   │   # Only providers.yml config schema validation is included (in config.py).
│   │   # Provider implementations (anthropic_provider.py, router.py, etc.)
│   │   # are deferred to Phase 2.5. See docs/LLM_ROUTING.md.
│   │
│   └── tests/
│       ├── test_hiring_cafe.py
│       ├── test_filters.py
│       ├── test_scoring.py
│       ├── test_dedup.py
│       └── test_pipeline.py
│
├── data/
│   ├── seeker.db                  # SQLite (auto-created)
│   └── cache/                     # HTTP response cache (auto-created)
│
├── config/
│   ├── queries.yml                # Default search queries
│   ├── filters.yml                # Default filter thresholds
│   └── blacklist.txt              # Company blacklist
│
└── docs/  (existing — no changes)
```

### 1.2 Dependencies

```toml
# pyproject.toml
[project]
name = "seeker-os"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "httpx>=0.27",           # HTTP client (async-capable, but sync for Phase 1)
    "pydantic>=2.0",         # Data models (BaseModel, not dataclasses)
    "pyyaml>=6.0",           # Config files
    "python-dotenv>=1.0",    # .env file loading for API keys
    "rapidfuzz>=3.0",        # Fuzzy dedup matching
    "rich>=13.0",            # CLI output (tables, colors)
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]
```

**Config loading order:**
1. `config.py` loads `.env` file (via `python-dotenv`) at startup, before any config parsing
2. YAML config files are loaded and parsed
3. `${ENV_VAR}` references in YAML (e.g. `providers.yml` API keys) are resolved against `os.environ`
4. Path values (e.g. `~/projects/job-search`) are expanded: `~` → user home, relative paths → project root
5. Pydantic models validate the final merged config; validation errors are fatal at startup

No FastAPI, no Next.js, no LLM libraries in Phase 1. Those come in Phase 2/3.

### 1.3 Configuration Files

**IMPORTANT:** All user-specific values are in YAML config files, not hardcoded in Python.
See `docs/PRODUCT_DESIGN.md` for the full config-driven architecture.

Phase 1 uses these config files:

| File | Purpose | Personal data? | Used in Phase 1? |
|---|---|---|---|
| `config/sources.yml` | Source adapter config (hiring.cafe + future sources) | No — can be committed | Yes |
| `config/providers.yml` | LLM providers, models, tier mapping | Yes (API keys via env vars) — `.gitignore`d | Schema defined, not used (no LLM calls) |
| `config/profile.yml` | User identity, comp, location, blacklist, paths | Yes — `.gitignore`d | Yes |
| `config/scoring_rubric.yml` | Scoring weights, patterns, thresholds | Yes — `.gitignore`d | Yes |
| `config/queries.yml` | Search queries (source + slug + commitment) | Somewhat — `.gitignore`d | Yes |
| `config/filters.yml` | Filter thresholds, request settings | No — can be committed | Yes |
| `config/blacklist.txt` | Company blacklist (flat list) | Yes — `.gitignore`d | Yes |
| `config/accuracy_rules.yml` | Resume accuracy rules | Yes — `.gitignore`d | Schema defined, not used (Phase 3) |

**Note:** `providers.yml` and `accuracy_rules.yml` are defined now so the config schema
is stable from the start, but Phase 1 makes no LLM calls. The scoring engine is
rules-based (regex + structured fields). LLM integration begins in Phase 2.5 (onboarding)
and Phase 3 (resume generation). See `docs/LLM_ROUTING.md` for the full provider/model
architecture, including auto-discovery and search.

Ship `*.example.yml` templates with placeholder values. Users copy to active config.

**`config/profile.yml`:** (see `docs/PRODUCT_DESIGN.md` for full schema)
```yaml
# User identity, compensation, location, employment preferences
# This is what makes Seeker OS "Tony's" vs "anyone else's"
user:
  name: "Tony Perkins"
  email: "tony.perkins@perkinslab.com"
  location: "Leander, TX"
location:
  remote_only: true
  accepted_cities: [austin, leander, cedar park, round rock, georgetown, pflugerville, taylor]
  accepted_states: [tx, texas]
comp:
  floor: 150000
  target: 165000
  stretch: 220000
experience:
  years: 25
  anchor_phrase: "25+ years"
employment:
  commitment: "Full Time"
  role_type: "Individual Contributor"
blacklist:
  - avidxchange
  - fidelity
  - fidelity investments
  - marriott
  - zapcom
resume:
  master_path: "~/projects/job-search/resume/Tony_Perkins_Master_Resume.md"
  accuracy_rules_path: "config/accuracy_rules.yml"
  output_dir: "data/resumes"
cross_reference:
  repo_path: "~/projects/job-search"
  auto_pull: true
hard_rejects:
  - reason: "FedRAMP/clearance required"
    pattern: "fedramp|security clearance|active clearance|ts/sci|top secret"
  - reason: "Customer-facing/solutions role"
    pattern: "pre.?sales|solutions architect|customer success|technical account manager"
  # ... (see PRODUCT_DESIGN.md for full list)
```

**`config/scoring_rubric.yml`:** (see `docs/PRODUCT_DESIGN.md` for full schema)
```yaml
# The entire scoring rubric is data-driven. The engine reads this file.
scoring:
  post_threshold: 6.0
  per_company_cap: 3
  max_score: 10
  base_scores:
    - pattern: "(principal|staff).*(sre|site reliability|platform|infra|devops)"
      score: 4.5
      label: "Principal/Staff SRE/Platform/Infra"
    # ... (see PRODUCT_DESIGN.md for full list)
  positive_modifiers:
    - signal: "aws"
      pattern: "aws|amazon web services"
      points: 1.0
      check: "jd"
    # ... (see PRODUCT_DESIGN.md for full list)
  negative_modifiers:
    - signal: "relocation_required"
      pattern: "on.?site only|in.?office only|must.*relocat|relocation required"
      points: -3.0
      check: "jd"
    # ... (see PRODUCT_DESIGN.md for full list)
  freshness:
    hard_filter_days: 30
```

**`config/queries.yml`:**
```yaml
# All queries default to max_pages: 1 (page 0 only — stays within robots.txt).
# Deeper pagination (max_pages: 2+) is explicit opt-in per query and crosses
# the robots.txt pagination line. Use sparingly with conservative request timing.
queries:
  - source_id: hiring_cafe       # which source adapter to use (see sources.yml)
    slug: senior-sre-remote
    label: "Senior SRE Remote"
    commitment: full_time
    max_pages: 1
    enabled: true
  - source_id: hiring_cafe
    slug: staff-sre-remote
    label: "Staff SRE Remote"
    commitment: full_time
    max_pages: 1
    enabled: true
  - source_id: hiring_cafe
    slug: principal-sre-remote
    label: "Principal SRE Remote"
    commitment: full_time
    max_pages: 1
    enabled: true
  - source_id: hiring_cafe
    slug: senior-site-reliability-engineer-remote
    label: "Senior Site Reliability Engineer"
    commitment: full_time
    max_pages: 1
    enabled: true
  - source_id: hiring_cafe
    slug: staff-platform-engineer-remote
    label: "Staff Platform Engineer"
    commitment: full_time
    max_pages: 1
    enabled: true
  - source_id: hiring_cafe
    slug: principal-devops-engineer-remote
    label: "Principal DevOps"
    commitment: full_time
    max_pages: 1
    enabled: true
  - source_id: hiring_cafe
    slug: senior-devops-engineer-remote-us
    label: "Senior DevOps US"
    commitment: full_time
    max_pages: 1
    enabled: true
  - source_id: hiring_cafe
    slug: senior-infrastructure-engineer-remote
    label: "Senior Infrastructure"
    commitment: full_time
    max_pages: 1
    enabled: true
```

**`config/filters.yml`:**
```yaml
# Tier 2 hard filter thresholds
filters:
  remote_only: true
  us_only: true
  seniority_floor: ["Senior Level", "Staff", "Principal", "Senior"]
  seniority_reject: ["Mid Level", "Entry Level", "Junior", "Associate"]
  seniority_unknown_passes: true   # unrecognized/None seniority passes to scoring
                                   # (see HIRINGCAFE_FIELDS.md § Seniority Enum)
  # Comp floor applies to comp_max (ceiling), not comp_min.
  # If comp_max < floor, the job can't pay enough → hard reject.
  # If comp_max >= floor but comp_min < floor, job passes and scoring
  # applies a comp_marginal penalty.
  # If comp is null (not listed), job passes (unknown comp isn't a hard reject).
  # NOTE: comp_floor here should match profile.comp.floor. On startup, config.py
  # validates they're equal and warns if they diverge. profile.comp.floor is the
  # canonical source — this field is kept in filters.yml for explicitness.
  comp_floor: 150000          # USD ceiling floor, must match profile.comp.floor
  freshness_days: 30          # reject if older than N days
  commitment_required: "Full Time"  # must contain this

title_filters:
  positive:
    - devops
    - sre
    - site reliability
    - platform engineer
    - infrastructure engineer
    - cloud engineer
    - staff engineer
    - principal engineer
    - release engineer
    - build engineer
    - reliability engineer
  negative:
    - manager
    - director
    - vp
    - vice president
    - head of
    - recruiter
    - sales
    - marketing
    - data scientist
    - frontend developer
    - backend developer
    - mobile
    - android
    - ios
    - qa engineer
    - test engineer
    - business analyst
    - scrum master
    - product manager
    - solutions engineer

# NOTE: request_settings (delay, retries, cache, timeout) are owned by
# sources.yml, NOT this file. filters.yml owns only Tier 2 hard filter thresholds.
# This prevents dual-source-of-truth drift.
# - post_threshold → scoring_rubric.yml: scoring.post_threshold
# - per_company_cap → scoring_rubric.yml: scoring.per_company_cap
# - freshness hard filter → filters.yml: filters.freshness_days (Tier 2 reject)
# - freshness ranking factors → scoring_rubric.yml: scoring.freshness (Tier 5 ranking)
# - request timing/retries/cache → sources.yml: per-source settings
```

**`config/blacklist.txt`:**
```
avidxchange
fidelity
fidelity investments
marriott
zapcom
```

**Blacklist loading:** `config.py` loads `blacklist.txt` (one company per line) and
merges it with `profile.yml`'s `blacklist` list at runtime. The merged set is exposed
as `profile.blacklist`. The filter engine only reads `profile.blacklist` — it doesn't
know about `blacklist.txt` directly. This allows users to maintain a simple flat list
and/or structured blacklist entries in profile.yml.

---

## 2. Database Schema

See `docs/PLAN.md` §4 for the full schema. Phase 1 creates these tables:

- `jobs` — all discovered jobs with structured fields, JD text, score, status
- `search_queries` — query configuration (synced from queries.yml on startup)
- `dedup_registry` — dedup keys (composite, content_hash, fuzzy)
- `pipeline_runs` — run logs
- `settings` — key-value config (synced from filters.yml on startup)

**Not created in Phase 1:** `applications`, `stage_history`, `resumes` (Phase 2/3).

### Phase 1 Job Status State Machine

```
                    ┌───────────┐
                    │ discovered │  ← Tier 1 insert (new job from source adapter)
                    └─────┬─────┘
                          │ Tier 2 filter
              ┌───────────┼───────────┐
              │ pass      │           │ fail
              ▼           │           ▼
      ┌───────────┐       │    ┌──────────┐
      │  filtered  │       │    │ rejected │  (reason stored)
      └─────┬─────┘       │    └──────────┘
            │ Tier 3 JD   │
            │ fetch       │
      ┌─────┼─────┐       │
      │ ok  │     │ fail  │
      ▼     │     ▼       │
  ┌──────────┐  ┌────────┐│
  │jd_fetched│  │rejected││  (jd_fetch_error stored)
  └─────┬───┘  └────────┘│
        │ dedup 3+4       │
        ├─────────┐       │
        │ dup     │ clean │
        ▼         │       │
  ┌──────────────┐│       │
  │duplicate_    ││       │
  │flagged       ││       │
  └──────────────┘│       │
                  ▼       │
            Tier 4 scoring│
        ┌─────────────────┘
        │
   ┌────┼────────┐
   │ ≥threshold  │ <threshold
   ▼             ▼
┌──────┐   ┌──────────┐
│ ready │   │ rejected │  (score + reject_reason stored)
└──┬───┘   └──────────┘
   │ Tier 5 per_company_cap
   ├──────────┐
   │ in cap   │ over cap
   ▼          ▼
┌──────┐  ┌────────┐
│ ready │  │ capped │  (excess per company, still scored)
└──────┘  └────────┘
```

**Phase 1 statuses:** `discovered`, `filtered`, `jd_fetched`, `ready`, `rejected`,
`duplicate_flagged`, `capped`.

**Phase 2+ adds:** `reviewing`, `interested`, `applied`, `interviewing`, `offered`,
`closed`, `archived`.

### Migration Approach

No Alembic. Simple versioned migrations in `database.py`:

```python
MIGRATIONS = [
    # v1: initial schema
    """
    CREATE TABLE jobs (...);
    CREATE TABLE search_queries (...);
    CREATE TABLE dedup_registry (...);
    CREATE TABLE pipeline_runs (...);
    CREATE TABLE settings (...);
    CREATE INDEX idx_jobs_url_hash ON jobs(url_hash);
    CREATE INDEX idx_jobs_status ON jobs(status);
    CREATE INDEX idx_jobs_company_norm ON jobs(company_norm);
    CREATE INDEX idx_dedup_key_value ON dedup_registry(key_value);
    """,
]

def run_migrations(db_path: str):
    # Check PRAGMA user_version, apply pending migrations, increment version
    ...
```

---

## 3. Module Specifications

### 3.1 `discovery/sources/hiring_cafe.py` — Tier 1

> **See `docs/SOURCE_ADAPTERS.md`** for the full `SourceAdapter` protocol, `JobCard`,
> `SourcePage`, and `SourceQuery` definitions. The hiring.cafe adapter is one
> implementation of that interface.

```python
class HiringCafeAdapter:
    """hiring.cafe source adapter. See docs/SOURCE_ADAPTERS.md for full design.

    Implements the SourceAdapter protocol. All source-specific logic is encapsulated
    here — the pipeline downstream never sees hiring.cafe-specific fields.
    """

    def __init__(self, config: HiringCafeConfig):
        """config comes from config/sources.yml (source_map, request settings, etc.)."""

    def fetch_jobs(self, query: SourceQuery, page: int = 0) -> SourcePage:
        """Fetch one page from hiring.cafe.

        1. Check disk cache first (key: {query.slug}:{page})
        2. If not cached: GET {base_url}/jobs/{query.slug}?page={page}
        3. Extract __NEXT_DATA__ JSON from HTML
        4. Parse ssrHits[] into JobCard objects (using source_map for ATS normalization)
        5. Filter out pinned jobs (is_hc_pinned=true or source='hiring_cafe_pin')
        6. Cache response to disk
        7. Return SourcePage with jobs, total_count, is_last_page
        """

    def test_connection(self) -> bool:
        """Verify hiring.cafe is reachable and __NEXT_DATA__ is present."""
```

### 3.1b `discovery/engine.py` — Discovery Orchestrator

```python
def fetch_all_queries(
    queries: list[SourceQuery],
    adapters: dict[str, SourceAdapter],
    cache: DiskCache,
) -> list[JobCard]:
    """Fetch all enabled queries across all sources, with delay between requests.

    For each query:
      - Look up adapter by query.source_id
      - Fetch pages 0 to query.max_pages-1
      - Respect adapter-specific request delay (from sources.yml)
      - Stop early if SourcePage.is_last_page is true
    Deduplicate across queries (same source_job_id appearing in multiple queries).
    Return combined list of unique JobCards.
    """
```

### 3.1c `discovery/sources/registry.py` — Adapter Registry

```python
def build_adapters(sources_config: list[SourceConfig]) -> dict[str, SourceAdapter]:
    """Build adapter instances from sources.yml config.

    Maps source type → adapter class, instantiates with source-specific config.
    Only enabled sources are included. Returns {source_id: adapter_instance}.
    """
```

### 3.2 `discovery/cache.py`

```python
class DiskCache:
    """Simple file-based HTTP response cache."""

    def __init__(self, cache_dir: str, ttl_hours: int = 6): ...

    def get(self, key: str) -> str | None:
        """Return cached response if not expired, else None."""

    def set(self, key: str, content: str):
        """Cache a response."""

    def clear_expired(self):
        """Remove expired entries."""
```

### 3.3 `discovery/ats_fetch.py` — Tier 3

```python

class JDFetchResult(BaseModel):
    job_id: int                   # Seeker OS job ID
    jd_text: str
    status: str                   # fetched, failed, skipped
    source_used: str              # which ATS API or URL was used
    error: str | None


def fetch_jd(job: Job) -> JDFetchResult:
    """Fetch full JD for a single job.

    Route by ats_source:
      - greenhouse: GET boards-api.greenhouse.io/v1/boards/{board}/jobs/{id}
      - ashby: GET api.ashbyhq.com/posting-api/job-board/{board}
      - lever: GET api.lever.co/v0/postings/{board}
      - other: GET apply_url, extract text from HTML

    Strip HTML tags, decode entities, normalize whitespace.
    If fetch fails: return status='failed' with error message.
    """


def fetch_all_jds(jobs: list[Job], config: RequestConfig) -> list[JDFetchResult]:
    """Fetch JDs for all jobs, with delay between requests.

    Checkpoint mechanism:
    - After each successful JD fetch, write to data/checkpoint.json:
      {"run_id": "...", "last_job_id": N, "fetched_count": M, "timestamp": "..."}
    - On resume (pipeline re-run), skip jobs where jd_fetch_status='fetched'.
    - If checkpoint.json is corrupt/unreadable, log a warning and continue
      (the DB is the source of truth — checkpoint is just a convenience).
    - Checkpoint is deleted at the end of a successful full run.
    - Tier 1 (discovery) doesn't need checkpointing — re-runs are deduped by
      URL hash + composite key, so duplicate fetches are harmless (and cached).
    """
```

### 3.4 `filtering/hard_filters.py` — Tier 2

```python

class FilterResult(BaseModel):
    passed: bool
    reason: str                   # rejection reason if not passed


def apply_filters(job: JobCard | Job, profile: UserProfile, filters: FilterConfig) -> FilterResult:
    """Apply all Tier 2 hard filters using config-driven thresholds.

    Accepts either a JobCard (from discovery) or a Job (from DB) — both expose the
    same structured fields (workplace_type, seniority_level, comp_max, etc.).
    The runner calls this with DB Job rows loaded from the jobs table.

    The filter engine is GENERIC — all thresholds and lists come from config:
    - profile.location.remote_only, profile.location.accepted_cities
    - profile.comp.floor
    - profile.blacklist
    - profile.employment.commitment
    - filters.seniority_floor, filters.seniority_reject
    - filters.freshness_days
    - filters.title_filters.positive, filters.title_filters.negative

    Checks (in order, short-circuit on first failure):
    1. Pinned check (should already be filtered, but belt-and-suspenders)
    2. Remote only: workplace_type == 'Remote' (if profile.location.remote_only)
    3. US only: 'US' in workplace_countries (if configured)
    4. Seniority floor: seniority_level in filters.seniority_floor
       (with title-based fallback if seniority_level is None or not in known
        enum — see HIRINGCAFE_FIELDS.md. The observed enum is only "Senior Level"
        and "Mid Level"; Staff/Principal may not be tagged distinctly. Fallback:
        if seniority_level is None, check title for "staff"/"principal"/"senior"
        keywords. If title matches senior keywords, pass. If title matches junior
        keywords, reject. If no signal, pass through to scoring.)
    5. Comp ceiling floor: if comp_max is not None, comp_max >= profile.comp.floor
       (rejects if the CEILING is below the floor — job can't pay enough.
        If comp_max >= floor but comp_min < floor, the job passes Tier 2
        and the scoring rubric applies a comp_marginal penalty.)
    6. Title match: core_title matches positive pattern, not negative
    7. Blacklist: company not in profile.blacklist
    8. Commitment: profile.employment.commitment in job.commitment
    9. Freshness: date_posted within filters.freshness_days

    Returns FilterResult(passed=True) if all checks pass.
    Returns FilterResult(passed=False, reason=...) on first failure.
    """
```

### 3.5 `filtering/title_patterns.py`

```python
def title_matches(title: str, positive: list[str], negative: list[str]) -> bool:
    """Check if title matches any positive pattern AND no negative pattern.

    Case-insensitive substring matching.
    Returns True if positive match found and no negative match.
    """
```

### 3.6 `scoring/engine.py` — Tier 4

```python

class ScoreResult(BaseModel):
    score: float                  # 0-10, clamped
    reasons: list[str]            # human-readable scoring reasons
    gaps: list[str]               # fit concerns
    hard_reject: bool
    reject_reason: str | None


def score_job(
    title: str,
    jd_text: str,
    location: str,
    company: str,
    structured: StructuredInputs | None = None,  # from hiring.cafe fields
    rubric: ScoringRubric,        # loaded from config/scoring_rubric.yml
    profile: UserProfile,         # loaded from config/profile.yml
) -> ScoreResult:
    """Score a job against a config-driven rubric.

    The engine is GENERIC — no hardcoded values. All weights, patterns, thresholds
    come from the rubric and profile config objects.

    rubric: ScoringRubric — loaded from config/scoring_rubric.yml
        Contains: base_scores, positive_modifiers, negative_modifiers,
        post_threshold, per_company_cap, max_score

    profile: UserProfile — loaded from config/profile.yml
        Contains: comp.floor, comp.target, location.accepted_cities,
        blacklist, hard_rejects, employment prefs

    If structured inputs are provided (from hiring.cafe), use them for:
    - comp_min/comp_max (integer, bypasses regex parsing)
    - workplace_type (enum, bypasses regex)
    - seniority_level (enum)

    Steps:
    1. Evidence gate (see SCORING_RUBRIC.md §Step 0):
       - JD < 500 characters → reject (insufficient info to score)
       - No location information available → reject
       - Location is a city-only header AND JD never mentions "remote" → reject
       (These checks are config-driven via rubric.evidence_gate settings.)
    2. Hard reject checks (from profile.hard_rejects config)
    3. Base score (first matching pattern from rubric.base_scores)
    4. Positive modifiers (all matching from rubric.positive_modifiers)
    5. Negative modifiers (all matching from rubric.negative_modifiers)
    6. Clamp to rubric.min_score / rubric.max_score

    Returns ScoreResult.
    """
```

### 3.7 `dedup/normalize.py`

```python
def normalize_title(title: str) -> str:
    """Normalize job title for fuzzy matching.
    See docs/DEDUP_DESIGN.md for full implementation.
    """

def normalize_company(company: str) -> str:
    """Normalize company name for fuzzy matching.
    See docs/DEDUP_DESIGN.md for full implementation.
    """
```

### 3.8 `dedup/layers.py`

```python

class DedupResult(BaseModel):
    is_duplicate: bool
    layer: str                    # 'url_hash', 'composite', 'content_hash', 'fuzzy'
    matched_job_id: int | None
    confidence: str               # 'exact', 'high', 'medium'


def check_duplicate(job: JobCard, db: sqlite3.Connection, source_map: dict[str, str]) -> DedupResult:
    """Run job through all 4 dedup layers.

    source_map is from config/sources.yml (passed in, not hardcoded).

    Layer 1: url_hash (sha256 of apply_url) — exact
    Layer 2: composite key (canonical_source:board:jobid, using source_map) — exact
    Layer 3: content_hash (only if JD fetched) — high confidence
    Layer 4: fuzzy match (rapidfuzz on normalized title+company) — medium confidence

    Returns on first match. If no match, returns is_duplicate=False.
    """

def register_keys(job_id: int, job: JobCard, db: sqlite3.Connection, source_map: dict[str, str]):
    """Register dedup keys for a new job after insert.

    Registers url_hash (in jobs table via UNIQUE constraint) and composite key
    (in dedup_registry, using source_map for canonicalization).
    """
```

### 3.9 `crossref/jobsearch_repo.py`

**Note:** The master resume currently lives in the cross-reference repo
(`~/projects/job-search/resume/...`). When that repo is eventually deprecated,
resume generation (Phase 3) would break. The onboarding wizard (Phase 2.5) will
copy the master resume into Seeker OS config (`config/` or `data/`), decoupling
it from the cross-reference repo. For Phase 1, the resume path is configurable
in `profile.yml` and the cross-reference repo is read-only.

```python

class CrossRefResult(BaseModel):
    matched: bool
    prior_status: str | None      # applied, rejected, closed, opportunities, found
    prior_date: str | None
    prior_score: float | None
    match_confidence: str         # exact, high, fuzzy


def sync_repo(repo_path: str = "~/projects/job-search") -> bool:
    """Git pull --rebase the job-search repo. Returns True on success."""


def check_cross_reference(job: Job, repo_path: str) -> CrossRefResult:
    """Check if a job matches anything in the job-search repo.

    Scans:
      - applied/ subdirs (parse status.md for company + role)
      - rejected/*.md (parse filename + content for company + title + score)
      - closed/ subdirs (parse status.md)
      - opportunities/ subdirs
      - found/*.md

    Matching: normalized company + title fuzzy match (rapidfuzz).

    Parser notes:
      - The markdown formats vary across directories (older vs newer format).
        Use a tolerant parser — extract company+title with multiple fallback patterns.
      - Unparseable files go to an "unparseable" log bucket, don't crash the pipeline.
      - The status.md format has evolved (some have "Company:" fields, some don't).
        Parse what's available; missing fields are OK for fuzzy matching.

    Returns CrossRefResult.
    """
```

### 3.10 `pipeline/runner.py` — Orchestrator

```python
def run_pipeline(
    queries: list[SearchQuery] | None = None,  # None = all enabled
    tiers: list[int] | None = None,             # None = all tiers (1-5)
    dry_run: bool = False,
) -> PipelineRunResult:
    """Run the full pipeline (or specific tiers).

    Tier 1: Fetch cards from source adapters
      - For each enabled query (per source), fetch pages
      - Dedup check (layers 1-2) before insert
      - Insert new jobs into DB with status='discovered', tier_passed=1

    Tier 2: Card-level hard filters
      - For all jobs with status='discovered' and tier_passed=1
      - Apply hard filters
      - Pass: update status='filtered', tier_passed=2
      - Fail: update status='rejected', store reason

    Tier 3: Full JD fetch
      - For all jobs with status='filtered' and tier_passed=2
      - Fetch JD from ATS API or apply_url
      - Success: update status='jd_fetched', jd_full, tier_passed=3
      - Fail: update status='rejected', store jd_fetch_error
      - Run dedup layer 3 (content_hash) after JD is available
      - Run dedup layer 4 (fuzzy) after JD is available
        (fuzzy match uses title+company, not score — no need to wait for scoring)
      - If duplicate: update status='duplicate_flagged'

    Tier 4: Scoring
      - For all jobs with status='jd_fetched' and tier_passed=3 and score is NULL
      - Run score_job()
      - Hard reject: status='rejected'
      - Score >= threshold: status='ready', tier_passed=4
      - Score < threshold: status='rejected'

    Tier 5: Ranking + cross-reference + report
      - Query all jobs with status='ready' and tier_passed=4
      - Apply per_company_cap: max N jobs per company (from scoring_rubric.yml).
        Keep top N by score per company; mark excess as status='capped' with reason.
      - Cross-reference against job-search repo
      - Rank by score desc, comp_max desc, date_posted desc
      - Output report to stdout (rich table)
      - Optionally write report-{date}.md

    Returns PipelineRunResult with counts at each tier.
    """
```

### 3.11 `main.py` — CLI Entry Point

```python
# CLI interface using argparse or click

# Commands:
python -m seeker_os.main run                          # full pipeline
python -m seeker_os.main run --tiers 1,2              # only tiers 1-2
python -m seeker_os.main run --queries senior-sre-remote  # single query
python -m seeker_os.main run --dry-run                # no DB writes, just report
python -m seeker_os.main report                       # re-generate report from DB
python -m seeker_os.main report --top 30              # top 30
python -m seeker_os.main report --format md           # markdown output
python -m seeker_os.main stats                        # pipeline stats
python -m seeker_os.main dedup-check                  # show duplicate stats
python -m seeker_os.main sync-config                  # sync yml files to DB

# Model management (OPTIONAL Phase 1.1 — not required for core pipeline)
# providers.yml schema validation IS required in Phase 1.
# These CLI commands can be deferred to Phase 1.1 or Phase 2.5.
python -m seeker_os.main models list                  # list all providers + models
python -m seeker_os.main models list --provider kilo  # list models for one provider
python -m seeker_os.main models search "claude"       # search across all providers
python -m seeker_os.main models search "gpt-4" --provider kilo  # search one provider
python -m seeker_os.main models fetch --provider kilo # auto-fetch available models
python -m seeker_os.main models fetch --all           # fetch from all providers
python -m seeker_os.main models tag <id> --provider <p> --tier <tier>  # tag a model
python -m seeker_os.main models set-tier heavy --provider <p> --model <m>
python -m seeker_os.main models test --provider kilo  # test provider connection
```

---

## 4. CLI Output Format

### `run` command output:

```
╭─────────────────────────────────────────────────────────────╮
│  Seeker OS — Pipeline Run 2026-06-23                        │
╰─────────────────────────────────────────────────────────────╯

Tier 1: Discovery
  Query: senior-sre-remote (page 0) ........... 20 cards
  Query: senior-sre-remote (page 1) ........... 20 cards
  Query: staff-sre-remote (page 0) ........... 19 cards
  ...
  Total fetched: 156 cards
  New (after dedup): 142
  Duplicates skipped: 14

Tier 2: Card-Level Filters
  Passed: 47
  Rejected: 95
    - Not remote: 3
    - Seniority below floor: 28
    - Title negative match: 18
    - Comp below floor: 12
    - Freshness expired: 22
    - Blacklisted: 2
    - Commitment mismatch: 10

Tier 3: JD Fetch
  Fetched: 45
  Failed: 2
  Skipped (already fetched): 0

Tier 4: Scoring
  Scored ≥6.0: 18
  Scored <6.0: 25
  Hard rejected: 2

Tier 5: Ranking & Report
  Cross-referenced against job-search repo (832 rejected, 27 applied, 13 closed)
  Prior matches found: 3

╭──────────────────────────────────────────────────────────────────────────────╮
│  Top Matches (18 jobs scored ≥6.0)                                           │
├──────┬──────┬────────────────────────────────┬───────────────┬───────────────┤
│ Rank │ Score │ Title                          │ Company       │ Comp          │
├──────┼──────┼────────────────────────────────┼───────────────┼───────────────┤
│ 1    │ 9.5  │ Staff SRE - Volcano            │ Kong          │ $150k-$210k   │
│ 2    │ 8.0  │ Sr DevOps Engineer/SRE         │ Stellar Cyber │ $165k-$215k   │
│ 3    │ 7.5  │ Sr Platform Engineer           │ Tango         │ $140k-$175k   │
│ ...  │      │                                │               │               │
├──────┴──────┴────────────────────────────────┴───────────────┴───────────────┤
│ ⚠ 3 jobs matched prior applications/rejections in job-search repo           │
╰──────────────────────────────────────────────────────────────────────────────╯

Run complete. 18 jobs ready for review.
Use 'python -m seeker_os.main report' to re-generate this report.
```

### `report` command output:

Same table as above, but reads from DB (no new fetch). Supports `--top N` and `--format md`.

### `stats` command output:

```
Seeker OS — Database Stats

  Total jobs: 1,247
  Discovered (ready for review): 18
  Rejected: 1,189
  Duplicate-flagged: 40

  By tier passed:
    Tier 1 only: 0
    Tier 2: 95
    Tier 3: 2 (JD fetch failed)
    Tier 4: 1,150

  By source ATS:
    greenhouse: 412
    ashby: 380
    workday: 198
    icims: 112
    bamboohr: 87
    other: 58

  Pipeline runs: 12
  Last run: 2026-06-23 14:32:15
```

---

## 5. Acceptance Criteria

Phase 1 is complete when ALL of the following pass:

### 5.0 Product Design (No Hardcoded Values)
- [ ] No personal values in `.py` files (names, comp numbers, company names, specific technologies in scoring logic)
- [ ] `grep -ri "tony\|perkins\|leander\|150000\|165000\|avidxchange\|fidelity\|marriott" backend/seeker_os/**/*.py` returns 0 hits (checks ALL .py files recursively, not just top-level)
- [ ] All scoring weights/patterns read from `config/scoring_rubric.yml`
- [ ] All filter thresholds read from `config/profile.yml` and `config/filters.yml`
- [ ] All hard rejects read from `config/profile.yml`
- [ ] All accuracy rules read from `config/accuracy_rules.yml` (schema defined, validation in Phase 3)
- [ ] `*.example.yml` templates shipped for all config files
- [ ] Real config files (`profile.yml`, etc.) in `.gitignore`
- [ ] Config validation runs on startup and reports errors clearly

### 5.1 Discovery
- [ ] `fetch_query("senior-sre-remote", page=0)` returns ~20 JobCard objects
- [ ] Pinned jobs are filtered out (no `is_hc_pinned=true` in results)
- [ ] Disk cache prevents re-fetching within TTL
- [ ] 3-second delay between requests is enforced
- [ ] `fetch_all_queries()` deduplicates across queries (same source_job_id)

### 5.2 Filtering
- [ ] Non-remote jobs are rejected
- [ ] Non-US jobs are rejected
- [ ] Mid Level / Entry Level / Junior seniority are rejected
- [ ] Jobs with comp_max < $150k (when listed) are rejected (ceiling below floor)
- [ ] Jobs with comp_max >= $150k but comp_min < $150k pass Tier 2 (scoring handles marginal comp)
- [ ] Negative title matches (manager, director, frontend, etc.) are rejected
- [ ] Blacklisted companies are rejected
- [ ] Jobs older than 30 days are rejected
- [ ] Non-full-time jobs are rejected (when query is full_time)
- [ ] Each rejection has a human-readable reason

### 5.3 JD Fetch
- [ ] Greenhouse JDs are fetched via API
- [ ] Ashby JDs are fetched via API
- [ ] Lever JDs are fetched via API
- [ ] Other ATS JDs are fetched via apply_url HTML extraction
- [ ] Failed fetches are marked with error, not crashed
- [ ] Checkpoint allows resuming after interruption
- [ ] 2-second delay between fetches is enforced

### 5.4 Scoring
- [ ] `score_job()` returns 0-10 score with reasons and gaps
- [ ] Hard rejects return score=0 with reject_reason
- [ ] Principal/Staff SRE titles get base 4.5
- [ ] Senior SRE/Platform titles get base 4.0
- [ ] AWS mention adds +1.0
- [ ] Terraform mention adds +1.0
- [ ] Remote + US confirmed adds +1.0
- [ ] Comp ≥$165k adds +1.0
- [ ] Score is clamped to 0-10
- [ ] Structured comp fields (integers) are used when available

### 5.5 Dedup
- [ ] Same apply_url across two queries → caught by Layer 1
- [ ] Same job from hiring.cafe + direct ATS → caught by Layer 2
- [ ] Reposted job (same JD, new ID) → caught by Layer 3
- [ ] Same job, different title phrasing → caught by Layer 4
- [ ] Flagged duplicates are stored with status='duplicate_flagged', not deleted
- [ ] Second run of same queries produces 0 new jobs (all deduped)

### 5.6 Cross-Reference
- [ ] `git pull --rebase` runs before scanning
- [ ] Jobs in `applied/` are matched by company+title
- [ ] Jobs in `rejected/` are matched by company+title
- [ ] Matched jobs are annotated in report with prior status
- [ ] No writes to the job-search repo

### 5.7 Pipeline
- [ ] `python -m seeker_os.main run` completes end-to-end without errors
- [ ] All data is persisted to SQLite
- [ ] Report is printed to stdout with rich table formatting
- [ ] `--tiers 1,2` runs only specified tiers
- [ ] `--dry-run` produces report without writing to DB
- [ ] Re-running produces 0 new jobs (dedup working)
- [ ] `stats` command shows correct counts
- [ ] Per-company cap applied: max N jobs per company in report (excess marked 'capped')
- [ ] Jobs that pass scoring get status='ready' (not 'discovered' — that's for Tier 1)

### 5.8 Tests
- [ ] `pytest tests/` passes all tests
- [ ] Test fixtures include sample hiring.cafe HTML responses
- [ ] Scoring tests cover hard rejects, base scores, modifiers, penalties
- [ ] Dedup tests cover all 4 layers with known duplicate pairs
- [ ] Filter tests cover each filter independently

---

## 6. Implementation Order

Build in this order (each step is testable independently):

0. **Seniority enum probe** (pre-implementation) — Run a quick curl across all 8
   queries, collect distinct `seniority_level` values from `__NEXT_DATA__`. Update
   `filters.yml` `seniority_floor` to match the actual enum. See
   `docs/HIRINGCAFE_FIELDS.md` § Seniority Enum.
1. **Project setup** — pyproject.toml, directory structure, config files
2. **Database** — schema, migrations, connection helper
3. **Dedup normalize** — `normalize_title()`, `normalize_company()` (needed early)
4. **Discovery** — `sources/hiring_cafe.py` (fetch + parse), `cache.py`, `sources/base.py`
5. **Dedup layers** — `layers.py` (needs DB + normalize)
6. **Filtering** — `hard_filters.py`, `title_patterns.py`
7. **ATS fetch** — `ats_fetch.py` (JD fetch)
8. **Scoring** — `engine.py` (the rubric)
9. **Cross-reference** — `jobsearch_repo.py`
10. **Pipeline runner** — `runner.py` (orchestrator)
11. **CLI** — `main.py` (entry point)
12. **Tests** — write alongside each module, run full suite at end

---

## 7. What's NOT in Phase 1

- No FastAPI server (Phase 2)
- No Next.js frontend (Phase 2)
- No resume generation (Phase 3)
- No LLM calls for scoring/resume/onboarding (Phase 2.5+)
  - `providers.yml` config schema IS defined and validated in Phase 1 (Pydantic models in config.py)
  - Provider implementations (`llm/provider.py`, `router.py`, etc.) are NOT created
        in Phase 1 — deferred to Phase 2.5 to avoid dead code
  - `models list/fetch/search/test` CLI commands are OPTIONAL (Phase 1.1) —
        not required for core pipeline DoD
- No onboarding interview (Phase 2.5)
- No cron scheduling (Phase 4)
- No Chrome extension (Phase 4)
- No analytics charts (Phase 2)
- No Kanban board (Phase 2)
- No historical data import from job-search repo (Phase 4)
- No AI search integration (Phase 4)
