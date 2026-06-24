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
    auth_method: str = "api_key"
    oauth_token_path: str | None = None
    base_url: str | None = None
    # api_key is never sent to the frontend — only whether it's set
    api_key_set: bool = False
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


class ProviderUpdateRequest(BaseModel):
    """PUT /api/models/providers/{id} — update provider settings."""
    label: str | None = None
    api_key: str | None = None  # new API key value (raw, not env var). None = unchanged
    base_url: str | None = None
    enabled: bool | None = None
    auto_fetch_models: bool | None = None
    auth_method: str | None = None  # 'api_key' or 'oauth'
    oauth_token_path: str | None = None


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
            auth_method=pc.auth_method,
            oauth_token_path=pc.oauth_token_path,
            base_url=pc.base_url,
            api_key_set=bool(pc.api_key),
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


@router.put("/providers/{provider_id}", response_model=ProviderInfoResponse)
def update_provider(provider_id: str, body: ProviderUpdateRequest):
    """Update a provider's settings and write back to providers.yml.

    Only fields that are provided (non-None) are updated.
    API keys are written as env var references (${VAR_NAME}) to .env,
    not stored literally in providers.yml.
    """
    import os
    import yaml
    from seeker_os.config import Settings, CONFIG_DIR, PROJECT_ROOT

    settings = Settings()
    if not settings.providers:
        raise HTTPException(status_code=400, detail="No providers configured")

    # Find the provider in config
    providers_yml_path = CONFIG_DIR / "providers.yml"
    if not providers_yml_path.exists():
        raise HTTPException(status_code=404, detail="providers.yml not found")

    with open(providers_yml_path) as f:
        raw = yaml.safe_load(f)

    providers_list = raw.get("providers", [])
    provider_found = None
    for p in providers_list:
        if p.get("id") == provider_id:
            provider_found = p
            break

    if provider_found is None:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found in providers.yml")

    # Apply updates
    env_updates: dict[str, str] = {}

    if body.label is not None:
        provider_found["label"] = body.label
    if body.base_url is not None:
        provider_found["base_url"] = body.base_url
    if body.enabled is not None:
        provider_found["enabled"] = body.enabled
    if body.auto_fetch_models is not None:
        provider_found["auto_fetch_models"] = body.auto_fetch_models
    if body.auth_method is not None:
        provider_found["auth_method"] = body.auth_method
    if body.oauth_token_path is not None:
        provider_found["oauth_token_path"] = body.oauth_token_path

    if body.api_key is not None:
        # Store the API key in .env, reference it in providers.yml
        env_var_name = f"{provider_id.upper()}_API_KEY"
        env_updates[env_var_name] = body.api_key
        provider_found["api_key"] = f"${{{env_var_name}}}"

    # Write .env updates (append or update)
    if env_updates:
        env_path = PROJECT_ROOT / ".env"
        existing_env = {}
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    k, _, v = line.partition("=")
                    existing_env[k.strip()] = v.strip()

        existing_env.update(env_updates)
        env_lines = [f"{k}={v}" for k, v in existing_env.items()]
        env_path.write_text("\n".join(env_lines) + "\n")

    # Write providers.yml back
    with open(providers_yml_path, "w") as f:
        yaml.dump(raw, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    # Reload and return updated provider
    settings = Settings()
    router_client = __import__("seeker_os.llm.router", fromlist=["ModelRouter"]).ModelRouter(settings)
    router_client._init_providers()

    # Find the updated provider config
    pc = next((p for p in settings.providers.providers if p.id == provider_id), None)
    if not pc:
        raise HTTPException(status_code=500, detail="Provider disappeared after update")

    # Get models
    models: list[ModelInfoResponse] = []
    try:
        all_models = router_client.list_all_models(provider_id=pc.id)
        models = [
            ModelInfoResponse(
                id=m.id, label=m.label, provider_id=m.provider_id,
                context_window=m.context_window, max_output=m.max_output,
                tags=m.tags, source=m.source, available=m.available,
            )
            for m in all_models
        ]
    except Exception:
        pass

    # Check health
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

    return ProviderInfoResponse(
        id=pc.id,
        type=pc.type,
        label=pc.label or pc.id,
        enabled=pc.enabled,
        auto_fetch_models=pc.auto_fetch_models,
        auth_method=pc.auth_method,
        oauth_token_path=pc.oauth_token_path,
        base_url=pc.base_url,
        api_key_set=bool(pc.api_key),
        models=models,
        healthy=healthy,
        health_message=health_message,
    )
