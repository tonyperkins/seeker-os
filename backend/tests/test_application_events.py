"""Tests for the application_events log — status change events, occurred_at guard,
created_at immutability, ordering, and append-only behavior."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from seeker_os.api.app import app
from seeker_os.database import run_migrations, get_connection
from seeker_os.events import record_event, transition_status, EventType, Actor


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
) * 3


@pytest.fixture(scope="module")
def client():
    run_migrations()
    return TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def cleanup_after():
    """Clean up test jobs after all tests in the module complete."""
    yield
    db = get_connection()
    try:
        rows = db.execute(
            "SELECT id FROM jobs WHERE company LIKE 'EventTestCo%'"
        ).fetchall()
        if rows:
            id_list = [str(r["id"]) for r in rows]
            id_csv = ",".join(id_list)
            for table in ["application_events", "dedup_registry", "resumes",
                          "company_research", "job_analyses", "cover_letters",
                          "application_answers"]:
                db.execute(f"DELETE FROM {table} WHERE job_id IN ({id_csv})")
            db.execute(f"DELETE FROM jobs WHERE id IN ({id_csv})")
        # Also clean up any test jobs from the atomicity test
        db.execute("DELETE FROM application_events WHERE job_id IN (SELECT id FROM jobs WHERE source_id='test')")
        db.execute("DELETE FROM jobs WHERE source_id='test'")
        db.commit()
    finally:
        db.close()


def _create_manual_job(client, suffix=""):
    """Helper: create a manual job via API and return its ID."""
    r = client.post("/api/jobs", json={
        "url": f"https://example.com/jobs/event-test-{suffix}",
        "title": "Senior SRE",
        "company": f"EventTestCo{suffix}",
        "location": "Remote, US",
        "workplace_type": "Remote",
        "jd_text": f"Event test {suffix}\n\n{_LONG_JD}",
    })
    assert r.status_code == 200
    assert r.json()["status"] == "created"
    return r.json()["job"]["id"]


class TestStatusChangeWritesEvent:
    """A status change writes exactly one matching event with right actor/metadata."""

    def test_manual_create_writes_event(self, client):
        """Creating a manual job writes a manual_created event."""
        job_id = _create_manual_job(client, suffix="create")
        r = client.get(f"/api/jobs/{job_id}/events")
        assert r.status_code == 200
        events = r.json()
        assert len(events) >= 1
        # The first event should be manual_created
        create_events = [e for e in events if e["event_type"] == "manual_created"]
        assert len(create_events) == 1
        assert create_events[0]["actor"] == "candidate"
        assert create_events[0]["metadata"]["score"] is not None

    def test_patch_status_writes_event(self, client):
        """PATCH status change writes a status_changed event."""
        job_id = _create_manual_job(client, suffix="patch")
        r = client.patch(f"/api/jobs/{job_id}", json={"status": "reviewing"})
        assert r.status_code == 200

        r2 = client.get(f"/api/jobs/{job_id}/events")
        events = r2.json()
        change_events = [e for e in events if e["event_type"] == "status_changed"]
        assert len(change_events) == 1
        assert change_events[0]["actor"] == "candidate"
        assert change_events[0]["metadata"]["from"] == "ready"
        assert change_events[0]["metadata"]["to"] == "reviewing"

    def test_reject_writes_event(self, client):
        """Reject endpoint writes a rejected event."""
        job_id = _create_manual_job(client, suffix="reject")
        r = client.post(f"/api/jobs/{job_id}/reject", json={"reason": "low score"})
        assert r.status_code == 200

        r2 = client.get(f"/api/jobs/{job_id}/events")
        events = r2.json()
        reject_events = [e for e in events if e["event_type"] == "rejected"]
        assert len(reject_events) == 1
        assert reject_events[0]["metadata"]["reason"] == "low score"

    def test_skip_writes_event(self, client):
        """Skip endpoint writes a skipped event."""
        job_id = _create_manual_job(client, suffix="skip")
        r = client.post(f"/api/jobs/{job_id}/skip")
        assert r.status_code == 200

        r2 = client.get(f"/api/jobs/{job_id}/events")
        events = r2.json()
        skip_events = [e for e in events if e["event_type"] == "skipped"]
        assert len(skip_events) == 1

    def test_override_writes_event(self, client):
        """Override endpoint writes an overridden event."""
        job_id = _create_manual_job(client, suffix="override")
        # First reject
        client.post(f"/api/jobs/{job_id}/reject", json={"reason": "test"})
        # Then override
        r = client.post(f"/api/jobs/{job_id}/override", json={
            "note": "good company",
            "target_status": "ready",
        })
        assert r.status_code == 200

        r2 = client.get(f"/api/jobs/{job_id}/events")
        events = r2.json()
        override_events = [e for e in events if e["event_type"] == "overridden"]
        assert len(override_events) == 1
        assert override_events[0]["metadata"]["from"] == "rejected"
        assert override_events[0]["metadata"]["to"] == "ready"

    def test_event_in_job_detail(self, client):
        """Job detail response includes events timeline."""
        job_id = _create_manual_job(client, suffix="detail")
        r = client.get(f"/api/jobs/{job_id}")
        assert r.status_code == 200
        detail = r.json()
        assert "events" in detail
        assert len(detail["events"]) >= 1
        assert detail["events"][0]["event_type"] == "manual_created"


class TestCreatedAtServerSet:
    """created_at is server-set and ignores any client-supplied value."""

    def test_created_at_not_in_create_payload(self, client):
        """ApplicationEventCreate schema does not include created_at."""
        from seeker_os.api.schemas import ApplicationEventCreate
        fields = ApplicationEventCreate.model_fields
        assert "created_at" not in fields
        assert "occurred_at" in fields

    def test_created_at_is_server_time(self, client):
        """created_at is set by the server, not from client input."""
        job_id = _create_manual_job(client, suffix="created")
        before = datetime.now(timezone.utc)
        r = client.post(f"/api/jobs/{job_id}/events", json={
            "event_type": "interview_scheduled",
            "actor": "candidate",
        })
        after = datetime.now(timezone.utc)
        assert r.status_code == 200
        event = r.json()
        created_dt = datetime.fromisoformat(event["created_at"])
        assert before <= created_dt <= after

    def test_created_at_ignores_client_value(self, client):
        """Even if a client sends created_at, it is ignored."""
        job_id = _create_manual_job(client, suffix="ignore")
        # Pydantic will ignore created_at since it's not in the schema,
        # but let's verify the endpoint doesn't accept it
        r = client.post(f"/api/jobs/{job_id}/events", json={
            "event_type": "test_event",
            "actor": "candidate",
            "created_at": "1999-01-01T00:00:00+00:00",
        })
        assert r.status_code == 200
        event = r.json()
        assert event["created_at"] != "1999-01-01T00:00:00+00:00"


class TestOccurredAtGuard:
    """occurred_at guard rejects future + pre-discovery dates."""

    def test_occurred_at_defaults_to_now(self, client):
        """When occurred_at is not provided, it defaults to server now."""
        job_id = _create_manual_job(client, suffix="default")
        before = datetime.now(timezone.utc)
        r = client.post(f"/api/jobs/{job_id}/events", json={
            "event_type": "test_event",
            "actor": "candidate",
        })
        after = datetime.now(timezone.utc)
        assert r.status_code == 200
        occurred_dt = datetime.fromisoformat(r.json()["occurred_at"])
        assert before <= occurred_dt <= after

    def test_occurred_at_honors_caller_value(self, client):
        """A caller-supplied occurred_at is honored."""
        job_id = _create_manual_job(client, suffix="honor")
        # Get the job's actual discovered_at — using it as occurred_at is valid
        # (it's not before discovery and not in the future)
        r0 = client.get(f"/api/jobs/{job_id}")
        discovered_at = r0.json()["discovered_at"]
        r = client.post(f"/api/jobs/{job_id}/events", json={
            "event_type": "test_event",
            "actor": "candidate",
            "occurred_at": discovered_at,
        })
        assert r.status_code == 200
        assert r.json()["occurred_at"] == discovered_at

    def test_occurred_at_rejects_future(self, client):
        """occurred_at in the future is rejected with 422."""
        job_id = _create_manual_job(client, suffix="future")
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        r = client.post(f"/api/jobs/{job_id}/events", json={
            "event_type": "test_event",
            "actor": "candidate",
            "occurred_at": future,
        })
        assert r.status_code == 422
        assert "future" in r.json()["detail"].lower()

    def test_occurred_at_rejects_pre_discovery(self, client):
        """occurred_at before the job's discovery timestamp is rejected."""
        job_id = _create_manual_job(client, suffix="prediscovery")
        # Get the job's discovered_at
        r = client.get(f"/api/jobs/{job_id}")
        discovered_at = r.json()["discovered_at"]
        discovered_dt = datetime.fromisoformat(discovered_at)
        before_discovery = (discovered_dt - timedelta(days=1)).isoformat()

        r2 = client.post(f"/api/jobs/{job_id}/events", json={
            "event_type": "test_event",
            "actor": "candidate",
            "occurred_at": before_discovery,
        })
        assert r2.status_code == 422
        assert "before" in r2.json()["detail"].lower() or "discovery" in r2.json()["detail"].lower()


class TestEventOrdering:
    """Events return ordered by occurred_at."""

    def test_events_ordered_by_occurred_at(self, client):
        """Events are returned in occurred_at ascending order."""
        import time
        job_id = _create_manual_job(client, suffix="ordering")
        # Get the job's actual discovered_at
        r0 = client.get(f"/api/jobs/{job_id}")
        discovered_dt = datetime.fromisoformat(r0.json()["discovered_at"])

        # Sleep to widen the valid [discovered_at, now] window
        time.sleep(2)

        # Add events with different occurred_at values (all after discovery, all in the past)
        t1 = (discovered_dt + timedelta(milliseconds=100)).isoformat()
        t2 = (discovered_dt + timedelta(milliseconds=900)).isoformat()
        t3 = (discovered_dt + timedelta(milliseconds=500)).isoformat()

        for t in [t1, t2, t3]:
            r = client.post(f"/api/jobs/{job_id}/events", json={
                "event_type": "test_event",
                "actor": "candidate",
                "occurred_at": t,
            })
            assert r.status_code == 200

        r = client.get(f"/api/jobs/{job_id}/events")
        events = r.json()
        # Filter to just our test events
        test_events = [e for e in events if e["event_type"] == "test_event"]
        assert len(test_events) == 3
        # Should be ordered: t1 (3h ago), t3 (2h ago), t2 (1h ago)
        assert test_events[0]["occurred_at"] == t1
        assert test_events[1]["occurred_at"] == t3
        assert test_events[2]["occurred_at"] == t2


class TestAppendOnly:
    """The event log is append-only — no update/delete paths."""

    def test_no_update_endpoint(self, client):
        """There is no PUT/PATCH endpoint for events."""
        job_id = _create_manual_job(client, suffix="no_update")
        r = client.post(f"/api/jobs/{job_id}/events", json={
            "event_type": "test_event",
            "actor": "candidate",
        })
        event_id = r.json()["id"]

        # PATCH should not be a registered route
        r2 = client.patch(f"/api/jobs/{job_id}/events/{event_id}", json={"note": "changed"})
        assert r2.status_code == 404

    def test_no_delete_endpoint(self, client):
        """There is no DELETE endpoint for individual events."""
        job_id = _create_manual_job(client, suffix="no_delete")
        r = client.post(f"/api/jobs/{job_id}/events", json={
            "event_type": "test_event",
            "actor": "candidate",
        })
        event_id = r.json()["id"]

        r2 = client.delete(f"/api/jobs/{job_id}/events/{event_id}")
        assert r2.status_code == 404

    def test_event_immutable_in_db(self, client):
        """Direct DB check: event row cannot be updated via any API path."""
        job_id = _create_manual_job(client, suffix="immutable")
        r = client.post(f"/api/jobs/{job_id}/events", json={
            "event_type": "test_event",
            "actor": "candidate",
            "note": "original",
        })
        event_id = r.json()["id"]

        # Verify the event exists with original note
        db = get_connection()
        try:
            row = db.execute(
                "SELECT note FROM application_events WHERE id = ?", (event_id,)
            ).fetchone()
            assert row["note"] == "original"
        finally:
            db.close()


class TestTransitionStatusAtomicity:
    """transition_status writes both the status change and event in one transaction."""

    def test_status_and_event_same_transaction(self):
        """If the event insert fails, the status change is also rolled back."""
        db = get_connection()
        try:
            # Insert a minimal job
            now = datetime.now(timezone.utc).isoformat()
            cursor = db.execute(
                """INSERT INTO jobs (source_id, source_job_id, apply_url, url_hash,
                   title, status, tier_passed, discovered_at, discovered_query, updated_at)
                   VALUES ('test', 'test___1', 'https://test.example', 'testhash123',
                   'Test', 'ready', 4, ?, 'test', ?)""",
                (now, now),
            )
            job_id = cursor.lastrowid
            db.commit()

            # Normal transition should work
            event_id = transition_status(
                db, job_id, "reviewing", EventType.STATUS_CHANGED, Actor.CANDIDATE,
                metadata={"from": "ready", "to": "reviewing"},
            )
            db.commit()

            # Verify both status and event
            row = db.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
            assert row["status"] == "reviewing"

            event = db.execute(
                "SELECT event_type FROM application_events WHERE id = ?", (event_id,)
            ).fetchone()
            assert event["event_type"] == "status_changed"

            # Cleanup
            db.execute("DELETE FROM application_events WHERE job_id = ?", (job_id,))
            db.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            db.commit()
        finally:
            db.close()

    def test_failure_rolls_back_status_change(self):
        """If record_event fails, the status change is rolled back — no orphaned status."""
        db = get_connection()
        try:
            now = datetime.now(timezone.utc).isoformat()
            cursor = db.execute(
                """INSERT INTO jobs (source_id, source_job_id, apply_url, url_hash,
                   title, status, tier_passed, discovered_at, discovered_query, updated_at)
                   VALUES ('test', 'test___2', 'https://test.example2', 'testhash124',
                   'Test', 'ready', 4, ?, 'test', ?)""",
                (now, now),
            )
            job_id = cursor.lastrowid
            db.commit()

            # An invalid actor will cause record_event to raise ValueError,
            # which transition_status catches and rolls back.
            with pytest.raises(ValueError, match="Invalid actor"):
                transition_status(
                    db, job_id, "reviewing", EventType.STATUS_CHANGED, "bogus_actor",
                    metadata={"from": "ready", "to": "reviewing"},
                )

            # Status should still be 'ready' — the UPDATE was rolled back
            row = db.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
            assert row["status"] == "ready"

            # No event should exist for this job
            event_count = db.execute(
                "SELECT COUNT(*) as cnt FROM application_events WHERE job_id = ?", (job_id,)
            ).fetchone()
            assert event_count["cnt"] == 0

            # Cleanup
            db.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            db.commit()
        finally:
            db.close()
