"""Models API routes — LLM provider and model management."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from seeker_os.api.schemas import MessageResponse

router = APIRouter(prefix="/api/models", tags=["models"])


class ModelInfoResponse(BaseModel):
    id: str
    label: str
    provider_id: str
    context_window: int | None = None
    max_output: int | None = None
    tags: list[str] = []
    source: str = "manual"
    available: bool = True


class ProviderInfoResponse(BaseModel):
    id: str
    type: str
    label: str
    enabled: bool = True
    auto_fetch_models: bool = False
    models: list[ModelInfoResponse] = []
    healthy: bool | None = None
    health_message: str = ""


class TierMappingResponse(BaseModel):
    provider: str
    model: str


class TaskOverrideResponse(BaseModel):
    tier: str
    provider: str | None = None
    model: str | None = None


class ProvidersConfigResponse(BaseModel):
    providers: list[ProviderInfoResponse] = []
    tiers: dict[str, TierMappingResponse] = {}
    tasks: dict[str, TaskOverrideResponse] = {}


@router.get("", response_model=ProvidersConfigResponse)
def get_providers_config():
    """Get all providers, their models, tier mappings, and task overrides."""
    from seeker_os.config import Settings
    from seeker_os.llm.router import ModelRouter

    settings = Settings()
    if not settings.providers:
        return ProvidersConfigResponse()

    router_client = ModelRouter(settings)
    router_client._init_providers()

    providers_response: list[ProviderInfoResponse] = []

    for pc in settings.providers.providers:
        # Get models (merge manual + auto-fetched)
        models: list[ModelInfoResponse] = []
        try:
            all_models = router_client.list_all_models(provider_id=pc.id)
            models = [
                ModelInfoResponse(
                    id=m.id,
                    label=m.label,
                    provider_id=m.provider_id,
                    context_window=m.context_window,
                    max_output=m.max_output,
                    tags=m.tags,
                    source=m.source,
                    available=m.available,
                )
                for m in all_models
            ]
        except Exception:
            pass

        # Check health if provider is available
        healthy = None
        health_message = ""
        if pc.id in router_client._providers:
            try:
                health = router_client._providers[pc.id].test_connection()
                healthy = health.healthy
                health_message = health.message
            except Exception as e:
                healthy = False
                health_message = str(e)

        providers_response.append(ProviderInfoResponse(
            id=pc.id,
            type=pc.type,
            label=pc.label or pc.id,
            enabled=pc.enabled,
            auto_fetch_models=pc.auto_fetch_models,
            models=models,
            healthy=healthy,
            health_message=health_message,
        ))

    tiers = {
        k: TierMappingResponse(provider=v.provider, model=v.model)
        for k, v in (settings.providers.tiers or {}).items()
    }

    tasks = {
        k: TaskOverrideResponse(tier=v.tier, provider=v.provider, model=v.model)
        for k, v in (settings.providers.tasks or {}).items()
    }

    return ProvidersConfigResponse(
        providers=providers_response,
        tiers=tiers,
        tasks=tasks,
    )


@router.post("/fetch/{provider_id}", response_model=list[ModelInfoResponse])
def fetch_models(provider_id: str):
    """Fetch models from a provider's API and cache them."""
    from seeker_os.config import Settings
    from seeker_os.llm.router import ModelRouter
    from seeker_os.llm.cache import save_cached_models

    settings = Settings()
    if not settings.providers:
        raise HTTPException(status_code=400, detail="No providers configured")

    router_client = ModelRouter(settings)
    providers = router_client.get_available_providers()

    if provider_id not in providers:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not available")

    try:
        models = providers[provider_id].list_models()
        save_cached_models(provider_id, models)
        return [
            ModelInfoResponse(
                id=m.id,
                label=m.label,
                provider_id=m.provider_id,
                context_window=m.context_window,
                tags=m.tags,
                source=m.source,
                available=m.available,
            )
            for m in models
        ]
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch models: {e}")


@router.post("/test/{provider_id}", response_model=dict)
def test_provider(provider_id: str):
    """Test connectivity to a provider."""
    from seeker_os.config import Settings
    from seeker_os.llm.router import ModelRouter

    settings = Settings()
    if not settings.providers:
        raise HTTPException(status_code=400, detail="No providers configured")

    router_client = ModelRouter(settings)
    providers = router_client.get_available_providers()

    if provider_id not in providers:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not available")

    health = providers[provider_id].test_connection()
    return {
        "provider_id": health.provider_id,
        "healthy": health.healthy,
        "message": health.message,
        "latency_ms": health.latency_ms,
    }


@router.post("/test-all", response_model=list[dict])
def test_all_providers():
    """Test connectivity to all configured providers."""
    from seeker_os.config import Settings
    from seeker_os.llm.router import ModelRouter

    settings = Settings()
    if not settings.providers:
        return []

    router_client = ModelRouter(settings)
    results = router_client.test_all_providers()
    return [
        {
            "provider_id": h.provider_id,
            "healthy": h.healthy,
            "message": h.message,
            "latency_ms": h.latency_ms,
        }
        for h in results
    ]
