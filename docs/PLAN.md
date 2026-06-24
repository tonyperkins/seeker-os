# Seeker OS — Design & Implementation Plan

**Status:** Planning (awaiting approval before implementation)
**Date:** 2026-06-23
**Owner:** Tony Perkins
**Repo:** `~/projects/seeker-os`

---

## 1. Executive Summary

Seeker OS is a structured, dashboard-driven job search pipeline that replaces the
current scattered-markdown-files approach (Hermes/Clawford) with a unified system.
It sources jobs from hiring.cafe's regular search API (no browser required), applies
tiered filtering to narrow the funnel before fetching full JDs, scores survivors
against Tony's profile, generates tailored resumes locally, and tracks the full
application lifecycle through a web UI.

**Core principles:**
- **Funnel, not firehose** — narrow aggressively at each tier before doing expensive work
- **Structured data, not markdown files** — SQLite database as source of truth, web UI for interaction
- **Human-like request behavior** — slow, realistic requests to hiring.cafe; no aggressive crawling
- **No embellishing** — resume generation enforces strict accuracy constraints from the master resume
- **Model routing** — use cheap models for bulk tasks, expensive models only where they add value
- **On-demand first, cron later** — get it working manually before automating

---

## 2. AI Search Question: Theirs vs Ours

**Question:** Is using hiring.cafe's standard search + our own AI equal to or better
than leveraging their AI search?

**Answer: Yes — ours is equal or better, for these reasons:**

1. **Data access is identical.** The regular `/jobs/{query}` search returns the same
   underlying job data via `__NEXT_DATA__` JSON. The AI search (`/ai-search/c/...`)
   loads the same data client-side — it's a UI layer on top of the same index, not a
   different data source. We confirmed this: the AI search page's SSR contains no job
   data (`pageProps` only has `countryAllowed` and `country`), meaning it fetches from
   the same backend at runtime.

2. **We control the filtering logic.** hiring.cafe's AI search applies their proprietary
   relevance ranking. We can't inspect, tune, or audit it. With our own pipeline, every
   filter and scoring decision is transparent and configurable.

3. **We have richer structured fields than their AI sees.** The `__NEXT_DATA__` JSON
   exposes `workplace_type`, `seniority_level`, `yearly_min/max_compensation` (as
   integers, not text), `technical_tools`, `requirements_summary`, `source` (ATS),
   `apply_url`, `estimated_publish_date`, `role_type`, `commitment`. Their AI search
   uses these same fields but we can apply our own multi-tier filtering logic that's
   tuned to Tony's specific constraints (comp floor, blacklist, remote-only, etc.).

4. **No browser dependency for the main pipeline.** The AI search requires an
   authenticated browser session (client-side rendering). The regular search works
   with plain curl. This makes the pipeline portable, scriptable, and cron-friendly.

5. **We can still use their AI search as a supplementary input.** If we want to
   cross-pollinate, we can drive the AI search via Chrome debug port (as we did
   in the spike) and feed those results into the same pipeline. But it's an optional
   enhancement, not the foundation.

**Decision:** Build on the regular search API. AI search is a v2 optional enhancement.

---

## 3. Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Seeker OS Dashboard                    │
│              (Web UI — Next.js or similar)                │
│  Config · Review · State Changes · Resume Gen · Analytics │
└────────────────────────┬────────────────────────────────┘
                         │ REST API
┌────────────────────────▼────────────────────────────────┐
│                    Seeker OS Core                         │
│                   (Python FastAPI)                        │
│                                                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐ │
│  │  Discovery │  │ Filtering │  │  Scoring  │  │  Resume   │ │
│  │  Engine    │  │  Engine   │  │  Engine   │  │  Engine   │ │
│  └─────┬────┘  └─────┬────┘  └─────┬────┘  └─────┬────┘ │
│        │             │             │             │       │
│        └─────────────┴─────────────┴─────────────┘       │
│                          │                               │
│                   ┌──────▼──────┐                        │
│                   │   SQLite     │                        │
│                   │  Database    │                        │
│                   └─────────────┘                        │
└──────────────────────────────────────────────────────────┘
                          │
              ┌───────────┼───────────┐
              │           │           │
        ┌─────▼────┐ ┌───▼────┐ ┌───▼──────┐
        │hiring.cafe│ │  ATS   │ │ job-search│
        │  search   │ │  APIs  │ │   repo    │
        │  (curl)   │ │(GH/ etc)│ │ (git pull)│
        └──────────┘ └────────┘ └──────────┘
```

### Tech Stack

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| Database | SQLite | Single-user, local, zero-config, portable. No server process. |
| Backend | Python + FastAPI | Matches existing scoring code (Python). FastAPI gives async + auto OpenAPI docs. |
| Frontend | Next.js (React) + Tailwind | Mature ecosystem, SSR if needed, component libraries (shadcn/ui). |
| Job scraping | Python + httpx/curl | hiring.cafe via `__NEXT_DATA__` extraction; ATS APIs for JD fetch. |
| AI/LLM | Multi-provider (Ollama local, Anthropic, OpenAI) | Model routing — cheap for bulk, expensive for resume gen. |
| Resume output | Markdown → PDF (via pandoc/weasyprint) | ATS-friendly, version-controlled, diffable. |

**Why not adopt an existing tool?** (see §10 — Existing Tools Analysis)
The existing tools (CareerPulse, JobSync, Jobs Optima, etc.) are close but:
- None use hiring.cafe as a source (they scrape LinkedIn/Indeed/etc.)
- None have Tony's specific scoring rubric and accuracy constraints
- Most are designed for general use, not tuned to a specific senior IC profile
- Several have heavy dependencies (MongoDB, Redis, .NET) that are overkill for single-user

**Decision:** Build fresh, taking inspiration from the best patterns in existing tools.
Specifically borrowing from:
- **CareerPulse**: Multi-provider AI support, Ollama for local inference, ATS-specific scrapers
- **JobSync**: Next.js + Tailwind dashboard pattern, resume management
- **jermsmit/job-tracker**: Pipeline funnel analytics, Kanban board, response rate tracking
- **Jobs Optima**: BYOK model, Chrome extension for autofill (future)

---

## 4. Data Model

### Core Tables (SQLite)

```sql
-- Jobs discovered from hiring.cafe or other sources
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- Identity
    source_id TEXT,                -- which adapter found this (e.g. 'hiring_cafe')
    source_job_id TEXT,            -- source-specific job ID (e.g. hc_id: source___board___jobid)
    ats_source TEXT,               -- canonical: greenhouse, ashby, lever, workday, icims, etc.
    ats_board_token TEXT,          -- company slug on the ATS
    ats_job_id TEXT,               -- job id on the ATS
    apply_url TEXT,                -- canonical ATS apply URL
    url_hash TEXT UNIQUE,          -- sha256 of apply_url (dedup key)

    -- Job details (from card / structured fields)
    title TEXT,
    core_title TEXT,               -- v5_processed_job_data.core_job_title
    company TEXT,
    company_homepage TEXT,
    location TEXT,                 -- formatted_workplace_location
    workplace_type TEXT,           -- Remote, On-Site, Hybrid
    workplace_countries TEXT,      -- JSON array
    seniority_level TEXT,
    commitment TEXT,               -- JSON array: ["Full Time"]
    comp_min INTEGER,              -- yearly_min_compensation (integer USD)
    comp_max INTEGER,              -- yearly_max_compensation (integer USD)
    comp_currency TEXT,
    technical_tools TEXT,          -- JSON array of skill names
    requirements_summary TEXT,
    date_posted TEXT,              -- ISO timestamp
    role_type TEXT,                -- Individual Contributor, etc.

    -- Pipeline state
    status TEXT DEFAULT 'discovered',  -- discovered, filtered, jd_fetched, ready,
                                        -- rejected, duplicate_flagged, capped,
                                        -- reviewing, interested, applied, etc.
    tier_passed INTEGER,           -- highest tier this job passed (1-4)
    score REAL,                    -- final rubric score (0-10)
    score_reasons TEXT,            -- JSON array of scoring reasons
    score_gaps TEXT,               -- JSON array of gaps
    jd_full TEXT,                  -- full JD text (fetched at Tier 3)
    jd_fetch_status TEXT,          -- pending, fetched, failed, skipped

    -- Metadata
    discovered_at TEXT,            -- when first seen by Seeker OS
    discovered_query TEXT,         -- which query found it
    updated_at TEXT,
    is_pinned BOOLEAN DEFAULT FALSE,  -- hiring.cafe pinned (excluded from pipeline)

    -- Dedup
    content_hash TEXT,             -- md5 of first 500 chars of JD (for repost detection)
    title_norm TEXT,               -- normalized title for fuzzy matching
    company_norm TEXT              -- normalized company for fuzzy matching
);

-- Application lifecycle tracking
CREATE TABLE applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER REFERENCES jobs(id),
    stage TEXT,                    -- discovered, reviewing, interested, applied,
                                   -- screening, interviewing, offer, rejected, closed, ghosted
    stage_entered_at TEXT,
    notes TEXT,
    follow_up_due TEXT,
    resume_id INTEGER REFERENCES resumes(id),
    created_at TEXT,
    updated_at TEXT
);

-- Stage history (audit trail)
CREATE TABLE stage_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER REFERENCES jobs(id),
    from_stage TEXT,
    to_stage TEXT,
    changed_at TEXT,
    changed_by TEXT,               -- 'system', 'manual', 'cron'
    note TEXT
);

-- Generated resumes
CREATE TABLE resumes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER REFERENCES jobs(id),
    resume_text TEXT,              -- markdown content
    resume_path TEXT,              -- path to generated file
    model_used TEXT,               -- which LLM generated it
    generated_at TEXT,
    -- Accuracy enforcement
    accuracy_check_passed BOOLEAN,
    accuracy_violations TEXT       -- JSON array of any violations found
);

-- Search queries (configurable)
CREATE TABLE search_queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT,                -- which adapter to use (e.g. 'hiring_cafe')
    query_slug TEXT,               -- URL slug: senior-sre-remote
    label TEXT,                    -- human label
    commitment_filter TEXT,        -- full_time, contract, both
    max_pages INTEGER DEFAULT 1,
    enabled BOOLEAN DEFAULT TRUE,
    last_run_at TEXT,
    notes TEXT
);

-- Dedup registry (beyond url_hash in jobs table)
CREATE TABLE dedup_registry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER REFERENCES jobs(id),
    key_type TEXT,                 -- 'composite', 'url_hash', 'content_hash', 'fuzzy'
    key_value TEXT,
    created_at TEXT
);

-- Run logs
CREATE TABLE pipeline_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT,
    completed_at TEXT,
    queries_run TEXT,              -- JSON array
    cards_fetched INTEGER,
    cards_survived_tier2 INTEGER,
    jds_fetched INTEGER,
    jobs_scored INTEGER,
    jobs_posted INTEGER,           -- scored >= threshold
    status TEXT                    -- running, completed, failed
);

-- Settings (key-value for configurable thresholds)
CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT,                    -- JSON encoded
    updated_at TEXT
);
```

### State Machine

**Phase 1 pipeline states** (see `docs/PHASE1_SPEC.md` §2.2 for the authoritative version):

```
discovered → filtered → jd_fetched → ready → (capped if over per_company_cap)
                ↓           ↓          ↓
            rejected    rejected    rejected (score < threshold or hard reject)
                ↓           ↓
        duplicate_flagged (layers 3-4 after JD fetch)
```

**Phase 2+ application lifecycle** (user-driven, via dashboard):

```
                    ┌─────────────┐
                    │   ready      │ ← scored ≥ threshold, ready for review
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  reviewing   │ ← user opened in dashboard
                    └──┬───┬───┬──┘
                       │   │   │
          ┌────────────┘   │   └────────────┐
          │                │                │
   ┌──────▼─────┐  ┌───────▼──────┐  ┌─────▼──────┐
   │ interested  │  │  rejected    │  │  skipped   │
   │             │  │  (with reason)│  │ (not now,  │
   └──────┬─────┘  └──────────────┘  │  snooze)   │
          │                           └────────────┘
   ┌──────▼─────┐
   │   applied   │ ← resume generated + submitted
   └──────┬─────┘
          │
   ┌──────▼──────┐
   │  screening   │ ← recruiter contact, initial response
   └──────┬──────┘
          │
   ┌──────▼──────┐
   │ interviewing │ ← phone screen, technical, onsite
   └──────┬──────┘
          │
   ┌──────▼──────┐
   │    offer     │
   └──────┬──────┘
          │
   ┌──────▼──────┐
   │   accepted   │
   └─────────────┘

   Any stage → rejected (with reason)
   Any stage → ghosted (no response after N days)
```

---

## 5. Tiered Funnel Pipeline

### Tier 1: Discovery (hiring.cafe search)

**Access method:** Plain curl to `https://hiring.cafe/jobs/{query-slug}`
Extract `__NEXT_DATA__` JSON → `props.pageProps.ssrHits[]`.

**Request behavior (human-like):**
- 3-5 seconds between requests (configurable, default 3s)
- Standard browser User-Agent
- No concurrent requests
- Cache responses to disk (avoid re-fetching within same run)
- Respect 429/503 with exponential backoff

**Query configuration (in DB, editable via dashboard):**

All queries default to `max_pages: 1` (page 0 only — stays within robots.txt).
Deeper pagination is explicit opt-in per query.

| Query slug | Label | Commitment | Max pages |
|---|---|---|---|
| `senior-sre-remote` | Senior SRE Remote | full_time | 1 |
| `staff-sre-remote` | Staff SRE Remote | full_time | 1 |
| `principal-sre-remote` | Principal SRE Remote | full_time | 1 |
| `senior-site-reliability-engineer-remote` | Senior Site Reliability Engineer | full_time | 1 |
| `staff-platform-engineer-remote` | Staff Platform Engineer | full_time | 1 |
| `principal-devops-engineer-remote` | Principal DevOps | full_time | 1 |
| `senior-devops-engineer-remote-us` | Senior DevOps US | full_time | 1 |
| `senior-infrastructure-engineer-remote` | Senior Infrastructure | full_time | 1 |

**Pagination note:** `/jobs/*?page=*` is disallowed in robots.txt. All queries default
to page 0 only. Deeper pagination (`max_pages: 2+`) is explicit opt-in per query and
crosses the robots.txt line — use sparingly with 3-5s between requests, human-like
volume. Prefer more targeted page-0 queries over paging broad queries. This
approximates manual browsing behavior. Total requests per run: ~8-16 (8 queries × 1-2
pages). At 3s spacing, that's under a minute of request time.

**Output:** Raw cards inserted into `jobs` table with `status='discovered'`,
`tier_passed=1`. Pinned jobs (`is_hc_pinned=true` or `source='hiring_cafe_pin'`) are
skipped entirely.

### Tier 2: Card-Level Hard Filters

Apply filters using **only structured fields** — no JD fetch. This is where the funnel
narrows dramatically.

| Filter | Field(s) | Logic | Configurable? |
|---|---|---|---|
| Skip pinned | `pinned` | Exclude | No (always) |
| Remote only | `workplace_type` | Must be "Remote" | Yes (setting) |
| US only | `workplace_countries` | Must include "US" | Yes (setting) |
| Seniority floor | `seniority_level` | Must be Senior/Staff/Principal — reject Mid/Entry/Junior | Yes (setting) |
| Comp floor | `comp_max` | If comp_max is present, must be ≥ threshold (default $150k) — rejects if the CEILING is below the floor. If comp_max ≥ floor but comp_min < floor, job passes Tier 2 and scoring applies a comp_marginal penalty. If null, pass through. | Yes (setting) |
| Title match | `core_title` | Must match positive pattern, not match negative pattern | Yes (config file) |
| Blacklist | `company` | Reject blacklisted companies | Yes (config file) |
| Commitment | `commitment` | Must match query's commitment filter | Yes (per-query) |
| Freshness | `date_posted` | Reject if older than N days (default 30) | Yes (setting) |

**Jobs that fail Tier 2** → `status='rejected'`, with rejection reason stored.
**Jobs that pass Tier 2** → `tier_passed=2`, proceed to Tier 3.

**Estimated yield:** ~160 raw cards → ~40-80 survivors.

### Tier 3: Full JD Fetch

For Tier 2 survivors only, fetch the full job description.

**Fetch strategy by ATS source:**

| ATS | Method | Notes |
|---|---|---|
| Greenhouse (`grnhse`) | `boards-api.greenhouse.io/v1/boards/{slug}/jobs/{id}` | Existing logic, reliable |
| Ashby (`ashby`) | `api.ashbyhq.com/posting-api/job-board/{slug}` | Existing logic |
| Lever (`lever`) | `api.lever.co/v0/postings/{slug}` | Existing logic |
| Workday | Fetch `apply_url` HTML, extract JD | New — generic HTML extraction |
| iCIMS | Fetch `apply_url` HTML, extract JD | New |
| BambooHR | Fetch `apply_url` HTML, extract JD | New |
| Other | Fetch `apply_url` HTML, generic text extraction | Fallback |

**Throttle:** 2-3 seconds between fetches (human-like). **Resumable:** checkpoint
after each fetch. **Error handling:** if JD fetch fails, mark `jd_fetch_status='failed'`,
skip scoring, surface in dashboard for manual review.

**Output:** `jd_full` populated, `tier_passed=3`, proceed to Tier 4.

### Tier 4: Scoring

Run the scoring rubric on the full JD text. **Same rubric as Clawford** — hard filters,
base score, modifiers, penalties, clamp 1-10. The rubric is config-driven
(`config/scoring_rubric.yml`) and evaluated by the generic engine in
`seeker_os/scoring/engine.py`. The engine implements the mechanism (pattern matching,
score aggregation, clamping); the YAML provides the policy (weights, patterns,
thresholds). This is the single source of truth (break from Hermes version, per decision).

**Structured-field inputs:** For hiring.cafe jobs, feed the rubric with structured comp
data (integer, not regex-parsed) and structured workplace_type. The rubric logic stays
identical; only the input extraction improves.

**Score ≥ threshold (default 6.0)** → `status='ready'` (ready for review),
`tier_passed=4`.
**Score < threshold** → `status='rejected'` with score and reasons.

### Tier 5: Ranking + Report

**Ranking formula:** `score desc, comp_max desc, date_posted desc`

**Cross-reference (read-only):** Before surfacing results, check the local
`~/projects/job-search` repo (git pull first!) for matches in `applied/`, `rejected/`,
`closed/`, `opportunities/`. Match by normalized company+title fuzzy match. Annotate
each result with prior status if found.

**Output:**
- Results visible in dashboard (primary interface)
- Optional: `report-{date}.md` export
- stdout summary for CLI runs

---

## 6. Dedup System (Robust, Multi-Layer)

The current Hermes system uses simple `source:slug:jobid` string keys. This catches
exact duplicates but misses:
- Same job reposted with a new ID
- Same job across different ATS sources (Greenhouse vs hiring.cafe's re-index)
- Same job with slightly different titles ("Sr SRE" vs "Senior Site Reliability Engineer")
- Same company, different name variants ("TREX Solutions" vs "TREX Solutions LLC")

### Multi-Layer Dedup Architecture

```
Layer 1: Exact URL hash (sha256 of apply_url)
    → Catches: same job re-indexed by hiring.cafe, same URL across sources
    → Cost: O(1) lookup, indexed
    → Catches: ~70% of duplicates

Layer 2: Composite key (ats_source:board_token:job_id)
    → Catches: same job seen via direct ATS scan + hiring.cafe
    → Cost: O(1) lookup, indexed
    → Catches: ~20% of duplicates (cross-source)

Layer 3: Content hash (md5 of first 500 chars of normalized JD text)
    → Catches: reposted jobs (same JD, new ID)
    → Cost: O(1) lookup after hash computation
    → Catches: ~5% of duplicates (reposts)

Layer 4: Fuzzy match (normalized title + company similarity)
    → Catches: same job with different title phrasing or company name variants
    → Cost: O(n) scan against existing jobs, but narrowed by company_norm index
    → Method: rapidfuzz library (Levenshtein-based, fast, no GPU needed)
       - Title similarity > 90 (after normalization)
       - Company similarity > 85 (after normalization)
       - Same commitment type
    → Catches: ~5% of duplicates (fuzzy)
    → False positive risk: low — two genuinely different "Senior SRE" roles at the
      same company would have different JD content, caught by Layer 3

Layer 5 (optional, future): Semantic embedding similarity
    → Catches: same job with substantially rewritten JD
    → Method: local sentence embedding (bge-small-en-v1.5) + cosine similarity
    → Threshold: > 0.92 on JD embedding
    → Cost: higher (embedding computation), only run if Layers 1-4 all pass
    → Deferred to v2 — Layers 1-4 catch ~98% of duplicates
```

### Normalization Functions

> **Canonical implementation:** `docs/DEDUP_DESIGN.md` § Normalization Functions.
> The code below is a summary — see DEDUP_DESIGN.md for the full, corrected version
> with word-boundary regex and no bidirectional mapping bugs.

```python
# See docs/DEDUP_DESIGN.md for the canonical implementation.
# Key points (don't repeat the bugs from earlier drafts):
# - normalize_title uses \b word-boundary regex, NOT bare substring replace
# - No bidirectional pairs (devops↔dev ops self-cancel with dict iteration)
# - normalize_company uses slicing (c[:-len(suffix)]), NOT rstrip (strips char set)

def normalize_title(title: str) -> str:
    """Normalize job title for fuzzy matching. See DEDUP_DESIGN.md."""
    ...  # full implementation in DEDUP_DESIGN.md

def normalize_company(company: str) -> str:
    """Normalize company name for fuzzy matching. See DEDUP_DESIGN.md."""
    c = company.lower().strip()
    # Strip common suffixes (use slicing, NOT rstrip — rstrip strips a character set)
    for suffix in [' inc', ' inc.', ' llc', ' ltd', ' corp', ' corporation',
                   ' technologies', ' tech', ' labs', ' ai', ' co',
                   ' group', ' holdings', ' partners', ' solutions',
                   ' systems', ' software', ' digital', ' global']:
        if c.endswith(suffix):
            c = c[:-len(suffix)]
            break  # only strip one suffix
    # Remove punctuation
    c = re.sub(r'[^a-z0-9\s]', '', c)
    c = re.sub(r'\s+', ' ', c).strip()
    return c
```

### Dedup Flow

```
New job arrives (Tier 1)
    │
    ├─ Layer 1: url_hash in jobs table? → DUPLICATE, skip
    ├─ Layer 2: composite key in dedup_registry? → DUPLICATE, skip
    ├─ Layer 3: content_hash in dedup_registry? → LIKELY REPOST, flag for review
    └─ Layer 4: fuzzy match against existing jobs (same company_norm)?
       → Title similarity > 90? → LIKELY DUPLICATE, flag for review
       → No match? → NEW JOB, insert

Flagged duplicates are not silently dropped — they're marked `status='duplicate_flagged'`
and surfaced in the dashboard for manual confirmation. This prevents false merges.
```

---

## 7. Resume Generation Engine

### Current State

Tony manually posts JDs to Claude Opus/Sonnet to get custom-tailored resumes. This is
token-expensive and manual. Seeker OS automates this with strict accuracy enforcement.

### Architecture

```
Job (scored, user clicks "Generate Resume")
    │
    ├─ Load master resume (resume/Tony_Perkins_Master_Resume.md)
    │   └─ Includes "Accuracy Notes" section with never-claim constraints
    │
    ├─ Load job JD (full text from Tier 3)
    │
    ├─ Model selection (configurable per task):
    │   ├─ Resume generation: Claude Sonnet (or Opus for high-value roles)
    │   └─ Accuracy check: Haiku (fast, cheap, just validates constraints)
    │
    ├─ Prompt construction:
    │   ├─ System: "You are a resume writer. NEVER embellish. Only use skills
    │   │          and experience from the master resume. Follow accuracy notes."
    │   ├─ Context: Master resume (full text including accuracy notes)
    │   ├─ Task: Job JD
    │   └─ Output: Tailored resume in markdown, ATS-optimized
    │
    ├─ Accuracy validation pass (separate LLM call, cheap model):
    │   ├─ Check: Does generated resume claim anything not in master resume?
    │   ├─ Check: Does it violate any "never claim" constraint?
    │   ├─ Check: Are skill claims consistent with accuracy notes?
    │   └─ Result: accuracy_check_passed + violations list
    │
    └─ Output:
        ├─ Resume saved to resumes table + file
        ├─ If accuracy check failed: flagged for manual review
        └─ PDF export available (pandoc/weasyprint)
```

### Accuracy Enforcement Rules (from master resume)

These are config-driven validation rules (`config/accuracy_rules.yml`), enforced
programmatically by a generic validator — not just prompt instructions:

1. **AWS:** Never claim "deep AWS expertise" or hard year count. Frame as breadth
   across core services + delivery-with-AI.
2. **Azure:** Production project experience with AI assistance. Don't claim deep
   independent expertise.
3. **GCP:** Minimal only — never claim production depth.
4. **PowerShell:** May list as scripting language (Accelya bullets), never claim
   depth/mastery/strong proficiency.
5. **Ansible:** Never claim as current competency. Fidelity bullet is dated historical.
6. **Kubernetes:** Honest self-rating 1-3 currently. Re-ramping. Don't claim cluster
   administration depth.
7. **Go:** Familiar, growing — not a primary language.
8. **Spinnaker:** Source-of-builds consumer, not operational depth.
9. **Experience anchor:** "25+ years" only, attached to overall engineering career.
10. **Education:** Omit entirely (DeVry EET — no value add).
11. **AI assistance:** Claims should reflect what Tony can do WITH AI assistance,
    not deep independent expertise.
12. **Technologies NOT on resume:** ArgoCD, Helm, Kargo, Consul, Vault (production),
    Rust, Temporal, Ansible (as current competency).

### Model Routing

| Task | Model | Why |
|---|---|---|
| JD scoring (Tier 4) | Local rules engine (no LLM) | Deterministic, fast, auditable |
| Resume generation | Claude Sonnet 4 | Good writing quality, reasonable cost |
| Resume generation (high-value) | Claude Opus 4 | Best quality for top-scored roles |
| Accuracy validation | Claude Haiku 4 | Fast, cheap, just constraint checking |
| Company research | Haiku or Ollama (local) | Summarization task, doesn't need expensive model |
| Cover letter (optional) | Sonnet | Good writing, moderate cost |

All model selection is configurable via settings table / dashboard.

---

## 8. Dashboard Design

### Layout

```
┌─────────────────────────────────────────────────────────────┐
│  Seeker OS                              [Settings] [Run Scan] │
├──────────┬──────────────────────────────────────────────────┤
│          │                                                   │
│ Dashboard│  ╔══════════════════════════════════════════════╗ │
│ Jobs     │  ║  Pipeline Funnel                              ║ │
│ Pipeline │  ║  Discovered: 160 → Survived: 52 → Scored: 18 ║ │
│ Resumes  │  ╚══════════════════════════════════════════════╝ │
│ Queries  │                                                   │
│ Settings │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ │
│          │  │ Applied  │ │ Active   │ │ Rejected │ │ Response│ │
│          │  │   27     │ │   18     │ │   832    │ │  Rate   │ │
│          │  │          │ │          │ │          │ │  12%    │ │
│          │  └─────────┘ └─────────┘ └─────────┘ └─────────┘ │
│          │                                                   │
│          │  ┌─────────────────────────────────────────────┐ │
│          │  │  Recent Matches (scored ≥6)                  │ │
│          │  │                                               │ │
│          │  │ Score Title                        Company    │ │
│          │  │ ───────────────────────────────────────────── │ │
│          │  │ 9.5   Staff SRE                    Kong       │ │
│          │  │ 8.0   Sr DevOps Engineer           Stellar    │ │
│          │  │ 7.5   Sr Platform Engineer         Tango      │ │
│          │  │  ...                                          │ │
│          │  │              [Open in Kanban]                 │ │
│          │  └─────────────────────────────────────────────┘ │
└──────────┴──────────────────────────────────────────────────┘
```

### Views

**1. Dashboard (overview)**
- Pipeline funnel: discovered → survived → scored → applied
- Stat cards: active applications, total rejected, response rate, avg time-to-response
- Recent matches table (top 10 by score)
- Weekly activity chart (applications submitted, responses received)

**2. Jobs (list/table view)**
- Sortable, filterable table of all jobs in the system
- Columns: score, title, company, location, comp, status, date posted, source
- Filters: status, score range, date range, company, source ATS
- Row click → job detail drawer (see below)
- Bulk actions: reject, mark interested, generate resumes

**3. Job Detail (drawer/modal)**
- Full JD text (rendered)
- Structured fields: comp, location, seniority, skills, source ATS
- Scoring breakdown: score, reasons, gaps
- Cross-reference status: "⚠ Previously applied (2026-04-21)" or "⚠ Previously rejected"
- Action buttons: [Mark Interested] [Generate Resume] [Reject] [Snooze]
- Stage history timeline
- Notes field (markdown)

**4. Pipeline (Kanban board)**
- Columns: Discovered → Reviewing → Interested → Applied → Screening → Interviewing → Offer → Closed
- Drag-and-drop between columns
- Card shows: title, company, score, comp, date
- Click card → job detail drawer

**5. Resumes**
- List of generated resumes with: job title, company, model used, accuracy status
- Click to view rendered resume
- Regenerate button (with different model if desired)
- Download as PDF / DOCX
- Compare against master resume (diff view)

**6. Queries (search configuration)**
- Table of configured search queries
- Add/edit/remove queries
- Toggle enabled/disabled
- Set max pages per query
- Set commitment filter (full_time / contract / both)
- "Run now" button per query or "Run all"

**7. Settings**
- Scoring thresholds (comp floor, post threshold, freshness window)
- Title filter patterns (positive/negative)
- Company blacklist
- Model routing configuration (which model for which task)
- API keys (encrypted at rest)
- Request timing settings (delay between requests, max pages default)
- Dedup thresholds (fuzzy match similarity cutoffs)

### API Endpoints

```
# Jobs
GET    /api/jobs                    # list with filters
GET    /api/jobs/{id}               # detail
PATCH  /api/jobs/{id}               # update status/notes
POST   /api/jobs/{id}/reject        # reject with reason
POST   /api/jobs/{id}/snooze        # snooze for N days
GET    /api/jobs/{id}/cross-ref     # check against job-search repo

# Pipeline
POST   /api/pipeline/run            # trigger full scan
GET    /api/pipeline/runs           # run history
GET    /api/pipeline/runs/{id}      # run details
POST   /api/pipeline/run/tier/{n}   # run specific tier only

# Resumes
POST   /api/resumes/generate        # generate resume for job
GET    /api/resumes                 # list
GET    /api/resumes/{id}            # detail
GET    /api/resumes/{id}/pdf        # download PDF
POST   /api/resumes/{id}/validate   # re-run accuracy check

# Queries
GET    /api/queries                 # list
POST   /api/queries                 # create
PATCH  /api/queries/{id}            # update
DELETE /api/queries/{id}            # delete
POST   /api/queries/{id}/run        # run single query

# Settings
GET    /api/settings                # get all
PATCH  /api/settings/{key}          # update

# Analytics
GET    /api/analytics/funnel        # pipeline funnel stats
GET    /api/analytics/response-rate # response rate by source/time
```

---

## 9. Cross-Reference with Existing job-search Repo

**Source:** `~/projects/job-search` (local git clone of the Hermes/Clawford repo)

**Protocol:**
1. **Always `git pull --rebase` first** before reading any data
2. Scan these directories for prior interactions:
   - `applied/` — jobs Tony has applied to (subdirs with `status.md`, `jd.md`, `notes.md`, resume)
   - `rejected/` — jobs scored but rejected (markdown files with score + reason)
   - `closed/` — jobs that went through the full cycle and closed
   - `opportunities/` — jobs marked as "pursue" but not yet applied
   - `found/` — recently scored matches not yet actioned
3. **Matching method:** Fuzzy match on normalized company + title (same normalization
   functions from §6). If match found, annotate the Seeker OS job with prior status.
4. **Read-only:** Seeker OS never writes to the job-search repo. Cross-reference is
   purely informational.
5. **Migration path (future):** Once Seeker OS is stable, we can import the job-search
   repo's historical data into Seeker OS's database and deprecate the markdown-based
   system. This is a separate project phase.

---

## 10. Existing Tools Analysis

### Tools Evaluated

| Tool | Stack | Strengths | Why Not Adopt |
|---|---|---|---|
| **CareerPulse** | Python, Next.js | Multi-provider AI (Ollama/OpenAI/Anthropic), ATS scrapers (GH/Ashby/Lever), PDF resume gen, Chrome extension | Doesn't use hiring.cafe; no custom scoring rubric; MongoDB dependency |
| **JobSync** | Next.js | Clean dashboard, resume management, AI matching | No job scraping; manual entry focused; no tiered funnel |
| **Jobs Optima** | Next.js, NestJS, MongoDB | Full loop (scan → tailor → track → autofill), BYOK | MongoDB/Redis overkill; no hiring.cafe; no custom rubric |
| **jermsmit/job-tracker** | Node, PostgreSQL | Excellent pipeline analytics, Kanban, response rates | No scraping/AI; tracking only; would need major extension |
| **career-ops** | Node | Claude AI evaluation, Greenhouse/Ashby/Lever scanning, PDF CV | Closest match but no hiring.cafe; AWS-focused deploy; no tiered funnel |
| **hireforge** | Next.js | AI CV gen, cover letters, interview prep, fit analysis | No scraping; paste-URL focused; no pipeline |
| **applypilot** | Next.js, PostgreSQL | 5-agent pipeline, company research, interview prep | Gemini-only; no scraping; paste-URL focused |
| **OSApplyTrack** | .NET, Python, PostgreSQL | Multi-tenant, poller, pipeline stages | .NET dependency; no AI resume gen; no hiring.cafe |

### What We're Borrowing

- **From CareerPulse:** Multi-provider AI pattern, Ollama for local inference, ATS-specific
  scraper logic (Greenhouse/Ashby/Lever API patterns)
- **From jermsmit/job-tracker:** Pipeline funnel analytics, Kanban board pattern,
  response rate tracking, source analysis
- **From Jobs Optima:** BYOK model routing concept, Chrome extension for autofill (v2)
- **From career-ops:** Claude-based JD evaluation pattern, PDF CV generation

### What We're Building Differently

- **hiring.cafe as primary source** (no existing tool does this)
- **Tiered funnel** (no existing tool narrows before JD fetch — they all fetch everything)
- **Tony's specific scoring rubric** with accuracy constraints from master resume
- **Strict no-embellish enforcement** (other tools optimize for ATS gaming; we optimize
  for honest representation)
- **SQLite, not PostgreSQL/MongoDB** (single-user, zero-config, portable)
- **Structured data, not markdown files** (the core problem with the current Hermes system)

---

## 11. Request Behavior & robots.txt

### hiring.cafe

- `/jobs/*` is **allowed** for standard bots in robots.txt
- `/jobs/*?page=*` (pagination) is **disallowed** — we use it cautiously
- `/viewjob/`, `/org/`, `/company/` are **disallowed** — we don't access these

### Our Approach

1. **Page 0 only by default** — stays within robots.txt allowance
2. **Deeper pagination is opt-in per query** (max_pages config), with human-like timing
3. **3-5 seconds between requests** — approximates manual browsing speed
4. **Standard browser User-Agent** — not a bot UA, not deceptive, just normal
5. **No concurrent requests** — sequential only
6. **Disk cache** — never re-fetch the same URL within a run
7. **Respect 429/503** — exponential backoff, abort after 3 retries
8. **Total volume per run:** ~8-16 requests (8 queries × 1-2 pages), under 1 minute
   of request time at 3s spacing

### ATS APIs (Greenhouse, Ashby, Lever)

These are public APIs with no auth required. Standard rate limiting applies. We use
existing throttling patterns from the Hermes pipeline (1 req/sec).

### apply_url HTML Fetches (Workday, iCIMS, etc.)

- 2-3 seconds between fetches
- Standard User-Agent
- Cache to disk
- These are public job posting pages — same as a human visiting them

---

## 12. Project Structure (Full System — All Phases)

> **Note:** This is the full-system tree. Phase 1 builds only `backend/seeker_os/`
> (excluding `api/`, `resume/`, `llm/`), `config/`, and `data/`. Frontend is Phase 2.
> See `docs/PHASE1_SPEC.md` for the Phase 1-specific subtree.

```
~/projects/seeker-os/
├── docs/
│   ├── PLAN.md                    # This document
│   ├── PRODUCT_DESIGN.md          # Config-driven architecture (read first)
│   ├── SOURCE_ADAPTERS.md         # Pluggable source adapter design
│   ├── LLM_ROUTING.md             # Provider/model routing
│   ├── CONTEXT.md                 # Current state & decisions
│   ├── PHASE1_SPEC.md             # Phase 1 implementation spec
│   ├── SCORING_RUBRIC.md          # Scoring rubric reference
│   ├── ACCURACY_RULES.md          # Resume accuracy rules reference
│   ├── HIRINGCAFE_FIELDS.md       # hiring.cafe __NEXT_DATA__ field reference
│   ├── DEDUP_DESIGN.md            # Dedup system detailed design
│   └── API_REFERENCE.md           # Auto-generated from FastAPI OpenAPI
├── backend/
│   ├── seeker_os/
│   │   ├── __init__.py
│   │   ├── main.py                # CLI entry point (Phase 1) / FastAPI app (Phase 2)
│   │   ├── config.py              # Settings management (loads all YAML configs)
│   │   ├── database.py            # SQLite connection, migrations
│   │   ├── models.py              # Pydantic v2 models
│   │   │
│   │   ├── discovery/             # Tier 1: source-agnostic discovery
│   │   │   ├── __init__.py
│   │   │   ├── engine.py          # Discovery engine: iterates sources × queries
│   │   │   ├── ats_fetch.py       # Tier 3: JD fetch from ATS APIs/URLs
│   │   │   ├── cache.py           # Disk cache for responses
│   │   │   └── sources/
│   │   │       ├── base.py        # SourceAdapter protocol
│   │   │       ├── hiring_cafe.py # hiring.cafe adapter (one of N sources)
│   │   │       └── registry.py    # Adapter registry
│   │   │
│   │   ├── filtering/             # Tier 2: card-level filters
│   │   │   ├── __init__.py
│   │   │   ├── hard_filters.py    # Structured-field hard filters
│   │   │   └── title_patterns.py  # Title matching (positive/negative)
│   │   │
│   │   ├── scoring/               # Tier 4: rubric scoring
│   │   │   ├── __init__.py
│   │   │   └── engine.py          # Generic rubric evaluator (reads scoring_rubric.yml)
│   │   │
│   │   ├── dedup/                 # Multi-layer dedup
│   │   │   ├── __init__.py
│   │   │   ├── normalize.py       # Title/company normalization
│   │   │   └── layers.py          # 4-layer dedup pipeline
│   │   │
│   │   ├── llm/                   # LLM provider abstraction (Phase 2.5+)
│   │   │   ├── __init__.py
│   │   │   ├── provider.py        # LLMProvider protocol
│   │   │   ├── anthropic_provider.py
│   │   │   ├── openai_compat_provider.py
│   │   │   └── router.py          # ModelRouter: task → tier → provider + model
│   │   │
│   │   ├── resume/                # Resume generation (Phase 3)
│   │   │   ├── __init__.py
│   │   │   ├── generator.py       # LLM-based resume tailoring
│   │   │   ├── validator.py       # Accuracy constraint checking (reads accuracy_rules.yml)
│   │   │   └── export.py          # PDF/DOCX export
│   │   │
│   │   ├── crossref/              # Cross-reference with job-search repo
│   │   │   ├── __init__.py
│   │   │   └── jobsearch_repo.py  # git pull + scan applied/rejected/closed
│   │   │
│   │   ├── pipeline/              # Orchestrator
│   │   │   ├── __init__.py
│   │   │   └── runner.py          # Tier 1→5 orchestration
│   │   │
│   │   └── api/                   # FastAPI routes (Phase 2)
│   │       ├── __init__.py
│   │       ├── jobs.py
│   │       ├── pipeline.py
│   │       ├── resumes.py
│   │       ├── queries.py
│   │       ├── settings.py
│   │       └── analytics.py
│   │
│   ├── tests/
│   ├── pyproject.toml
│   └── requirements.txt
│
├── frontend/                      # Phase 2
│   ├── package.json
│   ├── next.config.js
│   ├── tailwind.config.js
│   ├── src/
│   │   ├── app/
│   │   │   ├── layout.tsx
│   │   │   ├── page.tsx           # Dashboard
│   │   │   ├── jobs/page.tsx      # Jobs list
│   │   │   ├── pipeline/page.tsx  # Kanban
│   │   │   ├── resumes/page.tsx   # Resumes
│   │   │   ├── queries/page.tsx   # Query config
│   │   │   └── settings/page.tsx  # Settings
│   │   ├── components/
│   │   │   ├── JobTable.tsx
│   │   │   ├── JobDetail.tsx
│   │   │   ├── KanbanBoard.tsx
│   │   │   ├── PipelineFunnel.tsx
│   │   │   ├── StatCard.tsx
│   │   │   └── ResumeViewer.tsx
│   │   └── lib/
│   │       └── api.ts             # API client
│   └── ...
│
├── data/
│   ├── seeker.db                  # SQLite database
│   ├── cache/                     # Disk cache for HTTP responses
│   └── resumes/                   # Generated resume files
│
├── config/
│   ├── sources.yml                # Source adapter config (hiring.cafe + future)
│   ├── sources.example.yml        # Template
│   ├── providers.yml              # LLM providers, models, tier mapping
│   ├── providers.example.yml      # Template
│   ├── profile.yml                # User identity, comp, location (gitignored)
│   ├── profile.example.yml        # Template
│   ├── scoring_rubric.yml         # Scoring weights, patterns (gitignored)
│   ├── scoring_rubric.example.yml # Template
│   ├── accuracy_rules.yml         # Resume accuracy rules (gitignored)
│   ├── accuracy_rules.example.yml # Template
│   ├── queries.yml                # Search queries (gitignored)
│   ├── queries.example.yml        # Template
│   ├── filters.yml                # Filter thresholds
│   ├── filters.example.yml        # Template
│   ├── blacklist.txt              # Company blacklist (gitignored)
│   └── blacklist.example.txt      # Template
│
├── AGENTS.md                      # Project rules for AI agents
└── README.md
```

---

## 13. Implementation Phases

### Phase 1: Core Pipeline (no UI)
**Goal:** End-to-end pipeline that discovers, filters, fetches JDs, scores, and outputs
a ranked report. CLI-only.

**Build order** (see `docs/PHASE1_SPEC.md` §6 for the authoritative version):

0. Seniority enum probe — curl all 8 queries, collect distinct `seniority_level` values, update `filters.yml`
1. Set up project structure, dependencies, SQLite schema, config files
2. Implement Tier 1: source adapter interface + hiring.cafe adapter + `__NEXT_DATA__` extraction
3. Implement dedup normalize (`normalize_title()`, `normalize_company()`)
4. Implement dedup layers 1-4
5. Implement Tier 2: card-level hard filters
6. Implement Tier 3: JD fetch (Greenhouse/Ashby/Lever first, generic HTML fallback)
7. Implement Tier 4: scoring engine (config-driven, reads `scoring_rubric.yml`)
8. Implement Tier 5: ranking + cross-reference with job-search repo
9. CLI runner: `python -m seeker_os.main run` (entry point in `main.py`, orchestrator in `pipeline/runner.py`)
10. Output: stdout report + data in SQLite
11. Tests: write alongside each module, run full suite at end

### Phase 2: Web Dashboard
**Goal:** Visual interface for reviewing jobs, changing state, and configuring queries.

1. FastAPI backend with all API endpoints
2. Next.js frontend with dashboard, jobs list, job detail, Kanban
3. Query configuration UI
4. Settings UI
5. Basic analytics (funnel, response rate)

### Phase 3: Resume Generation
**Goal:** Automated resume tailoring with accuracy enforcement.

1. LLM integration (multi-provider: Anthropic, Ollama)
2. Resume generation prompt + model routing
3. Accuracy validation pass
4. PDF/DOCX export
5. Resume viewer in dashboard

### Phase 4: Polish & Automation
**Goal:** Production-ready, optionally automated.

1. Cron scheduling (opt-in, configurable)
2. Chrome extension for autofill (inspired by Jobs Optima)
3. Analytics dashboard (charts, trends, source analysis)
4. Import historical data from job-search repo
5. AI search integration (optional, browser-based)

---

## 14. Open Decisions (Resolved)

| # | Decision | Resolution |
|---|---|---|
| 1 | Query set | Configurable in DB/dashboard. Start with 8 queries from §5. |
| 2 | Page depth | Configurable per query (max_pages). Default 1, opt-in for 2+. |
| 3 | Freshness | Hard filter at Tier 2 (default 30 days, configurable). Also minor factor in scoring. |
| 4 | Contract search | Commitment filter per query (full_time/contract/both). |
| 5 | Shared scoring | Break from Hermes. New `scoring/engine.py` in Seeker OS. |
| 6 | Cross-reference | Local `~/projects/job-search` repo (git pull first). No SSH to Hermes. |
| 7 | AI search | Use regular search + our own AI. AI search is v2 optional. |
| 8 | Cron | On-demand first. Reconsider cron after manual validation. |
| 9 | Resume gen | Build locally with strict no-embellish enforcement. Model routing. |
| 10 | Dedup | 4-layer system (URL hash, composite key, content hash, fuzzy match). v2: embeddings. |
| 11 | robots.txt | Human-like requests (3-5s spacing), shallow pagination, standard UA. |
| 12 | Data structure | SQLite + web UI. No more scattered markdown files. |
| 13 | Existing tools | Build fresh, borrow patterns from CareerPulse/job-tracker/Jobs Optima. |

---

## 15. Risks & Mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| hiring.cafe structural change (Next.js refactor) | MEDIUM | Detect `ssrHits` key in response; fail loudly if missing. Cache last-known-good schema. |
| New ATS JD extraction quality | MEDIUM | Generic HTML-to-text fallback. Flag extraction quality in UI. Manual review path. |
| Fuzzy dedup false positives | LOW | Flagged for manual review, not silently merged. Conservative thresholds (90/85). |
| Resume accuracy violations | HIGH | Two-pass validation (generation + accuracy check). Flagged for review if violations found. Config-driven constraints (`accuracy_rules.yml`), not just prompt instructions. |
| LLM cost runaway | MEDIUM | Model routing (cheap models for bulk, expensive only for resume gen). Ollama for local inference. Configurable per task. |
| Scope creep (dashboard complexity) | MEDIUM | Phase 1 is CLI-only. UI is Phase 2. Resist adding features before core pipeline works. |
| job-search repo git conflicts on pull | LOW | `git pull --rebase` (not stash+pull, per Hermes lessons). Read-only access. |

---

## 16. References

- **Hermes job-scanner skill:** `~/.hermes/skills/research/job-scanner/SKILL.md` (on 192.168.50.195)
- **hiring.cafe feasibility spike:** `~/job-search/spikes/hiring-cafe-feasibility.md` (on 192.168.50.195)
- **hiring.cafe probe notes:** `~/.hermes/skills/research/job-scanner/references/hiringcafe-probe-jun2026.md` (on 192.168.50.195)
- **Existing scoring rubric:** `~/projects/job-search/ARCHITECTURE.md`
- **Master resume:** `~/projects/job-search/resume/Tony_Perkins_Master_Resume.md`
- **Targets config:** `~/projects/job-search/targets.yml`
- **Existing tools researched:** CareerPulse, JobSync, Jobs Optima, jermsmit/job-tracker, career-ops, hireforge, applypilot, OSApplyTrack
- **Dedup research:** pg_trgm fuzzy matching, multi-layer dedup patterns, embedding-based job dedup (MDPI paper)
