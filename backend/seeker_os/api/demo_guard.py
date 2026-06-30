"""Central demo-mode guard middleware.

Default-deny on writes: only allowlisted read endpoints are permitted when
DEMO_MODE is enabled. Mutations return 403 with a clear message.
"""

from __future__ import annotations

import re

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from seeker_os.config import is_demo_mode


# Allowed methods for any path (health, logs, static OpenAPI docs, etc.)
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# Exact allowlisted paths for read-only demo data.
_ALLOWED_PATHS = {
    "/",
    "/api/health",
    "/api/logs",
    "/api/demo-mode",
    "/docs",
    "/openapi.json",
    "/api/jobs",  # list
    "/api/pipeline/runs",  # list
    "/api/resumes",  # list
    "/api/resumes/master",  # info
    "/api/settings",
    "/api/profile",
    "/api/filters",
    "/api/accuracy-rules",
    "/api/settings/company-research",
    "/api/models",
    "/api/models/providers",
    "/api/models/tiers",
    "/api/models/tasks",
    "/api/analytics/funnel",
    "/api/analytics/response-rate",
    "/api/backup",
}

# Pattern allowlist for paths with path parameters.
_ALLOWED_PATTERNS = [
    re.compile(r"^/api/jobs/\d+/?$"),  # get job
    re.compile(r"^/api/jobs/\d+/events/?$"),
    re.compile(r"^/api/jobs/\d+/cross-ref/?$"),
    re.compile(r"^/api/jobs/\d+/company-research/?$"),
    re.compile(r"^/api/jobs/\d+/analysis/?$"),
    re.compile(r"^/api/pipeline/runs/[a-zA-Z0-9_-]+/?$"),  # get run
    re.compile(r"^/api/resumes/\d+/?$"),
    re.compile(r"^/api/resumes/\d+/(pdf|markdown|docx)/?$"),
    re.compile(r"^/api/models/providers/[a-zA-Z0-9_-]+/?$"),
    re.compile(r"^/api/models/tiers/[a-zA-Z0-9_-]+/?$"),
    re.compile(r"^/api/models/tasks/[a-zA-Z0-9_-]+/?$"),
    re.compile(r"^/api/settings/[a-zA-Z0-9_-]+/?$"),
]


class DemoGuardMiddleware(BaseHTTPMiddleware):
    """Block mutation requests in demo mode; allow only read-only endpoints."""

    async def dispatch(self, request: Request, call_next):
        if not is_demo_mode():
            return await call_next(request)

        if request.method in _SAFE_METHODS:
            if self._is_allowed_path(request.url.path):
                return await call_next(request)

        return JSONResponse(
            status_code=403,
            content={
                "detail": "Demo mode is read-only. This action is disabled.",
                "demo_mode": True,
            },
        )

    def _is_allowed_path(self, path: str) -> bool:
        # Strip trailing slash for matching
        normalized = path.rstrip("/") or "/"
        if normalized in _ALLOWED_PATHS:
            return True
        return any(pattern.match(path) for pattern in _ALLOWED_PATTERNS)
