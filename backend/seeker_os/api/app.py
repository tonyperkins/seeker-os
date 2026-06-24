"""FastAPI application — Seeker OS API backend.

Run with:
  uvicorn seeker_os.api.app:app --reload --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager

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
from seeker_os.database import run_migrations


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

# CORS — allow the Next.js dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(jobs_router)
app.include_router(pipeline_router)
app.include_router(queries_router)
app.include_router(settings_router)
app.include_router(analytics_router)
app.include_router(resumes_router)
app.include_router(models_router)
app.include_router(profile_router)


@app.get("/")
def root():
    return {"name": "Seeker OS API", "version": "0.1.0", "docs": "/docs"}


@app.get("/api/health")
def health():
    return {"status": "ok"}
