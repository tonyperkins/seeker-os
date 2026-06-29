"""Tests for the resume API endpoints.

Covers list/get/update/delete, master resume info, and revalidation.
Does NOT test LLM generation (POST /api/resumes/generate) or file upload
endpoints (POST /api/resumes/master/upload, POST /api/resumes/parse) since
those require API keys / binary uploads.
"""

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from seeker_os.api.app import app
import seeker_os.database as dbmod
from seeker_os.database import run_migrations


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Test client with the SQLite DB redirected to a temp path.

    Patches _db_path and get_connection in every module that imported it
    at module level (generator, resumes) plus the database module itself
    (covers validator, which imports get_connection inside a function).
    """
    db_path = tmp_path / "test.db"
    run_migrations(db_path)

    monkeypatch.setattr(dbmod, "_db_path", lambda: db_path)

    _orig_get_connection = dbmod.get_connection

    def _temp_get_connection(_db_path=db_path):
        return _orig_get_connection(_db_path)

    monkeypatch.setattr(dbmod, "get_connection", _temp_get_connection)

    import seeker_os.resume.generator as genmod
    import seeker_os.api.resumes as resmod

    monkeypatch.setattr(genmod, "get_connection", _temp_get_connection)
    monkeypatch.setattr(resmod, "get_connection", _temp_get_connection)

    return TestClient(app)


def _insert_job(db_path: Path, title: str = "Site Reliability Engineer", company: str = "Acme Corp") -> int:
    """Insert a minimal job row and return its id."""
    conn = sqlite3.connect(str(db_path))
    cur = conn.execute(
        "INSERT INTO jobs (title, company, status) VALUES (?, ?, ?)",
        (title, company, "ready"),
    )
    job_id = cur.lastrowid
    conn.commit()
    conn.close()
    return job_id


def _insert_resume(
    db_path: Path,
    job_id: int,
    resume_text: str = "# Test Resume\n\nExperienced engineer.",
    task: str = "resume_generation_standard",
    provider: str = "test-provider",
    model: str = "test-model",
    validation_passed: bool = True,
    violations: list | None = None,
) -> int:
    """Insert a minimal resume row referencing a job and return its id."""
    conn = sqlite3.connect(str(db_path))
    cur = conn.execute(
        """INSERT INTO resumes
           (job_id, task, provider, model, resume_text, master_resume_path,
            validation_passed, validation_violations, generated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            job_id,
            task,
            provider,
            model,
            resume_text,
            "/nonexistent/master_resume.md",
            validation_passed,
            json.dumps(violations or []),
            "2025-01-01T00:00:00+00:00",
        ),
    )
    resume_id = cur.lastrowid
    conn.commit()
    conn.close()
    return resume_id


class TestListResumes:
    def test_list_resumes_empty(self, client, tmp_path):
        r = client.get("/api/resumes")
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        assert r.json() == []

    def test_list_resumes_with_data(self, client, tmp_path):
        db_path = tmp_path / "test.db"
        job_id = _insert_job(db_path)
        resume_id = _insert_resume(db_path, job_id)

        r = client.get("/api/resumes")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) == 1
        item = data[0]
        assert item["id"] == resume_id
        assert item["job_id"] == job_id
        assert item["task"] == "resume_generation_standard"
        assert item["provider"] == "test-provider"
        assert item["model"] == "test-model"
        assert item["validation_passed"] is True

    def test_list_resumes_filter_by_job(self, client, tmp_path):
        db_path = tmp_path / "test.db"
        job1 = _insert_job(db_path, title="Job A")
        job2 = _insert_job(db_path, title="Job B")
        _insert_resume(db_path, job1)
        _insert_resume(db_path, job2)

        r = client.get(f"/api/resumes?job_id={job1}")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["job_id"] == job1


class TestGetResume:
    def test_get_resume_detail(self, client, tmp_path):
        db_path = tmp_path / "test.db"
        job_id = _insert_job(db_path)
        resume_id = _insert_resume(db_path, job_id, resume_text="# Tailored Resume\n\nSkills.")

        r = client.get(f"/api/resumes/{resume_id}")
        assert r.status_code == 200
        detail = r.json()
        assert detail["id"] == resume_id
        assert detail["job_id"] == job_id
        assert detail["job_title"] == "Site Reliability Engineer"
        assert detail["job_company"] == "Acme Corp"
        assert detail["resume_text"] == "# Tailored Resume\n\nSkills."
        assert detail["task"] == "resume_generation_standard"
        assert "validation_checked_at" in detail

    def test_get_resume_not_found(self, client):
        r = client.get("/api/resumes/99999")
        assert r.status_code == 404


class TestUpdateResume:
    def test_update_resume_text(self, client, tmp_path):
        db_path = tmp_path / "test.db"
        job_id = _insert_job(db_path)
        resume_id = _insert_resume(db_path, job_id, resume_text="Before edit")

        r = client.put(f"/api/resumes/{resume_id}", json={"resume_text": "After edit"})
        assert r.status_code == 200
        assert "updated" in r.json()["message"].lower()

        # Verify the change persisted
        r2 = client.get(f"/api/resumes/{resume_id}")
        assert r2.status_code == 200
        assert r2.json()["resume_text"] == "After edit"

    def test_update_resume_not_found(self, client):
        r = client.put("/api/resumes/99999", json={"resume_text": "nope"})
        assert r.status_code == 404


class TestDeleteResume:
    def test_delete_resume(self, client, tmp_path):
        db_path = tmp_path / "test.db"
        job_id = _insert_job(db_path)
        resume_id = _insert_resume(db_path, job_id)

        r = client.delete(f"/api/resumes/{resume_id}")
        assert r.status_code == 200
        assert "deleted" in r.json()["message"].lower()

        # Verify it's gone
        r2 = client.get(f"/api/resumes/{resume_id}")
        assert r2.status_code == 404

    def test_delete_resume_not_found(self, client):
        r = client.delete("/api/resumes/99999")
        assert r.status_code == 404


class TestMasterResume:
    def test_get_master_resume_info(self, client):
        r = client.get("/api/resumes/master")
        # Either configured (200) or no resume config (404); both acceptable.
        if r.status_code == 200:
            data = r.json()
            assert "path" in data
            assert "exists" in data
            assert "format" in data
            assert isinstance(data["exists"], bool)
        else:
            assert r.status_code == 404


class TestRevalidate:
    def test_revalidate_resume(self, client, tmp_path):
        db_path = tmp_path / "test.db"
        job_id = _insert_job(db_path)
        resume_id = _insert_resume(
            db_path,
            job_id,
            resume_text="# Resume\n\n25+ years of experience.",
        )

        r = client.post(f"/api/resumes/{resume_id}/validate")
        assert r.status_code == 200
        data = r.json()
        assert "passed" in data
        assert "violations" in data
        assert "checked_at" in data
        assert isinstance(data["violations"], list)

    def test_revalidate_not_found(self, client):
        r = client.post("/api/resumes/99999/validate")
        assert r.status_code == 404
