"""Tests for L2 post-apply lifecycle — transitions, engaged sub-events,
clean-start, and derived stale flag."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from seeker_os.api.app import app
from seeker_os.database import run_migrations, get_connection
from seeker_os.events import (
    record_event, transition_status, EventType, Actor,
    JobStatus, EngagedEventType, compute_stale_flag,
    STALE_ACTIVITY_EVENTS,
)


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
            "SELECT id FROM jobs WHERE company LIKE 'L2TestCo%'"
        ).fetchall()
        if rows:
            id_list = [str(r["id"]) for r in rows]
            id_csv = ",".join(id_list)
            for table in ["application_events", "dedup_registry", "resumes",
                          "job_analyses"]:
                db.execute(f"DELETE FROM {table} WHERE job_id IN ({id_csv})")
            db.execute(f"DELETE FROM jobs WHERE id IN ({id_csv})")
        db.commit()
    finally:
        db.close()


def _create_manual_job(client, suffix=""):
    """Helper: create a manual job via API and return its ID."""
    r = client.post("/api/jobs", json={
        "url": f"https://example.com/jobs/l2-test-{suffix}",
        "title": "Senior SRE",
        "company": f"L2TestCo{suffix}",
        "location": "Remote, US",
        "workplace_type": "Remote",
        "jd_text": f"L2 test {suffix}\n\n{_LONG_JD}",
    })
    assert r.status_code == 200
    assert r.json()["status"] == "created"
    return r.json()["job"]["id"]


def _set_applied(client, job_id):
    """Helper: transition a job to applied via clean-start."""
    r = client.post(f"/api/jobs/{job_id}/clean-start", json={
        "target_status": "applied",
    })
    assert r.status_code == 200
    return job_id


def _set_engaged(client, job_id):
    """Helper: transition a job from applied to engaged."""
    _set_applied(client, job_id)
    r = client.post(f"/api/jobs/{job_id}/transition", json={
        "target_status": "engaged",
    })
    assert r.status_code == 200
    return job_id


# ---------------------------------------------------------------------------
# Task 1: Post-apply transitions set status + log the right event/actor
# ---------------------------------------------------------------------------

class TestPostApplyTransitions:
    """Post-apply transitions set status and log the correct event/actor."""

    def test_applied_to_engaged(self, client):
        """applied → engaged logs 'engaged' event with actor=candidate."""
        job_id = _create_manual_job(client, suffix="eng1")
        _set_applied(client, job_id)

        r = client.post(f"/api/jobs/{job_id}/transition", json={
            "target_status": "engaged",
        })
        assert r.status_code == 200

        detail = client.get(f"/api/jobs/{job_id}").json()
        assert detail["status"] == "engaged"

        events = client.get(f"/api/jobs/{job_id}/events").json()
        engaged_events = [e for e in events if e["event_type"] == "engaged"]
        assert len(engaged_events) == 1
        assert engaged_events[0]["actor"] == "candidate"

    def test_applied_to_company_rejected(self, client):
        """applied → company_rejected logs 'company_rejected' event with actor=company."""
        job_id = _create_manual_job(client, suffix="cr1")
        _set_applied(client, job_id)

        r = client.post(f"/api/jobs/{job_id}/transition", json={
            "target_status": "company_rejected",
        })
        assert r.status_code == 200

        detail = client.get(f"/api/jobs/{job_id}").json()
        assert detail["status"] == "company_rejected"

        events = client.get(f"/api/jobs/{job_id}/events").json()
        cr_events = [e for e in events if e["event_type"] == "company_rejected"]
        assert len(cr_events) == 1
        assert cr_events[0]["actor"] == "company"

    def test_applied_to_withdrawn(self, client):
        """applied → withdrawn logs 'withdrawn' event with actor=candidate."""
        job_id = _create_manual_job(client, suffix="wd1")
        _set_applied(client, job_id)

        r = client.post(f"/api/jobs/{job_id}/transition", json={
            "target_status": "withdrawn",
        })
        assert r.status_code == 200

        detail = client.get(f"/api/jobs/{job_id}").json()
        assert detail["status"] == "withdrawn"

        events = client.get(f"/api/jobs/{job_id}/events").json()
        wd_events = [e for e in events if e["event_type"] == "withdrawn"]
        assert len(wd_events) == 1
        assert wd_events[0]["actor"] == "candidate"

    def test_engaged_to_offer_accepted(self, client):
        """engaged → offer_accepted logs 'offer_accepted' event with actor=candidate."""
        job_id = _create_manual_job(client, suffix="oa1")
        _set_engaged(client, job_id)

        r = client.post(f"/api/jobs/{job_id}/transition", json={
            "target_status": "offer_accepted",
        })
        assert r.status_code == 200

        detail = client.get(f"/api/jobs/{job_id}").json()
        assert detail["status"] == "offer_accepted"

        events = client.get(f"/api/jobs/{job_id}/events").json()
        oa_events = [e for e in events if e["event_type"] == "offer_accepted"]
        assert len(oa_events) == 1
        assert oa_events[0]["actor"] == "candidate"

    def test_engaged_to_offer_declined(self, client):
        """engaged → offer_declined logs 'offer_declined' event with actor=candidate."""
        job_id = _create_manual_job(client, suffix="od1")
        _set_engaged(client, job_id)

        r = client.post(f"/api/jobs/{job_id}/transition", json={
            "target_status": "offer_declined",
        })
        assert r.status_code == 200

        detail = client.get(f"/api/jobs/{job_id}").json()
        assert detail["status"] == "offer_declined"

        events = client.get(f"/api/jobs/{job_id}/events").json()
        od_events = [e for e in events if e["event_type"] == "offer_declined"]
        assert len(od_events) == 1
        assert od_events[0]["actor"] == "candidate"

    def test_engaged_to_company_rejected(self, client):
        """engaged → company_rejected logs 'company_rejected' event with actor=company."""
        job_id = _create_manual_job(client, suffix="ecr1")
        _set_engaged(client, job_id)

        r = client.post(f"/api/jobs/{job_id}/transition", json={
            "target_status": "company_rejected",
        })
        assert r.status_code == 200

        detail = client.get(f"/api/jobs/{job_id}").json()
        assert detail["status"] == "company_rejected"

        events = client.get(f"/api/jobs/{job_id}/events").json()
        cr_events = [e for e in events if e["event_type"] == "company_rejected"]
        assert len(cr_events) == 1
        assert cr_events[0]["actor"] == "company"

    def test_invalid_transition_rejected(self, client):
        """Cannot transition from 'ready' to 'engaged' directly."""
        job_id = _create_manual_job(client, suffix="inv1")
        # Job is 'ready' after creation

        r = client.post(f"/api/jobs/{job_id}/transition", json={
            "target_status": "engaged",
        })
        assert r.status_code == 400
        assert "Cannot transition" in r.json()["detail"]

    def test_invalid_target_status(self, client):
        """Invalid target_status returns 422."""
        job_id = _create_manual_job(client, suffix="inv2")
        _set_applied(client, job_id)

        r = client.post(f"/api/jobs/{job_id}/transition", json={
            "target_status": "bogus_status",
        })
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# Task 2: Engaged sub-events append WITHOUT changing status
# ---------------------------------------------------------------------------

class TestEngagedSubEvents:
    """Engaged sub-lifecycle events append without changing status."""

    def test_interview_does_not_change_status(self, client):
        """Logging an interview event does not change status from 'engaged'."""
        job_id = _create_manual_job(client, suffix="iv1")
        _set_engaged(client, job_id)

        r = client.post(f"/api/jobs/{job_id}/engaged-events", json={
            "event_type": "interview",
            "note": "Phone screen with recruiter",
        })
        assert r.status_code == 200

        detail = client.get(f"/api/jobs/{job_id}").json()
        assert detail["status"] == "engaged"

        events = client.get(f"/api/jobs/{job_id}/events").json()
        interview_events = [e for e in events if e["event_type"] == "interview"]
        assert len(interview_events) == 1
        assert interview_events[0]["note"] == "Phone screen with recruiter"

    def test_challenge_assigned(self, client):
        """Logging challenge_assigned does not change status."""
        job_id = _create_manual_job(client, suffix="ca1")
        _set_engaged(client, job_id)

        r = client.post(f"/api/jobs/{job_id}/engaged-events", json={
            "event_type": "challenge_assigned",
            "metadata": {"deadline": "2025-01-15"},
        })
        assert r.status_code == 200

        detail = client.get(f"/api/jobs/{job_id}").json()
        assert detail["status"] == "engaged"

    def test_followup_sent(self, client):
        """Logging followup_sent does not change status."""
        job_id = _create_manual_job(client, suffix="fu1")
        _set_engaged(client, job_id)

        r = client.post(f"/api/jobs/{job_id}/engaged-events", json={
            "event_type": "followup_sent",
        })
        assert r.status_code == 200

        detail = client.get(f"/api/jobs/{job_id}").json()
        assert detail["status"] == "engaged"

    def test_contact_received(self, client):
        """Logging contact_received does not change status."""
        job_id = _create_manual_job(client, suffix="ct1")
        _set_engaged(client, job_id)

        r = client.post(f"/api/jobs/{job_id}/engaged-events", json={
            "event_type": "contact_received",
        })
        assert r.status_code == 200

        detail = client.get(f"/api/jobs/{job_id}").json()
        assert detail["status"] == "engaged"

    def test_engaged_event_rejected_when_not_engaged(self, client):
        """Engaged events are rejected when status is not 'engaged'."""
        job_id = _create_manual_job(client, suffix="ne1")
        _set_applied(client, job_id)

        r = client.post(f"/api/jobs/{job_id}/engaged-events", json={
            "event_type": "interview",
        })
        assert r.status_code == 400

    def test_invalid_engaged_event_type(self, client):
        """Invalid engaged event_type returns 422."""
        job_id = _create_manual_job(client, suffix="ie1")
        _set_engaged(client, job_id)

        r = client.post(f"/api/jobs/{job_id}/engaged-events", json={
            "event_type": "bogus_event",
        })
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# Task 3: Clean-start — enter directly at applied with backdated event
# ---------------------------------------------------------------------------

class TestCleanStart:
    """Clean-start path: enter directly at a post-apply status with backdated events."""

    def test_clean_start_applied_backdated(self, client):
        """A job can be clean-started to 'applied' with a backdated applied event.
        The event's occurred_at is the supplied past date and created_at is now.
        """
        job_id = _create_manual_job(client, suffix="cs1")

        past_date = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        r = client.post(f"/api/jobs/{job_id}/clean-start", json={
            "target_status": "applied",
            "occurred_at": past_date,
            "note": "Applied externally 30 days ago",
        })
        assert r.status_code == 200

        detail = client.get(f"/api/jobs/{job_id}").json()
        assert detail["status"] == "applied"

        events = client.get(f"/api/jobs/{job_id}/events").json()
        applied_events = [e for e in events if e["event_type"] == "applied"]
        assert len(applied_events) == 1
        assert applied_events[0]["occurred_at"] == past_date
        assert applied_events[0]["note"] == "Applied externally 30 days ago"
        # created_at should be close to now, not the backdated date
        created_dt = datetime.fromisoformat(applied_events[0]["created_at"])
        now = datetime.now(timezone.utc)
        assert (now - created_dt).total_seconds() < 10  # within 10 seconds

    def test_clean_start_skips_pre_apply_funnel(self, client):
        """Clean-start to applied skips the reviewing → interested → applied funnel.
        No intermediate status events exist.
        """
        job_id = _create_manual_job(client, suffix="cs2")

        past_date = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        r = client.post(f"/api/jobs/{job_id}/clean-start", json={
            "target_status": "applied",
            "occurred_at": past_date,
        })
        assert r.status_code == 200

        events = client.get(f"/api/jobs/{job_id}/events").json()
        event_types = [e["event_type"] for e in events]
        # Should have manual_created and applied, but NOT reviewing or interested
        assert "manual_created" in event_types
        assert "applied" in event_types
        assert "status_changed" not in event_types or "applied" in event_types
        # No reviewing or interested events
        reviewing_events = [e for e in events if e.get("metadata", {}) and e["metadata"].get("to") == "reviewing"]
        assert len(reviewing_events) == 0

    def test_clean_start_engaged(self, client):
        """Clean-start to engaged sets status and logs engaged event."""
        job_id = _create_manual_job(client, suffix="cs3")

        past_date = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        r = client.post(f"/api/jobs/{job_id}/clean-start", json={
            "target_status": "engaged",
            "occurred_at": past_date,
        })
        assert r.status_code == 200

        detail = client.get(f"/api/jobs/{job_id}").json()
        assert detail["status"] == "engaged"

        events = client.get(f"/api/jobs/{job_id}/events").json()
        engaged_events = [e for e in events if e["event_type"] == "engaged"]
        assert len(engaged_events) == 1
        assert engaged_events[0]["occurred_at"] == past_date

    def test_clean_start_rejected(self, client):
        """Clean-start to rejected sets status and logs status_changed event."""
        job_id = _create_manual_job(client, suffix="cs4")

        past_date = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        r = client.post(f"/api/jobs/{job_id}/clean-start", json={
            "target_status": "rejected",
            "occurred_at": past_date,
            "note": "Already rejected by company",
        })
        assert r.status_code == 200

        detail = client.get(f"/api/jobs/{job_id}").json()
        assert detail["status"] == "rejected"

    def test_clean_start_invalid_status(self, client):
        """Clean-start to an invalid status returns 422."""
        job_id = _create_manual_job(client, suffix="cs5")

        r = client.post(f"/api/jobs/{job_id}/clean-start", json={
            "target_status": "ready",
        })
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# Task 4: Stale flag computes correctly
# ---------------------------------------------------------------------------

class TestStaleFlag:
    """Derived stale flag — computed, not stored, never auto-transitions."""

    def test_stale_applied_old_event(self, client):
        """An applied job with an old event is flagged stale."""
        job_id = _create_manual_job(client, suffix="st1")

        past_date = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
        client.post(f"/api/jobs/{job_id}/clean-start", json={
            "target_status": "applied",
            "occurred_at": past_date,
        })

        detail = client.get(f"/api/jobs/{job_id}").json()
        assert detail["status"] == "applied"
        assert detail["is_stale"] is True
        assert detail["days_since_last_activity"] is not None
        assert detail["days_since_last_activity"] >= 20

    def test_not_stale_applied_recent_event(self, client):
        """An applied job with a recent event is not stale."""
        job_id = _create_manual_job(client, suffix="st2")

        client.post(f"/api/jobs/{job_id}/clean-start", json={
            "target_status": "applied",
        })

        detail = client.get(f"/api/jobs/{job_id}").json()
        assert detail["status"] == "applied"
        assert detail["is_stale"] is False

    def test_stale_engaged_old_event(self, client):
        """An engaged job with an old event is flagged stale."""
        job_id = _create_manual_job(client, suffix="st3")

        past_date = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        client.post(f"/api/jobs/{job_id}/clean-start", json={
            "target_status": "engaged",
            "occurred_at": past_date,
        })

        detail = client.get(f"/api/jobs/{job_id}").json()
        assert detail["status"] == "engaged"
        assert detail["is_stale"] is True

    def test_followup_resets_staleness(self, client):
        """A followup_sent event on an engaged job resets the staleness clock."""
        job_id = _create_manual_job(client, suffix="st4")

        past_date = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        client.post(f"/api/jobs/{job_id}/clean-start", json={
            "target_status": "engaged",
            "occurred_at": past_date,
        })

        # Confirm it's stale
        detail = client.get(f"/api/jobs/{job_id}").json()
        assert detail["is_stale"] is True

        # Log a recent followup_sent
        client.post(f"/api/jobs/{job_id}/engaged-events", json={
            "event_type": "followup_sent",
        })

        # Should no longer be stale
        detail = client.get(f"/api/jobs/{job_id}").json()
        assert detail["is_stale"] is False

    def test_contact_received_resets_staleness(self, client):
        """A contact_received event on an engaged job resets the staleness clock."""
        job_id = _create_manual_job(client, suffix="st5")

        past_date = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        client.post(f"/api/jobs/{job_id}/clean-start", json={
            "target_status": "engaged",
            "occurred_at": past_date,
        })

        # Confirm it's stale
        detail = client.get(f"/api/jobs/{job_id}").json()
        assert detail["is_stale"] is True

        # Log a recent contact_received
        client.post(f"/api/jobs/{job_id}/engaged-events", json={
            "event_type": "contact_received",
        })

        # Should no longer be stale
        detail = client.get(f"/api/jobs/{job_id}").json()
        assert detail["is_stale"] is False

    def test_terminal_status_not_stale(self, client):
        """Terminal statuses (company_rejected, withdrawn, etc.) are never stale."""
        job_id = _create_manual_job(client, suffix="st6")

        past_date = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        client.post(f"/api/jobs/{job_id}/clean-start", json={
            "target_status": "company_rejected",
            "occurred_at": past_date,
        })

        detail = client.get(f"/api/jobs/{job_id}").json()
        assert detail["status"] == "company_rejected"
        assert detail["is_stale"] is False
        assert detail["days_since_last_activity"] is None

    def test_stale_flag_never_auto_transitions(self, client):
        """Stale flag does not change the job status."""
        job_id = _create_manual_job(client, suffix="st7")

        past_date = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        client.post(f"/api/jobs/{job_id}/clean-start", json={
            "target_status": "applied",
            "occurred_at": past_date,
        })

        detail = client.get(f"/api/jobs/{job_id}").json()
        assert detail["is_stale"] is True
        # Status must still be 'applied' — stale flag never auto-transitions
        assert detail["status"] == "applied"

    def test_stale_flag_in_list_response(self, client):
        """Stale flag appears in job list responses."""
        job_id = _create_manual_job(client, suffix="st8")

        past_date = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        client.post(f"/api/jobs/{job_id}/clean-start", json={
            "target_status": "applied",
            "occurred_at": past_date,
        })

        jobs = client.get("/api/jobs?status=applied").json()["jobs"]
        test_jobs = [j for j in jobs if j["id"] == job_id]
        assert len(test_jobs) == 1
        assert test_jobs[0]["is_stale"] is True
        assert test_jobs[0]["days_since_last_activity"] is not None


# ---------------------------------------------------------------------------
# FIX 1: Stale filter uses an allowlist, not a denylist
# ---------------------------------------------------------------------------

class TestStaleAllowlist:
    """The stale filter uses STALE_ACTIVITY_EVENTS allowlist — non-activity
    events do NOT reset the staleness clock."""

    def test_allowlist_contents(self):
        """STALE_ACTIVITY_EVENTS contains exactly the expected events."""
        expected = {
            "applied", "engaged",
            "interview", "challenge_assigned", "challenge_submitted",
            "offer_received", "offer_countered",
            "followup_sent", "contact_received",
        }
        assert STALE_ACTIVITY_EVENTS == expected

    def test_non_activity_event_does_not_reset_staleness(self, client):
        """An event type NOT in the allowlist does not reset the staleness clock.

        Simulate a future event type ('note_added') being written directly to the
        DB. Even though it's recent, the stale flag should still report stale
        because the old 'applied' event is the latest allowlisted activity.
        """
        job_id = _create_manual_job(client, suffix="al1")

        old_date = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        client.post(f"/api/jobs/{job_id}/clean-start", json={
            "target_status": "applied",
            "occurred_at": old_date,
        })

        # Confirm it's stale
        detail = client.get(f"/api/jobs/{job_id}").json()
        assert detail["is_stale"] is True

        # Write a recent non-activity event directly to the DB
        db = get_connection()
        try:
            record_event(
                db=db,
                job_id=job_id,
                event_type="note_added",
                actor=Actor.CANDIDATE,
                note="A future event type not in the allowlist",
            )
            db.commit()
        finally:
            db.close()

        # Should still be stale — 'note_added' is not in STALE_ACTIVITY_EVENTS
        detail = client.get(f"/api/jobs/{job_id}").json()
        assert detail["is_stale"] is True
        assert detail["days_since_last_activity"] is not None
        assert detail["days_since_last_activity"] >= 30

    def test_followup_sent_still_resets_staleness(self, client):
        """followup_sent is in the allowlist and still resets staleness."""
        job_id = _create_manual_job(client, suffix="al2")

        old_date = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        client.post(f"/api/jobs/{job_id}/clean-start", json={
            "target_status": "engaged",
            "occurred_at": old_date,
        })

        # Confirm it's stale
        detail = client.get(f"/api/jobs/{job_id}").json()
        assert detail["is_stale"] is True

        # Log a recent followup_sent (in the allowlist)
        client.post(f"/api/jobs/{job_id}/engaged-events", json={
            "event_type": "followup_sent",
        })

        # Should no longer be stale
        detail = client.get(f"/api/jobs/{job_id}").json()
        assert detail["is_stale"] is False

    def test_contact_received_still_resets_staleness(self, client):
        """contact_received is in the allowlist and still resets staleness."""
        job_id = _create_manual_job(client, suffix="al3")

        old_date = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        client.post(f"/api/jobs/{job_id}/clean-start", json={
            "target_status": "engaged",
            "occurred_at": old_date,
        })

        # Confirm it's stale
        detail = client.get(f"/api/jobs/{job_id}").json()
        assert detail["is_stale"] is True

        # Log a recent contact_received (in the allowlist)
        client.post(f"/api/jobs/{job_id}/engaged-events", json={
            "event_type": "contact_received",
        })

        # Should no longer be stale
        detail = client.get(f"/api/jobs/{job_id}").json()
        assert detail["is_stale"] is False


# ---------------------------------------------------------------------------
# FIX 2: Clean-start with optional applied_occurred_at
# ---------------------------------------------------------------------------

class TestCleanStartAppliedDate:
    """Engaged/company_rejected clean-start with optional applied_occurred_at."""

    def test_engaged_clean_start_with_applied_date(self, client):
        """Engaged clean-start WITH applied_occurred_at creates two events:
        applied (backdated) then engaged, status=engaged."""
        job_id = _create_manual_job(client, suffix="ad1")

        applied_date = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
        engaged_date = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()

        r = client.post(f"/api/jobs/{job_id}/clean-start", json={
            "target_status": "engaged",
            "occurred_at": engaged_date,
            "applied_occurred_at": applied_date,
        })
        assert r.status_code == 200

        detail = client.get(f"/api/jobs/{job_id}").json()
        assert detail["status"] == "engaged"

        events = client.get(f"/api/jobs/{job_id}/events").json()
        applied_events = [e for e in events if e["event_type"] == "applied"]
        engaged_events = [e for e in events if e["event_type"] == "engaged"]
        assert len(applied_events) == 1
        assert len(engaged_events) == 1
        assert applied_events[0]["occurred_at"] == applied_date
        assert engaged_events[0]["occurred_at"] == engaged_date
        # Applied event should be before engaged event
        assert applied_events[0]["occurred_at"] < engaged_events[0]["occurred_at"]

    def test_engaged_clean_start_without_applied_date(self, client):
        """Engaged clean-start WITHOUT applied_occurred_at: only the engaged
        event exists, no applied event, status=engaged (stands alone)."""
        job_id = _create_manual_job(client, suffix="ad2")

        engaged_date = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()

        r = client.post(f"/api/jobs/{job_id}/clean-start", json={
            "target_status": "engaged",
            "occurred_at": engaged_date,
        })
        assert r.status_code == 200

        detail = client.get(f"/api/jobs/{job_id}").json()
        assert detail["status"] == "engaged"

        events = client.get(f"/api/jobs/{job_id}/events").json()
        applied_events = [e for e in events if e["event_type"] == "applied"]
        engaged_events = [e for e in events if e["event_type"] == "engaged"]
        assert len(applied_events) == 0
        assert len(engaged_events) == 1
        assert engaged_events[0]["occurred_at"] == engaged_date

    def test_company_rejected_clean_start_with_applied_date(self, client):
        """Company_rejected clean-start WITH applied_occurred_at creates two
        events: applied (backdated) then company_rejected."""
        job_id = _create_manual_job(client, suffix="ad3")

        applied_date = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
        rejected_date = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()

        r = client.post(f"/api/jobs/{job_id}/clean-start", json={
            "target_status": "company_rejected",
            "occurred_at": rejected_date,
            "applied_occurred_at": applied_date,
        })
        assert r.status_code == 200

        detail = client.get(f"/api/jobs/{job_id}").json()
        assert detail["status"] == "company_rejected"

        events = client.get(f"/api/jobs/{job_id}/events").json()
        applied_events = [e for e in events if e["event_type"] == "applied"]
        cr_events = [e for e in events if e["event_type"] == "company_rejected"]
        assert len(applied_events) == 1
        assert len(cr_events) == 1
        assert applied_events[0]["occurred_at"] == applied_date

    def test_applied_date_after_engaged_date_rejected(self, client):
        """applied_occurred_at later than the engaged event's occurred_at → 422."""
        job_id = _create_manual_job(client, suffix="ad4")

        applied_date = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        engaged_date = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()

        r = client.post(f"/api/jobs/{job_id}/clean-start", json={
            "target_status": "engaged",
            "occurred_at": engaged_date,
            "applied_occurred_at": applied_date,
        })
        assert r.status_code == 422
        assert "cannot be later than" in r.json()["detail"]

    def test_applied_date_in_future_rejected(self, client):
        """applied_occurred_at in the future → 422."""
        job_id = _create_manual_job(client, suffix="ad5")

        future_date = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
        engaged_date = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()

        r = client.post(f"/api/jobs/{job_id}/clean-start", json={
            "target_status": "engaged",
            "occurred_at": engaged_date,
            "applied_occurred_at": future_date,
        })
        assert r.status_code == 422
        assert "future" in r.json()["detail"]

    def test_applied_clean_start_ignores_applied_occurred_at(self, client):
        """When target_status is 'applied', applied_occurred_at is ignored —
        the occurred_at field IS the applied date."""
        job_id = _create_manual_job(client, suffix="ad6")

        applied_date = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        extra_applied_date = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()

        r = client.post(f"/api/jobs/{job_id}/clean-start", json={
            "target_status": "applied",
            "occurred_at": applied_date,
            "applied_occurred_at": extra_applied_date,
        })
        assert r.status_code == 200

        events = client.get(f"/api/jobs/{job_id}/events").json()
        applied_events = [e for e in events if e["event_type"] == "applied"]
        assert len(applied_events) == 1
        # Should use occurred_at, not applied_occurred_at
        assert applied_events[0]["occurred_at"] == applied_date
