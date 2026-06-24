# Seeker OS — Project Rules

## Overview

Seeker OS is a **reusable product** — a structured job search pipeline with a web
dashboard. It sources jobs from hiring.cafe, applies tiered filtering, scores against
a user-configured rubric, generates tailored resumes with accuracy enforcement, and
tracks the application lifecycle. It happens to be built for Tony Perkins' needs but
the architecture is product-grade.

## Key Files

- `docs/PRODUCT_DESIGN.md` — **Read first.** Config-driven architecture, no-hardcode principles
- `docs/SOURCE_ADAPTERS.md` — Pluggable source adapter interface, hiring.cafe as one adapter
- `docs/LLM_ROUTING.md` — Provider abstraction, 3-tier model system, auto-discovery, search
- `docs/CONTEXT.md` — "You are here" condensed state and decisions
- `docs/PLAN.md` — Full design and implementation plan
- `docs/PHASE1_SPEC.md` — Implementation-ready spec for Phase 1
- `docs/SCORING_RUBRIC.md` — Scoring rubric reference (values; engine reads from YAML)
- `docs/ACCURACY_RULES.md` — Resume accuracy rules reference (values; validator reads from YAML)
- `docs/HIRINGCAFE_FIELDS.md` — hiring.cafe `__NEXT_DATA__` field reference
- `docs/DEDUP_DESIGN.md` — Multi-layer dedup system design

## Critical Rules

### Product Design (MOST IMPORTANT)
- **NO HARDCODED PERSONAL VALUES in Python code.** All user-specific config lives in
  YAML files: `profile.yml`, `scoring_rubric.yml`, `accuracy_rules.yml`, `queries.yml`,
  `filters.yml`. Engines are generic; config makes them personal.
- Ship `*.example.yml` templates with placeholder values. Real configs are `.gitignore`d.
- Audit rule: grep `.py` files for personal values (names, comp numbers, company names,
  specific technologies in scoring logic) — if found, it's a bug.

### Resume Generation
- **NO EMBELLISHING.** Every claim must be traceable to the master resume.
- Accuracy rules are config-driven (`config/accuracy_rules.yml`), validated
  programmatically after generation. Violations are flagged for manual review.
- Forbidden technologies (from config) must NEVER appear in generated resumes.

### hiring.cafe Access
- hiring.cafe is one source adapter, not hardcoded. See `docs/SOURCE_ADAPTERS.md`.
- Use httpx (Python HTTP client) to fetch `https://hiring.cafe/jobs/{query-slug}` — no
  browser needed. (Docs may say "curl" informally to mean "plain HTTP GET, no browser".)
- Extract job data from `__NEXT_DATA__` JSON in the HTML response.
- Request delay is configurable (default 3-5 seconds). No concurrent requests.
- Page 0 only by default. Deeper pagination is opt-in per query (configurable).
- Skip pinned jobs (`is_hc_pinned=true` or `source='hiring_cafe_pin'`).
- Cache responses to disk to avoid re-fetching within a run.
- Source map (grnhse → greenhouse) is in `config/sources.yml`, not code.

### Data Conventions
- Use Pydantic v2 models for all config and data structures (not dataclasses).
  This ensures validation, serialization, and consistent typing.
- Config files (YAML) are the source of truth. DB tables are derived caches.
  YAML wins on startup. See `docs/PRODUCT_DESIGN.md` § Config ↔ DB Sync Ownership.

### Cross-Reference Repo
- Path is configurable in `profile.yml` (default: `~/projects/job-search`).
- **ALWAYS `git pull --rebase` first** before reading any data.
- Read-only access — never write to the cross-reference repo from Seeker OS.
- Scan: `applied/`, `rejected/`, `closed/`, `opportunities/`, `found/`

### Scoring
- Scoring rubric is config-driven (`config/scoring_rubric.yml`).
- `docs/SCORING_RUBRIC.md` documents the values — the engine reads them from YAML.
- Post threshold, per-company cap, all weights/patterns are configurable.
- Use structured fields from hiring.cafe for comp/workplace/seniority when available.

### Dedup
- 4-layer system: URL hash → composite key → content hash → fuzzy match.
- Flagged duplicates are NOT silently dropped — surfaced for manual review.
- Normalization functions in `docs/DEDUP_DESIGN.md`.
- Fuzzy thresholds are configurable.

### Database
- SQLite at `data/seeker.db` — single-user, zero-config.
- Schema migrations in `backend/seeker_os/database.py`.

### LLM Routing
- 1 to N providers (Anthropic direct + any OpenAI-compatible gateway like Kilo).
- 1 to N models per provider, with auto-discovery (`GET /models`) and search.
- 3 tiers: heavy (generation), moderate (analysis), light (validation).
- Per-task overrides for fine-grained model selection.
- API keys as env var references (`${VAR_NAME}`), never literal in config files.
- `providers.yml` schema is defined in Phase 1; LLM calls begin in Phase 2.5+.
- See `docs/LLM_ROUTING.md` for full details.

## Build Commands

```bash
# Backend
cd backend
pip install -e .
uvicorn seeker_os.main:app --reload --port 8000

# Frontend
cd frontend
npm install
npm run dev
```

## Testing

```bash
cd backend
pytest tests/
```

## Architecture Decisions

- **SQLite, not PostgreSQL/MongoDB** — single-user, zero-config, portable.
- **Python FastAPI backend** — matches existing scoring code, async, auto OpenAPI docs.
- **Next.js frontend** — mature ecosystem, SSR if needed, shadcn/ui components.
- **Multi-provider LLM** — model routing (cheap for bulk, expensive for resume gen).
- **On-demand first** — cron is a future opt-in, not the default.
- **Break from Hermes** — Seeker OS is the future of the job search project. The Hermes
  skill and markdown-file system are the past.
