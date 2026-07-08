"""Synthetic demo seed loader for Seeker OS.

Reads per-job JSON fixtures from backend/seeker_os/demo/fixtures/ and writes them
into a SQLite DB. Validates every fixture before insert; fails loudly on malformed
data so the demo never renders broken.

Usage:
    cd backend
    python3 -m seeker_os.demo.seed [DB_PATH]

Default DB_PATH: ../../data/seeker.demo.db
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from seeker_os.database import json_decode, json_encode, run_migrations
from seeker_os.dedup.layers import content_hash, url_hash
from seeker_os.dedup.normalize import normalize_company, normalize_title


PROJECT_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "seeker.demo.db"

LEGAL_COMP_SOURCES = {"structured", "parsed", "manual", "none"}
LEGAL_VERIFICATION_STATES = {"verified", "unverified", "mismatch"}
LEGAL_STATUSES = {
    "discovered", "filtered", "jd_fetched", "ready", "rejected", "capped",
    "skipped", "applied", "engaged", "duplicate_flagged", "withdrawn",
    "company_rejected", "offer_accepted", "offer_declined",
}
LEGAL_WORKPLACE_TYPES = {"Remote", "Hybrid", "Onsite", "", None}

REQUIRED_JOB_KEYS = {
    "id", "title", "core_title", "company", "company_homepage", "location",
    "workplace_type", "workplace_countries", "seniority_level", "commitment",
    "comp_min", "comp_max", "comp_currency", "comp_source", "technical_tools",
    "date_posted", "role_type", "status", "tier_passed", "score", "score_reasons",
    "score_gaps", "score_modifiers", "apply_url", "detail_url", "discovered_query",
    "ai_policy", "jd_summary",
}

REQUIRED_DOSSIER_KEYS = {
    "overall_confidence", "summary", "verdict_flags", "funding_data",
    "sentiment_data", "fit_data", "gaps", "verification_state",
    "sources_used", "retrieval_used", "retrieval_sources", "retrieval_snippets",
}

REQUIRED_RESUME_KEYS = {
    "fixture_type", "job_id", "task", "provider", "model", "resume_text",
    "master_resume_path", "validation_passed", "validation_violations",
    "input_tokens", "output_tokens", "latency_ms", "generated_at",
}


class FixtureValidationError(Exception):
    """A fixture failed validation."""

    def __init__(self, filename: str, message: str):
        self.filename = filename
        self.message = message
        super().__init__(f"{filename}: {message}")


def _validate_job_fixture(data: dict[str, Any], filename: str) -> None:
    """Validate a job fixture dict."""
    if not isinstance(data, dict):
        raise FixtureValidationError(filename, "top-level value must be a JSON object")

    # Job keys
    missing = REQUIRED_JOB_KEYS - data.keys()
    if missing:
        raise FixtureValidationError(filename, f"missing job keys: {sorted(missing)}")

    # Dossier keys — only required when a dossier is provided (most jobs)
    if data.get("status") != "rejected" or "overall_confidence" in data:
        missing = REQUIRED_DOSSIER_KEYS - data.keys()
        if missing:
            raise FixtureValidationError(filename, f"missing dossier keys: {sorted(missing)}")

    # Enum-ish fields
    if data["comp_source"] not in LEGAL_COMP_SOURCES:
        raise FixtureValidationError(
            filename, f"invalid comp_source '{data['comp_source']}'"
        )
    vs = data.get("verification_state")
    if vs is not None and vs not in LEGAL_VERIFICATION_STATES:
        raise FixtureValidationError(
            filename, f"invalid verification_state '{vs}'"
        )
    if data["status"] not in LEGAL_STATUSES:
        raise FixtureValidationError(filename, f"invalid status '{data['status']}'")
    if data["workplace_type"] not in LEGAL_WORKPLACE_TYPES:
        raise FixtureValidationError(
            filename, f"invalid workplace_type '{data['workplace_type']}'"
        )

    # Dossier section shapes
    for section in ("funding_data", "sentiment_data", "fit_data"):
        if data.get(section) is not None and not isinstance(data[section], dict):
            raise FixtureValidationError(filename, f"{section} must be an object or null")

    for key in ("verdict_flags", "score_modifiers"):
        if not isinstance(data.get(key, {}), dict):
            raise FixtureValidationError(filename, f"{key} must be an object")

    for key in ("workplace_countries", "commitment", "technical_tools", "score_reasons",
                "score_gaps", "gaps", "sources_used", "retrieval_sources",
                "retrieval_snippets"):
        if not isinstance(data.get(key, []), list):
            raise FixtureValidationError(filename, f"{key} must be an array")

    # Type checks
    if not isinstance(data["id"], int):
        raise FixtureValidationError(filename, "id must be an integer")
    if not isinstance(data["score"], (int, float)):
        raise FixtureValidationError(filename, "score must be a number")

    # Research-adjustment fields
    if "research_delta" in data:
        for key in ("research_adjusted_score", "research_delta", "net_score"):
            if not isinstance(data.get(key), (int, float)):
                raise FixtureValidationError(filename, f"{key} must be a number")
        if not isinstance(data.get("research_breakdown", []), list):
            raise FixtureValidationError(filename, "research_breakdown must be an array")


def _validate_resume_fixture(data: dict[str, Any], filename: str) -> None:
    """Validate a resume fixture dict."""
    if not isinstance(data, dict):
        raise FixtureValidationError(filename, "top-level value must be a JSON object")

    if data.get("fixture_type") != "resume":
        raise FixtureValidationError(filename, "fixture_type must be 'resume'")

    missing = REQUIRED_RESUME_KEYS - data.keys()
    if missing:
        raise FixtureValidationError(filename, f"missing resume keys: {sorted(missing)}")

    if not isinstance(data["job_id"], int):
        raise FixtureValidationError(filename, "job_id must be an integer")
    if not isinstance(data["resume_text"], str):
        raise FixtureValidationError(filename, "resume_text must be a string")
    if not isinstance(data["validation_violations"], list):
        raise FixtureValidationError(filename, "validation_violations must be an array")


def _build_jd_text(data: dict[str, Any]) -> str:
    """Build a JD stub from the fixture summary."""
    comp_str = f"${data['comp_min']:,} - ${data['comp_max']:,} {data['comp_currency']}"
    return f"""{data['title']} at {data['company']}

Location: {data['location']} | Workplace: {data['workplace_type']}
Compensation: {comp_str}

About {data['company']}
{data['company']} builds reliable infrastructure for modern teams. {data['jd_summary']}

About the role
We are looking for a {data['title']} to help scale our production platform. You will work with {', '.join(data['technical_tools'][:5])}, and modern observability tools. You will participate in on-call rotation, lead incident response, and contribute to blameless postmortems. We value SLOs, error budgets, and chaos engineering.

Requirements
- 8+ years in software engineering and infrastructure.
- Strong experience with cloud platforms, Kubernetes, and Terraform.
- Comfort with on-call, incident response, and reliability practices.
- Excellent written communication and collaboration skills.

Compensation and benefits
{comp_str}. We offer full-time employment, health benefits, and a flexible PTO policy.

We are an equal opportunity employer.
"""


def _insert_job(conn: sqlite3.Connection, data: dict[str, Any]) -> None:
    """Insert a job row from a fixture."""
    now = data.get("discovered_at", "2026-06-28T12:00:00+00:00")
    jd_text = _build_jd_text(data)
    comp_display = (
        f"${data['comp_min']:,} - ${data['comp_max']:,} {data['comp_currency']}"
        if data["comp_min"] is not None else "Not listed"
    )

    row = {
        "id": data["id"],
        "source_id": "demo",
        "source_job_id": f"demo_{data['id']}",
        "ats_source": None,
        "ats_board_token": None,
        "ats_job_id": None,
        "apply_url": data["apply_url"],
        "url_hash": url_hash(data["apply_url"]),
        "title": data["title"],
        "core_title": data["core_title"],
        "company": data["company"],
        "company_homepage": data["company_homepage"],
        "location": data["location"],
        "workplace_type": data["workplace_type"],
        "workplace_countries": json_encode(data["workplace_countries"]),
        "seniority_level": data["seniority_level"],
        "commitment": json_encode(data["commitment"]),
        "comp_min": data["comp_min"],
        "comp_max": data["comp_max"],
        "comp_currency": data["comp_currency"],
        "technical_tools": json_encode(data["technical_tools"]),
        "requirements_summary": data["jd_summary"],
        "date_posted": data["date_posted"],
        "role_type": data["role_type"],
        "status": data["status"],
        "tier_passed": data["tier_passed"],
        "score": data["score"],
        "score_reasons": json_encode(data["score_reasons"]),
        "score_gaps": json_encode(data["score_gaps"]),
        "score_modifiers": json_encode(data["score_modifiers"]),
        "jd_full": jd_text,
        "jd_fetch_status": "fetched",
        "discovered_at": now,
        "discovered_query": data["discovered_query"],
        "updated_at": now,
        "is_pinned": False,
        "reject_reason": data.get("reject_reason"),
        "detail_url": data["detail_url"],
        "content_hash": content_hash(jd_text),
        "title_norm": normalize_title(data["title"]),
        "company_norm": normalize_company(data["company"]),
        "comp_source": data["comp_source"],
        "ai_policy": data["ai_policy"],
        "research_adjusted_score": data.get("research_adjusted_score"),
        "research_delta": data.get("research_delta", 0.0),
        "research_breakdown": json_encode(data.get("research_breakdown", [])),
        "net_score": data.get("net_score"),
    }

    columns = ", ".join(row.keys())
    placeholders = ", ".join([f"?" for _ in row])
    conn.execute(
        f"INSERT INTO jobs ({columns}) VALUES ({placeholders})",
        tuple(row.values()),
    )


def _insert_dossier(conn: sqlite3.Connection, data: dict[str, Any]) -> None:
    """Insert a company_research row for a job."""
    if data.get("status") == "rejected" and "overall_confidence" not in data:
        return

    now = "2026-06-28T12:00:00+00:00"
    row = {
        "triggered_by_job_id": data["id"],
        "company_name": data["company"],
        "company_homepage": data["company_homepage"],
        "wikipedia_data": None,
        "funding_data": json_encode(data["funding_data"]) if data.get("funding_data") else None,
        "sentiment_data": json_encode(data["sentiment_data"]) if data.get("sentiment_data") else None,
        "fit_data": json_encode(data["fit_data"]) if data.get("fit_data") else None,
        "overall_confidence": data.get("overall_confidence", 0.0),
        "summary": data.get("summary", ""),
        "verdict_flags": json_encode(data["verdict_flags"]),
        "gaps": json_encode(data["gaps"]),
        "sources_used": json_encode(data["sources_used"]),
        "errors": json_encode([]),
        "researched_at": now,
        "created_at": now,
        "retrieval_sources": json_encode(data["retrieval_sources"]),
        "retrieval_snippets_data": json_encode(data["retrieval_snippets"]),
        "company_norm": normalize_company(data["company"]),
        "verification_state": data["verification_state"],
    }

    columns = ", ".join(row.keys())
    placeholders = ", ".join([f"?" for _ in row])
    conn.execute(
        f"INSERT INTO company_research ({columns}) VALUES ({placeholders})",
        tuple(row.values()),
    )


def _insert_resume(conn: sqlite3.Connection, data: dict[str, Any]) -> None:
    """Insert a resume row for a job."""
    now = "2026-06-28T12:00:00+00:00"
    row = {
        "job_id": data["job_id"],
        "task": data["task"],
        "provider": data["provider"],
        "model": data["model"],
        "resume_text": data["resume_text"],
        "master_resume_path": data["master_resume_path"],
        "validation_passed": data["validation_passed"],
        "validation_violations": json_encode(data["validation_violations"]),
        "validation_checked_at": now,
        "input_tokens": data["input_tokens"],
        "output_tokens": data["output_tokens"],
        "latency_ms": data["latency_ms"],
        "generated_at": data["generated_at"],
        "updated_at": now,
        "markdown_path": data.get("markdown_path"),
        "pdf_path": data.get("pdf_path"),
        "docx_path": data.get("docx_path"),
    }

    columns = ", ".join(row.keys())
    placeholders = ", ".join([f"?" for _ in row])
    conn.execute(
        f"INSERT INTO resumes ({columns}) VALUES ({placeholders})",
        tuple(row.values()),
    )


def seed_demo_db(db_path: str | Path = DEFAULT_DB_PATH) -> tuple[int, int, int]:
    """Seed the demo DB from fixtures. Returns (job_count, dossier_count, resume_count)."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Delete existing DB so we start fresh
    if db_path.exists():
        db_path.unlink()

    run_migrations(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    all_fixtures = sorted(FIXTURES_DIR.glob("*.json"))
    if not all_fixtures:
        raise RuntimeError(f"No fixtures found in {FIXTURES_DIR}")

    job_fixtures = [p for p in all_fixtures if not p.name.startswith("resume_")]
    resume_fixtures = [p for p in all_fixtures if p.name.startswith("resume_")]

    job_count = 0
    dossier_count = 0

    for fixture in job_fixtures:
        data = json.loads(fixture.read_text(encoding="utf-8"))
        _validate_job_fixture(data, fixture.name)
        _insert_job(conn, data)
        job_count += 1
        _insert_dossier(conn, data)
        dossier_count += 1

    resume_count = 0
    for fixture in resume_fixtures:
        data = json.loads(fixture.read_text(encoding="utf-8"))
        _validate_resume_fixture(data, fixture.name)
        _insert_resume(conn, data)
        resume_count += 1

    conn.commit()
    conn.close()
    return job_count, dossier_count, resume_count


if __name__ == "__main__":
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB_PATH
    jobs, dossiers, resumes = seed_demo_db(db_path)
    print(f"Seeded {jobs} jobs, {dossiers} dossiers, and {resumes} resumes into {db_path}")
