"""FastAPI application — Seeker OS API backend.

Run with:
  uvicorn seeker_os.api.app:app --reload --port 8000
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from seeker_os.api.demo_guard import DemoGuardMiddleware
from seeker_os.api.jobs import router as jobs_router
from seeker_os.api.pipeline import router as pipeline_router
from seeker_os.api.queries import router as queries_router
from seeker_os.api.settings_routes import router as settings_router
from seeker_os.api.analytics import router as analytics_router
from seeker_os.api.resumes import router as resumes_router
from seeker_os.api.models import router as models_router
from seeker_os.api.profile_routes import router as profile_router
from seeker_os.api.company_research import router as company_research_router
from seeker_os.api.company_research_settings import router as company_research_settings_router
from seeker_os.api.jd_analysis import router as jd_analysis_router
from seeker_os.api.backup import router as backup_router
from seeker_os.config import is_demo_mode
from seeker_os.database import run_migrations

logger = logging.getLogger(__name__)


class RootResponse(BaseModel):
    name: str
    version: str
    docs: str


class HealthResponse(BaseModel):
    status: str


class DemoModeResponse(BaseModel):
    demo_mode: bool


class LogsResponse(BaseModel):
    lines: list[str] = Field(default_factory=list)
    path: str | None = None
    note: str | None = None

# ---------------------------------------------------------------------------
# Logging — write to data/backend.log so the UI can retrieve recent lines in
# live mode. In demo mode, logs go to stdout only (correct for containers and
# avoids a writable data/ directory).
# ---------------------------------------------------------------------------
_LOG_DIR = Path(__file__).resolve().parents[2] / "data"
_LOG_FILE = _LOG_DIR / "backend.log"

_log_handlers = [logging.StreamHandler()]
if not is_demo_mode():
    _LOG_DIR.mkdir(exist_ok=True)
    _log_handlers.append(logging.FileHandler(_LOG_FILE, encoding="utf-8"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=_log_handlers,
)

# Suppress watchfiles (uvicorn --reload) to WARNING in the log file to prevent
# a feedback loop: watchfiles detects the log file changing → logs the detection
# → writes to the log file → triggers another detection.
logging.getLogger("watchfiles.main").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run DB migrations on startup (live mode only) and log the active mode."""
    mode = "DEMO (read-only)" if is_demo_mode() else "LIVE"
    logger.info("Seeker OS starting in %s mode", mode)

    if is_demo_mode():
        # Demo DB is immutable and pre-baked; migrations are skipped at runtime.
        # Build-time seeding runs run_migrations() before the image is baked.
        from seeker_os.database import _db_path, get_connection
        from seeker_os.demo.seed import seed_demo_db

        conn = get_connection()
        job_count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        conn.close()
        if job_count == 0:
            logger.info("Demo DB is empty; seeding synthetic data")
            seed_demo_db(_db_path())
            logger.info("Demo seed complete")
    else:
        run_migrations()
        _sync_queries_from_yaml()

    yield


def _sync_queries_from_yaml() -> None:
    """Sync queries from config/queries.yml into the search_queries table.

    Inserts new queries, updates existing ones (by query_slug), and deletes
    queries that no longer exist in the YAML file.
    """
    from seeker_os.config import get_settings
    from seeker_os.database import get_connection

    settings = get_settings()
    if not settings.queries or not settings.queries.queries:
        return

    yaml_slugs = {q.slug for q in settings.queries.queries}
    db = get_connection()
    try:
        # Delete queries that no longer exist in YAML
        if yaml_slugs:
            db.execute(
                "DELETE FROM search_queries WHERE query_slug NOT IN (%s)" % ",".join("?" * len(yaml_slugs)),
                tuple(yaml_slugs),
            )
        # Upsert each query by slug (delete + insert to avoid duplicate rows)
        for q in settings.queries.queries:
            db.execute("DELETE FROM search_queries WHERE query_slug = ?", (q.slug,))
            db.execute(
                """
                INSERT INTO search_queries
                (source_id, query_slug, label, commitment_filter, max_pages, enabled, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (q.source_id, q.slug, q.label, q.commitment, q.max_pages, q.enabled, "synced from queries.yml"),
            )
        db.commit()
        logger.info("Synced %d queries from queries.yml", len(yaml_slugs))
    except Exception:
        logger.exception("Failed to sync queries from YAML")
    finally:
        db.close()


app = FastAPI(
    title="Seeker OS API",
    description="Structured job search pipeline — REST API",
    version="0.1.0",
    lifespan=lifespan,
)

# Demo guard — must be early in the middleware stack so it blocks mutations
# before any route handler runs.
app.add_middleware(DemoGuardMiddleware)

# CORS — configurable via env var CORS_ORIGINS (comma-separated).
# Defaults to localhost:3000 for local dev. For Docker/production, set
# CORS_ORIGINS=https://yourdomain.com,https://www.yourdomain.com
_default_origins = ["http://localhost:3000", "http://127.0.0.1:3000"]
_cors_env = os.environ.get("CORS_ORIGINS", "")
allow_origins = [o.strip() for o in _cors_env.split(",") if o.strip()] if _cors_env else _default_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(jobs_router)
app.include_router(pipeline_router)
app.include_router(queries_router)
app.include_router(company_research_settings_router)
app.include_router(settings_router)
app.include_router(analytics_router)
app.include_router(resumes_router)
app.include_router(models_router)
app.include_router(profile_router)
app.include_router(company_research_router)
app.include_router(jd_analysis_router)
app.include_router(backup_router)


@app.get("/", response_model=RootResponse)
def root():
    return {"name": "Seeker OS API", "version": "0.1.0", "docs": "/docs"}


@app.get("/api/health", response_model=HealthResponse)
def health():
    return {"status": "ok"}


@app.get("/api/demo-mode", response_model=DemoModeResponse)
def demo_mode_status():
    """Return whether the backend is running in read-only demo mode."""
    return {"demo_mode": is_demo_mode()}


@app.get("/api/logs", response_model=LogsResponse)
def get_logs(tail: int = 80):
    """Return the last *tail* lines of the backend log file for UI display."""
    if is_demo_mode():
        return {"lines": [], "path": None, "note": "Demo mode logs are emitted to stdout only."}
    try:
        lines = _LOG_FILE.read_text(encoding="utf-8").splitlines()
        return {"lines": lines[-tail:], "path": str(_LOG_FILE)}
    except FileNotFoundError:
        return {"lines": [], "path": str(_LOG_FILE)}
