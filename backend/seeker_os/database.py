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

MIGRATIONS: list[str | callable] = [
    # Squashed v1-v31: all tables in their final form.
    # This single migration replaces migrations 1-31 for fresh DBs.
    # Existing prod DBs at user_version >= 31 skip this entirely
    # (range(31, 1) is empty — run_migrations loop does nothing).
    """
    -- jobs (final form: all ALTER TABLE columns merged in, no recruiter_* columns)
    CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id TEXT,
        source_job_id TEXT,
        ats_source TEXT,
        ats_board_token TEXT,
        ats_job_id TEXT,
        apply_url TEXT,
        url_hash TEXT UNIQUE,
        title TEXT,
        core_title TEXT,
        company TEXT,
        company_homepage TEXT,
        location TEXT,
        workplace_type TEXT,
        workplace_countries TEXT,
        seniority_level TEXT,
        commitment TEXT,
        comp_min INTEGER,
        comp_max INTEGER,
        comp_currency TEXT,
        technical_tools TEXT,
        requirements_summary TEXT,
        date_posted TEXT,
        role_type TEXT,
        status TEXT DEFAULT 'discovered',
        tier_passed INTEGER DEFAULT 0,
        score REAL,
        score_reasons TEXT,
        score_gaps TEXT,
        jd_full TEXT,
        jd_fetch_status TEXT DEFAULT 'pending',
        discovered_at TEXT,
        discovered_query TEXT,
        updated_at TEXT,
        is_pinned BOOLEAN DEFAULT FALSE,
        reject_reason TEXT,
        content_hash TEXT,
        title_norm TEXT,
        company_norm TEXT,
        cross_ref_status TEXT,
        cross_ref_date TEXT,
        cross_ref_score REAL,
        reject_details TEXT,
        detail_url TEXT,
        ai_policy TEXT,
        research_adjusted_score REAL,
        research_delta REAL DEFAULT 0,
        research_breakdown TEXT,
        filter_warnings TEXT,
        overridden_at TEXT,
        override_note TEXT,
        original_reject_reason TEXT,
        analysis_verdict TEXT,
        analysis_delta REAL DEFAULT 0,
        net_score REAL,
        run_id TEXT,
        score_modifiers TEXT,
        comp_source TEXT DEFAULT 'none'
    );

    CREATE INDEX IF NOT EXISTS idx_jobs_url_hash ON jobs(url_hash);
    CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
    CREATE INDEX IF NOT EXISTS idx_jobs_company_norm ON jobs(company_norm);
    CREATE INDEX IF NOT EXISTS idx_jobs_source_job_id ON jobs(source_job_id);
    CREATE INDEX IF NOT EXISTS idx_jobs_tier_passed ON jobs(tier_passed);
    CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs(score);
    CREATE INDEX IF NOT EXISTS idx_jobs_run_id ON jobs(run_id);

    -- search_queries (final form: + search_query column)
    CREATE TABLE IF NOT EXISTS search_queries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id TEXT,
        query_slug TEXT,
        label TEXT,
        commitment_filter TEXT,
        max_pages INTEGER DEFAULT 1,
        enabled BOOLEAN DEFAULT TRUE,
        last_run_at TEXT,
        notes TEXT,
        search_query TEXT
    );

    -- dedup_registry (final form: ON DELETE CASCADE)
    CREATE TABLE IF NOT EXISTS dedup_registry (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
        key_type TEXT,
        key_value TEXT,
        created_at TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_dedup_key_value ON dedup_registry(key_value);
    CREATE INDEX IF NOT EXISTS idx_dedup_key_type ON dedup_registry(key_type);

    -- pipeline_runs (unchanged from v1)
    CREATE TABLE IF NOT EXISTS pipeline_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT,
        started_at TEXT,
        completed_at TEXT,
        queries_run TEXT,
        cards_fetched INTEGER,
        cards_new INTEGER,
        cards_survived_tier2 INTEGER,
        jds_fetched INTEGER,
        jobs_scored INTEGER,
        jobs_ready INTEGER,
        status TEXT
    );

    -- settings (unchanged from v1)
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT,
        updated_at TEXT
    );

    -- resumes (final form: ON DELETE CASCADE from v26)
    CREATE TABLE IF NOT EXISTS resumes (
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

    CREATE INDEX IF NOT EXISTS idx_resumes_job_id ON resumes(job_id);
    CREATE INDEX IF NOT EXISTS idx_resumes_generated_at ON resumes(generated_at);

    -- company_research (final form: decoupled from jobs in v27, no job_id FK)
    CREATE TABLE IF NOT EXISTS company_research (
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
    );

    CREATE INDEX IF NOT EXISTS idx_company_research_company_norm ON company_research(company_norm);
    CREATE INDEX IF NOT EXISTS idx_company_research_company_name ON company_research(company_name);

    -- job_analyses (final form: ON DELETE CASCADE from v26)
    CREATE TABLE IF NOT EXISTS job_analyses (
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

    CREATE INDEX IF NOT EXISTS idx_job_analyses_job_id ON job_analyses(job_id);
    CREATE INDEX IF NOT EXISTS idx_job_analyses_verdict ON job_analyses(verdict);

    -- application_events (final form: ON DELETE CASCADE from v26)
    CREATE TABLE IF NOT EXISTS application_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
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

    -- recruiters (from v25)
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

    -- recruiter_job_contacts (from v25)
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

    -- llm_calls (from v30)
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

    -- llm_evaluations (from v30)
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

    -- retrieval_calls (from v31)
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
