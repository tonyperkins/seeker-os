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
5. **Generates** tailored resumes with strict no-embellish accuracy enforcement (deterministic deny-list checks + LLM-judged claim traceability against the master resume) and an ATS parse-survival gate that verifies critical content survives text extraction from HTML, DOCX, and PDF formats
6. **Researches** companies with a pluggable retrieval adapter (Tavily as one adapter) — live web search for funding signals and employee sentiment, config-driven thresholds (confidence floor, staleness, source trust ordering), and graceful degradation when no retrieval provider is configured
7. **Tracks** the full application lifecycle through a web dashboard

## JD Lifecycle — Discovery to Outcome

Every job flows through an automated pipeline (Tiers 1-5), then human review, then a post-apply lifecycle — with every status change recorded in an append-only event log.

```mermaid
flowchart TD
    subgraph Pipeline["Automated Pipeline (Tiers 1-5)"]
        T1["Tier 1: Discovery\nSource adapters fetch job cards\n→ DISCOVERED"] --> DEDUP1{"Duplicate?\nLayers 1-2: source ID\n+ fuzzy title/company"}
        DEDUP1 -->|Yes| DROP["Skipped — duplicate"]
        DEDUP1 -->|No| T2["Tier 2: Card-Level Filters\nTitle/seniority/location/workplace\nhard filters"]
        T2 -->|Pass| T3["Tier 3: Full JD Fetch\nATS API or detail page scrape\n→ JD_FETCHED"]
        T2 -->|Fail| REJ_SYS["REJECTED\nfilter_rejected"]
        T3 --> DEDUP2{"Content hash\nduplicate?\nLayer 3"}
        DEDUP2 -->|Yes| DUP["DUPLICATE_FLAGGED"]
        DEDUP2 -->|No| T4["Tier 4: Heuristic Scoring\nRegex rubric on title + JD text\n→ score + modifiers"]
        T3 -->|Fetch fail| REJ_SYS
        T4 --> HARD{"Hard reject?\nEvidence gate /\nnever-claim patterns"}
        HARD -->|Yes| REJ_SYS
        HARD -->|No| THRESH{"Score ≥\npost_threshold?"}
        THRESH -->|No| REJ_SYS
        THRESH -->|Yes| READY["READY\nscored_ready"]
        READY --> T5["Tier 5: Ranking\nPer-company cap + cross-ref"]
        T5 --> CAP{"Over per-company\ncap?"}
        CAP -->|Yes| CAPPED["CAPPED"]
        CAP -->|No| REVIEW["Ready for human review"]
    end

    subgraph Human["Human Review (Candidate)"]
        REVIEW --> CHOICE{"Candidate\ndecision"}
        CHOICE -->|Skip| SKIPPED["SKIPPED\nmanual skip"]
        CHOICE -->|Reject| REJ_MAN["REJECTED\nmanual reject w/ reason"]
        CHOICE -->|Review| REV["REVIEWING\ntransient review state"]
        REV -->|Generate resume| INTERESTED["INTERESTED\nresume_generated"]
        REV -->|Skip| SKIPPED
        INTERESTED --> APPLY_DECIDE{"Apply?"}
        INTERESTED -->|Decline| SKIPPED
        APPLY_DECIDE -->|Yes| APPLIED["APPLIED\ncandidate submits"]
        APPLY_DECIDE -->|No| SKIPPED
    end

    subgraph PostApply["Post-Apply Lifecycle"]
        APPLIED --> ENGAGE{"Company\nresponds?"}
        ENGAGE -->|Silent / rejected| COMP_REJ["COMPANY_REJECTED\nterminal"]
        ENGAGE -->|Candidate withdraws| WITHDRAWN["WITHDRAWN\nterminal"]
        ENGAGE -->|Engages| ENGAGED["ENGAGED\ninterview / challenge /\noffer sub-events"]
        ENGAGED --> OFFER{"Offer\nreceived?"}
        OFFER -->|No offer / rejected| COMP_REJ
        OFFER -->|Candidate withdraws| WITHDRAWN
        OFFER -->|Accept| OFFER_ACC["OFFER_ACCEPTED\nterminal ✓"]
        OFFER -->|Decline| OFFER_DEC["OFFER_DECLINED\nterminal"]
    end

    REJ_SYS -.->|Refilter/rescore\nmay revive| T4
    REJ_MAN -.->|Override| REV
```

**Automated pipeline:**

- **Tier 1: Discovery** — source adapters fetch job cards and normalize them into `JobCard` models. Dedup layers 1-2 (source ID + fuzzy title/company match) run before DB insert.
- **Tier 2: Card-Level Filters** — hard filters on title patterns, seniority, location, workplace type. Fail → `rejected` with reason.
- **Tier 3: Full JD Fetch** — fetches complete JD text via ATS API or detail page scrape. Content hash dedup (layer 3) runs after fetch. Fail → `rejected` (retryable on next run).
- **Tier 4: Heuristic Scoring** — deterministic regex rubric scores title + JD text. Hard rejects or below-threshold → `rejected`. Above threshold → `ready`.
- **Tier 5: Ranking** — per-company cap limits how many jobs from one company appear in a run. Over-cap → `capped`. Cross-reference against prior application history.

**Human review:**

- **Reviewing** → **Interested** (via resume generation) → **Applied**. Skip and manual reject are dead ends (can be overridden).
- **Applied** is the handoff from automated pipeline to post-apply lifecycle.

**Post-apply lifecycle:**

- **Engaged** — company responded (interview, challenge, offer sub-events recorded as timeline events).
- Terminal states: **Offer Accepted** ✓, **Offer Declined**, **Company Rejected**, **Withdrawn**.
- Transitions are enforced by a `VALID_TRANSITIONS` map — no skipping states.

See [Application Lifecycle](docs/APPLICATION_LIFECYCLE.md) for full details.

## Why

Replaces scattered-markdown-files approaches with a unified, structured system. The old
way works but is messy — hundreds of markdown files spread across folders with no
queryable interface, no analytics, and no resume automation.

## Documentation

- [Product Design](docs/PRODUCT_DESIGN.md) — Config-driven architecture (read first)
- [Architecture](docs/ARCHITECTURE.md) — Comprehensive system architecture
- [API Reference](docs/API_REFERENCE.md) — All REST API endpoints
- [Application Lifecycle](docs/APPLICATION_LIFECYCLE.md) — Job statuses, events, Kanban, stale tracking
- [LLM Routing](docs/LLM_ROUTING.md) — Multi-provider model routing, OAuth, task tiers
- [Scoring Rubric](docs/SCORING_RUBRIC.md) — Base score, research-adjusted score, net score
- [Resume Accuracy Rules](docs/ACCURACY_RULES.md) — Validation, identity rules, channel rules, AI policy, ATS parse-survival gate
- [Source Adapters](docs/SOURCE_ADAPTERS.md) — Pluggable source adapter design
- [hiring.cafe Field Reference](docs/HIRINGCAFE_FIELDS.md)
- [Dedup Design](docs/DEDUP_DESIGN.md)
- [Langfuse LLM Observability](docs/LANGFUSE_INTEGRATION.md) — Optional tracing, cost-per-artifact, budget caps
- [Inbound Email](docs/INBOUND_EMAIL.md) — Dedicated Gmail setup, Cloudflare Worker fan-out, review workflow, and recovery

## Status

**Phases 1-3 complete** — Core pipeline, web dashboard, resume generation with
accuracy enforcement, cover letter generation, application answer generation,
AI-powered JD analysis, company research with live retrieval, research-adjusted
scoring, net score (verdict cap composite), application lifecycle events, Kanban
board, onboarding wizard, manual job entry, and backup/restore are all implemented.
Phase 4 (cron, analytics, historical import, Chrome extension) is pending.

## Tech Stack

- **Database:** SQLite
- **Backend:** Python + FastAPI
- **Frontend:** Next.js + Tailwind CSS + shadcn/ui
- **AI:** Multi-provider (Anthropic direct + OpenAI-compatible gateways) with 3-tier model routing, OAuth support, and per-task overrides
- **Job sources:** Pluggable adapter architecture (currently supports hiring.cafe via `__NEXT_DATA__` JSON extraction)
- **Company research:** Pluggable retrieval adapter (Tavily as one adapter, degrades to Wikipedia/Wikidata when unconfigured)
- **Deployment:** Docker Compose (backend + frontend containers, shared volume for SQLite + config)

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
- **Backup & Restore** — download all config files as a zip (`.env` excluded by
  default; pass `include_secrets=true` to include it), restore from upload,
  download SQLite DB snapshot, restore DB from upload.

## Security & Data Hygiene

Seeker OS runs locally on your machine — there is no network-facing attack surface
by design. However, the data at rest is sensitive:

- **`data/seeker.db`** contains candid employer assessments, application notes,
  and scoring data. Treat it as private.
- **`config/*.yml`** files contain your personal profile, scoring rubric, and
  identity rules. Real configs are gitignored.
- **`.env`** contains API keys for LLM providers and retrieval services. It is
  gitignored and excluded from default backups.
- **Gmail OAuth tokens** are stored locally in `data/.gmail_oauth.json` with
  owner-only permissions. They are never included in backup archives, including
  `include_secrets=true`; restoring requires a fresh Gmail authorization.

**Backup awareness:** Backup zips downloaded via the API exclude `.env` by default.
Use `include_secrets=true` only when you need to transfer keys to a new machine,
and delete the backup afterward. Be deliberate about where backup files and the
SQLite database are stored — cloud sync folders, shared drives, and version
control are all potential leak vectors for this data.

## Onboarding

The **Onboarding** wizard (`/onboarding`) guides new users through initial setup:
1. **LLM Provider** — configure at least one provider (API key or OAuth).
2. **Resume Upload** — upload master resume (Markdown or text), parsed by LLM.
3. **Config Review** — review and edit auto-extracted profile, filters, and accuracy rules.
