"""SQLite connection helper and schema migrations.

SQLite at data/seeker.db — single-user, zero-config.
No Alembic. Simple versioned migrations via PRAGMA user_version.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from seeker_os.config import DATA_DIR

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
]


def run_migrations(db_path: Path | str = DB_PATH) -> None:
    """Apply pending migrations based on PRAGMA user_version.

    Each entry in MIGRATIONS is either a SQL string (executed via executescript)
    or a callable(conn) that runs Python code (for data backfills that need
    application-level logic like normalize_company).
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    try:
        current_version = conn.execute("PRAGMA user_version").fetchone()[0]
        for i in range(current_version, len(MIGRATIONS)):
            migration = MIGRATIONS[i]
            if callable(migration):
                migration(conn)
            else:
                conn.executescript(migration)
            conn.execute(f"PRAGMA user_version = {i + 1}")
            conn.commit()
            print(f"  Migration v{i + 1} applied")
    finally:
        conn.close()


def get_connection(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    """Get a SQLite connection. Run migrations if needed."""
    db_path = Path(db_path)
    if not db_path.exists():
        run_migrations(db_path)
    else:
        # Check if migrations are needed
        conn = sqlite3.connect(str(db_path))
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        conn.close()
        if current < len(MIGRATIONS):
            run_migrations(db_path)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row  # dict-like access
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
