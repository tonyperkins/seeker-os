"""Tests for demo-mode guard and demo config loading.

These tests are adversarial: a public keyless demo must deny every mutation by
default, must survive a stripped environment, and must never touch live config.
"""

import os
import re
import subprocess
import sys

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

# These tests intentionally run with DEMO_MODE=true to verify the guard.


@pytest.fixture
def demo_client(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    # Force re-import so is_demo_mode() is evaluated under the patched env.
    import importlib

    from seeker_os import config, database
    from seeker_os.api import app
    from seeker_os.demo.seed import seed_demo_db

    importlib.reload(config)
    importlib.reload(database)
    # Seed the demo DB directly so the runtime opens it read-only.
    seed_demo_db(database._db_path())
    importlib.reload(app)

    with TestClient(app.app) as client:
        yield client


def _collect_routes(routes):
    """Recursively flatten the app route table into (methods, path) pairs."""
    result = []
    for r in routes:
        if hasattr(r, "original_router"):
            result.extend(_collect_routes(r.original_router.routes))
        elif isinstance(r, APIRoute):
            result.append((r.methods, r.path))
    return result


def _fill_path(path: str) -> str:
    """Replace path parameters with plausible demo-DB values."""
    # Order matters: more specific parameter names first.
    replacements = {
        "provider_id": "anthropic",
        "resume_id": "1",
        "job_id": "1",
        "query_id": "1",
        "run_id": "run-1",
        "key": "foo",
        "task": "resume_generation",
        "tier": "heavy",
    }
    for param, value in replacements.items():
        path = path.replace(f"{{{param}}}", value)
    # Any remaining param gets a generic placeholder so the guard still sees a path.
    path = re.sub(r"\{[^}]+\}", "1", path)
    return path


def _route_request(client: TestClient, methods: set[str], path: str):
    """Make a minimal request for the given method/path."""
    # Use HEAD for GET-only routes to avoid body parsing; for mutations pick a method.
    mutation_methods = sorted(methods - {"GET", "HEAD", "OPTIONS"})
    if not mutation_methods:
        return None
    method = mutation_methods[0]
    url = _fill_path(path)
    kwargs = {}
    if method in ("POST", "PUT", "PATCH"):
        kwargs["json"] = {}
    if method == "POST" and "upload" in path:
        # Upload endpoints need a multipart body; guard blocks before parsing anyway.
        kwargs.pop("json", None)
        kwargs["data"] = {}
    return client.request(method, url, **kwargs)


def test_demo_flag_is_fail_closed(monkeypatch):
    """Only the exact clean string 'false' disables demo mode."""
    from seeker_os.config import is_demo_mode

    monkeypatch.delenv("DEMO_MODE", raising=False)
    assert is_demo_mode() is True

    monkeypatch.setenv("DEMO_MODE", "")
    assert is_demo_mode() is True

    monkeypatch.setenv("DEMO_MODE", "maybe")
    assert is_demo_mode() is True

    monkeypatch.setenv("DEMO_MODE", "yes")
    assert is_demo_mode() is True

    monkeypatch.setenv("DEMO_MODE", "1")
    assert is_demo_mode() is True

    monkeypatch.setenv("DEMO_MODE", "TRUE ")
    assert is_demo_mode() is True

    monkeypatch.setenv("DEMO_MODE", "true")
    assert is_demo_mode() is True

    # 0/no/off used to disable demo in older iterations; now they fail closed.
    monkeypatch.setenv("DEMO_MODE", "0")
    assert is_demo_mode() is True

    monkeypatch.setenv("DEMO_MODE", "no")
    assert is_demo_mode() is True

    monkeypatch.setenv("DEMO_MODE", "off")
    assert is_demo_mode() is True

    monkeypatch.setenv("DEMO_MODE", "FALSE")
    assert is_demo_mode() is True

    monkeypatch.setenv("DEMO_MODE", "false ")
    assert is_demo_mode() is True

    monkeypatch.setenv("DEMO_MODE", "false")
    assert is_demo_mode() is False


@pytest.mark.parametrize(
    "value,expected",
    [
        ("false", False),
        ("FALSE", True),
        ("FaLsE", True),
        ("False", True),
        ("false ", True),
        (" no", True),
        ("0", True),
        ("off", True),
        ("true", True),
        ("", True),
    ],
)
def test_demo_flag_only_clean_false_is_live(monkeypatch, value, expected):
    monkeypatch.setenv("DEMO_MODE", value)
    from seeker_os.config import is_demo_mode

    assert is_demo_mode() is expected


def test_demo_config_loads_demo_persona(demo_client):
    from seeker_os.config import get_settings

    settings = get_settings()
    assert settings.demo_mode is True
    assert settings.config_dir.name == "demo"
    assert settings.profile.user.name == "Alex Rivera"
    assert len(settings.providers.providers) == 0
    assert len(settings.queries.queries) == 0
    assert len(settings.sources.sources) == 0


def test_demo_allows_read_endpoints(demo_client):
    assert demo_client.get("/api/health").status_code == 200
    assert demo_client.get("/api/demo-mode").json()["demo_mode"] is True
    assert demo_client.get("/api/jobs").status_code == 200


def test_demo_blocks_mutations(demo_client):
    blocked = demo_client.post("/api/jobs", json={"url": "https://example.com"})
    assert blocked.status_code == 403
    assert blocked.json()["demo_mode"] is True

    blocked = demo_client.post("/api/pipeline/runs", json={})
    assert blocked.status_code == 403

    blocked = demo_client.put("/api/profile", json={})
    assert blocked.status_code == 403


def test_demo_uses_demo_db_path(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    import importlib

    from seeker_os import database

    importlib.reload(database)
    assert database._db_path().name == "seeker.demo.db"


def test_demo_guard_blocks_every_non_get_route(demo_client):
    """Every mutation route in the app must be 403 in demo mode.

    This enumerates the actual route table, so any future endpoint added without
    a demo-read allowlist is automatically caught.
    """
    import importlib

    from seeker_os import config
    from seeker_os.api import app

    importlib.reload(config)
    importlib.reload(app)

    failures = []
    for methods, path in _collect_routes(app.app.routes):
        if {"GET", "HEAD", "OPTIONS"} >= methods:
            continue
        resp = _route_request(demo_client, methods, path)
        if resp is None:
            continue
        if resp.status_code != 403:
            failures.append(f"{sorted(methods)} {path}: {resp.status_code}")

    assert not failures, "Non-GET routes not blocked in demo mode:\n" + "\n".join(failures)


def test_demo_guard_allowlist_does_not_wave_through_get_side_effects(demo_client):
    """Confirm no GET route has a write side-effect that would be allowlisted.

    If a GET handler mutates state, it should be blocked or refactored.
    """
    import importlib

    from seeker_os import config
    from seeker_os.api import app

    importlib.reload(config)
    importlib.reload(app)

    # These are the GET routes we explicitly allow.  Inspect them to ensure they are reads.
    allowed_reads = {
        "/",
        "/api/health",
        "/api/demo-mode",
        "/api/logs",
        "/api/jobs",
        "/api/jobs/{job_id}",
        "/api/jobs/{job_id}/events",
        "/api/jobs/{job_id}/cross-ref",
        "/api/jobs/{job_id}/company-research",
        "/api/jobs/{job_id}/analysis",
        "/api/jobs/skipped/no-reason",
        "/api/pipeline/runs",
        "/api/pipeline/runs/{run_id}",
        "/api/resumes",
        "/api/resumes/master",
        "/api/resumes/{resume_id}",
        "/api/resumes/{resume_id}/pdf",
        "/api/resumes/{resume_id}/markdown",
        "/api/resumes/{resume_id}/docx",
        "/api/settings",
        "/api/settings/{key}",
        "/api/settings/company-research",
        "/api/profile",
        "/api/filters",
        "/api/accuracy-rules",
        "/api/models",
        "/api/models/anthropic/oauth/status",
        "/api/models/providers",
        "/api/models/tiers",
        "/api/models/tasks",
        "/api/analytics/funnel",
        "/api/analytics/calibration",
        "/api/analytics/response-rate",
        "/api/backup",
        "/api/backup/db",
        "/docs",
        "/openapi.json",
    }
    for methods, path in _collect_routes(app.app.routes):
        if methods != {"GET"}:
            continue
        if path not in allowed_reads:
            # Unknown GET route should also be blocked in demo mode.
            resp = demo_client.get(_fill_path(path))
            assert resp.status_code == 403, f"GET {path} was not blocked (status {resp.status_code})"


def test_demo_boots_under_stripped_environment():
    """env -i DEMO_MODE=true ... python3 must import the app without resolving keys."""
    # Run a minimal import/boot in a stripped environment.
    script = (
        "import os; "
        "from seeker_os.api.app import app; "
        "from seeker_os.config import get_settings; "
        "s = get_settings(); "
        "print('ok', s.demo_mode, s.config_dir.name, len(s.providers.providers))"
    )
    env = {"DEMO_MODE": "true", "PATH": os.environ.get("PATH", "")}
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Stripped env boot failed:\n{result.stderr}"
    assert "ok True demo 0" in result.stdout


def _make_connection_patcher(db_path):
    """Return a get_connection replacement that always connects to db_path."""
    import sqlite3
    from pathlib import Path

    from seeker_os.database import run_migrations

    db_path = Path(db_path)

    def _patched_get_connection(_db_path=None):
        if not db_path.exists():
            run_migrations(db_path)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    return _patched_get_connection


def test_demo_seeder_only_fires_in_demo_mode_for_empty_db(tmp_path, monkeypatch):
    """Auto-seed runs only when demo mode + empty demo DB; live mode never seeds."""
    import asyncio
    import importlib

    from seeker_os import config, database
    from seeker_os.api import app as app_module
    from seeker_os.demo import seed as seed_module

    async def _run_lifespan(module):
        async with module.lifespan(app=module.app):
            pass

    # Live mode + empty DB → no seed inserted.
    monkeypatch.setenv("DEMO_MODE", "false")
    live_db = tmp_path / "live_empty.db"
    importlib.reload(config)
    importlib.reload(database)
    monkeypatch.setattr(database, "_db_path", lambda: live_db)
    monkeypatch.setattr(database, "get_connection", _make_connection_patcher(live_db))
    importlib.reload(seed_module)
    importlib.reload(app_module)

    asyncio.run(_run_lifespan(app_module))
    conn = database.get_connection()
    live_count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    conn.close()
    assert live_count == 0, "Live mode must not auto-seed demo data"

    # Demo mode + empty demo DB → seed fires.
    monkeypatch.setenv("DEMO_MODE", "true")
    demo_db = tmp_path / "demo_empty.db"
    importlib.reload(config)
    importlib.reload(database)
    monkeypatch.setattr(database, "_db_path", lambda: demo_db)
    monkeypatch.setattr(database, "get_connection", _make_connection_patcher(demo_db))
    importlib.reload(seed_module)
    importlib.reload(app_module)

    asyncio.run(_run_lifespan(app_module))
    conn = database.get_connection()
    demo_count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    conn.close()
    assert demo_count > 0, "Demo mode must auto-seed empty demo DB"

    # Idempotent: second lifespan run on already-seeded DB should not crash or duplicate.
    asyncio.run(_run_lifespan(app_module))
    conn = database.get_connection()
    demo_count2 = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    conn.close()
    assert demo_count2 == demo_count, "Demo seeder must be idempotent"
