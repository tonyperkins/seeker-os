"""Models API routes — LLM provider and model management."""

from __future__ import annotations

import logging
import threading as _threading

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
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
    input_price_per_mtok: float | None = None
    output_price_per_mtok: float | None = None
    pricing_source: str | None = None


class ProviderInfoResponse(BaseModel):
    id: str
    type: str
    label: str
    enabled: bool = True
    auto_fetch_models: bool = False
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
    default_tier: str | None = None


class ProvidersConfigResponse(BaseModel):
    providers: list[ProviderInfoResponse] = []
    tiers: dict[str, TierMappingResponse] = {}
    tasks: dict[str, TaskOverrideResponse] = {}
    partial: bool = False
    warnings: list[str] = []


class ProviderUpdateRequest(BaseModel):
    """PUT /api/models/providers/{id} — update provider settings."""
    label: str | None = None
    api_key: str | None = None  # new API key value (raw, not env var). None = unchanged
    base_url: str | None = None
    enabled: bool | None = None
    auto_fetch_models: bool | None = None


@router.get("", response_model=ProvidersConfigResponse)
def get_providers_config():
    """Get all providers, their models, tier mappings, and task overrides."""
    from seeker_os.config import get_settings
    from seeker_os.llm.router import ModelRouter

    settings = get_settings()
    if not settings.providers:
        return ProvidersConfigResponse()

    router_client = ModelRouter(settings)
    router_client._init_providers()

    providers_response: list[ProviderInfoResponse] = []
    warnings: list[str] = []

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
                    input_price_per_mtok=m.input_price_per_mtok,
                    output_price_per_mtok=m.output_price_per_mtok,
                    pricing_source=m.pricing_source,
                )
                for m in all_models
            ]
        except KeyError:
            # Disabled or unauthenticated providers are intentionally absent
            # from the live router; their configured models remain visible.
            models = [
                ModelInfoResponse(
                    id=m.id,
                    label=m.label,
                    provider_id=pc.id,
                    context_window=m.context_window,
                    max_output=m.max_output,
                    tags=m.tags,
                    source="manual",
                    available=False,
                    input_price_per_mtok=m.input_price_per_mtok,
                    output_price_per_mtok=m.output_price_per_mtok,
                    pricing_source="manual" if m.input_price_per_mtok is not None or m.output_price_per_mtok is not None else None,
                )
                for m in pc.models
            ]
        except Exception:
            logger.exception("Failed to enumerate models for provider '%s'", pc.id)
            warnings.append(f"Models for provider '{pc.id}' are unavailable.")

        # Health is intentionally NOT probed here: this endpoint is hit on every
        # dashboard load and a synchronous test_connection() per provider adds N
        # network round-trips (seconds when a provider is down). healthy=None
        # means "unknown — not yet checked"; the UI calls POST /test/{id} (or
        # /test-all) on demand. See audit §2.11.
        healthy = None
        health_message = ""

        # Check if auth is available — an unresolved ${VAR_NAME} placeholder
        # means the env var is not set, so we must not treat it as a real key.
        auth_available = bool(pc.api_key) and not pc.api_key.startswith("${")

        providers_response.append(ProviderInfoResponse(
            id=pc.id,
            type=pc.type,
            label=pc.label or pc.id,
            enabled=pc.enabled,
            auto_fetch_models=pc.auto_fetch_models,
            base_url=pc.base_url,
            api_key_set=auth_available,
            models=models,
            healthy=healthy,
            health_message=health_message,
        ))

    tiers = {
        k: TierMappingResponse(provider=v.provider, model=v.model)
        for k, v in (settings.providers.tiers or {}).items()
    }

    tasks = {
        k: TaskOverrideResponse(
            tier=v.tier,
            provider=v.provider,
            model=v.model,
            default_tier=router_client._infer_tier(k),
        )
        for k, v in (settings.providers.tasks or {}).items()
    }

    return ProvidersConfigResponse(
        providers=providers_response,
        tiers=tiers,
        tasks=tasks,
        partial=bool(warnings),
        warnings=warnings,
    )


@router.post("/fetch/{provider_id}", response_model=list[ModelInfoResponse])
def fetch_models(provider_id: str):
    """Fetch models from a provider's API and cache them."""
    from seeker_os.config import get_settings
    from seeker_os.llm.cache import save_cached_models
    from seeker_os.llm.router import ModelRouter

    settings = get_settings()
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
                input_price_per_mtok=m.input_price_per_mtok,
                output_price_per_mtok=m.output_price_per_mtok,
            )
            for m in models
        ]
    except Exception as e:
        logger.exception("Failed to fetch models from provider '%s'", provider_id)
        raise HTTPException(status_code=502, detail=f"Failed to fetch models from {provider_id}: {e}")


@router.post("/test/{provider_id}", response_model=dict)
def test_provider(provider_id: str):
    """Test connectivity to a provider."""
    from seeker_os.config import get_settings
    from seeker_os.llm.router import ModelRouter

    settings = get_settings()
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
    from seeker_os.config import get_settings
    from seeker_os.llm.router import ModelRouter

    settings = get_settings()
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
    import yaml

    from seeker_os.config import CONFIG_DIR, get_settings

    settings = get_settings()
    if not settings.providers:
        raise HTTPException(status_code=400, detail="No providers configured")

    # Find the provider in config
    providers_yml_path = CONFIG_DIR / "providers.yml"
    if not providers_yml_path.exists():
        raise HTTPException(status_code=404, detail="providers.yml not found")

    # Serialize the read-modify-write of providers.yml under the same lock as
    # update_tier/update_task so concurrent config edits can't lose each other's
    # writes (read-modify-write on the same file is otherwise a lost-update race).
    with _providers_yml_lock:
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

        if body.api_key is not None:
            # Store the API key in .env, reference it in providers.yml
            env_var_name = f"{provider_id.upper()}_API_KEY"
            env_updates[env_var_name] = body.api_key
            provider_found["api_key"] = f"${{{env_var_name}}}"

        # Write .env updates (append or update)
        if env_updates:
            from seeker_os.env_utils import write_env
            write_env(env_updates)

        # Write providers.yml back
        with open(providers_yml_path, "w") as f:
            yaml.dump(raw, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

        # Invalidate cached settings so the next read reloads from disk
        from seeker_os.config import invalidate_settings_cache
        invalidate_settings_cache()

    # Reload and return updated provider
    settings = get_settings()
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
                input_price_per_mtok=m.input_price_per_mtok,
                output_price_per_mtok=m.output_price_per_mtok,
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

    auth_available = bool(pc.api_key) and not pc.api_key.startswith("${")

    return ProviderInfoResponse(
        id=pc.id,
        type=pc.type,
        label=pc.label or pc.id,
        enabled=pc.enabled,
        auto_fetch_models=pc.auto_fetch_models,
        base_url=pc.base_url,
        api_key_set=auth_available,
        models=models,
        healthy=healthy,
        health_message=health_message,
    )


class TierUpdateRequest(BaseModel):
    """PUT /api/models/tiers/{tier} — update a tier mapping."""
    provider: str
    model: str


class TaskUpdateRequest(BaseModel):
    """PUT /api/models/tasks/{task} — update a task override."""
    tier: str
    provider: str | None = None
    model: str | None = None


_providers_yml_lock = _threading.Lock()

# Canonical routing tiers (mirrors ModelRouter._infer_tier). A tier mapping
# written under any other key would never be resolved.
_VALID_TIERS = frozenset({"heavy", "moderate", "light"})


def _validate_provider_model(provider: str, model: str | None) -> None:
    """Reject an unknown provider; warn (don't reject) on an unknown model.

    A tier/task mapping pointing at a missing provider silently breaks resolve()
    mid-generation, so it's rejected here. Model lists can be auto-fetched and
    may lag config, so an unknown model is only logged.
    """
    from seeker_os.config import get_settings

    settings = get_settings()
    providers = settings.providers.providers if settings.providers else []
    pc = next((p for p in providers if p.id == provider), None)
    if pc is None:
        known = sorted(p.id for p in providers)
        raise HTTPException(
            status_code=422,
            detail=f"Unknown provider '{provider}'. Configured providers: {known}",
        )
    if model:
        known_models = {m.id for m in (pc.models or [])}
        if known_models and model not in known_models:
            logger.warning(
                "Model '%s' is not in provider '%s' config (known: %s) — "
                "writing anyway; verify it is valid.",
                model, provider, sorted(known_models),
            )


def _write_providers_yml(raw: dict) -> None:
    """Write the providers.yml config back to disk."""
    import yaml

    from seeker_os.config import CONFIG_DIR

    providers_yml_path = CONFIG_DIR / "providers.yml"
    with open(providers_yml_path, "w") as f:
        yaml.dump(raw, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    from seeker_os.config import invalidate_settings_cache
    invalidate_settings_cache()


def _read_providers_yml() -> dict:
    """Read the raw providers.yml config from disk."""
    import yaml

    from seeker_os.config import CONFIG_DIR

    providers_yml_path = CONFIG_DIR / "providers.yml"
    if not providers_yml_path.exists():
        raise HTTPException(status_code=404, detail="providers.yml not found")
    with open(providers_yml_path) as f:
        return yaml.safe_load(f)


@router.put("/tiers/{tier}", response_model=TierMappingResponse)
def update_tier(tier: str, body: TierUpdateRequest):
    """Update a tier mapping in providers.yml."""
    if tier not in _VALID_TIERS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown tier '{tier}'. Valid tiers: {', '.join(sorted(_VALID_TIERS))}",
        )
    _validate_provider_model(body.provider, body.model)
    with _providers_yml_lock:
        raw = _read_providers_yml()
        tiers = raw.setdefault("tiers", {})
        tiers[tier] = {"provider": body.provider, "model": body.model}
        _write_providers_yml(raw)
    return TierMappingResponse(provider=body.provider, model=body.model)


@router.put("/tasks/{task}", response_model=TaskOverrideResponse)
def update_task(task: str, body: TaskUpdateRequest):
    """Update a task override in providers.yml."""
    if body.tier not in _VALID_TIERS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown tier '{body.tier}'. Valid tiers: {', '.join(sorted(_VALID_TIERS))}",
        )
    if body.provider is not None:
        _validate_provider_model(body.provider, body.model)
    with _providers_yml_lock:
        raw = _read_providers_yml()
        tasks = raw.setdefault("tasks", {})
        entry: dict = {"tier": body.tier}
        if body.provider is not None:
            entry["provider"] = body.provider
        if body.model is not None:
            entry["model"] = body.model
        tasks[task] = entry
        _write_providers_yml(raw)
    return TaskOverrideResponse(tier=body.tier, provider=body.provider, model=body.model)


class ModelPricingUpdateRequest(BaseModel):
    """PUT /api/models/{provider_id}/models/{model_id}/pricing — update model pricing."""
    input_price_per_mtok: float | None = None
    output_price_per_mtok: float | None = None


class ModelPricingResponse(BaseModel):
    """Response for pricing update."""
    provider_id: str
    model_id: str
    input_price_per_mtok: float | None = None
    output_price_per_mtok: float | None = None
    pricing_source: str = "manual"


@router.put("/{provider_id}/models/{model_id}/pricing", response_model=ModelPricingResponse)
def update_model_pricing(provider_id: str, model_id: str, body: ModelPricingUpdateRequest):
    """Update a model's pricing in providers.yml.

    If the model doesn't exist in the provider's config, it will be added
    as a manual entry with the given pricing.
    """
    with _providers_yml_lock:
        raw = _read_providers_yml()
        providers_list = raw.get("providers", [])
        provider_found = None
        for p in providers_list:
            if p.get("id") == provider_id:
                provider_found = p
                break
        if provider_found is None:
            raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found in providers.yml")

        models_list = provider_found.setdefault("models", [])
        model_found = None
        for m in models_list:
            if m.get("id") == model_id:
                model_found = m
                break

        if model_found is None:
            # Create a new model entry with pricing
            model_found = {"id": model_id, "label": model_id}
            models_list.append(model_found)

        model_found["input_price_per_mtok"] = body.input_price_per_mtok
        model_found["output_price_per_mtok"] = body.output_price_per_mtok

        _write_providers_yml(raw)

    return ModelPricingResponse(
        provider_id=provider_id,
        model_id=model_id,
        input_price_per_mtok=body.input_price_per_mtok,
        output_price_per_mtok=body.output_price_per_mtok,
        pricing_source="manual",
    )


@router.delete("/{provider_id}/models/{model_id}/pricing", response_model=ModelPricingResponse)
def reset_model_pricing(provider_id: str, model_id: str):
    """Reset a model's manual pricing, allowing auto-fetched pricing to take over.

    Removes pricing fields from the model entry in providers.yml. If the model
    was auto-discovered (not in providers.yml), this is a no-op.
    """
    with _providers_yml_lock:
        raw = _read_providers_yml()
        providers_list = raw.get("providers", [])
        provider_found = None
        for p in providers_list:
            if p.get("id") == provider_id:
                provider_found = p
                break
        if provider_found is None:
            raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found in providers.yml")

        models_list = provider_found.get("models", [])
        model_found = None
        for m in models_list:
            if m.get("id") == model_id:
                model_found = m
                break

        if model_found is not None:
            model_found.pop("input_price_per_mtok", None)
            model_found.pop("output_price_per_mtok", None)
            _write_providers_yml(raw)

    return ModelPricingResponse(
        provider_id=provider_id,
        model_id=model_id,
        pricing_source="auto",
    )
