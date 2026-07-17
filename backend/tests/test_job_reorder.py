"""Tests for candidate-controlled job preference ranking (POST /api/jobs/reorder)."""

import pytest
from fastapi.testclient import TestClient

from seeker_os.api.app import app
from seeker_os.database import run_migrations, get_connection


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
            "SELECT id FROM jobs WHERE company LIKE 'ReorderTestCo%'"
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
        "url": f"https://example.com/jobs/reorder-test-{suffix}",
        "title": "Senior SRE",
        "company": f"ReorderTestCo{suffix}",
        "location": "Remote, US",
        "workplace_type": "Remote",
        "jd_text": f"Reorder test {suffix}\n\n{_LONG_JD}",
    })
    assert r.status_code == 200
    assert r.json()["status"] == "created"
    return r.json()["job"]["id"]


class TestJobReorder:
    def test_reorder_assigns_sequential_ranks(self, client):
        ids = [_create_manual_job(client, suffix=f"seq{i}") for i in range(3)]
        # Rank in reverse order of creation: most preferred first.
        desired_order = list(reversed(ids))

        r = client.post("/api/jobs/reorder", json={"job_ids": desired_order})
        assert r.status_code == 200

        for rank, job_id in enumerate(desired_order, start=1):
            detail = client.get(f"/api/jobs/{job_id}").json()
            assert detail["preference_rank"] == rank

    def test_reorder_is_idempotent_and_can_be_repeated(self, client):
        ids = [_create_manual_job(client, suffix=f"idem{i}") for i in range(2)]

        r1 = client.post("/api/jobs/reorder", json={"job_ids": ids})
        assert r1.status_code == 200
        first = client.get(f"/api/jobs/{ids[0]}").json()["preference_rank"]
        assert first == 1

        # Re-reorder with swapped order updates ranks accordingly.
        r2 = client.post("/api/jobs/reorder", json={"job_ids": list(reversed(ids))})
        assert r2.status_code == 200
        swapped = client.get(f"/api/jobs/{ids[0]}").json()["preference_rank"]
        assert swapped == 2

    def test_reorder_rejects_empty_list(self, client):
        r = client.post("/api/jobs/reorder", json={"job_ids": []})
        assert r.status_code == 422

    def test_reorder_rejects_duplicate_ids(self, client):
        job_id = _create_manual_job(client, suffix="dup")
        r = client.post("/api/jobs/reorder", json={"job_ids": [job_id, job_id]})
        assert r.status_code == 422

    def test_reorder_rejects_unknown_job_id(self, client):
        job_id = _create_manual_job(client, suffix="unknown")
        r = client.post("/api/jobs/reorder", json={"job_ids": [job_id, 99999999]})
        assert r.status_code == 404

    def test_unranked_jobs_default_to_null_preference_rank(self, client):
        job_id = _create_manual_job(client, suffix="unranked")
        detail = client.get(f"/api/jobs/{job_id}").json()
        assert detail["preference_rank"] is None

    def test_list_sort_by_preference_orders_ranked_jobs_first(self, client):
        ids = [_create_manual_job(client, suffix=f"sort{i}") for i in range(2)]
        r = client.post("/api/jobs/reorder", json={"job_ids": ids})
        assert r.status_code == 200

        resp = client.get(
            "/api/jobs",
            params={"company": "ReorderTestCosort", "sort_by": "preference", "order": "asc"},
        )
        assert resp.status_code == 200
        returned_ids = [j["id"] for j in resp.json()["jobs"]]
        assert returned_ids == ids

    def test_patch_update_can_set_preference_rank(self, client):
        job_id = _create_manual_job(client, suffix="patch")
        r = client.patch(f"/api/jobs/{job_id}", json={"preference_rank": 5})
        assert r.status_code == 200
        detail = client.get(f"/api/jobs/{job_id}").json()
        assert detail["preference_rank"] == 5
