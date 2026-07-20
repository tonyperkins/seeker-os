"""Phase 1 correctness & data-integrity regression tests.

Covers the audit fixes:
  * §2.1  transition_status rejects invalid status strings (choke-point guard)
  * §2.2  router fallback matches the override model by id, not object identity
  * §2.3  deleting a job preserves the company-keyed dossier for sibling jobs

See ai-audit/REMEDIATION_PLAN_2026-07-02.md, Phase 1.
"""

import pytest
from fastapi.testclient import TestClient

from seeker_os.api.app import app
from seeker_os.database import run_migrations, get_connection
from seeker_os.events import transition_status, EventType, Actor


_LONG_JD = (
    "We are looking for a Senior Site Reliability Engineer to join our platform team. "
    "You will be responsible for designing, building, and operating the infrastructure "
    "that powers our distributed systems. This includes Kubernetes cluster management, "
    "Terraform infrastructure as code, CI/CD pipeline development, observability with "
    "Prometheus and Grafana, and incident response. The ideal candidate has 5+ years "
    "of experience with cloud platforms (AWS or GCP), strong programming skills in "
    "Python or Go, and deep knowledge of distributed systems. This is a fully remote "
    "position open to candidates in the United States."
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
            "SELECT id FROM jobs WHERE company LIKE 'Phase1%'"
        ).fetchall()
        if rows:
            id_csv = ",".join(str(r["id"]) for r in rows)
            for table in ["application_events", "dedup_registry", "resumes",
                          "job_analyses"]:
                db.execute(f"DELETE FROM {table} WHERE job_id IN ({id_csv})")
            # company_research is company-scoped (no job_id column). Clean up
            # by company_norm for the test companies.
            db.execute(
                "DELETE FROM company_research WHERE company_norm LIKE 'phase1%'"
            )
            db.execute(f"DELETE FROM jobs WHERE id IN ({id_csv})")
        db.commit()
    finally:
        db.close()


def _create_job(client, company, suffix):
    r = client.post("/api/jobs", json={
        "url": f"https://example.com/jobs/phase1-{suffix}",
        "title": "Senior SRE",
        "company": company,
        "location": "Remote, US",
        "workplace_type": "Remote",
        "jd_text": f"Phase1 test {suffix}\n\n{_LONG_JD}",
    })
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "created"
    return r.json()["job"]["id"]


# --------------------------------------------------------------------------
# §2.1 — status validation at the transition_status choke point
# --------------------------------------------------------------------------

class TestStatusValidation:
    def test_transition_status_rejects_unknown_status(self, client):
        """An unknown status must raise ValueError before any DB write."""
        db = get_connection()
        try:
            with pytest.raises(ValueError, match="Invalid status"):
                transition_status(
                    db, 1, "pwned", EventType.STATUS_CHANGED, Actor.CANDIDATE,
                )
        finally:
            db.close()

    def test_patch_invalid_status_returns_422(self, client):
        """PATCH /api/jobs/{id} with a bad status is a 422, and the job is untouched."""
        job_id = _create_job(client, "Phase1StatusCo", "status")
        r = client.patch(f"/api/jobs/{job_id}", json={"status": "aplied"})
        assert r.status_code == 422

        detail = client.get(f"/api/jobs/{job_id}").json()
        assert detail["status"] == "ready"  # unchanged

    def test_patch_valid_status_still_works(self, client):
        """A valid status transition is unaffected by the guard."""
        job_id = _create_job(client, "Phase1StatusCo", "status-ok")
        r = client.patch(f"/api/jobs/{job_id}", json={"status": "reviewing"})
        assert r.status_code == 200
        assert client.get(f"/api/jobs/{job_id}").json()["status"] == "reviewing"


# --------------------------------------------------------------------------
# §2.2 — router fallback compares override model by id, not object
# --------------------------------------------------------------------------

class TestRouterOverrideFallback:
    def _router(self):
        from seeker_os.config import (
            Settings, ProvidersConfig, ProviderConfig, TierMapping, TaskOverride,
        )
        from seeker_os.llm.router import ModelRouter
        from seeker_os.llm.models import ModelInfo, LLMResponse, ProviderHealth

        class MockProvider:
            def __init__(self, pid):
                self._id = pid
            @property
            def id(self): return self._id
            @property
            def type(self): return "mock"
            def generate(self, request):
                return LLMResponse(text="mock", model=request.model, provider=self._id)
            def list_models(self):
                return [ModelInfo(id="override-model", label="Override", provider_id=self._id)]
            def test_connection(self):
                return ProviderHealth(provider_id=self._id, healthy=True)

        settings = Settings.__new__(Settings)
        settings.providers = ProvidersConfig(
            providers=[ProviderConfig(id="p1", type="anthropic", api_key="x", enabled=True)],
            tiers={"heavy": TierMapping(provider="p1", model="test-premium-model")},
            # Override names an unavailable provider, but its model DOES exist on
            # the tier provider (p1) — the fallback branch must find it by id.
            tasks={"resume_generation": TaskOverride(
                tier="heavy", provider="p_missing", model="override-model",
            )},
            approved_models=["test-premium-model", "override-model"],
        )
        router = ModelRouter(settings)
        router._providers = {"p1": MockProvider("p1")}
        router._provider_configs = {"p1": ProviderConfig(id="p1", type="anthropic", api_key="x")}
        router._initialized = True
        return router

    def test_override_model_resolved_on_tier_provider(self):
        """The override model exists on the tier provider → resolve returns it.

        Regression: `str in list[ModelInfo]` was always False, so this branch
        never fired and resolution silently fell through to the tier default.
        """
        provider, model = self._router().resolve("resume_generation")
        assert provider.id == "p1"
        assert model == "override-model"


# --------------------------------------------------------------------------
# §2.3 — deleting a job must not evict a shared company dossier
# --------------------------------------------------------------------------

class TestSharedDossierOnDelete:
    def _insert_dossier(self, job_id, company_norm):
        db = get_connection()
        try:
            db.execute(
                "INSERT INTO company_research (triggered_by_job_id, company_name, company_norm, "
                "researched_at, created_at) VALUES (?, ?, ?, ?, ?)",
                (job_id, "Phase1DossierCo", company_norm, "2026-07-02", "2026-07-02"),
            )
            db.commit()
        finally:
            db.close()

    def _dossier_for_company(self, company_norm):
        db = get_connection()
        try:
            return db.execute(
                "SELECT triggered_by_job_id FROM company_research WHERE company_norm = ?",
                (company_norm,),
            ).fetchone()
        finally:
            db.close()

    def test_dossier_survives_all_job_deletes(self, client):
        """company_research is company-scoped (no job_id FK). Deleting jobs
        must never delete the dossier — other jobs at the same company share it."""
        job_a = _create_job(client, "Phase1DossierCo", "dossier-a")
        job_b = _create_job(client, "Phase1DossierCo", "dossier-b")

        db = get_connection()
        try:
            norm = db.execute("SELECT company_norm FROM jobs WHERE id = ?", (job_a,)).fetchone()["company_norm"]
        finally:
            db.close()
        assert norm, "manual job should populate company_norm"

        self._insert_dossier(job_a, norm)

        # Deleting job_a must preserve the dossier (company-scoped, not job-scoped).
        assert client.delete(f"/api/jobs/{job_a}").status_code == 200
        surviving = self._dossier_for_company(norm)
        assert surviving is not None, "dossier must survive job delete (company-scoped)"

        # Deleting the last job at the company must STILL preserve the dossier.
        # company_research has no FK to jobs — delete_job does not touch it.
        assert client.delete(f"/api/jobs/{job_b}").status_code == 200
        assert self._dossier_for_company(norm) is not None, (
            "dossier must survive even when no jobs remain — it is company-scoped"
        )
