# Seeker OS — Project Rules

## Overview

Seeker OS is a reusable product — a structured job search pipeline with a web dashboard. It sources jobs from pluggable source adapters (currently hiring.cafe), applies tiered filtering, scores against a user-configured rubric, generates tailored resumes / cover letters / application answers with accuracy enforcement, runs on-demand company research with verified citations, and tracks the application lifecycle. The architecture is product-grade and config-driven — engines are generic, config makes them personal.

## Key Files

- `docs/PRODUCT_DESIGN.md` — Read first. Config-driven architecture, no-hardcode principles.
- `docs/SOURCE_ADAPTERS.md` — Pluggable source adapter interface, hiring.cafe as one adapter.
- `docs/LLM_ROUTING.md` — Provider abstraction, 3-tier model system, auto-discovery, search.
- `docs/CONTEXT.md` — "You are here" condensed state and decisions.
- `docs/SCORING_RUBRIC.md` — Scoring rubric reference (values; engine reads from YAML).
- `docs/ACCURACY_RULES.md` — Accuracy rules reference (values; validator reads from YAML).
- `docs/HIRINGCAFE_FIELDS.md` — hiring.cafe `__NEXT_DATA__` field reference.
- `docs/DEDUP_DESIGN.md` — Multi-layer dedup system design.
- `config/*.example.yml` — Config templates (placeholder values; real configs are gitignored).
- `docs/PLAN.md`, `docs/PHASE1_SPEC.md` — Historical design records. Useful for intent/rationale, but the code at HEAD is the source of truth where they differ.

---

## Critical Rules

### Product Design (MOST IMPORTANT)

- **NO HARDCODED PERSONAL VALUES in Python code.** All user-specific config lives in YAML: `profile.yml`, `scoring_rubric.yml`, `accuracy_rules.yml`, `identity_rules.yml`, `channel_rules.yml`, `queries.yml`, `filters.yml`, `company_research.yml`. Engines are generic; config makes them personal.
- This includes identity/positioning statements, experience-year counts, company names, and specific technologies in scoring/validation logic — none of these belong in `.py`, not as literals, not as defaults, not as example values baked into engine logic.
- Ship `*.example.yml` templates with **placeholder** values only. Real configs are `.gitignored`.
- **Audit rule:** grep `.py` files (and example configs) for personal values — names, comp numbers, company names, year counts, positioning strings, never-claim technologies. If found, it's a bug.

### Credentials

- **Secrets are NEVER literal in any committed file.** Config holds `${VAR_NAME}` references resolved from the environment at load time. The literal lives only in `.env` (gitignored) or an externally-injected env var.
- The settings UI captures keys, writes the literal to `.env`, writes only the `${VAR}` reference into the config, and calls `os.environ.update(...)` so a saved/rotated key takes effect without a restart. Mirror this pattern for any new secret (see `api/models.py` for LLM providers, `api/company_research_settings.py` for retrieval).
- Loader warns (does not fail) on an unresolved `${VAR}` (env unset → feature disabled) and on a literal-looking secret sitting in a committed YAML field.
- A pre-commit secret guard blocks staging `.env`/gitignored configs and literals in YAML.

### Resume / Cover Letter / Application Answer Generation

- **NO EMBELLISHING. Every claim must be traceable to the master resume.**
- Accuracy enforcement is two layers, both config-driven: (1) deterministic deny-list checks (disallowed phrases, forbidden technologies, required phrases, experience anchor, education omission) from `accuracy_rules.yml`, and (2) **LLM-judged claim traceability** — each factual claim is judged supported/unsupported/overstated against the master resume; unsupported/overstated is a high-severity violation. Empty master → fail closed (flag for review), not pass.
- The validator is **artifact-agnostic** (`seeker_os/validation/`): resume, cover_letter, application_answer all route through it. `resume/validator.py` is a backward-compat shim.
- Forbidden technologies / never-claim items (from config) must NEVER appear in generated output.
- **Identity rules** (`config/identity_rules.yml`) define positioning, experience anchor, honest qualifiers, and never-claim list. Injected into the JD analyzer and generator prompts at call time. No hardcoded identity values in system prompts. If no anchor is configured, the anchor check does not run — there is no default value in code.
- **Channel rules** (`config/channel_rules.yml`) define per-output-type constraints (resume `require_visible_urls`/`format_hints`, cover-letter tone, application-answer AI-generation default, analysis verdict thresholds).
- **Per-application AI policy** (`jobs.ai_policy`: `allowed` | `draft_only` | `forbidden` | null=channel default). `forbidden` → the generator refuses to author and returns a refusal; only critique of a user-supplied draft is allowed, and critique returns observations only (never authored/replacement prose). `draft_only` → content is generated clean; the draft notice is **separate metadata** (`is_draft` + `draft_notice`), never embedded in the copyable text.

### Company Research

- **On-demand only.** Triggered per job by the user, never batch/cron. A cache hit makes **zero** paid calls; a cache miss makes 2 Tavily calls (funding + sentiment query).
- **Pluggable retrieval adapter** (`seeker_os/research/retrieval/base.py`). Tavily is one adapter (`tavily.py`); registry builds from config (`registry.py`). Degrades cleanly to Wikipedia + Wikidata + JD context when no provider is configured.
- Retrieval provider type and API key come from `config/company_research.yml`, not code. Key is an env-var reference (`${RETRIEVAL_API_KEY}`), never literal.
- Query templates (`funding_query_template`, `sentiment_query_template`) are config-driven with a `{company}` placeholder; defaults preserve behavior when absent.
- **Citation verification is ENFORCED, not just prompted.** After the LLM returns the dossier, `_verify_dossier_sources` strips any claim-attached source URL that was not actually retrieved. The verified set = Tavily snippet URLs **plus** Wikipedia/Wikidata source URLs. URL matching is full host+path (a guessed path on a real domain is stripped), tracking params (`utm_*`, `ref`, `fbclid`, etc.) are normalized away, case-insensitive, subdomain-tolerant. Stripping that empties a section lowers that section's confidence; `overall_confidence` is then capped to the mean of section confidences (downward only) so the `is_stub` check reflects lost grounding. The raw retrieved snippets are persisted so provenance is verifiable.
- Thresholds are config-driven: `confidence_floor` (marks stubs), `staleness_months` (flags stale sentiment), `source_trust_order` (ranks sources — ordering only, no filtering or confidence inflation; stable sort, subdomain-tolerant, case-insensitive), `research_ttl_days` (cache reuse window).
- **Company-keyed caching.** Dossiers are stored and looked up by normalized company key, not job_id, so multiple jobs at one company reuse one dossier. Within `research_ttl_days` a fresh dossier is reused (no Tavily call); `force_refresh=true` bypasses the cache. The TTL trades freshness for cost — the signals the rescore weights most (layoffs, RTO) go stale fastest, so a stale-but-reused dossier is the first suspect if a research-adjusted score looks wrong.

### Scoring

- Scoring rubric is config-driven (`config/scoring_rubric.yml`). `docs/SCORING_RUBRIC.md` documents the values; the engine reads them from YAML. Post threshold, per-company cap, all weights/patterns are configurable.
- The heuristic/rubric score is **independent** of the LLM analysis — the precomputed score is never injected into the analyzer prompt.
- **Research-adjusted score** (`compute_research_adjustment`, `scoring/research_adjustment.py`): when company research has run, a separate adjusted score is produced from the base score plus confidence-gated, deterministic modifiers over dossier fields (layoffs, runway, remote walkback, recurring negative sentiment themes). It is **additive and auditable** (a factor/delta/confidence/section breakdown) and **never overwrites the base score** — both `base score` and `research_adjusted_score` are preserved. An `is_stub` or no-retrieval dossier produces zero adjustment. Thin-sample sentiment ratings do not move the score; only high-confidence recurring themes do. Modifier thresholds/magnitudes live in config.
- Use structured fields from hiring.cafe for comp/workplace/seniority when available.

### hiring.cafe Access

- hiring.cafe is one source adapter, not hardcoded. See `docs/SOURCE_ADAPTERS.md`.
- Use httpx to fetch `https://hiring.cafe/jobs/{query-slug}` — no browser. (Docs may say "curl" informally to mean "plain HTTP GET, no browser".)
- Extract job data from `__NEXT_DATA__` JSON in the HTML response.
- Request delay is configurable (default 3–5s). No concurrent requests.
- Page 0 only by default; deeper pagination is opt-in per query (configurable).
- Skip pinned jobs (`is_hc_pinned=true` or `source='hiring_cafe_pin'`).
- Cache responses to disk to avoid re-fetching within a run.
- Source map (`grnhse → greenhouse`) is in `config/sources.yml`, not code.

### Dedup

- 4-layer system: URL hash → composite key → content hash → fuzzy match.
- Flagged duplicates are NOT silently dropped — surfaced for manual review.
- Fuzzy thresholds are configurable. Normalization functions in `docs/DEDUP_DESIGN.md`.
- **One canonical company normalizer:** `dedup/normalize.py:normalize_company` is the single source for company-name normalization across the codebase (dedup AND company-research cache keys). Do not create a second normalizer — divergent normalizers cause silent cache misses and inconsistent dedup.

### Data Conventions

- Use **Pydantic v2** models for all config and data structures (not dataclasses) — validation, serialization, consistent typing.
- Config files (YAML) are the source of truth. DB tables are derived caches. YAML wins on startup. See `docs/PRODUCT_DESIGN.md` § Config ↔ DB Sync Ownership.

### Cross-Reference Repo

- Path is configurable in `profile.yml` (default: `~/projects/job-search`).
- ALWAYS `git pull --rebase` first before reading any data.
- Read-only access — never write to the cross-reference repo from Seeker OS.
- Scan: `applied/`, `rejected/`, `closed/`, `opportunities/`, `found/`.

### Database

- SQLite at `data/seeker.db` — single-user, zero-config.
- Schema migrations in `backend/seeker_os/database.py`. Migrations may be SQL strings or Python callables (callables used for data backfills); each runs once via version tracking.

### LLM Routing

- 1→N providers (Anthropic direct + any OpenAI-compatible gateway like Kilo).
- 1→N models per provider, with auto-discovery (`GET /models`) and search.
- 3 tiers: heavy (generation), moderate (analysis/critique), light (validation/traceability).
- Per-task overrides for fine-grained model selection. An unrecognized task name warns rather than silently defaulting.
- API keys as env-var references (`${VAR_NAME}`), never literal in config files.
- See `docs/LLM_ROUTING.md` for full details.

---

## Build Commands

```
# Backend
cd backend
pip install -e .
uvicorn seeker_os.api.app:app --reload --port 8000

# Frontend
cd frontend
npm install
npm run dev
```

## Testing

```
cd backend
pytest tests/
```

---

## Architecture Decisions

- **SQLite, not PostgreSQL/MongoDB** — single-user, zero-config, portable.
- **Python FastAPI backend** — matches existing scoring code, async, auto OpenAPI docs.
- **Next.js frontend** — mature ecosystem, SSR if needed, shadcn/ui components.
- **Multi-provider LLM** — model routing (cheap for bulk, expensive for generation).
- **On-demand first** — cron is a future opt-in, not the default.
- **Config-driven, no-hardcode** — generic engines + per-user YAML; the product is reusable by anyone, not personalized in code.
- **Break from legacy** — Seeker OS replaces scattered markdown-file approaches with a structured, queryable system.

---

## Known Limitations / Tracked Follow-ups (not defects)

- Company-research sources are section-level, not per-claim — verifiable in stored data but not attributable to a specific claim in the UI. Per-claim attribution is a future enhancement.
- `source_trust_order` affects display ordering only, not confidence weighting.
- No rate limiter on the Tavily adapter (fine for on-demand; needs a cap if research is ever auto-fired in bulk).
- Cover-letter / application-answer display pages not yet built (backend returns clean content + draft metadata; `DraftBanner` component exists).
- Onboarding wizard does not yet generate `identity_rules.yml` / `channel_rules.yml`.