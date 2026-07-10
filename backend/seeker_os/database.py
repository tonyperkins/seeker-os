"""SQLite connection helper and schema migrations.

SQLite at data/seeker.db (live) or data/seeker.demo.db (demo) — single-user, zero-config.
No Alembic. Simple versioned migrations via PRAGMA user_version.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from seeker_os.config import DATA_DIR, is_demo_mode


def _db_path() -> Path:
    """Return the active DB path, evaluating is_demo_mode() at call time.

    This must be dynamic, not a module-level constant, because .env is loaded
    by Settings.__init__ which runs after module import. A constant set at
    import time would lock DB_PATH to the demo DB before .env is read.
    """
    return DATA_DIR / ("seeker.demo.db" if is_demo_mode() else "seeker.db")


# Backward-compatible module-level constant. Set at import time — may be
# stale if DEMO_MODE is set via .env (loaded later). Production code uses
# _db_path() instead. Tests that monkeypatch this should patch _db_path.
DB_PATH = DATA_DIR / ("seeker.demo.db" if is_demo_mode() else "seeker.db")

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
    # storing it lets the UI and demo surface "research discarded: entity mismatch".
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
    """Get a SQLite connection. Run migrations if needed.

    In demo mode the database is treated as immutable: it is opened read-only
    and migrations are skipped. The demo DB must be pre-baked before startup.
    """
    if db_path is None:
        db_path = _db_path()
    db_path = Path(db_path)
    if is_demo_mode() and db_path == _db_path():
        if not db_path.exists():
            raise RuntimeError(
                f"Demo DB not found at {db_path}. "
                "Build the image with a pre-seeded demo DB or run the seeder before startup."
            )
        # Read-only, immutable connection. URI mode requires check_same_thread=False.
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    # Live mode or an explicit non-default path: writable connection with migrations.
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
