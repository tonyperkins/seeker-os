"""Tests for manual events (notes, calls, emails, meetings) — the global
events API, the manual/append-only mutation boundary, and the global feed."""

import pytest
from fastapi.testclient import TestClient

from seeker_os.api.app import app
from seeker_os.database import get_connection, run_migrations
from seeker_os.events import MANUAL_EVENT_TYPES, EventType

_MARKER = "[manual-events-test]"

_LONG_JD = (
    "We are looking for a Senior Site Reliability Engineer to join our platform team. "
    "You will be responsible for designing, building, and operating the infrastructure "
    "that powers our distributed systems. This includes Kubernetes cluster management, "
    "Terraform infrastructure as code, CI/CD pipeline development, observability with "
    "Prometheus and Grafana, and incident response. The ideal candidate has 5+ years "
    "of experience with cloud platforms (AWS or GCP), strong programming skills in "
    "Python or Go, and deep knowledge of distributed systems."
) * 3


@pytest.fixture(scope="module")
def client():
    run_migrations()
    return TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def cleanup_after():
    yield
    db = get_connection()
    try:
        rows = db.execute(
            "SELECT id FROM jobs WHERE company LIKE 'ManualEvtTestCo%'"
        ).fetchall()
        if rows:
            id_csv = ",".join(str(r["id"]) for r in rows)
            for table in ["application_events", "dedup_registry", "resumes", "job_analyses"]:
                db.execute(f"DELETE FROM {table} WHERE job_id IN ({id_csv})")
            db.execute(f"DELETE FROM jobs WHERE id IN ({id_csv})")
        db.execute("DELETE FROM application_events WHERE note LIKE ?", (f"%{_MARKER}%",))
        db.commit()
    finally:
        db.close()


def _create_job(client, suffix=""):
    r = client.post("/api/jobs", json={
        "url": f"https://example.com/jobs/manual-evt-test-{suffix}",
        "title": "Senior SRE",
        "company": f"ManualEvtTestCo{suffix}",
        "location": "Remote, US",
        "workplace_type": "Remote",
        "jd_text": f"Manual event test {suffix}\n\n{_LONG_JD}",
    })
    assert r.status_code == 200
    return r.json()["job"]["id"]


class TestGlobalEventCreate:
    def test_create_global_note(self, client):
        r = client.post("/api/events", json={
            "event_type": "note", "note": f"general note {_MARKER}",
        })
        assert r.status_code == 200
        body = r.json()
        assert body["job_id"] is None
        assert body["event_type"] == "note"
        assert body["actor"] == "candidate"
        assert body["job_title"] is None

    def test_create_job_scoped_call(self, client):
        job_id = _create_job(client, "call")
        r = client.post("/api/events", json={
            "event_type": "call", "job_id": job_id,
            "note": f"recruiter call {_MARKER}",
        })
        assert r.status_code == 200
        assert r.json()["job_id"] == job_id
        assert r.json()["job_company"] == "ManualEvtTestCocall"

        # Appears in the job's own timeline too
        r2 = client.get(f"/api/jobs/{job_id}/events")
        assert any(e["event_type"] == "call" for e in r2.json())

    def test_lifecycle_type_rejected(self, client):
        r = client.post("/api/events", json={
            "event_type": "applied", "note": f"nope {_MARKER}",
        })
        assert r.status_code == 422

    def test_unknown_job_404(self, client):
        r = client.post("/api/events", json={
            "event_type": "note", "job_id": 99999999, "note": f"x {_MARKER}",
        })
        assert r.status_code == 404

    def test_manual_event_does_not_change_status(self, client):
        job_id = _create_job(client, "status")
        before = client.get(f"/api/jobs/{job_id}").json()["status"]
        client.post("/api/events", json={
            "event_type": "meeting", "job_id": job_id, "note": f"m {_MARKER}",
        })
        after = client.get(f"/api/jobs/{job_id}").json()["status"]
        assert before == after


class TestMutationBoundary:
    def test_edit_manual_event(self, client):
        r = client.post("/api/events", json={
            "event_type": "note", "note": f"before edit {_MARKER}",
        })
        eid = r.json()["id"]
        r2 = client.patch(f"/api/events/{eid}", json={"note": f"after edit {_MARKER}"})
        assert r2.status_code == 200
        assert r2.json()["note"] == f"after edit {_MARKER}"

    def test_edit_to_lifecycle_type_rejected(self, client):
        r = client.post("/api/events", json={
            "event_type": "note", "note": f"type change {_MARKER}",
        })
        eid = r.json()["id"]
        r2 = client.patch(f"/api/events/{eid}", json={"event_type": "applied"})
        assert r2.status_code == 422
        # Changing to another manual type is fine
        r3 = client.patch(f"/api/events/{eid}", json={"event_type": "call"})
        assert r3.status_code == 200
        assert r3.json()["event_type"] == "call"

    def test_delete_manual_event(self, client):
        r = client.post("/api/events", json={
            "event_type": "email_sent", "note": f"to delete {_MARKER}",
        })
        eid = r.json()["id"]
        assert client.delete(f"/api/events/{eid}").status_code == 200
        assert client.delete(f"/api/events/{eid}").status_code == 404

    def test_system_event_immutable(self, client):
        """Lifecycle events (e.g. manual_created from job creation) reject edit/delete."""
        job_id = _create_job(client, "immutable")
        events = client.get(f"/api/jobs/{job_id}/events").json()
        system_event = next(
            e for e in events if e["event_type"] not in MANUAL_EVENT_TYPES
        )
        eid = system_event["id"]
        assert client.patch(f"/api/events/{eid}", json={"note": "hack"}).status_code == 403
        assert client.delete(f"/api/events/{eid}").status_code == 403


class TestGlobalFeed:
    def test_scope_global_excludes_job_events(self, client):
        job_id = _create_job(client, "feed")
        client.post("/api/events", json={
            "event_type": "note", "job_id": job_id, "note": f"job-scoped {_MARKER}",
        })
        client.post("/api/events", json={
            "event_type": "note", "note": f"global-scoped {_MARKER}",
        })
        r = client.get("/api/events", params={"scope": "global", "limit": 500})
        assert r.status_code == 200
        assert all(e["job_id"] is None for e in r.json())

    def test_type_filter(self, client):
        client.post("/api/events", json={
            "event_type": "interview", "note": f"screen {_MARKER}",
        })
        r = client.get("/api/events", params={"event_type": "interview", "limit": 500})
        assert r.status_code == 200
        assert all(e["event_type"] == "interview" for e in r.json())

    def test_manual_only_filter(self, client):
        r = client.get("/api/events", params={"manual_only": "true", "limit": 500})
        assert r.status_code == 200
        assert all(e["event_type"] in MANUAL_EVENT_TYPES for e in r.json())


class TestVocabulary:
    def test_manual_types_are_known_event_types(self):
        assert MANUAL_EVENT_TYPES <= EventType._ALL

    def test_interview_is_manual(self):
        assert EventType.INTERVIEW in MANUAL_EVENT_TYPES
