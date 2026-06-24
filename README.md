# Seeker OS

A structured, dashboard-driven job search pipeline.

## What It Does

1. **Discovers** jobs from hiring.cafe's search API (no browser required)
2. **Filters** aggressively using structured fields before fetching full JDs
3. **Scores** survivors against a tuned SRE/Platform/DevOps rubric
4. **Generates** tailored resumes with strict no-embellish accuracy enforcement
5. **Tracks** the full application lifecycle through a web dashboard

## Why

Replaces the scattered-markdown-files approach (Hermes/Clawford) with a unified,
structured system. The old system works but is messy — hundreds of markdown files
spread across folders with no queryable interface, no analytics, and no resume
automation.

## Documentation

- [Plan & Architecture](docs/PLAN.md)
- [Scoring Rubric](docs/SCORING_RUBRIC.md)
- [Resume Accuracy Rules](docs/ACCURACY_RULES.md)
- [hiring.cafe Field Reference](docs/HIRINGCAFE_FIELDS.md)
- [Dedup Design](docs/DEDUP_DESIGN.md)

## Status

**Planning phase** — design complete, implementation not started.

## Tech Stack

- **Database:** SQLite
- **Backend:** Python + FastAPI
- **Frontend:** Next.js + Tailwind CSS
- **AI:** Multi-provider (Ollama local, Anthropic, OpenAI) with model routing
- **Job source:** hiring.cafe regular search API (`__NEXT_DATA__` JSON extraction)
