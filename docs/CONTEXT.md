# Seeker OS — Context & Current State

**Last updated:** 2026-06-23
**Phase:** Planning complete, Phase 1 implementation starting

---

## You Are Here

Seeker OS is a **reusable product** — a job search pipeline with a web dashboard.
It is built to replace scattered-markdown-files approaches with a structured system.
No personal values are hardcoded in code. All user-specific config (comp floor,
blacklist, scoring weights, accuracy rules, resume path, location prefs) lives in
YAML config files.

The design is complete and documented. No code has been written yet.

**Product mindset:** The engines (discovery, filtering, scoring, dedup, resume gen)
are generic. The config files (`profile.yml`, `scoring_rubric.yml`, `accuracy_rules.yml`)
make them personal. A different user creates their own config and gets their own
pipeline — without touching Python code. See `docs/PRODUCT_DESIGN.md`.

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
| `docs/SOURCE_ADAPTERS.md` | Pluggable source adapter interface, hiring.cafe as one adapter, sources.yml config | Implementing discovery layer |
| `docs/LLM_ROUTING.md` | Provider abstraction, 3-tier model system, auto-discovery, search, multi-resume | Implementing LLM integration (schema defined in Phase 1) |
| `docs/PLAN.md` | Full architecture, data model, dashboard design, 4 implementation phases | Understanding the big picture |
| `docs/PHASE1_SPEC.md` | Exact interfaces, function signatures, CLI contract, acceptance criteria for Phase 1 | Implementing Phase 1 |
| `docs/SCORING_RUBRIC.md` | Scoring rubric reference (the *values* — the *engine* reads them from YAML) | Implementing the scoring engine |
| `docs/ACCURACY_RULES.md` | Resume accuracy rules reference (the *values* — the *validator* reads them from YAML) | Implementing resume generation (Phase 3) |
| `docs/HIRINGCAFE_FIELDS.md` | `__NEXT_DATA__` field reference, source mapping, query counts | Implementing discovery + dedup |
| `docs/DEDUP_DESIGN.md` | 4-layer dedup with normalization functions and code examples | Implementing dedup |
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
| 1 | Core pipeline (CLI): discover → filter → fetch JD → score → report. User configures profile, rubric, and rules via YAML. | Starting now |
| 2 | Web dashboard: FastAPI + Next.js, all views | Pending Phase 1 |
| 2.5 | Onboarding wizard (CLI first, path to dashboard): resume ingest → AI interview → freeform rules → AI synthesis → config review. Generates profile.yml, scoring_rubric.yml, accuracy_rules.yml for new users. | Pending Phase 2 |
| 3 | Resume generation: LLM + accuracy enforcement + PDF export | Pending Phase 2.5 |
| 4 | Polish: cron, analytics, historical import, Chrome extension | Pending Phase 3 |

## LLM Configuration

- **Providers:** 1 to N providers (Anthropic direct + any OpenAI-compatible gateway like Kilo)
- **Models:** 1 to N models per provider, with auto-discovery (`GET /models`) and search
- **3 tiers:** heavy (generation — Opus/Sonnet), moderate (analysis — Sonnet), light (validation — Haiku)
- **Per-task overrides:** fine-grained control (e.g., Opus for high-value resume gen, Sonnet for standard)
- **Config:** `config/providers.yml` (schema defined in Phase 1, LLM calls begin Phase 2.5+)
- See `docs/LLM_ROUTING.md` for full details

## Critical Constraints (Don't Forget)

1. **NO HARDCODED PERSONAL VALUES** — all user-specific config (comp, blacklist, scoring
   weights, accuracy rules, paths) lives in YAML config files. Engines are generic.
   See `docs/PRODUCT_DESIGN.md`.
2. **NO EMBELLISHING** in resume generation — accuracy rules are config-driven validation,
   not just prompt instructions
3. **Always `git pull --rebase`** before reading the cross-reference repo (path is configurable)
4. **3-5 seconds between hiring.cafe requests** — human-like, not aggressive (configurable)
5. **Skip pinned jobs** (`is_hc_pinned=true` or `source='hiring_cafe_pin'`)
6. **Read-only** to the cross-reference repo — never write to it from Seeker OS
7. **Flagged duplicates are surfaced for review** — never silently merged
8. **Structured comp fields** (integers) bypass the regex comp-parser bug
9. **Ship example configs** — `*.example.yml` templates with placeholder values.
   Real configs (`profile.yml`, etc.) are `.gitignore`d (contain personal data).
