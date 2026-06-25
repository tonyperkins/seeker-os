# Seeker OS

A structured, dashboard-driven job search pipeline.

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
- [Plan & Architecture](docs/PLAN.md)
- [LLM Routing](docs/LLM_ROUTING.md) — Multi-provider model routing
- [Scoring Rubric](docs/SCORING_RUBRIC.md)
- [Resume Accuracy Rules](docs/ACCURACY_RULES.md)
- [Source Adapters](docs/SOURCE_ADAPTERS.md) — Pluggable source adapter design
- [hiring.cafe Field Reference](docs/HIRINGCAFE_FIELDS.md)
- [Dedup Design](docs/DEDUP_DESIGN.md)

## Status

**Phases 1-3 complete, Phase 3 company research in progress** — Core pipeline, web
dashboard, resume generation, AI-powered JD analysis, and company research with live
retrieval are implemented. Phase 3 adds a pluggable retrieval adapter interface,
config-driven thresholds, and live web search for funding/sentiment signals. See
[docs/PLAN.md](docs/PLAN.md) for the full roadmap.

## Tech Stack

- **Database:** SQLite
- **Backend:** Python + FastAPI
- **Frontend:** Next.js + Tailwind CSS
- **AI:** Multi-provider (Ollama local, Anthropic, OpenAI) with model routing
- **Job sources:** Pluggable adapter architecture (currently supports hiring.cafe via `__NEXT_DATA__` JSON extraction)
