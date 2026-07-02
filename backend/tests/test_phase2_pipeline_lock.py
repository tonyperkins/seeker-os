"""Phase 2 concurrency regression tests — the pipeline run lock (§2.4/§2.10).

A pipeline run mutates shared job rows over minutes; overlapping runs interleave
writes. These tests assert the single-run lock rejects a concurrent run with 409
and that the /running endpoint reflects lock state — without actually running a
(slow, network-bound) pipeline, by holding the lock directly.

See ai-audit/REMEDIATION_PLAN_2026-07-02.md, Phase 2A.
"""

from fastapi.testclient import TestClient

from seeker_os.api.app import app
import seeker_os.api.pipeline as pipeline


client = TestClient(app)


def test_running_reports_false_when_idle():
    assert pipeline._run_lock.locked() is False
    assert client.get("/api/pipeline/running").json() == {"running": False}


def test_concurrent_run_returns_409():
    """While a run holds the lock, a second /run is refused with 409."""
    acquired = pipeline._run_lock.acquire(blocking=False)
    assert acquired, "lock should be free at test start"
    try:
        assert client.get("/api/pipeline/running").json() == {"running": True}

        r = client.post("/api/pipeline/run", json={"dry_run": True, "tiers": [1]})
        assert r.status_code == 409
        assert "in progress" in r.json()["detail"].lower()

        # The tier endpoint shares the same lock.
        r2 = client.post("/api/pipeline/run/tier/1")
        assert r2.status_code == 409

        # The streaming endpoint refuses too, without spawning a worker thread.
        r3 = client.post("/api/pipeline/run/stream", json={"dry_run": True, "tiers": [1]})
        assert r3.status_code == 409
    finally:
        pipeline._run_lock.release()

    # Lock is released again → reported idle.
    assert pipeline._run_lock.locked() is False
    assert client.get("/api/pipeline/running").json() == {"running": False}
