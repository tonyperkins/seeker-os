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
from seeker_os.database import run_migrations

# ---------------------------------------------------------------------------
# Logging — write to data/backend.log so the UI can retrieve recent lines
# ---------------------------------------------------------------------------
_LOG_DIR = Path(__file__).resolve().parents[2] / "data"
_LOG_DIR.mkdir(exist_ok=True)
_LOG_FILE = _LOG_DIR / "backend.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(_LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)

# Suppress watchfiles (uvicorn --reload) to WARNING in the log file to prevent
# a feedback loop: watchfiles detects the log file changing → logs the detection
# → writes to the log file → triggers another detection.
logging.getLogger("watchfiles.main").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run DB migrations on startup."""
    run_migrations()
    yield


app = FastAPI(
    title="Seeker OS API",
    description="Structured job search pipeline — REST API",
    version="0.1.0",
    lifespan=lifespan,
)

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


@app.get("/")
def root():
    return {"name": "Seeker OS API", "version": "0.1.0", "docs": "/docs"}


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/logs")
def get_logs(tail: int = 80):
    """Return the last *tail* lines of the backend log file for UI display."""
    try:
        lines = _LOG_FILE.read_text(encoding="utf-8").splitlines()
        return {"lines": lines[-tail:], "path": str(_LOG_FILE)}
    except FileNotFoundError:
        return {"lines": [], "path": str(_LOG_FILE)}
