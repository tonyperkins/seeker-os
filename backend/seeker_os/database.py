"""SQLite connection helper and schema migrations.

SQLite at data/seeker.db — single-user, zero-config.
No Alembic. Simple versioned migrations via PRAGMA user_version.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from seeker_os.config import DATA_DIR


def _db_path() -> Path:
    """Return the active DB path."""
    return DATA_DIR / "seeker.db"


# Backward-compatible module-level constant. Tests that monkeypatch this
# should patch _db_path.
DB_PATH = DATA_DIR / "seeker.db"

# ---------------------------------------------------------------------------
# Python-callable migrations (for data backfills that need application logic)
# ---------------------------------------------------------------------------

def _backfill_company_norm(conn):
    """Recompute company_norm for all existing rows using normalize_company."""
    from seeker_os.dedup.normalize import normalize_company
    rows = conn.execute(
        "SELECT id, company_name FROM company_research"
    ).fetchall()
    for row in rows:
        name = row[1] or ""
        norm = normalize_company(name)
        conn.execute(
            "UPDATE company_research SET company_norm = ? WHERE id = ?",
            (norm, row[0]),
        )


def _migrate_company_research_drop_job_id(conn):
    """Decouple company_research from jobs.

    1. Collapse stale duplicate rows sharing a company_norm (keep most recent
       researched_at). No UNIQUE constraint to satisfy, but stale dups waste
       space and the read path picks most-recent anyway.
    2. Recreate table without job_id FK, with triggered_by_job_id as
       metadata-only provenance (no FK, no CASCADE).
    3. Non-unique index on company_norm for fast lookups.
    """
    # Step 1: Delete stale duplicate rows (keep most recent researched_at per company_norm)
    conn.execute(
        """
        DELETE FROM company_research
        WHERE id NOT IN (
            SELECT id FROM company_research cr_keep
            WHERE cr_keep.id = (
                SELECT id FROM company_research cr_latest
                WHERE cr_latest.company_norm = cr_keep.company_norm
                  AND cr_latest.company_norm IS NOT NULL
                  AND cr_latest.company_norm != ''
                ORDER BY cr_latest.researched_at DESC
                LIMIT 1
            )
        )
        """,
    )

    # Step 2: Create new table without job_id FK, with triggered_by_job_id metadata
    conn.execute(
        """
        CREATE TABLE company_research_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            triggered_by_job_id INTEGER,
            company_name TEXT,
            company_homepage TEXT,
            wikipedia_data TEXT,
            funding_data TEXT,
            sentiment_data TEXT,
            sources_used TEXT,
            errors TEXT,
            researched_at TEXT,
            created_at TEXT,
            fit_data TEXT,
            overall_confidence REAL DEFAULT 0.0,
            summary TEXT DEFAULT '',
            verdict_flags TEXT,
            gaps TEXT,
            company_norm TEXT,
            retrieval_sources TEXT,
            retrieval_snippets_data TEXT,
            verification_state TEXT DEFAULT 'unverified'
        )
        """,
    )

    # Copy data: job_id -> triggered_by_job_id (preserve provenance)
    conn.execute(
        """
        INSERT INTO company_research_new (
            id, triggered_by_job_id, company_name, company_homepage,
            wikipedia_data, funding_data, sentiment_data, sources_used, errors,
            researched_at, created_at, fit_data, overall_confidence, summary,
            verdict_flags, gaps, company_norm, retrieval_sources,
            retrieval_snippets_data, verification_state
        )
        SELECT
            id, job_id, company_name, company_homepage,
            wikipedia_data, funding_data, sentiment_data, sources_used, errors,
            researched_at, created_at, fit_data, overall_confidence, summary,
            verdict_flags, gaps, company_norm, retrieval_sources,
            retrieval_snippets_data, verification_state
        FROM company_research
        """,
    )

    # Drop old, rename new
    conn.execute("DROP TABLE company_research")
    conn.execute("ALTER TABLE company_research_new RENAME TO company_research")

    # Step 3: Non-unique index on company_norm (lookup key, NOT a unique constraint)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_company_research_company_norm ON company_research(company_norm)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_company_research_company_name ON company_research(company_name)"
    )


def _migrate_flat_recruiter_columns(conn):
    """If jobs table has flat recruiter_* columns, migrate data and drop them."""
    cols = [r[1] for r in conn.execute("PRAGMA table_info(jobs)").fetchall()]
    recruiter_cols = [c for c in cols if c in (
        "recruiter_name", "recruiter_email", "recruiter_phone",
        "recruiter_linkedin", "recruiter_source",
    )]
    if not recruiter_cols:
        return  # Fresh DB — nothing to migrate

    now = datetime.now(UTC).isoformat()

    # Migrate existing data into recruiter_contacts
    rows = conn.execute(
        """
        SELECT id, recruiter_name, recruiter_email, recruiter_phone,
               recruiter_linkedin, recruiter_source
        FROM jobs
        WHERE recruiter_name IS NOT NULL
           OR recruiter_email IS NOT NULL
           OR recruiter_phone IS NOT NULL
           OR recruiter_linkedin IS NOT NULL
           OR recruiter_source IS NOT NULL
        """
    ).fetchall()
    for row in rows:
        conn.execute(
            """
            INSERT INTO recruiter_contacts
                (job_id, name, email, phone, linkedin, agency, source,
                 contacted_at, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, NULL, ?, NULL, NULL, ?, ?)
            """,
            (row[0], row[1], row[2], row[3], row[4], row[5], now, now),
        )

    # Drop old columns (SQLite 3.35+ supports ALTER TABLE DROP COLUMN)
    for col in recruiter_cols:
        conn.execute(f"ALTER TABLE jobs DROP COLUMN {col}")


# ---------------------------------------------------------------------------
# Schema migrations
# ---------------------------------------------------------------------------

# Fast bootstrap for brand-new databases. This is the schema after logical v32.
# Historical databases still use the explicit MIGRATIONS entries below so their
# existing PRAGMA user_version values remain meaningful.
FRESH_SCHEMA_VERSION = 32
FRESH_SCHEMA_SQL = "\n    -- jobs (final form: all ALTER TABLE columns merged in, no recruiter_* columns)\n    CREATE TABLE IF NOT EXISTS jobs (\n        id INTEGER PRIMARY KEY AUTOINCREMENT,\n        source_id TEXT,\n        source_job_id TEXT,\n        ats_source TEXT,\n        ats_board_token TEXT,\n        ats_job_id TEXT,\n        apply_url TEXT,\n        url_hash TEXT UNIQUE,\n        title TEXT,\n        core_title TEXT,\n        company TEXT,\n        company_homepage TEXT,\n        location TEXT,\n        workplace_type TEXT,\n        workplace_countries TEXT,\n        seniority_level TEXT,\n        commitment TEXT,\n        comp_min INTEGER,\n        comp_max INTEGER,\n        comp_currency TEXT,\n        technical_tools TEXT,\n        requirements_summary TEXT,\n        date_posted TEXT,\n        role_type TEXT,\n        status TEXT DEFAULT 'discovered',\n        tier_passed INTEGER DEFAULT 0,\n        score REAL,\n        score_reasons TEXT,\n        score_gaps TEXT,\n        jd_full TEXT,\n        jd_fetch_status TEXT DEFAULT 'pending',\n        discovered_at TEXT,\n        discovered_query TEXT,\n        updated_at TEXT,\n        is_pinned BOOLEAN DEFAULT FALSE,\n        reject_reason TEXT,\n        content_hash TEXT,\n        title_norm TEXT,\n        company_norm TEXT,\n        cross_ref_status TEXT,\n        cross_ref_date TEXT,\n        cross_ref_score REAL,\n        reject_details TEXT,\n        detail_url TEXT,\n        ai_policy TEXT,\n        research_adjusted_score REAL,\n        research_delta REAL DEFAULT 0,\n        research_breakdown TEXT,\n        filter_warnings TEXT,\n        overridden_at TEXT,\n        override_note TEXT,\n        original_reject_reason TEXT,\n        analysis_verdict TEXT,\n        analysis_delta REAL DEFAULT 0,\n        net_score REAL,\n        run_id TEXT,\n        score_modifiers TEXT,\n        comp_source TEXT DEFAULT 'none'\n    );\n\n    CREATE INDEX IF NOT EXISTS idx_jobs_url_hash ON jobs(url_hash);\n    CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);\n    CREATE INDEX IF NOT EXISTS idx_jobs_company_norm ON jobs(company_norm);\n    CREATE INDEX IF NOT EXISTS idx_jobs_source_job_id ON jobs(source_job_id);\n    CREATE INDEX IF NOT EXISTS idx_jobs_tier_passed ON jobs(tier_passed);\n    CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs(score);\n    CREATE INDEX IF NOT EXISTS idx_jobs_run_id ON jobs(run_id);\n\n    -- search_queries (final form: + search_query column)\n    CREATE TABLE IF NOT EXISTS search_queries (\n        id INTEGER PRIMARY KEY AUTOINCREMENT,\n        source_id TEXT,\n        query_slug TEXT,\n        label TEXT,\n        commitment_filter TEXT,\n        max_pages INTEGER DEFAULT 1,\n        enabled BOOLEAN DEFAULT TRUE,\n        last_run_at TEXT,\n        notes TEXT,\n        search_query TEXT\n    );\n\n    -- dedup_registry (final form: ON DELETE CASCADE)\n    CREATE TABLE IF NOT EXISTS dedup_registry (\n        id INTEGER PRIMARY KEY AUTOINCREMENT,\n        job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE,\n        key_type TEXT,\n        key_value TEXT,\n        created_at TEXT\n    );\n\n    CREATE INDEX IF NOT EXISTS idx_dedup_key_value ON dedup_registry(key_value);\n    CREATE INDEX IF NOT EXISTS idx_dedup_key_type ON dedup_registry(key_type);\n\n    -- pipeline_runs (unchanged from v1)\n    CREATE TABLE IF NOT EXISTS pipeline_runs (\n        id INTEGER PRIMARY KEY AUTOINCREMENT,\n        run_id TEXT,\n        started_at TEXT,\n        completed_at TEXT,\n        queries_run TEXT,\n        cards_fetched INTEGER,\n        cards_new INTEGER,\n        cards_survived_tier2 INTEGER,\n        jds_fetched INTEGER,\n        jobs_scored INTEGER,\n        jobs_ready INTEGER,\n        status TEXT\n    );\n\n    -- settings (unchanged from v1)\n    CREATE TABLE IF NOT EXISTS settings (\n        key TEXT PRIMARY KEY,\n        value TEXT,\n        updated_at TEXT\n    );\n\n    -- resumes (final form: ON DELETE CASCADE from v26)\n    CREATE TABLE IF NOT EXISTS resumes (\n        id INTEGER PRIMARY KEY AUTOINCREMENT,\n        job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE,\n        task TEXT,\n        provider TEXT,\n        model TEXT,\n        resume_text TEXT,\n        master_resume_path TEXT,\n        validation_passed BOOLEAN DEFAULT FALSE,\n        validation_violations TEXT,\n        validation_checked_at TEXT,\n        input_tokens INTEGER DEFAULT 0,\n        output_tokens INTEGER DEFAULT 0,\n        latency_ms INTEGER DEFAULT 0,\n        generated_at TEXT,\n        updated_at TEXT,\n        markdown_path TEXT,\n        pdf_path TEXT,\n        docx_path TEXT\n    );\n\n    CREATE INDEX IF NOT EXISTS idx_resumes_job_id ON resumes(job_id);\n    CREATE INDEX IF NOT EXISTS idx_resumes_generated_at ON resumes(generated_at);\n\n    -- company_research (final form: decoupled from jobs in v27, no job_id FK)\n    CREATE TABLE IF NOT EXISTS company_research (\n        id INTEGER PRIMARY KEY AUTOINCREMENT,\n        triggered_by_job_id INTEGER,\n        company_name TEXT,\n        company_homepage TEXT,\n        wikipedia_data TEXT,\n        funding_data TEXT,\n        sentiment_data TEXT,\n        sources_used TEXT,\n        errors TEXT,\n        researched_at TEXT,\n        created_at TEXT,\n        fit_data TEXT,\n        overall_confidence REAL DEFAULT 0.0,\n        summary TEXT DEFAULT '',\n        verdict_flags TEXT,\n        gaps TEXT,\n        company_norm TEXT,\n        retrieval_sources TEXT,\n        retrieval_snippets_data TEXT,\n        verification_state TEXT DEFAULT 'unverified'\n    );\n\n    CREATE INDEX IF NOT EXISTS idx_company_research_company_norm ON company_research(company_norm);\n    CREATE INDEX IF NOT EXISTS idx_company_research_company_name ON company_research(company_name);\n\n    -- job_analyses (final form: ON DELETE CASCADE from v26)\n    CREATE TABLE IF NOT EXISTS job_analyses (\n        id INTEGER PRIMARY KEY AUTOINCREMENT,\n        job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE,\n        provider TEXT,\n        model TEXT,\n        task TEXT,\n        input_tokens INTEGER DEFAULT 0,\n        output_tokens INTEGER DEFAULT 0,\n        latency_ms INTEGER DEFAULT 0,\n        analysis_json TEXT,\n        verdict TEXT,\n        weighted_score REAL,\n        one_line TEXT,\n        confidence REAL,\n        analyzed_at TEXT,\n        created_at TEXT\n    );\n\n    CREATE INDEX IF NOT EXISTS idx_job_analyses_job_id ON job_analyses(job_id);\n    CREATE INDEX IF NOT EXISTS idx_job_analyses_verdict ON job_analyses(verdict);\n\n    -- application_events (final form: ON DELETE CASCADE from v26)\n    CREATE TABLE IF NOT EXISTS application_events (\n        id INTEGER PRIMARY KEY AUTOINCREMENT,\n        job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE,\n        event_type TEXT,\n        actor TEXT,\n        occurred_at TEXT,\n        created_at TEXT,\n        metadata TEXT,\n        note TEXT\n    );\n\n    CREATE INDEX IF NOT EXISTS idx_application_events_job_id ON application_events(job_id);\n    CREATE INDEX IF NOT EXISTS idx_application_events_job_occurred ON application_events(job_id, occurred_at);\n    CREATE INDEX IF NOT EXISTS idx_application_events_event_type ON application_events(event_type);\n\n    -- recruiters (from v25)\n    CREATE TABLE recruiters (\n        id INTEGER PRIMARY KEY AUTOINCREMENT,\n        name TEXT,\n        email TEXT,\n        phone TEXT,\n        linkedin TEXT,\n        agency TEXT,\n        created_at TEXT NOT NULL,\n        updated_at TEXT NOT NULL\n    );\n\n    CREATE INDEX idx_recruiters_email ON recruiters(email);\n    CREATE INDEX idx_recruiters_name ON recruiters(name);\n\n    -- recruiter_job_contacts (from v25)\n    CREATE TABLE recruiter_job_contacts (\n        id INTEGER PRIMARY KEY AUTOINCREMENT,\n        recruiter_id INTEGER NOT NULL REFERENCES recruiters(id) ON DELETE CASCADE,\n        job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,\n        source TEXT,\n        contacted_at TEXT,\n        notes TEXT,\n        created_at TEXT NOT NULL,\n        updated_at TEXT NOT NULL,\n        UNIQUE(recruiter_id, job_id)\n    );\n\n    CREATE INDEX idx_recruiter_job_contacts_job_id ON recruiter_job_contacts(job_id);\n    CREATE INDEX idx_recruiter_job_contacts_recruiter_id ON recruiter_job_contacts(recruiter_id);\n\n    -- llm_calls (from v30)\n    CREATE TABLE llm_calls (\n        call_id TEXT PRIMARY KEY,\n        operation_id TEXT,\n        parent_call_id TEXT REFERENCES llm_calls(call_id) ON DELETE SET NULL,\n        task TEXT NOT NULL,\n        requested_provider TEXT,\n        requested_model TEXT,\n        actual_provider TEXT,\n        actual_model TEXT,\n        route_reason TEXT,\n        temperature REAL,\n        max_tokens INTEGER,\n        status TEXT NOT NULL,\n        error_type TEXT,\n        stop_reason TEXT,\n        input_tokens INTEGER NOT NULL DEFAULT 0,\n        output_tokens INTEGER NOT NULL DEFAULT 0,\n        latency_ms INTEGER NOT NULL DEFAULT 0,\n        input_price_per_mtok REAL,\n        output_price_per_mtok REAL,\n        estimated_cost REAL NOT NULL DEFAULT 0,\n        currency TEXT NOT NULL DEFAULT 'USD',\n        prompt_name TEXT,\n        prompt_version TEXT,\n        prompt_template_digest TEXT,\n        system_prompt_hmac TEXT,\n        user_prompt_hmac TEXT,\n        system_prompt_bytes INTEGER NOT NULL DEFAULT 0,\n        user_prompt_bytes INTEGER NOT NULL DEFAULT 0,\n        artifact_type TEXT,\n        artifact_id INTEGER,\n        content_capture_level TEXT NOT NULL DEFAULT 'metadata_only',\n        telemetry_schema_version TEXT NOT NULL DEFAULT '1',\n        started_at TEXT NOT NULL,\n        completed_at TEXT\n    );\n\n    CREATE INDEX idx_llm_calls_operation ON llm_calls(operation_id);\n    CREATE INDEX idx_llm_calls_task_started ON llm_calls(task, started_at);\n    CREATE INDEX idx_llm_calls_status ON llm_calls(status);\n    CREATE INDEX idx_llm_calls_artifact ON llm_calls(artifact_type, artifact_id);\n\n    -- llm_evaluations (from v30)\n    CREATE TABLE llm_evaluations (\n        evaluation_id TEXT PRIMARY KEY,\n        operation_id TEXT,\n        call_id TEXT REFERENCES llm_calls(call_id) ON DELETE SET NULL,\n        judge_call_id TEXT REFERENCES llm_calls(call_id) ON DELETE SET NULL,\n        artifact_type TEXT,\n        artifact_id INTEGER,\n        evaluator_name TEXT NOT NULL,\n        evaluator_type TEXT NOT NULL,\n        evaluator_version TEXT NOT NULL,\n        metric_name TEXT NOT NULL,\n        score REAL,\n        label TEXT,\n        passed BOOLEAN,\n        explanation_redacted TEXT,\n        details_json TEXT,\n        rubric_digest TEXT,\n        evaluated_at TEXT NOT NULL\n    );\n\n    CREATE INDEX idx_llm_evaluations_operation ON llm_evaluations(operation_id);\n    CREATE INDEX idx_llm_evaluations_call ON llm_evaluations(call_id);\n    CREATE INDEX idx_llm_evaluations_artifact ON llm_evaluations(artifact_type, artifact_id);\n    CREATE INDEX idx_llm_evaluations_metric ON llm_evaluations(metric_name, evaluated_at);\n\n    -- retrieval_calls (from v31)\n    CREATE TABLE IF NOT EXISTS retrieval_calls (\n        id INTEGER PRIMARY KEY AUTOINCREMENT,\n        adapter_type TEXT NOT NULL,\n        query TEXT NOT NULL,\n        status TEXT NOT NULL,\n        error_message TEXT,\n        called_at TEXT NOT NULL\n    );\n\n    CREATE INDEX IF NOT EXISTS idx_retrieval_calls_adapter_date\n        ON retrieval_calls(adapter_type, called_at);\n    "


MIGRATIONS: list[str | callable] = [
    # v1: initial schema
    """
    CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        -- Identity
        source_id TEXT,
        source_job_id TEXT,
        ats_source TEXT,
        ats_board_token TEXT,
        ats_job_id TEXT,
        apply_url TEXT,
        url_hash TEXT UNIQUE,

        -- Job details
        title TEXT,
        core_title TEXT,
        company TEXT,
        company_homepage TEXT,
        location TEXT,
        workplace_type TEXT,
        workplace_countries TEXT,      -- JSON array
        seniority_level TEXT,
        commitment TEXT,               -- JSON array
        comp_min INTEGER,
        comp_max INTEGER,
        comp_currency TEXT,
        technical_tools TEXT,          -- JSON array
        requirements_summary TEXT,
        date_posted TEXT,
        role_type TEXT,

        -- Pipeline state
        status TEXT DEFAULT 'discovered',
        tier_passed INTEGER DEFAULT 0,
        score REAL,
        score_reasons TEXT,            -- JSON array
        score_gaps TEXT,               -- JSON array
        jd_full TEXT,
        jd_fetch_status TEXT DEFAULT 'pending',

        -- Metadata
        discovered_at TEXT,
        discovered_query TEXT,
        updated_at TEXT,
        is_pinned BOOLEAN DEFAULT FALSE,
        reject_reason TEXT,

        -- Dedup
        content_hash TEXT,
        title_norm TEXT,
        company_norm TEXT,

        -- Cross-reference
        cross_ref_status TEXT,
        cross_ref_date TEXT,
        cross_ref_score REAL
    );

    CREATE TABLE IF NOT EXISTS search_queries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id TEXT,
        query_slug TEXT,
        label TEXT,
        commitment_filter TEXT,
        max_pages INTEGER DEFAULT 1,
        enabled BOOLEAN DEFAULT TRUE,
        last_run_at TEXT,
        notes TEXT
    );

    CREATE TABLE IF NOT EXISTS dedup_registry (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER REFERENCES jobs(id),
        key_type TEXT,                 -- 'composite', 'content_hash', 'fuzzy'
        key_value TEXT,
        created_at TEXT
    );

    CREATE TABLE IF NOT EXISTS pipeline_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT,
        started_at TEXT,
        completed_at TEXT,
        queries_run TEXT,              -- JSON array
        cards_fetched INTEGER,
        cards_new INTEGER,
        cards_survived_tier2 INTEGER,
        jds_fetched INTEGER,
        jobs_scored INTEGER,
        jobs_ready INTEGER,
        status TEXT
    );

    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT,                    -- JSON encoded
        updated_at TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_jobs_url_hash ON jobs(url_hash);
    CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
    CREATE INDEX IF NOT EXISTS idx_jobs_company_norm ON jobs(company_norm);
    CREATE INDEX IF NOT EXISTS idx_jobs_source_job_id ON jobs(source_job_id);
    CREATE INDEX IF NOT EXISTS idx_dedup_key_value ON dedup_registry(key_value);
    CREATE INDEX IF NOT EXISTS idx_dedup_key_type ON dedup_registry(key_type);
    CREATE INDEX IF NOT EXISTS idx_jobs_tier_passed ON jobs(tier_passed);
    CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs(score);
    """,
    # v2: resumes table (Phase 3)
    """
    CREATE TABLE IF NOT EXISTS resumes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER REFERENCES jobs(id),
        -- Generation
        task TEXT,                         -- 'resume_generation_high_value' or 'resume_generation_standard'
        provider TEXT,
        model TEXT,
        -- Content
        resume_text TEXT,                  -- generated markdown
        master_resume_path TEXT,
        -- Accuracy validation
        validation_passed BOOLEAN DEFAULT FALSE,
        validation_violations TEXT,        -- JSON array
        validation_checked_at TEXT,
        -- Metadata
        input_tokens INTEGER DEFAULT 0,
        output_tokens INTEGER DEFAULT 0,
        latency_ms INTEGER DEFAULT 0,
        generated_at TEXT,
        updated_at TEXT,
        -- File paths (for exported versions)
        markdown_path TEXT,
        pdf_path TEXT,
        docx_path TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_resumes_job_id ON resumes(job_id);
    CREATE INDEX IF NOT EXISTS idx_resumes_generated_at ON resumes(generated_at);
    """,
    # Migration 3: Add reject_details column for free-text rejection feedback
    """
    ALTER TABLE jobs ADD COLUMN reject_details TEXT;
    """,
    # Migration 4: Add detail_url column for hiring.cafe job detail page URL
    """
    ALTER TABLE jobs ADD COLUMN detail_url TEXT;
    """,
    # Migration 5: Company research table
    """
    CREATE TABLE IF NOT EXISTS company_research (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER REFERENCES jobs(id),
        company_name TEXT,
        company_homepage TEXT,
        -- Aggregated research data (JSON)
        wikipedia_data TEXT,          -- JSON: {title, description, extract, url, thumbnail}
        funding_data TEXT,            -- JSON: {total_funding, funding_stage, founded_year, rounds, source, source_url}
        sentiment_data TEXT,          -- JSON: {overall_sentiment, summary, key_themes, confidence, source}
        sources_used TEXT,            -- JSON array of source names
        errors TEXT,                  -- JSON array of error messages
        researched_at TEXT,
        created_at TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_company_research_job_id ON company_research(job_id);
    CREATE INDEX IF NOT EXISTS idx_company_research_company_name ON company_research(company_name);
    """,
    # Migration 6: Add dossier columns to company_research table
    """
    ALTER TABLE company_research ADD COLUMN fit_data TEXT;
    ALTER TABLE company_research ADD COLUMN overall_confidence REAL DEFAULT 0.0;
    ALTER TABLE company_research ADD COLUMN summary TEXT DEFAULT '';
    ALTER TABLE company_research ADD COLUMN verdict_flags TEXT;
    ALTER TABLE company_research ADD COLUMN gaps TEXT;
    """,
    # Migration 7: Job analyses table (JD analysis agent)
    """
    CREATE TABLE IF NOT EXISTS job_analyses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER REFERENCES jobs(id),
        -- LLM metadata
        provider TEXT,
        model TEXT,
        task TEXT,
        input_tokens INTEGER DEFAULT 0,
        output_tokens INTEGER DEFAULT 0,
        latency_ms INTEGER DEFAULT 0,
        -- Full analysis JSON (matches the output schema)
        analysis_json TEXT,
        -- Denormalized fields for quick access
        verdict TEXT,
        weighted_score REAL,
        one_line TEXT,
        confidence REAL,
        -- Timestamps
        analyzed_at TEXT,
        created_at TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_job_analyses_job_id ON job_analyses(job_id);
    CREATE INDEX IF NOT EXISTS idx_job_analyses_verdict ON job_analyses(verdict);
    """,
    # Migration 8: Add ai_policy column for per-application AI generation policy
    """
    ALTER TABLE jobs ADD COLUMN ai_policy TEXT;
    """,
    # Migration 9: Cover letters and application answers tables
    """
    CREATE TABLE IF NOT EXISTS cover_letters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER REFERENCES jobs(id),
        task TEXT,
        provider TEXT,
        model TEXT,
        cover_letter_text TEXT,
        master_resume_path TEXT,
        validation_passed BOOLEAN DEFAULT FALSE,
        validation_violations TEXT,
        validation_checked_at TEXT,
        input_tokens INTEGER DEFAULT 0,
        output_tokens INTEGER DEFAULT 0,
        latency_ms INTEGER DEFAULT 0,
        generated_at TEXT,
        updated_at TEXT,
        markdown_path TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_cover_letters_job_id ON cover_letters(job_id);

    CREATE TABLE IF NOT EXISTS application_answers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER REFERENCES jobs(id),
        question TEXT,
        task TEXT,
        provider TEXT,
        model TEXT,
        answer_text TEXT,
        master_resume_path TEXT,
        validation_passed BOOLEAN DEFAULT FALSE,
        validation_violations TEXT,
        validation_checked_at TEXT,
        input_tokens INTEGER DEFAULT 0,
        output_tokens INTEGER DEFAULT 0,
        latency_ms INTEGER DEFAULT 0,
        generated_at TEXT,
        updated_at TEXT,
        markdown_path TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_application_answers_job_id ON application_answers(job_id);
    """,
    # Migration 10: Persist retrieval snippets and sources for URL verification
    """
    ALTER TABLE company_research ADD COLUMN retrieval_sources TEXT;
    ALTER TABLE company_research ADD COLUMN retrieval_snippets_data TEXT;
    """,
    # Migration 11: Company-keyed research caching + research-adjusted score columns
    """
    ALTER TABLE company_research ADD COLUMN company_norm TEXT;
    CREATE INDEX IF NOT EXISTS idx_company_research_company_norm ON company_research(company_norm);

    ALTER TABLE jobs ADD COLUMN research_adjusted_score REAL;
    ALTER TABLE jobs ADD COLUMN research_delta REAL DEFAULT 0;
    ALTER TABLE jobs ADD COLUMN research_breakdown TEXT;
    """,
    # Migration 12: Backfill company_norm using the canonical normalizer
    # (dedup.normalize.normalize_company). This fixes rows written with the
    # old naive normalizer (strip().lower()) and NULL rows from pre-migration-11.
    _backfill_company_norm,
    # Migration 13: Manual job entry + override audit columns
    """
    ALTER TABLE jobs ADD COLUMN filter_warnings TEXT;
    ALTER TABLE jobs ADD COLUMN overridden_at TEXT;
    ALTER TABLE jobs ADD COLUMN override_note TEXT;
    ALTER TABLE jobs ADD COLUMN original_reject_reason TEXT;
    """,
    # Migration 14: AI analysis verdict + delta columns
    """
    ALTER TABLE jobs ADD COLUMN analysis_verdict TEXT;
    ALTER TABLE jobs ADD COLUMN analysis_delta REAL DEFAULT 0;
    """,
    # Migration 15: Application events log (append-only)
    """
    CREATE TABLE IF NOT EXISTS application_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER REFERENCES jobs(id),
        event_type TEXT,
        actor TEXT,
        occurred_at TEXT,
        created_at TEXT,
        metadata TEXT,
        note TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_application_events_job_id ON application_events(job_id);
    CREATE INDEX IF NOT EXISTS idx_application_events_job_occurred ON application_events(job_id, occurred_at);
    CREATE INDEX IF NOT EXISTS idx_application_events_event_type ON application_events(event_type);
    """,
    # Migration 16: Net score column (composite of base + research + verdict cap)
    """
    ALTER TABLE jobs ADD COLUMN net_score REAL;
    """,
    # Migration 17: Link jobs to the pipeline run that discovered them
    """
    ALTER TABLE jobs ADD COLUMN run_id TEXT;
    CREATE INDEX IF NOT EXISTS idx_jobs_run_id ON jobs(run_id);
    """,
    # Migration 18: Add search_query column to search_queries table
    # Stores the raw search text (e.g. "senior sre remote") used to build
    # hiring.cafe searchState URLs. Falls back to slug when absent.
    """
    ALTER TABLE search_queries ADD COLUMN search_query TEXT;
    """,
    # Migration 19: Add score_modifiers column for structured fired-modifier data
    # (signal name → realized points). Used by research-adjustment suppression
    # to know which base modifiers actually fired for a specific job.
    """
    ALTER TABLE jobs ADD COLUMN score_modifiers TEXT;
    """,
    # Migration 20: Add comp_source column for comp provenance tracking.
    # Values: structured (hiring.cafe/ATS structured fields), parsed (LLM text
    # extraction), manual (user-entered), none (unknown/backfilled).
    # Scoring uses this to gate comp_target bonus and sanity-check floor clearing.
    """
    ALTER TABLE jobs ADD COLUMN comp_source TEXT DEFAULT 'none';
    """,
    # Migration 21: Persist entity disambiguation verification_state.
    # Values: verified | unverified | mismatch. Previously computed at runtime;
    # storing it lets the UI surface "research discarded: entity mismatch".
    """
    ALTER TABLE company_research ADD COLUMN verification_state TEXT DEFAULT 'unverified';
    """,
    # Migration 22: Recruiter contact tracking — separate table supports
    # multiple recruiters per job, agency/firm tracking, and future CRM features.
    # source: 'linkedin', 'email', 'referral', 'agency', 'other' (free-text,
    # constrained by frontend dropdown).
    """
    CREATE TABLE recruiter_contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
        name TEXT,
        email TEXT,
        phone TEXT,
        linkedin TEXT,
        agency TEXT,
        source TEXT,
        contacted_at TEXT,
        notes TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX idx_recruiter_contacts_job_id ON recruiter_contacts(job_id);
    """,
    # Migration 23: Transition flat recruiter columns → recruiter_contacts table.
    # For DBs where migration 22 was applied with the old flat-columns SQL, this
    # creates the table, migrates existing data, and drops the old columns.
    # For fresh DBs (migration 22 already created the table), this is a no-op.
    """
    CREATE TABLE IF NOT EXISTS recruiter_contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
        name TEXT,
        email TEXT,
        phone TEXT,
        linkedin TEXT,
        agency TEXT,
        source TEXT,
        contacted_at TEXT,
        notes TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_recruiter_contacts_job_id ON recruiter_contacts(job_id);
    """,
    # Migration 24: Migrate data from flat recruiter columns → recruiter_contacts,
    # then drop the old columns. No-op on fresh DBs (columns never existed).
    _migrate_flat_recruiter_columns,
    # Migration 25: Normalize recruiter contacts — split into recruiters (entity)
    # and recruiter_job_contacts (association). Drops the old recruiter_contacts
    # table (0 rows in prod, no data migration needed).
    # UNIQUE(recruiter_id, job_id): the association is a FACT (this recruiter is
    # a contact for this job), not an event. Repeated outreach belongs in
    # application_events, NOT as duplicate association rows.
    # contacted_at = FIRST contact, set once on create, never overwritten.
    """
    CREATE TABLE recruiters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        email TEXT,
        phone TEXT,
        linkedin TEXT,
        agency TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE INDEX idx_recruiters_email ON recruiters(email);
    CREATE INDEX idx_recruiters_name ON recruiters(name);

    CREATE TABLE recruiter_job_contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        recruiter_id INTEGER NOT NULL REFERENCES recruiters(id) ON DELETE CASCADE,
        job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
        source TEXT,
        contacted_at TEXT,
        notes TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(recruiter_id, job_id)
    );

    CREATE INDEX idx_recruiter_job_contacts_job_id ON recruiter_job_contacts(job_id);
    CREATE INDEX idx_recruiter_job_contacts_recruiter_id ON recruiter_job_contacts(recruiter_id);

    DROP TABLE IF EXISTS recruiter_contacts;
    """,
    # Migration 26: Add ON DELETE CASCADE to child tables that reference jobs(id).
    # SQLite can't ALTER TABLE to change FK constraints, so we use the
    # create-new / copy / drop-old / rename pattern for each table.
    # Tables: application_events, resumes, job_analyses, cover_letters,
    #         application_answers, dedup_registry
    # (company_research is handled separately in P1 — skip here.)
    """
    -- application_events
    CREATE TABLE application_events_new (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
        event_type TEXT,
        actor TEXT,
        occurred_at TEXT,
        created_at TEXT,
        metadata TEXT,
        note TEXT
    );
    INSERT INTO application_events_new (id, job_id, event_type, actor, occurred_at, created_at, metadata, note)
        SELECT id, job_id, event_type, actor, occurred_at, created_at, metadata, note FROM application_events;
    DROP TABLE application_events;
    ALTER TABLE application_events_new RENAME TO application_events;
    CREATE INDEX idx_application_events_job_id ON application_events(job_id);
    CREATE INDEX idx_application_events_job_occurred ON application_events(job_id, occurred_at);
    CREATE INDEX idx_application_events_event_type ON application_events(event_type);

    -- resumes
    CREATE TABLE resumes_new (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
        task TEXT,
        provider TEXT,
        model TEXT,
        resume_text TEXT,
        master_resume_path TEXT,
        validation_passed BOOLEAN DEFAULT FALSE,
        validation_violations TEXT,
        validation_checked_at TEXT,
        input_tokens INTEGER DEFAULT 0,
        output_tokens INTEGER DEFAULT 0,
        latency_ms INTEGER DEFAULT 0,
        generated_at TEXT,
        updated_at TEXT,
        markdown_path TEXT,
        pdf_path TEXT,
        docx_path TEXT
    );
    INSERT INTO resumes_new (id, job_id, task, provider, model, resume_text, master_resume_path,
        validation_passed, validation_violations, validation_checked_at,
        input_tokens, output_tokens, latency_ms, generated_at, updated_at, markdown_path, pdf_path, docx_path)
        SELECT id, job_id, task, provider, model, resume_text, master_resume_path,
        validation_passed, validation_violations, validation_checked_at,
        input_tokens, output_tokens, latency_ms, generated_at, updated_at, markdown_path, pdf_path, docx_path
        FROM resumes;
    DROP TABLE resumes;
    ALTER TABLE resumes_new RENAME TO resumes;
    CREATE INDEX idx_resumes_job_id ON resumes(job_id);
    CREATE INDEX idx_resumes_generated_at ON resumes(generated_at);

    -- job_analyses
    CREATE TABLE job_analyses_new (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
        provider TEXT,
        model TEXT,
        task TEXT,
        input_tokens INTEGER DEFAULT 0,
        output_tokens INTEGER DEFAULT 0,
        latency_ms INTEGER DEFAULT 0,
        analysis_json TEXT,
        verdict TEXT,
        weighted_score REAL,
        one_line TEXT,
        confidence REAL,
        analyzed_at TEXT,
        created_at TEXT
    );
    INSERT INTO job_analyses_new (id, job_id, provider, model, task, input_tokens, output_tokens,
        latency_ms, analysis_json, verdict, weighted_score, one_line, confidence, analyzed_at, created_at)
        SELECT id, job_id, provider, model, task, input_tokens, output_tokens,
        latency_ms, analysis_json, verdict, weighted_score, one_line, confidence, analyzed_at, created_at
        FROM job_analyses;
    DROP TABLE job_analyses;
    ALTER TABLE job_analyses_new RENAME TO job_analyses;
    CREATE INDEX idx_job_analyses_job_id ON job_analyses(job_id);
    CREATE INDEX idx_job_analyses_verdict ON job_analyses(verdict);

    -- cover_letters
    CREATE TABLE cover_letters_new (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
        task TEXT,
        provider TEXT,
        model TEXT,
        cover_letter_text TEXT,
        master_resume_path TEXT,
        validation_passed BOOLEAN DEFAULT FALSE,
        validation_violations TEXT,
        validation_checked_at TEXT,
        input_tokens INTEGER DEFAULT 0,
        output_tokens INTEGER DEFAULT 0,
        latency_ms INTEGER DEFAULT 0,
        generated_at TEXT,
        updated_at TEXT,
        markdown_path TEXT
    );
    INSERT INTO cover_letters_new (id, job_id, task, provider, model, cover_letter_text, master_resume_path,
        validation_passed, validation_violations, validation_checked_at,
        input_tokens, output_tokens, latency_ms, generated_at, updated_at, markdown_path)
        SELECT id, job_id, task, provider, model, cover_letter_text, master_resume_path,
        validation_passed, validation_violations, validation_checked_at,
        input_tokens, output_tokens, latency_ms, generated_at, updated_at, markdown_path
        FROM cover_letters;
    DROP TABLE cover_letters;
    ALTER TABLE cover_letters_new RENAME TO cover_letters;
    CREATE INDEX idx_cover_letters_job_id ON cover_letters(job_id);

    -- application_answers
    CREATE TABLE application_answers_new (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
        question TEXT,
        task TEXT,
        provider TEXT,
        model TEXT,
        answer_text TEXT,
        master_resume_path TEXT,
        validation_passed BOOLEAN DEFAULT FALSE,
        validation_violations TEXT,
        validation_checked_at TEXT,
        input_tokens INTEGER DEFAULT 0,
        output_tokens INTEGER DEFAULT 0,
        latency_ms INTEGER DEFAULT 0,
        generated_at TEXT,
        updated_at TEXT,
        markdown_path TEXT
    );
    INSERT INTO application_answers_new (id, job_id, question, task, provider, model, answer_text,
        master_resume_path, validation_passed, validation_violations, validation_checked_at,
        input_tokens, output_tokens, latency_ms, generated_at, updated_at, markdown_path)
        SELECT id, job_id, question, task, provider, model, answer_text,
        master_resume_path, validation_passed, validation_violations, validation_checked_at,
        input_tokens, output_tokens, latency_ms, generated_at, updated_at, markdown_path
        FROM application_answers;
    DROP TABLE application_answers;
    ALTER TABLE application_answers_new RENAME TO application_answers;
    CREATE INDEX idx_application_answers_job_id ON application_answers(job_id);

    -- dedup_registry
    CREATE TABLE dedup_registry_new (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
        key_type TEXT,
        key_value TEXT,
        created_at TEXT
    );
    INSERT INTO dedup_registry_new (id, job_id, key_type, key_value, created_at)
        SELECT id, job_id, key_type, key_value, created_at FROM dedup_registry;
    DROP TABLE dedup_registry;
    ALTER TABLE dedup_registry_new RENAME TO dedup_registry;
    CREATE INDEX idx_dedup_key_value ON dedup_registry(key_value);
    CREATE INDEX idx_dedup_key_type ON dedup_registry(key_type);
    """,
    # Migration 27: Decouple company_research from jobs — drop job_id FK,
    # add triggered_by_job_id as metadata-only provenance, collapse stale dup
    # rows by company_norm, and add a non-unique index on company_norm.
    #
    # company_norm is NOT a UNIQUE key: normalize_company is tuned for dedup
    # (aggressive suffix stripping), and using it as a unique identity key
    # would hard-fail on legitimate collisions like "SAP" vs "SAP America".
    # The read path selects most-recent-by-researched_at when multiple rows
    # share a company_norm (option b), and the write path upserts by
    # company_norm lookup to avoid accumulating duplicates.
    _migrate_company_research_drop_job_id,
    # Migration 28: Drop unused cover_letters and application_answers tables.
    # These were created in v9, recreated with CASCADE in v26, and are now
    # dropped — neither feature was shipped to production. Future generated
    # documents (cover letters, application answers, etc.) will use a unified
    # generated_documents table. See ai-audit/DATA_MODEL_AUDIT_2026-07-08.md
    # §P4 for the roadmap note.
    """
    DROP TABLE IF EXISTS cover_letters;
    DROP TABLE IF EXISTS application_answers;
    """,
    # Migration 30: Metadata-only LLM execution and evaluation ledger.
    """
    CREATE TABLE llm_calls (
        call_id TEXT PRIMARY KEY,
        operation_id TEXT,
        parent_call_id TEXT REFERENCES llm_calls(call_id) ON DELETE SET NULL,
        task TEXT NOT NULL,
        requested_provider TEXT,
        requested_model TEXT,
        actual_provider TEXT,
        actual_model TEXT,
        route_reason TEXT,
        temperature REAL,
        max_tokens INTEGER,
        status TEXT NOT NULL,
        error_type TEXT,
        stop_reason TEXT,
        input_tokens INTEGER NOT NULL DEFAULT 0,
        output_tokens INTEGER NOT NULL DEFAULT 0,
        latency_ms INTEGER NOT NULL DEFAULT 0,
        input_price_per_mtok REAL,
        output_price_per_mtok REAL,
        estimated_cost REAL NOT NULL DEFAULT 0,
        currency TEXT NOT NULL DEFAULT 'USD',
        prompt_name TEXT,
        prompt_version TEXT,
        prompt_template_digest TEXT,
        system_prompt_hmac TEXT,
        user_prompt_hmac TEXT,
        system_prompt_bytes INTEGER NOT NULL DEFAULT 0,
        user_prompt_bytes INTEGER NOT NULL DEFAULT 0,
        artifact_type TEXT,
        artifact_id INTEGER,
        content_capture_level TEXT NOT NULL DEFAULT 'metadata_only',
        telemetry_schema_version TEXT NOT NULL DEFAULT '1',
        started_at TEXT NOT NULL,
        completed_at TEXT
    );
    CREATE INDEX idx_llm_calls_operation ON llm_calls(operation_id);
    CREATE INDEX idx_llm_calls_task_started ON llm_calls(task, started_at);
    CREATE INDEX idx_llm_calls_status ON llm_calls(status);
    CREATE INDEX idx_llm_calls_artifact ON llm_calls(artifact_type, artifact_id);

    CREATE TABLE llm_evaluations (
        evaluation_id TEXT PRIMARY KEY,
        operation_id TEXT,
        call_id TEXT REFERENCES llm_calls(call_id) ON DELETE SET NULL,
        judge_call_id TEXT REFERENCES llm_calls(call_id) ON DELETE SET NULL,
        artifact_type TEXT,
        artifact_id INTEGER,
        evaluator_name TEXT NOT NULL,
        evaluator_type TEXT NOT NULL,
        evaluator_version TEXT NOT NULL,
        metric_name TEXT NOT NULL,
        score REAL,
        label TEXT,
        passed BOOLEAN,
        explanation_redacted TEXT,
        details_json TEXT,
        rubric_digest TEXT,
        evaluated_at TEXT NOT NULL
    );
    CREATE INDEX idx_llm_evaluations_operation ON llm_evaluations(operation_id);
    CREATE INDEX idx_llm_evaluations_call ON llm_evaluations(call_id);
    CREATE INDEX idx_llm_evaluations_artifact ON llm_evaluations(artifact_type, artifact_id);
    CREATE INDEX idx_llm_evaluations_metric ON llm_evaluations(metric_name, evaluated_at);
    """,
]


def _backfill_llm_artifacts(conn: sqlite3.Connection) -> None:
    """Link existing jd_analysis and company_dossier_generation LLM calls to their artifacts."""
    conn.row_factory = sqlite3.Row

    # jd_analysis: exact match on model + input_tokens + output_tokens + latency_ms
    rows = conn.execute(
        """SELECT lc.call_id, ja.id AS analysis_id
           FROM llm_calls lc
           JOIN job_analyses ja
             ON ja.model = lc.actual_model
            AND ja.input_tokens = lc.input_tokens
            AND ja.output_tokens = lc.output_tokens
            AND ja.latency_ms = lc.latency_ms
           WHERE lc.task = 'jd_analysis' AND lc.operation_id IS NULL"""
    ).fetchall()
    for row in rows:
        op_id = str(uuid.uuid4())
        conn.execute(
            "UPDATE llm_calls SET operation_id = ?, artifact_type = 'job_analysis', artifact_id = ? WHERE call_id = ?",
            (op_id, row["analysis_id"], row["call_id"]),
        )

    # company_dossier_generation: closest timestamp match within 120s
    dossier_rows = conn.execute(
        """SELECT lc.call_id, lc.started_at
           FROM llm_calls lc
           WHERE lc.task = 'company_dossier_generation' AND lc.operation_id IS NULL"""
    ).fetchall()
    cr_rows = conn.execute(
        """SELECT id, triggered_by_job_id, researched_at
           FROM company_research WHERE triggered_by_job_id IS NOT NULL
           ORDER BY researched_at DESC"""
    ).fetchall()
    for dr in dossier_rows:
        lc_time = datetime.fromisoformat(dr["started_at"])
        best_cr_id = None
        best_diff = 999.0
        for cr in cr_rows:
            cr_time = datetime.fromisoformat(cr["researched_at"])
            diff = abs((lc_time - cr_time).total_seconds())
            if diff < best_diff:
                best_diff = diff
                best_cr_id = cr["id"]
        if best_cr_id is not None and best_diff < 120:
            op_id = str(uuid.uuid4())
            conn.execute(
                "UPDATE llm_calls SET operation_id = ?, artifact_type = 'company_research', artifact_id = ? WHERE call_id = ?",
                (op_id, best_cr_id, dr["call_id"]),
            )


MIGRATIONS.append(_backfill_llm_artifacts)

# Migration 31: Retrieval call tracking for budget cap enforcement.
# Each paid Tavily search query is recorded here so the budget guard can
# count daily/monthly calls before allowing the next one.
MIGRATIONS.append(
    """
    CREATE TABLE IF NOT EXISTS retrieval_calls (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        adapter_type TEXT NOT NULL,
        query TEXT NOT NULL,
        status TEXT NOT NULL,
        error_message TEXT,
        called_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_retrieval_calls_adapter_date
        ON retrieval_calls(adapter_type, called_at);
    """
)


# Migration 33: candidate-controlled preference ranking, independent of system score.
# NULL = unranked; lower value = more preferred (1 = top choice).
MIGRATIONS.append(
    """
    ALTER TABLE jobs ADD COLUMN preference_rank INTEGER;
    """
)


# Migration 34: Gmail inbound review queue and durable History API cursor.
#
# FK deletion rules are intentional:
# - suggested/final job links are hints and become NULL if a job is deleted;
# - a confirmed event cannot be deleted while its inbound provenance row exists;
# - deleting an inbound row is allowed because confirmation snapshots the audit
#   fields onto the append-only application event metadata.
MIGRATIONS.append(
    """
    CREATE TABLE inbound_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_key TEXT NOT NULL,
        gmail_message_id TEXT NOT NULL,
        gmail_thread_id TEXT,
        rfc822_message_id TEXT,
        sender_address TEXT NOT NULL DEFAULT '',
        sender_domain TEXT NOT NULL DEFAULT '',
        subject TEXT NOT NULL DEFAULT '',
        received_at TEXT NOT NULL,
        suggested_job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
        final_job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
        match_score REAL NOT NULL DEFAULT 0.0,
        match_features TEXT NOT NULL DEFAULT '{}',
        match_candidates TEXT NOT NULL DEFAULT '[]',
        matcher_version TEXT NOT NULL,
        state TEXT NOT NULL CHECK (
            state IN ('matched', 'unmatched', 'confirmed', 'dismissed')
        ),
        decision TEXT,
        decided_at TEXT,
        inferred_kind TEXT,
        confirmed_event_id INTEGER UNIQUE
            REFERENCES application_events(id) ON DELETE RESTRICT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(account_key, gmail_message_id)
    );
    CREATE INDEX idx_inbound_messages_state_received
        ON inbound_messages(state, received_at DESC);
    CREATE INDEX idx_inbound_messages_suggested_job
        ON inbound_messages(suggested_job_id);
    CREATE INDEX idx_inbound_messages_final_job
        ON inbound_messages(final_job_id);

    CREATE TABLE inbound_sync_state (
        account_key TEXT PRIMARY KEY,
        history_id TEXT,
        last_success_at TEXT,
        last_error TEXT,
        lease_owner TEXT,
        lease_expires_at TEXT,
        updated_at TEXT NOT NULL
    );
    """
)

def _split_sql_statements(script: str) -> list[str]:
    """Split a migration script into individual statements on ';'.

    The migrations here are plain CREATE/ALTER/INDEX statements with no triggers
    (no BEGIN...END bodies) and no ';' inside string literals, so a simple split
    is safe and lets each statement run inside one explicit transaction. If a
    future migration needs a trigger, give it its own callable migration.
    """
    return [s.strip() for s in script.split(";") if s.strip()]


def run_migrations(db_path: Path | str | None = None) -> None:
    """Apply pending migrations based on PRAGMA user_version.

    Each entry in MIGRATIONS is either a SQL string or a callable(conn) that runs
    Python code (for data backfills that need application-level logic like
    normalize_company).

    Each migration runs in an explicit transaction and only bumps user_version
    on full success. This avoids the executescript() hazard where an implicit
    COMMIT could leave a multi-statement migration (e.g. several non-idempotent
    ADD COLUMNs) partially applied with user_version un-bumped — which would then
    hard-fail on the next startup's retry.
    """
    db_path = Path(db_path) if db_path is not None else _db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.isolation_level = None  # manual BEGIN/COMMIT/ROLLBACK control
    try:
        current_version = conn.execute("PRAGMA user_version").fetchone()[0]

        # Fast path for a brand-new database: create the v32 schema in one
        # transaction, then let the normal loop apply v33+ migrations.
        if current_version == 0 and len(MIGRATIONS) >= FRESH_SCHEMA_VERSION:
            conn.execute("BEGIN")
            try:
                for stmt in _split_sql_statements(FRESH_SCHEMA_SQL):
                    conn.execute(stmt)
                conn.execute(f"PRAGMA user_version = {FRESH_SCHEMA_VERSION}")
                conn.execute("COMMIT")
                current_version = FRESH_SCHEMA_VERSION
                print(f"  Fresh schema v{FRESH_SCHEMA_VERSION} applied")
            except Exception:
                conn.execute("ROLLBACK")
                raise

        # The 2026 migration squash temporarily renumbered fully-migrated
        # databases to v1/v2. Detect only that unmistakable final-schema shape
        # and restore its logical version. Genuine historical v1/v2 databases
        # do not have retrieval_calls and therefore continue normally.
        if current_version in (1, 2):
            has_retrieval = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='retrieval_calls'"
            ).fetchone()
            if has_retrieval:
                has_preference = conn.execute(
                    "SELECT 1 FROM pragma_table_info('jobs') WHERE name='preference_rank'"
                ).fetchone()
                normalized_version = 33 if has_preference else FRESH_SCHEMA_VERSION
                conn.execute(f"PRAGMA user_version = {normalized_version}")
                current_version = normalized_version
                print(f"  Normalized squashed schema to v{normalized_version}")

        for i in range(current_version, len(MIGRATIONS)):
            migration = MIGRATIONS[i]
            conn.execute("BEGIN")
            try:
                if callable(migration):
                    migration(conn)
                else:
                    for stmt in _split_sql_statements(migration):
                        conn.execute(stmt)
                # user_version is stored in the DB header and participates in the
                # transaction, so it rolls back with the statements on failure.
                conn.execute(f"PRAGMA user_version = {i + 1}")
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            print(f"  Migration v{i + 1} applied")
    finally:
        conn.close()


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Get a SQLite connection. Run migrations if needed."""
    import logging
    _log = logging.getLogger(__name__)
    import time as _time
    _t0 = _time.monotonic()

    if db_path is None:
        db_path = _db_path()
    db_path = Path(db_path)

    # Writable connection with migrations.
    if not db_path.exists():
        run_migrations(db_path)
    else:
        conn = sqlite3.connect(str(db_path))
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        conn.close()
        if current < len(MIGRATIONS):
            run_migrations(db_path)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row  # dict-like access
    # WAL lets readers and a writer proceed concurrently; busy_timeout makes a
    # blocked connection wait (up to 5s) for a lock instead of immediately
    # raising "database is locked" under the threaded API + background pipeline.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    _log.debug("get_connection opened in %.3fs (path=%s)", _time.monotonic() - _t0, db_path)
    return conn


# ---------------------------------------------------------------------------
# JSON helpers for SQLite
# ---------------------------------------------------------------------------

def json_encode(value: Any) -> str:
    """Encode a Python value as JSON for SQLite storage."""
    return json.dumps(value)


def json_decode(value: str | None) -> Any:
    """Decode a JSON value from SQLite. Returns None if value is None."""
    if value is None:
        return None
    return json.loads(value)
