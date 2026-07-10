"""Company research settings API routes — retrieval config UI."""

from __future__ import annotations

import logging
import os

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from seeker_os.api.schemas import MessageResponse
from seeker_os.config import get_settings, CONFIG_DIR

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/settings", tags=["company-research-settings"])

RETRIEVAL_API_KEY_ENV = "RETRIEVAL_API_KEY"


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class RetrievalSettingsResponse(BaseModel):
    """Sanitized retrieval settings — never includes the API key."""
    provider_type: str = ""
    api_key_configured: bool = False
    max_results: int = 5
    timeout_seconds: int = 15
    funding_query_template: str = "{company} funding round investors valuation"
    sentiment_query_template: str = "{company} employee reviews sentiment glassdoor culture"
    confidence_floor: float = 0.3
    staleness_months: int = 18
    source_trust_order: list[str] = []
    user_agent: str = ""


class RetrievalSettingsUpdate(BaseModel):
    """Partial update for retrieval settings. api_key is write-only."""
    provider_type: str | None = None
    api_key: str | None = None
    max_results: int | None = None
    timeout_seconds: int | None = None
    funding_query_template: str | None = None
    sentiment_query_template: str | None = None
    confidence_floor: float | None = None
    staleness_months: int | None = None
    source_trust_order: list[str] | None = None
    user_agent: str | None = None


class TestConnectionResponse(BaseModel):
    ok: bool
    message: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_cr_yaml() -> dict:
    """Load company_research.yml as raw dict, or return empty dict if absent."""
    path = CONFIG_DIR / "company_research.yml"
    if not path.exists():
        return {}
    with open(path) as f:
        data = yaml.safe_load(f)
    return data or {}


def _save_cr_yaml(data: dict) -> None:
    """Write company_research.yml."""
    path = CONFIG_DIR / "company_research.yml"
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def _seed_cr_yaml() -> dict:
    """Seed company_research.yml from the example file or defaults."""
    example_path = CONFIG_DIR / "company_research.example.yml"
    if example_path.exists():
        with open(example_path) as f:
            data = yaml.safe_load(f)
        if data:
            return data
    from seeker_os.config import CompanyResearchConfig
    return CompanyResearchConfig().model_dump()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/company-research", response_model=RetrievalSettingsResponse)
def get_retrieval_settings():
    """Get retrieval settings, sanitized — never returns the API key."""
    settings = get_settings()
    cr = settings.company_research

    if cr is None:
        return RetrievalSettingsResponse()

    api_key_configured = bool(
        cr.retrieval.api_key
        and cr.retrieval.api_key != ""
        and not cr.retrieval.api_key.startswith("${")
    ) or bool(
        cr.retrieval.api_key
        and cr.retrieval.api_key.startswith("${")
        and os.environ.get(RETRIEVAL_API_KEY_ENV)
    )

    return RetrievalSettingsResponse(
        provider_type=cr.retrieval.type,
        api_key_configured=api_key_configured,
        max_results=cr.retrieval.max_results,
        timeout_seconds=cr.retrieval.timeout_seconds,
        funding_query_template=cr.retrieval.funding_query_template,
        sentiment_query_template=cr.retrieval.sentiment_query_template,
        confidence_floor=cr.confidence_floor,
        staleness_months=cr.staleness_months,
        source_trust_order=cr.source_trust_order,
        user_agent=cr.user_agent,
    )


@router.put("/company-research", response_model=MessageResponse)
def update_retrieval_settings(body: RetrievalSettingsUpdate):
    """Update retrieval settings. Writes API key to .env, reference to company_research.yml.

    Mirrors the LLM provider key-save pattern from api/models.py:
    - Literal key → .env under RETRIEVAL_API_KEY
    - ${RETRIEVAL_API_KEY} reference → company_research.yml
    - os.environ.update so key takes effect without restart
    """
    data = _load_cr_yaml()

    if not data:
        data = _seed_cr_yaml()

    retrieval = data.setdefault("retrieval", {})

    if body.provider_type is not None:
        retrieval["type"] = body.provider_type

    if body.api_key is not None:
        from seeker_os.env_utils import write_env
        write_env({RETRIEVAL_API_KEY_ENV: body.api_key})
        retrieval["api_key"] = f"${{{RETRIEVAL_API_KEY_ENV}}}"

    if body.max_results is not None:
        retrieval["max_results"] = body.max_results

    if body.timeout_seconds is not None:
        retrieval["timeout_seconds"] = body.timeout_seconds

    if body.funding_query_template is not None:
        retrieval["funding_query_template"] = body.funding_query_template

    if body.sentiment_query_template is not None:
        retrieval["sentiment_query_template"] = body.sentiment_query_template

    if body.confidence_floor is not None:
        data["confidence_floor"] = body.confidence_floor

    if body.staleness_months is not None:
        data["staleness_months"] = body.staleness_months

    if body.source_trust_order is not None:
        data["source_trust_order"] = body.source_trust_order

    if body.user_agent is not None:
        data["user_agent"] = body.user_agent

    _save_cr_yaml(data)

    from seeker_os.config import invalidate_settings_cache
    invalidate_settings_cache()

    return MessageResponse(message="Company research settings saved")


@router.post("/company-research/test-connection", response_model=TestConnectionResponse)
def test_retrieval_connection():
    """Test that the configured retrieval adapter is reachable and the key is valid."""
    settings = get_settings()
    cr = settings.company_research

    if cr is None or not cr.retrieval or not cr.retrieval.type:
        return TestConnectionResponse(ok=False, message="No retrieval provider configured")

    if not cr.retrieval.api_key:
        return TestConnectionResponse(ok=False, message="No API key configured")

    # Detect unresolved ${VAR} references (env var not set)
    if cr.retrieval.api_key.startswith("${") and cr.retrieval.api_key.endswith("}"):
        var_name = cr.retrieval.api_key[2:-1]
        if not os.environ.get(var_name):
            return TestConnectionResponse(ok=False, message=f"API key env var {var_name} not set")

    try:
        from seeker_os.research.retrieval.registry import build_retrieval_adapter
        adapter = build_retrieval_adapter(cr.retrieval.model_dump())
        if adapter is None:
            return TestConnectionResponse(ok=False, message="Failed to build retrieval adapter")
        ok = adapter.test_connection()
        return TestConnectionResponse(
            ok=ok,
            message="Connection successful" if ok else "Connection failed — check API key and network",
        )
    except Exception:
        logger.exception("Retrieval connection test failed")
        return TestConnectionResponse(ok=False, message="Connection test failed — see server logs for details")
