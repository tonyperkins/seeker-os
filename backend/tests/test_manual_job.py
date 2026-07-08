"""Tests for manual job entry, dedup handling, filter bypass, and override audit trail."""

import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import seeker_os.database as dbmod
from seeker_os.api.app import app
from seeker_os.database import run_migrations, get_connection


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """Create a test client with DB isolated to a temp path."""
    db_path = tmp_path_factory.mktemp("db") / "test.db"
    run_migrations(db_path)

    _orig_db_path = dbmod._db_path
    _orig_get_connection = dbmod.get_connection
    dbmod._db_path = lambda: db_path

    def _temp_get_connection(_db_path=None):
        return _orig_get_connection(db_path)

    dbmod.get_connection = _temp_get_connection
    yield TestClient(app)
    dbmod._db_path = _orig_db_path
    dbmod.get_connection = _orig_get_connection


# Long JD text that passes the evidence gate (>500 chars)
_LONG_JD = (
    "We are looking for a Senior Site Reliability Engineer to join our platform team. "
    "You will be responsible for designing, building, and operating the infrastructure "
    "that powers our distributed systems. This includes Kubernetes cluster management, "
    "Terraform infrastructure as code, CI/CD pipeline development, observability with "
    "Prometheus and Grafana, and incident response. The ideal candidate has 5+ years "
    "of experience with cloud platforms (AWS or GCP), strong programming skills in "
    "Python or Go, and deep knowledge of distributed systems. You will work closely "
    "with engineering teams to ensure reliability, scalability, and performance of "
    "our services. This is a fully remote position open to candidates in the United "
    "States. We offer competitive compensation, equity, and comprehensive benefits."
) * 3  # ~1800 chars — well above the 500 char evidence gate


class TestManualJobCreate:
    """POST /api/jobs — manual job creation with paste-JD path."""

    def test_create_with_pasted_jd(self, client):
        """Paste-JD path: provide url + jd_text, job is created and scored."""
        unique_jd = "First test ZZZ000\n\n" + _LONG_JD
        r = client.post("/api/jobs", json={
            "url": "https://example.com/jobs/sre-test-1",
            "title": "Senior SRE",
            "company": "TestCo",
            "location": "Remote, US",
            "workplace_type": "Remote",
            "jd_text": unique_jd,
        })
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "created"
        assert data["job"] is not None
        assert data["job"]["source_id"] == "manual"
        assert data["job"]["discovered_query"] == "manual"
        assert data["job"]["status"] == "ready"
        assert data["job"]["tier_passed"] == 4
        assert data["job"]["jd_fetch_status"] == "fetched"
        assert data["job"]["score"] is not None
        assert data["job"]["jd_full"] == unique_jd.strip()

    def test_create_jd_only_no_url(self, client):
        """JD-only path: provide jd_text with no url, job is created with synthetic URL."""
        unique_jd = "JD only test QQQ111\n\n" + _LONG_JD
        r = client.post("/api/jobs", json={
            "title": "Staff Engineer",
            "company": "JDOnlyCo",
            "location": "Remote, US",
            "workplace_type": "Remote",
            "jd_text": unique_jd,
        })
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "created"
        assert data["job"] is not None
        assert data["job"]["source_id"] == "manual"
        assert data["job"]["status"] == "ready"
        assert data["job"]["score"] is not None
        assert data["job"]["jd_full"] == unique_jd.strip()
        # Synthetic URL should be a manual:// scheme
        assert data["job"]["apply_url"].startswith("manual://jd-paste/")

    def test_create_jd_only_dedup(self, client):
        """Same JD text pasted twice with no URL → second request returns already_exists."""
        unique_jd = "Dedup JD only RRR222\n\n" + _LONG_JD
        r1 = client.post("/api/jobs", json={
            "title": "Backend Engineer",
            "company": "DedupJDOnlyCo",
            "jd_text": unique_jd,
        })
        assert r1.status_code == 200
        assert r1.json()["status"] == "created"
        job_id = r1.json()["job"]["id"]

        # Same JD, no URL again → should hit url_hash dedup
        r2 = client.post("/api/jobs", json={
            "title": "Different Title",
            "company": "DifferentCo",
            "jd_text": unique_jd,
        })
        assert r2.status_code == 200
        data = r2.json()
        assert data["status"] == "already_exists"
        assert data["existing_job_id"] == job_id

    def test_create_neither_url_nor_jd(self, client):
        """Neither url nor jd_text → validation error (422)."""
        r = client.post("/api/jobs", json={
            "title": "No URL or JD",
            "company": "FailCo",
        })
        assert r.status_code == 422

    def test_create_with_recruiter_info(self, client):
        """Recruiter contact info is stored in recruiters + recruiter_job_contacts and returned on the job detail."""
        unique_jd = "Recruiter test FOO333\n\n" + _LONG_JD
        r = client.post("/api/jobs", json={
            "url": "https://example.com/jobs/recruiter-test-1",
            "title": "Platform Engineer",
            "company": "RecruiterCo",
            "jd_text": unique_jd,
            "recruiter_name": "Jane Smith",
            "recruiter_email": "jane@recruiterco.com",
            "recruiter_phone": "+1 555-123-4567",
            "recruiter_linkedin": "linkedin.com/in/janesmith",
            "recruiter_agency": "CyberCoders",
            "recruiter_source": "LinkedIn",
            "recruiter_contacted_at": "2025-01-15T10:00:00Z",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "created"
        job = data["job"]
        assert len(job["recruiter_contacts"]) == 1
        rc = job["recruiter_contacts"][0]
        assert rc["recruiter_id"] is not None
        assert rc["name"] == "Jane Smith"
        assert rc["email"] == "jane@recruiterco.com"
        assert rc["phone"] == "+1 555-123-4567"
        assert rc["linkedin"] == "linkedin.com/in/janesmith"
        assert rc["agency"] == "CyberCoders"
        assert rc["source"] == "LinkedIn"
        assert rc["contacted_at"] == "2025-01-15T10:00:00Z"

        # Verify recruiter_contact event was logged in timeline
        events = job["events"]
        rc_events = [e for e in events if e["event_type"] == "recruiter_contact"]
        assert len(rc_events) == 1
        assert rc_events[0]["metadata"]["name"] == "Jane Smith"
        assert rc_events[0]["metadata"]["source"] == "LinkedIn"

    def test_recruiter_crud_endpoints(self, client):
        """Recruiter contacts can be added, updated, and deleted via CRUD endpoints."""
        unique_jd = "Recruiter CRUD test BAZ555\n\n" + _LONG_JD
        r = client.post("/api/jobs", json={
            "url": "https://example.com/jobs/recruiter-crud-1",
            "title": "DevOps Engineer",
            "company": "CrudCo",
            "jd_text": unique_jd,
        })
        assert r.status_code == 200
        job_id = r.json()["job"]["id"]

        # Add a recruiter via POST endpoint (inline fields → creates new recruiter)
        r2 = client.post(f"/api/jobs/{job_id}/recruiters", json={
            "name": "John Doe",
            "email": "john@crudco.com",
            "source": "email",
            "agency": "Robert Half",
            "contacted_at": "2025-06-01T09:00:00Z",
        })
        assert r2.status_code == 200
        rc = r2.json()
        assert rc["name"] == "John Doe"
        assert rc["email"] == "john@crudco.com"
        assert rc["source"] == "email"
        assert rc["agency"] == "Robert Half"
        assert rc["contacted_at"] == "2025-06-01T09:00:00Z"
        association_id = rc["id"]
        recruiter_entity_id = rc["recruiter_id"]

        # Verify it appears in job detail
        r3 = client.get(f"/api/jobs/{job_id}")
        assert r3.status_code == 200
        job = r3.json()
        assert len(job["recruiter_contacts"]) == 1
        assert job["recruiter_contacts"][0]["id"] == association_id

        # Update the recruiter ENTITY via PATCH /recruiters/{id}
        r4 = client.patch(f"/api/jobs/recruiters/{recruiter_entity_id}", json={
            "phone": "+1 555-999-8888",
        })
        assert r4.status_code == 200
        assert r4.json()["phone"] == "+1 555-999-8888"
        assert r4.json()["name"] == "John Doe"  # unchanged

        # Update the ASSOCIATION via PATCH /recruiters/association/{id}
        r5 = client.patch(f"/api/jobs/recruiters/association/{association_id}", json={
            "source": "LinkedIn",
            "notes": "Followed up on Monday",
        })
        assert r5.status_code == 200
        assert r5.json()["source"] == "LinkedIn"
        assert r5.json()["notes"] == "Followed up on Monday"
        # contacted_at must NOT change on association update
        assert r5.json()["contacted_at"] == "2025-06-01T09:00:00Z"

        # Delete the association via DELETE /recruiters/association/{id}
        r6 = client.delete(f"/api/jobs/recruiters/association/{association_id}")
        assert r6.status_code == 200

        # Verify it's gone from job detail
        r7 = client.get(f"/api/jobs/{job_id}")
        assert r7.status_code == 200
        assert len(r7.json()["recruiter_contacts"]) == 0

    def test_list_jobs_recruiter_filter(self, client):
        """list_jobs has_recruiter and recruiter_source filters work."""
        unique_jd = "Recruiter filter test QQQ777\n\n" + _LONG_JD
        # Create a job WITH recruiter
        client.post("/api/jobs", json={
            "url": "https://example.com/jobs/recruiter-filter-1",
            "title": "Filter Engineer",
            "company": "FilterCo",
            "jd_text": unique_jd,
            "recruiter_name": "Jane Smith",
            "recruiter_source": "LinkedIn",
        })
        # Create a job WITHOUT recruiter
        unique_jd2 = "No recruiter filter test RRR888\n\n" + _LONG_JD
        client.post("/api/jobs", json={
            "url": "https://example.com/jobs/recruiter-filter-2",
            "title": "No Recruiter Engineer",
            "company": "NoRecruitCo",
            "jd_text": unique_jd2,
        })

        # Filter has_recruiter=true
        r = client.get("/api/jobs?has_recruiter=true&limit=100")
        assert r.status_code == 200
        jobs = r.json()["jobs"]
        recruiter_jobs = [j for j in jobs if j["has_recruiter"]]
        assert len(recruiter_jobs) >= 1
        assert all(j["has_recruiter"] for j in jobs if j["company"] == "FilterCo")

        # Filter has_recruiter=false
        r2 = client.get("/api/jobs?has_recruiter=false&limit=100")
        assert r2.status_code == 200
        jobs2 = r2.json()["jobs"]
        assert all(not j["has_recruiter"] for j in jobs2)

        # Filter by recruiter_source=LinkedIn
        r3 = client.get("/api/jobs?recruiter_source=LinkedIn&limit=100")
        assert r3.status_code == 200
        jobs3 = r3.json()["jobs"]
        assert all(j["has_recruiter"] for j in jobs3)
        assert all(j["recruiter_source"] == "LinkedIn" for j in jobs3)

    def test_recruiter_upsert_same_pair(self, client):
        """POST same (recruiter_id, job_id) twice → one row, source/notes updated, contacted_at unchanged."""
        unique_jd = "Upsert test UUU111\n\n" + _LONG_JD
        # Create a job
        r = client.post("/api/jobs", json={
            "url": "https://example.com/jobs/upsert-test-1",
            "title": "Upsert Engineer",
            "company": "UpsertCo",
            "jd_text": unique_jd,
        })
        assert r.status_code == 200
        job_id = r.json()["job"]["id"]

        # First add — creates new recruiter + association
        r1 = client.post(f"/api/jobs/{job_id}/recruiters", json={
            "name": "Alice Lee",
            "email": "alice@upsertco.com",
            "source": "email",
            "contacted_at": "2025-03-01T10:00:00Z",
            "notes": "Initial contact",
        })
        assert r1.status_code == 200
        rc1 = r1.json()
        association_id = rc1["id"]
        recruiter_id = rc1["recruiter_id"]
        assert rc1["contacted_at"] == "2025-03-01T10:00:00Z"
        assert rc1["source"] == "email"
        assert rc1["notes"] == "Initial contact"

        # Second add — same recruiter_id, same job_id → upsert, NOT a new row
        r2 = client.post(f"/api/jobs/{job_id}/recruiters", json={
            "recruiter_id": recruiter_id,
            "source": "LinkedIn",
            "notes": "Updated notes",
        })
        assert r2.status_code == 200
        rc2 = r2.json()
        # Same association_id (no new row)
        assert rc2["id"] == association_id
        # source and notes updated
        assert rc2["source"] == "LinkedIn"
        assert rc2["notes"] == "Updated notes"
        # contacted_at must NOT be overwritten
        assert rc2["contacted_at"] == "2025-03-01T10:00:00Z"

        # Verify only one association in job detail
        r3 = client.get(f"/api/jobs/{job_id}")
        assert len(r3.json()["recruiter_contacts"]) == 1

        # Verify recruiter_contact event count did NOT increase on upsert
        events = r3.json()["events"]
        rc_events = [e for e in events if e["event_type"] == "recruiter_contact"]
        assert len(rc_events) == 1, "Second POST (upsert) must not create a duplicate event"

    def test_recruiter_contacted_at_write_once(self, client):
        """PATCH association does NOT change contacted_at."""
        unique_jd = "Write-once test WWW222\n\n" + _LONG_JD
        r = client.post("/api/jobs", json={
            "url": "https://example.com/jobs/write-once-1",
            "title": "Write Once Engineer",
            "company": "WriteOnceCo",
            "jd_text": unique_jd,
        })
        assert r.status_code == 200
        job_id = r.json()["job"]["id"]

        # Add recruiter with contacted_at
        r1 = client.post(f"/api/jobs/{job_id}/recruiters", json={
            "name": "Bob Chen",
            "email": "bob@writeonceco.com",
            "source": "email",
            "contacted_at": "2025-04-01T08:00:00Z",
        })
        assert r1.status_code == 200
        association_id = r1.json()["id"]
        original_contacted_at = r1.json()["contacted_at"]
        assert original_contacted_at == "2025-04-01T08:00:00Z"

        # Patch association — source and notes only
        r2 = client.patch(f"/api/jobs/recruiters/association/{association_id}", json={
            "source": "LinkedIn",
            "notes": "Changed source",
        })
        assert r2.status_code == 200
        assert r2.json()["contacted_at"] == original_contacted_at

    def test_recruiter_link_existing_vs_create_new(self, client):
        """POST with recruiter_id links existing; POST with inline fields creates new."""
        unique_jd1 = "Link test LLL333\n\n" + _LONG_JD
        unique_jd2 = "Link test LLL444\n\n" + _LONG_JD

        # Job 1 — create with inline recruiter
        r1 = client.post("/api/jobs", json={
            "url": "https://example.com/jobs/link-test-1",
            "title": "Link Engineer 1",
            "company": "LinkCo",
            "jd_text": unique_jd1,
        })
        job1_id = r1.json()["job"]["id"]

        r1a = client.post(f"/api/jobs/{job1_id}/recruiters", json={
            "name": "Carol King",
            "email": "carol@linkco.com",
            "agency": "Hired.com",
            "source": "email",
            "contacted_at": "2025-05-01T10:00:00Z",
        })
        assert r1a.status_code == 200
        recruiter_id = r1a.json()["recruiter_id"]

        # Job 2 — link the SAME recruiter by recruiter_id
        r2 = client.post("/api/jobs", json={
            "url": "https://example.com/jobs/link-test-2",
            "title": "Link Engineer 2",
            "company": "LinkCo",
            "jd_text": unique_jd2,
        })
        job2_id = r2.json()["job"]["id"]

        r2a = client.post(f"/api/jobs/{job2_id}/recruiters", json={
            "recruiter_id": recruiter_id,
            "source": "LinkedIn",
            "contacted_at": "2025-05-15T14:00:00Z",
        })
        assert r2a.status_code == 200
        rc2 = r2a.json()
        assert rc2["recruiter_id"] == recruiter_id
        assert rc2["name"] == "Carol King"  # entity fields from existing recruiter
        assert rc2["email"] == "carol@linkco.com"
        assert rc2["agency"] == "Hired.com"
        assert rc2["source"] == "LinkedIn"  # association-specific
        assert rc2["contacted_at"] == "2025-05-15T14:00:00Z"  # association-specific

        # Verify both jobs show the recruiter
        r3 = client.get(f"/api/jobs/{job1_id}")
        r4 = client.get(f"/api/jobs/{job2_id}")
        assert len(r3.json()["recruiter_contacts"]) == 1
        assert len(r4.json()["recruiter_contacts"]) == 1
        assert r3.json()["recruiter_contacts"][0]["recruiter_id"] == recruiter_id
        assert r4.json()["recruiter_contacts"][0]["recruiter_id"] == recruiter_id

    def test_recruiter_search(self, client):
        """GET /api/recruiters/search returns matches by email and by name."""
        unique_jd = "Search test SSS555\n\n" + _LONG_JD
        r = client.post("/api/jobs", json={
            "url": "https://example.com/jobs/search-test-1",
            "title": "Search Engineer",
            "company": "SearchCo",
            "jd_text": unique_jd,
        })
        job_id = r.json()["job"]["id"]

        client.post(f"/api/jobs/{job_id}/recruiters", json={
            "name": "Dave Wilson",
            "email": "dave@searchco.com",
            "agency": "CyberCoders",
        })

        # Search by name
        r1 = client.get("/api/jobs/recruiters/search?q=Dave")
        assert r1.status_code == 200
        results = r1.json()
        assert len(results) >= 1
        assert any(r["name"] == "Dave Wilson" for r in results)

        # Search by email
        r2 = client.get("/api/jobs/recruiters/search?q=dave@searchco")
        assert r2.status_code == 200
        results2 = r2.json()
        assert len(results2) >= 1
        assert any(r["email"] == "dave@searchco.com" for r in results2)

        # Empty query returns empty
        r3 = client.get("/api/jobs/recruiters/search?q=")
        assert r3.status_code == 200
        assert r3.json() == []

    def test_recruiter_search_route_not_captured_as_job_id(self, client):
        """Route ordering: GET /api/jobs/recruiters/search must return 200,
        not 422 from being captured by GET /{job_id} with 'recruiters' failing int parse."""
        r = client.get("/api/jobs/recruiters/search?q=foo")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_recruiter_cascade_delete(self, client):
        """Deleting a job cascades its recruiter associations; deleting a recruiter entity cascades its associations."""
        unique_jd = "Cascade test CCC666\n\n" + _LONG_JD
        r = client.post("/api/jobs", json={
            "url": "https://example.com/jobs/cascade-test-1",
            "title": "Cascade Engineer",
            "company": "CascadeCo",
            "jd_text": unique_jd,
        })
        job_id = r.json()["job"]["id"]

        # Add a recruiter
        r1 = client.post(f"/api/jobs/{job_id}/recruiters", json={
            "name": "Eve Adams",
            "email": "eve@cascadeco.com",
            "source": "email",
        })
        assert r1.status_code == 200
        recruiter_id = r1.json()["recruiter_id"]
        association_id = r1.json()["id"]

        # Delete the job — association should cascade
        r2 = client.delete(f"/api/jobs/{job_id}")
        assert r2.status_code == 200

        # Verify association is gone (query DB directly)
        import sqlite3
        conn = sqlite3.connect(str(dbmod._db_path()))
        conn.row_factory = sqlite3.Row
        assoc = conn.execute(
            "SELECT id FROM recruiter_job_contacts WHERE id = ?", (association_id,)
        ).fetchone()
        assert assoc is None, "Association should be cascade-deleted with job"
        # Recruiter entity should still exist
        recruiter = conn.execute(
            "SELECT id FROM recruiters WHERE id = ?", (recruiter_id,)
        ).fetchone()
        assert recruiter is not None, "Recruiter entity should survive job deletion"
        conn.close()

        # Now delete the recruiter entity directly — should cascade any remaining associations
        conn = sqlite3.connect(str(dbmod._db_path()))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("DELETE FROM recruiters WHERE id = ?", (recruiter_id,))
        conn.commit()
        # Verify recruiter is gone
        recruiter = conn.execute(
            "SELECT id FROM recruiters WHERE id = ?", (recruiter_id,)
        ).fetchone()
        assert recruiter is None, "Recruiter entity should be deleted"
        conn.close()

    def test_create_dedup_url_hash(self, client):
        """Same URL twice → second request returns already_exists."""
        url = "https://example.com/jobs/dedup-test-1"
        unique_jd = "Unique dedup test ABC123-XYZ789\n\n" + _LONG_JD
        # First create
        r1 = client.post("/api/jobs", json={
            "url": url,
            "title": "DevOps Engineer",
            "company": "DedupCo",
            "location": "Remote, US",
            "jd_text": unique_jd,
        })
        assert r1.status_code == 200
        assert r1.json()["status"] == "created"
        job_id = r1.json()["job"]["id"]

        # Second attempt with same URL
        r2 = client.post("/api/jobs", json={
            "url": url,
            "title": "Different Title",
            "company": "DifferentCo",
            "jd_text": "Different content DEF456\n\n" + _LONG_JD,
        })
        assert r2.status_code == 200
        data = r2.json()
        assert data["status"] == "already_exists"
        assert data["existing_job_id"] == job_id
        assert data["job"] is None  # no job created

    def test_create_fetch_failed_no_insert(self, client):
        """When JD fetch fails (no jd_text), no job is inserted."""
        r = client.post("/api/jobs", json={
            "url": "https://nonexistent.invalid/jobs/no-such-page",
            "title": "Test Job",
            "company": "FetchFailCo",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "fetch_failed"
        assert data["job"] is None
        assert data["fetch_error"] is not None

        # Verify no job was inserted
        db = get_connection()
        try:
            row = db.execute(
                "SELECT id FROM jobs WHERE company = 'FetchFailCo'"
            ).fetchone()
            assert row is None, "No job should be inserted on fetch failure"
        finally:
            db.close()

    def test_manual_job_bypasses_filters(self, client):
        """Manual job that would fail hard filters still lands in 'ready' with warnings."""
        # This job has no remote/workplace_type — would fail remote_only filter
        r = client.post("/api/jobs", json={
            "url": "https://example.com/jobs/filter-bypass-test",
            "title": "On-site Engineer",
            "company": "OnSiteCo",
            "location": "New York, NY",
            "workplace_type": "On-Site",
            "jd_text": "Filter bypass GHI789\n\n" + _LONG_JD,
        })
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "created"
        assert data["job"]["status"] == "ready"  # NOT rejected
        # Filter warnings should be recorded
        assert len(data["filter_warnings"]) > 0
        assert data["job"]["filter_warnings"] == data["filter_warnings"]

    def test_manual_job_low_score_not_rejected(self, client):
        """Manual job with a low score still lands in 'ready' — user decides."""
        # Use a title/company that won't match any scoring patterns → low score
        r = client.post("/api/jobs", json={
            "url": "https://example.com/jobs/low-score-test",
            "title": "Sales Representative",
            "company": "SalesCo",
            "location": "Remote, US",
            "workplace_type": "Remote",
            "jd_text": "Low score JKL012\n\n" + _LONG_JD,
        })
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "created"
        assert data["job"]["status"] == "ready"  # NOT rejected even with low score
        assert data["job"]["score"] is not None

    def test_source_filter(self, client):
        """List jobs with source=manual filter."""
        # First create a manual job
        client.post("/api/jobs", json={
            "url": "https://example.com/jobs/source-filter-test",
            "title": "Platform Engineer",
            "company": "FilterTestCo",
            "location": "Remote, US",
            "workplace_type": "Remote",
            "jd_text": "Source filter MNO345\n\n" + _LONG_JD,
        })

        r = client.get("/api/jobs?source=manual&limit=10")
        assert r.status_code == 200
        for job in r.json():
            assert job["source_id"] == "manual" if "source_id" in job else True

    def test_content_hash_soft_dup_no_force(self, client):
        """Same JD content, different URL → possible_duplicate, NO insert."""
        shared_jd = "Soft dup content HASHTEST999\n\n" + _LONG_JD
        # First create
        r1 = client.post("/api/jobs", json={
            "url": "https://example.com/jobs/content-dup-original",
            "title": "Backend Engineer",
            "company": "ContentDupCo",
            "location": "Remote, US",
            "workplace_type": "Remote",
            "jd_text": shared_jd,
        })
        assert r1.status_code == 200
        assert r1.json()["status"] == "created"
        original_id = r1.json()["job"]["id"]

        # Second attempt: different URL, same JD content
        r2 = client.post("/api/jobs", json={
            "url": "https://example.com/jobs/content-dup-second",
            "title": "Backend Engineer",
            "company": "ContentDupCo",
            "jd_text": shared_jd,
        })
        assert r2.status_code == 200
        data = r2.json()
        assert data["status"] == "possible_duplicate"
        assert data["existing_job_id"] == original_id
        assert data["existing_summary"] is not None
        assert data["job"] is None  # no job created

        # Verify no second row was inserted
        db = get_connection()
        try:
            dup_rows = db.execute(
                "SELECT id FROM jobs WHERE company = 'ContentDupCo'"
            ).fetchall()
            assert len(dup_rows) == 1, "Should be exactly 1 row — the original"
        finally:
            db.close()

    def test_content_hash_soft_dup_with_force(self, client):
        """Same JD content, different URL, force=True → inserts as likely_duplicate."""
        shared_jd = "Force dup content HASHTEST888\n\n" + _LONG_JD
        # First create
        r1 = client.post("/api/jobs", json={
            "url": "https://example.com/jobs/force-dup-original",
            "title": "Frontend Engineer",
            "company": "ForceDupCo",
            "location": "Remote, US",
            "workplace_type": "Remote",
            "jd_text": shared_jd,
        })
        assert r1.json()["status"] == "created"
        original_id = r1.json()["job"]["id"]

        # Second attempt: force=True
        r2 = client.post("/api/jobs", json={
            "url": "https://example.com/jobs/force-dup-second",
            "title": "Frontend Engineer",
            "company": "ForceDupCo",
            "jd_text": shared_jd,
            "force": True,
        })
        assert r2.status_code == 200
        data = r2.json()
        assert data["status"] == "likely_duplicate"
        assert data["existing_job_id"] == original_id
        assert data["job"] is not None  # job WAS created
        assert data["job"]["status"] == "ready"

    def test_url_hash_dupe_not_forceable(self, client):
        """Exact url_hash dupe returns already_exists even with force=True."""
        url = "https://example.com/jobs/exact-dup-not-forceable"
        jd = "Exact dup not forceable AAA111\n\n" + _LONG_JD
        r1 = client.post("/api/jobs", json={
            "url": url,
            "title": "Engineer",
            "company": "ExactDupCo",
            "jd_text": jd,
        })
        assert r1.json()["status"] == "created"

        r2 = client.post("/api/jobs", json={
            "url": url,
            "jd_text": jd,
            "force": True,
        })
        assert r2.json()["status"] == "already_exists"
        assert r2.json()["job"] is None

    def test_paste_retry_after_fetch_fail(self, client):
        """Fetch fails → no insert; re-submit same request with jd_text → inserts."""
        url = "https://nonexistent.invalid/jobs/paste-retry-test"
        # First attempt: no jd_text, fetch will fail
        r1 = client.post("/api/jobs", json={
            "url": url,
            "title": "Paste Retry Engineer",
            "company": "PasteRetryCo",
            "location": "Remote, US",
            "workplace_type": "Remote",
        })
        assert r1.status_code == 200
        data1 = r1.json()
        assert data1["status"] == "fetch_failed"
        assert data1["job"] is None

        # Verify no row inserted
        db = get_connection()
        try:
            row = db.execute(
                "SELECT id FROM jobs WHERE company = 'PasteRetryCo'"
            ).fetchone()
            assert row is None
        finally:
            db.close()

        # Re-submit with jd_text — same URL, now with pasted JD
        r2 = client.post("/api/jobs", json={
            "url": url,
            "title": "Paste Retry Engineer",
            "company": "PasteRetryCo",
            "location": "Remote, US",
            "workplace_type": "Remote",
            "jd_text": "Paste retry content BBB222\n\n" + _LONG_JD,
        })
        assert r2.status_code == 200
        data2 = r2.json()
        assert data2["status"] == "created"
        assert data2["job"] is not None
        assert data2["job"]["status"] == "ready"
        assert data2["job"]["score"] is not None
        assert data2["job"]["company"] == "PasteRetryCo"

    def test_research_cache_reuse(self, client):
        """Manual job at a cached company uses the cached dossier (no new research call)
        and gets a research-adjusted score."""
        from seeker_os.dedup.normalize import normalize_company

        company_name = "ResearchCacheCo"
        company_norm = normalize_company(company_name)

        # Seed a cached company dossier with high enough confidence to not be a stub
        # and a funding section with a recent layoff to trigger the recent_layoffs modifier.
        funding_data = {
            "founded": 2015,
            "stage": "Series B",
            "layoffs": [{"date": datetime.now(timezone.utc).isoformat(), "pct": 10.0}],
            "financial_health": "stable",
            "confidence": 0.8,
        }
        sentiment_data = {
            "overall_rating_estimate": 3.5,
            "confidence": 0.7,
        }
        now_iso = datetime.now(timezone.utc).isoformat()

        db = get_connection()
        try:
            db.execute(
                """INSERT INTO company_research (
                    triggered_by_job_id, company_name, company_norm, funding_data, sentiment_data,
                    overall_confidence, researched_at, created_at,
                    retrieval_sources
                ) VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    company_name,
                    company_norm,
                    json.dumps(funding_data),
                    json.dumps(sentiment_data),
                    0.8,
                    now_iso,
                    now_iso,
                    json.dumps(["https://example.com/source1"]),
                ),
            )
            db.commit()
        finally:
            db.close()

        # Create a manual job at this company
        r = client.post("/api/jobs", json={
            "url": "https://example.com/jobs/research-cache-test",
            "title": "Senior SRE",
            "company": company_name,
            "location": "Remote, US",
            "workplace_type": "Remote",
            "jd_text": "Research cache test CCC333\n\n" + _LONG_JD,
        })
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "created"
        assert data["job"] is not None
        assert data["job"]["score"] is not None

        job_id = data["job"]["id"]

        # Verify research-adjusted score was computed (not None, not equal to base score)
        db = get_connection()
        try:
            row = db.execute(
                "SELECT score, research_adjusted_score, research_delta, research_breakdown FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            assert row is not None
            base_score = row["score"]
            adjusted = row["research_adjusted_score"]
            delta = row["research_delta"]
            breakdown = row["research_breakdown"]

            # The research path should have run — adjusted score should be set
            assert adjusted is not None, "research_adjusted_score should be set (cache hit)"
            assert delta is not None and delta != 0, (
                f"research_delta should be non-zero (layoff modifier should apply), got {delta}"
            )
            # The recent_layoffs modifier is -1.5, so delta should be -1.5
            assert delta == -1.5, f"Expected -1.5 (recent_layoffs), got {delta}"
            # Adjusted score should be base + delta
            assert adjusted == base_score + delta, (
                f"adjusted ({adjusted}) should be base ({base_score}) + delta ({delta})"
            )
            # Breakdown should contain the recent_layoffs factor
            breakdown_list = json.loads(breakdown) if breakdown else []
            factors = [item["factor"] for item in breakdown_list]
            assert "recent_layoffs" in factors, (
                f"breakdown should include recent_layoffs, got {factors}"
            )

            # Prove no new retrieval call was made: the _try_apply_research_adjustment
            # path is cache-hit-only (SQL lookup, no Tavily/retrieval). Verify only
            # the one row we seeded exists — no second row was inserted.
            cr_rows = db.execute(
                "SELECT id FROM company_research WHERE company_norm = ?",
                (company_norm,),
            ).fetchall()
            assert len(cr_rows) == 1, (
                f"Expected exactly 1 company_research row (the seeded cache), "
                f"got {len(cr_rows)} — a new retrieval call may have been made"
            )
        finally:
            db.close()

        # Clean up the seeded dossier
        db = get_connection()
        try:
            db.execute("DELETE FROM company_research WHERE company_name = ?", (company_name,))
            db.commit()
        finally:
            db.close()


class TestJobOverride:
    """POST /api/jobs/{id}/override — auditable override of rejected jobs."""

    def test_override_preserves_audit_trail(self, client):
        """Override records timestamp, note, and original reject reason."""
        # Create a manual job (lands in ready)
        r = client.post("/api/jobs", json={
            "url": "https://example.com/jobs/override-test",
            "title": "Senior SRE",
            "company": "OverrideCo",
            "location": "Remote, US",
            "workplace_type": "Remote",
            "jd_text": "Override test PQR678\n\n" + _LONG_JD,
        })
        job_id = r.json()["job"]["id"]

        # Reject it
        client.post(f"/api/jobs/{job_id}/reject", json={"reason": "score below threshold"})

        # Verify it's rejected
        r2 = client.get(f"/api/jobs/{job_id}")
        assert r2.json()["status"] == "rejected"
        assert r2.json()["reject_reason"] == "score below threshold"

        # Override
        r3 = client.post(f"/api/jobs/{job_id}/override", json={
            "note": "Want to apply anyway — good company",
            "target_status": "ready",
        })
        assert r3.status_code == 200

        # Verify audit trail
        r4 = client.get(f"/api/jobs/{job_id}")
        detail = r4.json()
        assert detail["status"] == "ready"
        assert detail["overridden_at"] is not None
        assert detail["override_note"] == "Want to apply anyway — good company"
        assert detail["original_reject_reason"] == "score below threshold"
        # Score is still visible (not overwritten)
        assert detail["score"] is not None

    def test_override_only_rejected(self, client):
        """Override fails on non-rejected jobs."""
        # Create a manual job (lands in ready)
        r = client.post("/api/jobs", json={
            "url": "https://example.com/jobs/override-non-rejected",
            "title": "DevOps Engineer",
            "company": "NonRejectCo",
            "location": "Remote, US",
            "workplace_type": "Remote",
            "jd_text": "Non-reject STU901\n\n" + _LONG_JD,
        })
        job_id = r.json()["job"]["id"]

        # Try to override a ready job → should fail
        r2 = client.post(f"/api/jobs/{job_id}/override", json={"note": "test"})
        assert r2.status_code == 400

    def test_override_not_found(self, client):
        """Override on nonexistent job returns 404."""
        r = client.post("/api/jobs/99999/override", json={"note": "test"})
        assert r.status_code == 404

    def test_delete_job(self, client):
        """Delete removes the job and all dependent records."""
        r = client.post("/api/jobs", json={
            "url": "https://example.com/jobs/delete-test",
            "title": "Delete Me",
            "company": "DeleteCo",
            "location": "Remote, US",
            "workplace_type": "Remote",
            "jd_text": "Delete test VWX123\n\n" + _LONG_JD,
        })
        assert r.status_code == 200
        job_id = r.json()["job"]["id"]

        # Delete it
        r2 = client.delete(f"/api/jobs/{job_id}")
        assert r2.status_code == 200

        # Confirm it's gone
        r3 = client.get(f"/api/jobs/{job_id}")
        assert r3.status_code == 404

    def test_delete_not_found(self, client):
        """Delete on nonexistent job returns 404."""
        r = client.delete("/api/jobs/99999")
        assert r.status_code == 404

    def test_cascade_delete_removes_child_rows(self, client):
        """Deleting a job cascades to child tables (application_events, resumes, etc).

        This test proves ON DELETE CASCADE fires by using a raw sqlite3 connection
        with PRAGMA foreign_keys = ON to delete the job directly — bypassing the
        manual cleanup in delete_job endpoint. If CASCADE is not configured, child
        rows would survive and the test would fail.
        """
        import sqlite3

        # Create a job
        unique_jd = "Cascade child test CASC777\n\n" + _LONG_JD
        r = client.post("/api/jobs", json={
            "url": "https://example.com/jobs/cascade-child-test",
            "title": "Cascade Child Engineer",
            "company": "CascadeChildCo",
            "jd_text": unique_jd,
        })
        assert r.status_code == 200
        job_id = r.json()["job"]["id"]

        # The manual_created event is already there. Add an application_event
        # and a resume row directly so we have child rows to verify cascade.
        db = get_connection()
        try:
            now = datetime.now(timezone.utc).isoformat()
            db.execute(
                """INSERT INTO application_events
                   (job_id, event_type, actor, occurred_at, created_at, metadata)
                   VALUES (?, 'applied', 'candidate', ?, ?, '{}')""",
                (job_id, now, now),
            )
            db.execute(
                """INSERT INTO resumes
                   (job_id, task, provider, model, resume_text, generated_at, updated_at)
                   VALUES (?, 'resume_generation_standard', 'test', 'test', 'test resume', ?, ?)""",
                (job_id, now, now),
            )
            db.execute(
                """INSERT INTO dedup_registry
                   (job_id, key_type, key_value, created_at)
                   VALUES (?, 'content_hash', 'cascade_test_hash_777', ?)""",
                (job_id, now),
            )
            db.commit()
        finally:
            db.close()

        # Verify child rows exist
        db = get_connection()
        try:
            event_count = db.execute(
                "SELECT COUNT(*) FROM application_events WHERE job_id = ?", (job_id,)
            ).fetchone()[0]
            assert event_count >= 2, f"Expected >=2 events, got {event_count}"

            resume_count = db.execute(
                "SELECT COUNT(*) FROM resumes WHERE job_id = ?", (job_id,)
            ).fetchone()[0]
            assert resume_count == 1, f"Expected 1 resume, got {resume_count}"

            dedup_count = db.execute(
                "SELECT COUNT(*) FROM dedup_registry WHERE job_id = ?", (job_id,)
            ).fetchone()[0]
            assert dedup_count >= 1, f"Expected >=1 dedup row, got {dedup_count}"
        finally:
            db.close()

        # Delete the job using a RAW connection with PRAGMA foreign_keys = ON.
        # This bypasses the manual cleanup in delete_job endpoint, proving
        # that CASCADE alone removes the child rows.
        conn = sqlite3.connect(str(dbmod._db_path()))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        conn.commit()

        # Verify child rows are gone (CASCADE fired)
        event_count = conn.execute(
            "SELECT COUNT(*) FROM application_events WHERE job_id = ?", (job_id,)
        ).fetchone()[0]
        assert event_count == 0, f"CASCADE failed: {event_count} events survived job delete"

        resume_count = conn.execute(
            "SELECT COUNT(*) FROM resumes WHERE job_id = ?", (job_id,)
        ).fetchone()[0]
        assert resume_count == 0, f"CASCADE failed: {resume_count} resumes survived job delete"

        dedup_count = conn.execute(
            "SELECT COUNT(*) FROM dedup_registry WHERE job_id = ?", (job_id,)
        ).fetchone()[0]
        assert dedup_count == 0, f"CASCADE failed: {dedup_count} dedup rows survived job delete"

        conn.close()
