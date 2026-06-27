# Seeker OS — Database Schema

**Last updated:** 2026-06-27
**Database:** SQLite at `data/seeker.db`
**Migrations:** 16 (versioned via `PRAGMA user_version`, no Alembic)

---

## Tables

### `jobs`

Core table — one row per discovered or manually added job.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `source_id` | TEXT | Source adapter ID (e.g. `hiring_cafe`) |
| `source_job_id` | TEXT | Job ID from source |
| `ats_source` | TEXT | ATS type (greenhouse, lever, ashby, etc.) |
| `ats_board_token` | TEXT | ATS board token |
| `ats_job_id` | TEXT | Job ID within ATS |
| `apply_url` | TEXT | Direct application URL |
| `url_hash` | TEXT UNIQUE | SHA-256 of job URL (dedup layer 1) |
| `title` | TEXT | Job title |
| `core_title` | TEXT | Normalized core title |
| `company` | TEXT | Company name |
| `company_homepage` | TEXT | Company website URL |
| `location` | TEXT | Location string |
| `workplace_type` | TEXT | remote / hybrid / on-site |
| `workplace_countries` | TEXT (JSON array) | Countries from structured fields |
| `seniority_level` | TEXT | Seniority enum from structured fields |
| `commitment` | TEXT (JSON array) | Commitment types (full-time, etc.) |
| `comp_min` | INTEGER | Minimum yearly compensation |
| `comp_max` | INTEGER | Maximum yearly compensation |
| `comp_currency` | TEXT | Compensation currency |
| `technical_tools` | TEXT (JSON array) | Technologies from structured fields |
| `requirements_summary` | TEXT | Short requirements summary |
| `date_posted` | TEXT | Date posted (ISO) |
| `role_type` | TEXT | Role type |
| `status` | TEXT | Current job status (see APPLICATION_LIFECYCLE.md) |
| `tier_passed` | INTEGER | Highest tier passed (0-5) |
| `score` | REAL | Base heuristic rubric score (0-10) |
| `score_reasons` | TEXT (JSON array) | Scoring reasons |
| `score_gaps` | TEXT (JSON array) | Scoring gaps |
| `jd_full` | TEXT | Full job description text |
| `jd_fetch_status` | TEXT | pending / fetched / failed |
| `discovered_at` | TEXT | ISO timestamp |
| `discovered_query` | TEXT | Query slug that found this job |
| `updated_at` | TEXT | ISO timestamp |
| `is_pinned` | BOOLEAN | Pinned (skipped in discovery) |
| `reject_reason` | TEXT | Reason for rejection |
| `content_hash` | TEXT | Content hash (dedup layer 3) |
| `title_norm` | TEXT | Normalized title (dedup) |
| `company_norm` | TEXT | Normalized company (dedup + research cache key) |
| `cross_ref_status` | TEXT | Cross-reference repo match status |
| `cross_ref_date` | TEXT | Cross-reference check date |
| `cross_ref_score` | REAL | Cross-reference match score |
| `reject_details` | TEXT | Free-text rejection feedback (v3) |
| `detail_url` | TEXT | hiring.cafe detail page URL (v4) |
| `ai_policy` | TEXT | `allowed` / `draft_only` / `forbidden` / null (v8) |
| `filter_warnings` | TEXT | Filter warnings (v13) |
| `overridden_at` | TEXT | Override timestamp (v13) |
| `override_note` | TEXT | Override reason note (v13) |
| `original_reject_reason` | TEXT | Pre-override reject reason (v13) |
| `analysis_verdict` | TEXT | AI verdict: APPLY / CONDITIONAL / MONITOR / SKIP (v14) |
| `analysis_delta` | REAL | Reserved for future use (v14) |
| `research_adjusted_score` | REAL | Base + research delta, clamped (v11) |
| `research_delta` | REAL | Signed delta from company research (v11) |
| `research_breakdown` | TEXT (JSON) | Factor/delta/confidence/section breakdown (v11) |
| `net_score` | REAL | Composite: min(adjusted, verdict_cap) (v16) |

**Indexes:** `url_hash`, `status`, `company_norm`, `source_job_id`, `tier_passed`, `score`

---

### `search_queries`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `source_id` | TEXT | Source adapter ID |
| `query_slug` | TEXT | URL slug for the query |
| `label` | TEXT | Human-readable label |
| `commitment_filter` | TEXT | Filter by commitment type |
| `max_pages` | INTEGER | Max pages to fetch (default 1) |
| `enabled` | BOOLEAN | Whether query is active |
| `last_run_at` | TEXT | Last run timestamp |
| `notes` | TEXT | Free-text notes |

---

### `dedup_registry`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `job_id` | INTEGER FK → jobs(id) | |
| `key_type` | TEXT | `composite` / `content_hash` / `fuzzy` |
| `key_value` | TEXT | The dedup key value |
| `created_at` | TEXT | ISO timestamp |

**Indexes:** `key_value`, `key_type`

---

### `pipeline_runs`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `run_id` | TEXT | Unique run identifier |
| `started_at` | TEXT | ISO timestamp |
| `completed_at` | TEXT | ISO timestamp |
| `queries_run` | TEXT (JSON array) | Query slugs that were run |
| `cards_fetched` | INTEGER | Total cards fetched |
| `cards_new` | INTEGER | New cards (not in DB) |
| `cards_survived_tier2` | INTEGER | Cards that passed Tier 2 filtering |
| `jds_fetched` | INTEGER | JDs successfully fetched |
| `jobs_scored` | INTEGER | Jobs scored |
| `jobs_ready` | INTEGER | Jobs that passed scoring threshold |
| `status` | TEXT | running / completed / failed |

---

### `settings`

Key-value store for generic settings.

| Column | Type | Notes |
|---|---|---|
| `key` | TEXT PK | Setting key |
| `value` | TEXT | JSON-encoded value |
| `updated_at` | TEXT | ISO timestamp |

---

### `resumes`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `job_id` | INTEGER FK → jobs(id) | |
| `task` | TEXT | `resume_generation_high_value` or `resume_generation_standard` |
| `provider` | TEXT | LLM provider used |
| `model` | TEXT | LLM model used |
| `resume_text` | TEXT | Generated markdown |
| `master_resume_path` | TEXT | Path to master resume used |
| `validation_passed` | BOOLEAN | Accuracy validation result |
| `validation_violations` | TEXT (JSON array) | Validation violations |
| `validation_checked_at` | TEXT | Validation timestamp |
| `input_tokens` | INTEGER | LLM input token count |
| `output_tokens` | INTEGER | LLM output token count |
| `latency_ms` | INTEGER | Generation latency |
| `generated_at` | TEXT | ISO timestamp |
| `updated_at` | TEXT | ISO timestamp |
| `markdown_path` | TEXT | Path to exported markdown file |
| `pdf_path` | TEXT | Path to exported PDF file |
| `docx_path` | TEXT | Path to exported DOCX file |

**Indexes:** `job_id`, `generated_at`

---

### `cover_letters`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `job_id` | INTEGER FK → jobs(id) | |
| `task` | TEXT | `cover_letter_generation` |
| `provider` | TEXT | LLM provider used |
| `model` | TEXT | LLM model used |
| `cover_letter_text` | TEXT | Generated cover letter text |
| `master_resume_path` | TEXT | Path to master resume used |
| `validation_passed` | BOOLEAN | Accuracy validation result |
| `validation_violations` | TEXT (JSON array) | Validation violations |
| `validation_checked_at` | TEXT | Validation timestamp |
| `input_tokens` | INTEGER | LLM input token count |
| `output_tokens` | INTEGER | LLM output token count |
| `latency_ms` | INTEGER | Generation latency |
| `generated_at` | TEXT | ISO timestamp |
| `updated_at` | TEXT | ISO timestamp |
| `markdown_path` | TEXT | Path to exported markdown file |

**Index:** `job_id`

---

### `application_answers`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `job_id` | INTEGER FK → jobs(id) | |
| `question` | TEXT | The application question being answered |
| `task` | TEXT | `application_answer_generation` or `application_answer_critique` |
| `provider` | TEXT | LLM provider used |
| `model` | TEXT | LLM model used |
| `answer_text` | TEXT | Generated or critiqued answer text |
| `master_resume_path` | TEXT | Path to master resume used |
| `validation_passed` | BOOLEAN | Accuracy validation result |
| `validation_violations` | TEXT (JSON array) | Validation violations |
| `validation_checked_at` | TEXT | Validation timestamp |
| `input_tokens` | INTEGER | LLM input token count |
| `output_tokens` | INTEGER | LLM output token count |
| `latency_ms` | INTEGER | Generation latency |
| `generated_at` | TEXT | ISO timestamp |
| `updated_at` | TEXT | ISO timestamp |
| `markdown_path` | TEXT | Path to exported markdown file |

**Index:** `job_id`

---

### `company_research`

Company-keyed research cache. Multiple jobs at the same company reuse one dossier.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `job_id` | INTEGER FK → jobs(id) | |
| `company_name` | TEXT | Company name |
| `company_homepage` | TEXT | Company website |
| `wikipedia_data` | TEXT (JSON) | `{title, description, extract, url, thumbnail}` |
| `funding_data` | TEXT (JSON) | `{total_funding, funding_stage, founded_year, rounds, source, source_url}` |
| `sentiment_data` | TEXT (JSON) | `{overall_sentiment, summary, key_themes, confidence, source}` |
| `sources_used` | TEXT (JSON array) | Source names |
| `errors` | TEXT (JSON array) | Error messages |
| `researched_at` | TEXT | ISO timestamp |
| `created_at` | TEXT | ISO timestamp |
| `fit_data` | TEXT (JSON) | Fit analysis data |
| `overall_confidence` | REAL | Overall confidence score (0-1) |
| `summary` | TEXT | Dossier summary text |
| `verdict_flags` | TEXT (JSON) | Verdict flags |
| `gaps` | TEXT (JSON) | Identified gaps |
| `retrieval_sources` | TEXT (JSON) | Verified source URLs (v10) |
| `retrieval_snippets_data` | TEXT (JSON) | Raw retrieval snippets for provenance (v10) |
| `company_norm` | TEXT | Normalized company key for cache lookup (v11) |

**Indexes:** `job_id`, `company_name`, `company_norm`

---

### `job_analyses`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `job_id` | INTEGER FK → jobs(id) | |
| `provider` | TEXT | LLM provider used |
| `model` | TEXT | LLM model used |
| `task` | TEXT | `jd_analysis` |
| `input_tokens` | INTEGER | LLM input token count |
| `output_tokens` | INTEGER | LLM output token count |
| `latency_ms` | INTEGER | Analysis latency |
| `analysis_json` | TEXT (JSON) | Full analysis output (matches LLM output schema) |
| `verdict` | TEXT | APPLY / CONDITIONAL / MONITOR / SKIP |
| `weighted_score` | REAL | Weighted analysis score |
| `one_line` | TEXT | One-line summary |
| `confidence` | REAL | Analysis confidence (0-1) |
| `analyzed_at` | TEXT | ISO timestamp |
| `created_at` | TEXT | ISO timestamp |

**Indexes:** `job_id`, `verdict`

---

### `application_events`

Append-only event log. Every status change writes a row via `transition_status()`.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `job_id` | INTEGER FK → jobs(id) | |
| `event_type` | TEXT | EventType constant (see APPLICATION_LIFECYCLE.md) |
| `actor` | TEXT | `candidate` / `company` / `system` |
| `occurred_at` | TEXT | When the event occurred (user-settable, validated) |
| `created_at` | TEXT | Server timestamp (always now) |
| `metadata` | TEXT (JSON) | Event-specific metadata |
| `note` | TEXT | Free-text note |

**Indexes:** `job_id`, `(job_id, occurred_at)`, `event_type`

---

## Migration History

| Version | Description | Type |
|---|---|---|
| v1 | Initial schema: jobs, search_queries, dedup_registry, pipeline_runs, settings + indexes | SQL |
| v2 | Resumes table + indexes | SQL |
| v3 | `jobs.reject_details` column | SQL |
| v4 | `jobs.detail_url` column | SQL |
| v5 | `company_research` table + indexes | SQL |
| v6 | Dossier columns on company_research (fit_data, overall_confidence, summary, verdict_flags, gaps) | SQL |
| v7 | `job_analyses` table + indexes | SQL |
| v8 | `jobs.ai_policy` column | SQL |
| v9 | `cover_letters` + `application_answers` tables + indexes | SQL |
| v10 | `company_research.retrieval_sources` + `retrieval_snippets_data` columns | SQL |
| v11 | `company_research.company_norm` + index; `jobs.research_adjusted_score`, `research_delta`, `research_breakdown` columns | SQL |
| v12 | Backfill `company_norm` using canonical `normalize_company()` | Python callable |
| v13 | `jobs.filter_warnings`, `overridden_at`, `override_note`, `original_reject_reason` columns | SQL |
| v14 | `jobs.analysis_verdict`, `analysis_delta` columns | SQL |
| v15 | `application_events` table + indexes | SQL |
| v16 | `jobs.net_score` column | SQL |

### Migration Mechanism

- `database.py:run_migrations()` checks `PRAGMA user_version` and applies pending migrations.
- Each migration is either a SQL string (executed via `executescript`) or a Python callable
  (for data backfills like `_backfill_company_norm`).
- Each migration increments `PRAGMA user_version` by 1.
- Migrations run on app startup (via `lifespan` in `app.py`) and on first connection.
