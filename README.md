# Seeker OS

A structured, dashboard-driven job search pipeline.

## Screenshots

### Dashboard — pipeline funnel, recent runs, top matches

![Dashboard (light)](docs/screenshots/dashboard-light.png)

### Jobs — filterable list with scoring and status badges

![Jobs (light)](docs/screenshots/jobs-light.png)

### Job Detail — score breakdown, analysis, and actions (expanded)

![Job Detail (light)](docs/screenshots/job-detail-expanded-light.png)

### Kanban — application lifecycle tracking

![Kanban (light)](docs/screenshots/kanban-light.png)

### Settings — profile, filters, accuracy rules, and provider config

![Settings (light)](docs/screenshots/settings-expanded-light.png)

---

## What It Does

1. **Discovers** jobs from supported sources (currently hiring.cafe; pluggable adapter architecture for adding more)
2. **Filters** aggressively using structured fields before fetching full JDs
3. **Scores** survivors against a user-configured rubric
4. **Analyzes** job fit with an AI agent that evaluates JD vs. profile, producing a verdict (APPLY/CONDITIONAL/MONITOR/SKIP) with named gaps, rubric breakdown, and tailoring guidance
5. **Generates** tailored resumes with strict no-embellish accuracy enforcement (deterministic deny-list checks + LLM-judged claim traceability against the master resume)
6. **Researches** companies with a pluggable retrieval adapter (Tavily as one adapter) — live web search for funding signals and employee sentiment, config-driven thresholds (confidence floor, staleness, source trust ordering), and graceful degradation when no retrieval provider is configured
7. **Tracks** the full application lifecycle through a web dashboard

## Why

Replaces scattered-markdown-files approaches with a unified, structured system. The old
way works but is messy — hundreds of markdown files spread across folders with no
queryable interface, no analytics, and no resume automation.

## Documentation

- [Product Design](docs/PRODUCT_DESIGN.md) — Config-driven architecture (read first)
- [Architecture](docs/ARCHITECTURE.md) — Comprehensive system architecture at HEAD
- [API Reference](docs/API_REFERENCE.md) — All REST API endpoints
- [Database Schema](docs/DATABASE_SCHEMA.md) — Tables, columns, indexes, migrations
- [Application Lifecycle](docs/APPLICATION_LIFECYCLE.md) — Job statuses, events, Kanban, stale tracking
- [Frontend Architecture](docs/FRONTEND_ARCHITECTURE.md) — Next.js pages, components, API client
- [LLM Routing](docs/LLM_ROUTING.md) — Multi-provider model routing, OAuth, task tiers
- [Scoring Rubric](docs/SCORING_RUBRIC.md) — Base score, research-adjusted score, net score
- [Resume Accuracy Rules](docs/ACCURACY_RULES.md) — Validation, identity rules, channel rules, AI policy
- [Source Adapters](docs/SOURCE_ADAPTERS.md) — Pluggable source adapter design
- [hiring.cafe Field Reference](docs/HIRINGCAFE_FIELDS.md)
- [Dedup Design](docs/DEDUP_DESIGN.md)
- [Docker Decisions](docs/DOCKER_DECISIONS.md) — Containerization, volumes, production deployment
- [Plan & Architecture](docs/PLAN.md) — Historical design records

## Status

**Phases 1-3 complete** — Core pipeline, web dashboard, resume generation with
accuracy enforcement, cover letter generation, application answer generation,
AI-powered JD analysis, company research with live retrieval, research-adjusted
scoring, net score (verdict cap composite), application lifecycle events, Kanban
board, onboarding wizard, manual job entry, and backup/restore are all implemented.
Phase 4 (cron, analytics, historical import, Chrome extension) is pending. See
[docs/CONTEXT.md](docs/CONTEXT.md) for current state and
[docs/PLAN.md](docs/PLAN.md) for the full roadmap.

## Tech Stack

- **Database:** SQLite
- **Backend:** Python + FastAPI
- **Frontend:** Next.js + Tailwind CSS + shadcn/ui
- **AI:** Multi-provider (Anthropic direct + OpenAI-compatible gateways) with 3-tier model routing, OAuth support, and per-task overrides
- **Job sources:** Pluggable adapter architecture (currently supports hiring.cafe via `__NEXT_DATA__` JSON extraction)
- **Company research:** Pluggable retrieval adapter (Tavily as one adapter, degrades to Wikipedia/Wikidata when unconfigured)
- **Deployment:** Docker Compose (backend + frontend containers, shared volume for SQLite + config)

## Pre-commit Secret Guard

A lightweight hook blocks commits that stage gitignored files (`.env`, real config
YAMLs) or contain literal secrets in credential fields of YAML/Python files.

**Install with pre-commit (recommended):**

```bash
pip install pre-commit
pre-commit install
```

**Or install as a plain git hook:**

```bash
cp scripts/check-secrets.sh .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

Bypass with `git commit --no-verify` (not recommended).

## Settings UI

The **Settings** page in the web dashboard provides a no-edit-config-files interface for:

- **Company Research** — configure the retrieval provider (Tavily) and API key without
  hand-editing `config/company_research.yml`. The API key is written to `.env` as a
  literal under `RETRIEVAL_API_KEY`; the config file stores only the `${RETRIEVAL_API_KEY}`
  reference. A "Test Connection" button verifies the key works before running research.
  Advanced settings (max results, query templates, confidence floor, staleness months,
  source trust order, User-Agent) are available in a collapsible section.
- **Profile & Filters** — auto-extracted from your master resume, then editable.
- **Accuracy Rules** — resume validation constraints (disallowed phrases, forbidden tech, etc.).
- **LLM Providers** — model routing, tier assignments, and provider API keys. Supports
  API key auth and Anthropic OAuth (PKCE flow) for passwordless authentication.
- **Backup & Restore** — download all config files as a zip, restore from upload,
  download SQLite DB snapshot, restore DB from upload.

## Onboarding

The **Onboarding** wizard (`/onboarding`) guides new users through initial setup:
1. **LLM Provider** — configure at least one provider (API key or OAuth).
2. **Resume Upload** — upload master resume (Markdown or text), parsed by LLM.
3. **Config Review** — review and edit auto-extracted profile, filters, and accuracy rules.
