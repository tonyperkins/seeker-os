# Seeker OS — Context & Current State

**Last updated:** 2026-06-27
**Phase:** Phase 3 — complete. Company research, resume generation, cover letters, application answers, JD analysis, net score, application lifecycle events, onboarding wizard, backup/restore, and Kanban board all implemented. Phase 4 (cron, analytics, historical import, Chrome extension) pending.

---

## You Are Here

Seeker OS is a **reusable product** — a job search pipeline with a web dashboard.
It is built to replace scattered-markdown-files approaches with a structured system.
No personal values are hardcoded in code. All user-specific config (comp floor,
blacklist, scoring weights, accuracy rules, resume path, location prefs) lives in
YAML config files.

The design is complete and documented. Phases 1–2 added the core pipeline, web
dashboard, and a three-tier AI rules layer (identity rules, channel rules,
per-application AI policy). Phase 2.5 added an onboarding wizard (resume ingest →
AI interview → config synthesis). Phase 3 added resume generation with strict
accuracy enforcement, cover letter generation, application answer generation,
AI-powered JD analysis, company research with a pluggable retrieval adapter
interface (Tavily as one adapter), live web search for funding signals and
employee sentiment, config-driven thresholds (confidence floor, staleness, source
trust ordering), research-adjusted scoring, net score (composite of base +
research + AI verdict cap), an append-only application lifecycle event log,
Kanban board with drag-and-drop status tracking, manual job entry, backup/restore
(config files + SQLite DB), and graceful degradation when no retrieval provider
is configured.

**Product mindset:** The engines (discovery, filtering, scoring, dedup, resume gen)
are generic. The config files (`profile.yml`, `scoring_rubric.yml`, `accuracy_rules.yml`,
`identity_rules.yml`, `channel_rules.yml`) make them personal. A different user creates
their own config and gets their own pipeline — without touching Python code.
See `docs/PRODUCT_DESIGN.md`.

## The Problem Being Solved

The current job search process (scattered markdown files) runs daily cron scans of
Greenhouse/Lever/Ashby/Workday/LinkedIn, scores jobs against the user's profile,
and writes results as markdown files. It works but is messy:
- Hundreds of rejected files, dozens of applied dirs — no queryable interface
- No analytics, no dashboard, no resume automation
- Manual resume tailoring by pasting JDs into an LLM (token-expensive, manual)
- hiring.cafe (a job aggregator indexing ~2.8M listings from ~46 ATS platforms) is
  not yet integrated despite a completed feasibility spike

## The Solution

A tiered funnel pipeline that sources from hiring.cafe's regular search API (no browser
needed — data is in `__NEXT_DATA__` JSON), narrows aggressively before fetching JDs,
scores survivors, generates tailored resumes with strict accuracy enforcement, and
tracks everything in a dashboard.

## Key Decisions (All Resolved)

| Decision | Resolution |
|---|---|
| hiring.cafe AI search vs regular search | Regular search + our own AI. AI search is a UI layer on the same data. |
| Browser dependency | None for main pipeline. Plain curl to `/jobs/{query}` extracts `__NEXT_DATA__` JSON. |
| Database | SQLite (single-user, zero-config) |
| Backend | Python FastAPI |
| Frontend | Next.js + Tailwind (Phase 2) |
| Scoring | Port rubric from Hermes, break from that codebase. Single source of truth in Seeker OS. |
| Dedup | 4-layer: URL hash → composite key → content hash → fuzzy match (rapidfuzz) |
| Resume gen | Automated with config-driven accuracy rules. NO EMBELLISHING. Model routing. |
| Cron | On-demand first. Reconsider after manual validation. |
| Cross-reference | Local `~/projects/job-search` repo (git pull first, read-only) |
| robots.txt | Human-like: 3-5s between requests, shallow pagination, standard UA |
| Existing tools | Evaluated 8 tools. None fit. Building fresh, borrowing patterns. |

## Document Map

| Document | What's in it | When to read |
|---|---|---|
| `docs/PRODUCT_DESIGN.md` | Config-driven architecture, profile/rubric/rules YAML framework, no-hardcode principles | **Read first** — establishes the product mindset |
| `docs/ARCHITECTURE.md` | Comprehensive system architecture: module map, pipeline flow, data flow, frontend structure | Understanding the full system at HEAD |
| `docs/API_REFERENCE.md` | All REST API endpoints organized by router | Building or debugging API integrations |
| `docs/DATABASE_SCHEMA.md` | All SQLite tables, columns, indexes, migration history | Understanding data model |
| `docs/APPLICATION_LIFECYCLE.md` | Job statuses, event types, transition rules, Kanban board, stale tracking | Understanding the application lifecycle |
| `docs/FRONTEND_ARCHITECTURE.md` | Next.js pages, components, API client, state management | Working on the frontend |
| `docs/SOURCE_ADAPTERS.md` | Pluggable source adapter interface, hiring.cafe as one adapter, sources.yml config | Implementing discovery layer |
| `docs/LLM_ROUTING.md` | Provider abstraction, 3-tier model system, auto-discovery, search, OAuth, multi-resume | Implementing LLM integration |
| `docs/PLAN.md` | Full architecture, data model, dashboard design, 4 implementation phases | Understanding the big picture (historical) |
| `docs/PHASE1_SPEC.md` | Exact interfaces, function signatures, CLI contract, acceptance criteria for Phase 1 | Implementing Phase 1 (historical) |
| `docs/SCORING_RUBRIC.md` | Scoring rubric reference, net score, verdict caps, research-adjusted score | Implementing the scoring engine |
| `docs/ACCURACY_RULES.md` | Resume accuracy rules reference, identity-rules and channel-rules layers, AI policy enforcement | Implementing resume/cover letter/application answer generation |
| `docs/HIRINGCAFE_FIELDS.md` | `__NEXT_DATA__` field reference, source mapping, query counts | Implementing discovery + dedup |
| `docs/DEDUP_DESIGN.md` | 4-layer dedup with normalization functions and code examples | Implementing dedup |
| `docs/DOCKER_DECISIONS.md` | Docker containerization decisions, volumes, env vars, production deployment | Running in Docker |
| `config/company_research.example.yml` | Company research config template — retrieval provider, query templates, thresholds | Implementing company research |
| `AGENTS.md` | Project rules for AI agents | Always (auto-loaded by agent tools) |

## User Profile (Quick Reference)

User profile is configured in `config/profile.yml`. Key fields:

- **Role:** Configure target title patterns in `scoring_rubric.yml`
- **Location:** Set accepted cities/states and remote preference in `profile.yml`
- **Comp:** `floor` (hard reject below), `target` (positive modifier), `stretch` (display context)
- **Experience:** `years` and `anchor_phrase` for resume generation
- **Key skills:** Configure as positive modifiers in `scoring_rubric.yml`
- **NOT interested in:** Configure as hard rejects and negative modifiers
- **Blacklisted companies:** List in `profile.yml` and `blacklist.txt`
- **AI assistance:** Configure accuracy rules in `accuracy_rules.yml`

## Phase Roadmap

| Phase | Goal | Status |
|---|---|---|
| 1 | Core pipeline (CLI): discover → filter → fetch JD → score → report. User configures profile, rubric, and rules via YAML. | Complete |
| 2 | Web dashboard: FastAPI + Next.js, all views | Complete |
| 2.5 | Onboarding wizard (dashboard): resume ingest → AI parse → config review. Generates profile.yml, scoring_rubric.yml, accuracy_rules.yml for new users. | Complete |
| 3 | Resume generation (LLM + accuracy enforcement + PDF/DOCX export), cover letter generation, application answer generation, AI-powered JD analysis, company research with pluggable retrieval adapter, config-driven thresholds, live web search for funding/sentiment signals, research-adjusted scoring, net score (verdict cap composite), application lifecycle events, Kanban board, manual job entry, backup/restore. | Complete |
| 4 | Polish: cron, analytics, historical import, Chrome extension | Pending |

## LLM Configuration

- **Providers:** 1 to N providers (Anthropic direct + any OpenAI-compatible gateway like Kilo)
- **Auth:** API key (env var reference) or OAuth token file (Anthropic OAuth flow)
- **Models:** 1 to N models per provider, with auto-discovery (`GET /models`) and search
- **3 tiers:** heavy (generation — Opus/Sonnet), moderate (analysis — Sonnet), light (validation — Haiku)
- **Per-task overrides:** fine-grained control (e.g., Opus for high-value resume gen, Sonnet for standard)
- **Tasks:** resume_generation, cover_letter, application_answer, application_answer_critique, jd_evaluation, company_research, accuracy_validation, onboarding_interview, onboarding_synthesis, resume_parsing, text_extraction
- **Config:** `config/providers.yml`
- See `docs/LLM_ROUTING.md` for full details

## Critical Constraints (Don't Forget)

1. **NO HARDCODED PERSONAL VALUES** — all user-specific config (comp, blacklist, scoring
   weights, accuracy rules, paths) lives in YAML config files. Engines are generic.
   See `docs/PRODUCT_DESIGN.md`.
2. **NO EMBELLISHING** in resume/cover letter/application answer generation — accuracy
   rules are config-driven validation, not just prompt instructions. LLM-judged claim
   traceability against the master resume is enforced after generation.
3. **Always `git pull --rebase`** before reading the cross-reference repo (path is configurable)
4. **3-5 seconds between hiring.cafe requests** — human-like, not aggressive (configurable)
5. **Skip pinned jobs** (`is_hc_pinned=true` or `source='hiring_cafe_pin'`)
6. **Read-only** to the cross-reference repo — never write to it from Seeker OS
7. **Flagged duplicates are surfaced for review** — never silently merged
8. **Structured comp fields** (integers) bypass the regex comp-parser bug
9. **Ship example configs** — `*.example.yml` templates with placeholder values.
   Real configs (`profile.yml`, etc.) are `.gitignore`d (contain personal data).
10. **Status changes go through `transition_status()`** — never UPDATE jobs.status
    directly without also recording an event row. See `docs/APPLICATION_LIFECYCLE.md`.
11. **Net score never overwrites base score** — `base_score`, `research_adjusted_score`,
    and `net_score` are all preserved separately in the jobs table.

## URL Verification (Phase 3)

Company research retrieval snippets are now persisted to the `company_research`
table (`retrieval_sources` and `retrieval_snippets_data` columns, Migration 10).
This enables post-hoc verification of LLM-attached source URLs.

**Enforcement gate:** After the LLM returns a dossier, every claim-attached source
URL (funding.sources, sentiment.sources, fit.sources) is checked against the set
of URLs actually returned by the retrieval adapter PLUS URLs from Wikipedia and
Wikidata used in this run. URLs not in the verified set are stripped. Sections
left with zero sources have confidence halved, a note added, and `overall_confidence`
is recomputed (capped to the mean of section confidences) so the `confidence_floor`
/ `is_stub` check reflects the lost grounding. `stripped_count` per section tracks
how many URLs were removed.

**URL normalization:** Comparison uses normalized URLs — lowercase host, trailing
slash stripped, fragment stripped, and common tracking parameters (`utm_*`, `ref`,
`source`, `fbclid`, `gclid`, etc.) removed. This prevents false-positive stripping
when Tavily returns a URL with tracking params and the LLM cites the same page
without them. Host + path matching remains strict — a guessed path on a
legitimate domain does not match.

**Correction (2026-06-25):** An earlier analysis identified `tamnoon.io/news/series-a-announcement`
and `tamnoon.io/news/seed-funding-announcement` as "model-fabricated" URLs. A live
re-run confirmed these URLs were genuinely returned by Tavily — they were not
invented by the model. The original issue was unverifiable provenance (no persisted
snippet set to cross-check against), which is now fixed by the persistence and
verification gate.

**Known limitation — section-level sources, not per-claim:**
Sources are stored at the section level (e.g., `funding.sources` is a flat list
shared by all funding claims). A specific figure (e.g., "$12M Series A") cannot
be mapped to a specific URL. Per-claim source attribution is a future enhancement
that would require the LLM output schema to carry a `source_url` field on each
claim, and the verification gate to check each claim's URL individually.

## Research-Adjusted Scoring (Phase 3.2)

When company research has run for a job, the deterministic base score (from the
rubric engine) is combined with confidence-gated modifiers derived from the
dossier to produce a **research-adjusted score**. The base score is NEVER
mutated — both `base_score` and `research_adjusted_score` are preserved.

**How it works:**
1. The rubric engine produces `base_score` (deterministic, JD-only).
2. `compute_research_adjustment()` takes the base score + dossier + config rules.
3. Each rule has a `factor`, `delta`, `confidence_threshold`, and `source_section`.
4. A rule only applies if the relevant section's confidence ≥ threshold AND the
   factor's condition is met (e.g., layoffs present, down round detected).
5. The total delta is summed and clamped to `[min_score, max_score]`.
6. A breakdown `[{factor, delta, confidence, source_section}]` is returned for UI.

**No grounding, no rescore:** If the dossier `is_stub` or `retrieval_used` is False,
NO adjustment is applied — `adjusted_score == base_score`, delta 0.

**Modifier set** (configured in `scoring_rubric.yml` under `research_modifiers`):
- `recent_layoffs` — penalty, if funding.confidence ≥ T
- `down_round_runway_risk` — penalty, if funding.confidence ≥ T
- `healthy_runway` — small bonus, if funding.confidence ≥ T
- `remote_walkback_rto` — penalty, if fit.confidence ≥ T
- `strong_negative_sentiment` — penalty, if sentiment.confidence ≥ T (only
  high-frequency recurring themes, NOT thin-sample numeric ratings)

**Thin-sample protection:** Sentiment modifiers require `frequency` of `med` or
`high` on a `SentimentTheme`. A low-frequency complaint or a bare numeric rating
from a small sample does NOT trigger the modifier.

## Company-Keyed Research Caching (Phase 3.2)

Company research is now cached **per company** (normalized name), not per job.
N roles at the same company = 1 research run = 2 Tavily calls, not 2N.

**TTL reuse:** A configurable `research_ttl_days` (default 30, in
`company_research.yml`) controls freshness. On a research request, if a fresh
(within TTL) dossier exists for the company, it is reused — no Tavily call.
Re-research only on explicit `force_refresh=true` or when the dossier is older
than the TTL.

**Response fields:** `reused_from_cache` (bool) and `dossier_age_days` (int)
indicate whether the dossier was freshly fetched or reused from cache.

**Migration 11** adds `company_norm` to `company_research` (indexed) and
`research_adjusted_score`, `research_delta`, `research_breakdown` to `jobs`.
