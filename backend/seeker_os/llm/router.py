"""Model router — maps tasks to providers and models via config.

Resolution order:
1. Check tasks[task] for per-task override (provider + model)
2. Fall back to tier default (tiers[tier].provider + tiers[tier].model)
3. If resolved provider/model unavailable, use tier fallback
4. If fallback also unavailable, raise
"""

from __future__ import annotations

import os
from pathlib import Path

from seeker_os.config import Settings, ProviderConfig, ProvidersConfig, TierMapping, TaskOverride
from seeker_os.llm.models import LLMRequest, LLMResponse, ModelInfo, ProviderHealth
from seeker_os.llm.base import LLMProvider
from seeker_os.llm.anthropic_provider import AnthropicProvider
from seeker_os.llm.openai_compat_provider import OpenAICompatProvider


def _resolve_env(value: str) -> str:
    """Resolve ${ENV_VAR} references to actual env values."""
    if value.startswith("${") and value.endswith("}"):
        env_name = value[2:-1]
        return os.environ.get(env_name, "")
    return value


def create_provider(config: ProviderConfig) -> LLMProvider:
    """Create a provider instance from config."""
    api_key = _resolve_env(config.api_key or "")

    if config.type == "anthropic":
        return AnthropicProvider(
            provider_id=config.id,
            api_key=api_key,
            base_url=config.base_url,
            label=config.label,
        )
    elif config.type == "openai_compatible":
        if not config.base_url:
            raise ValueError(f"Provider '{config.id}' is openai_compatible but has no base_url")
        return OpenAICompatProvider(
            provider_id=config.id,
            api_key=api_key or "unused",
            base_url=config.base_url,
            label=config.label,
        )
    else:
        raise ValueError(f"Unknown provider type: {config.type}")


class ModelRouter:
    """Routes tasks to the correct provider + model based on config.

    Usage:
        router = ModelRouter(settings)
        response = router.generate("resume_generation", system_prompt, user_prompt)
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._providers: dict[str, LLMProvider] = {}
        self._provider_configs: dict[str, ProviderConfig] = {}
        self._initialized = False

    def _init_providers(self):
        """Lazily initialize provider clients."""
        if self._initialized:
            return

        config: ProvidersConfig | None = self.settings.providers
        if not config:
            raise RuntimeError("No providers configured (config/providers.yml missing or empty)")

        for pc in config.providers:
            if not pc.enabled:
                continue
            try:
                provider = create_provider(pc)
                self._providers[pc.id] = provider
                self._provider_configs[pc.id] = pc
            except Exception as e:
                # Provider failed to init — skip it, will be reported in health checks
                print(f"Warning: provider '{pc.id}' failed to initialize: {e}")

        self._initialized = True

    def get_provider(self, provider_id: str) -> LLMProvider:
        """Get a provider by ID."""
        self._init_providers()
        if provider_id not in self._providers:
            raise ValueError(f"Provider '{provider_id}' not available (not configured or failed to init)")
        return self._providers[provider_id]

    def get_available_providers(self) -> dict[str, LLMProvider]:
        """Get all available (initialized) providers."""
        self._init_providers()
        return dict(self._providers)

    def resolve(self, task: str) -> tuple[LLMProvider, str]:
        """Resolve a task name to (provider, model).

        1. Check tasks[task] for per-task override
        2. Fall back to tier default
        3. If provider/model unavailable, use tier fallback
        4. If fallback also unavailable, raise
        """
        self._init_providers()
        config = self.settings.providers
        if not config:
            raise RuntimeError("No providers configured")

        # Step 1: Check per-task override
        task_config = config.tasks.get(task)
        if task_config:
            tier = task_config.tier
            if task_config.provider and task_config.model:
                # Explicit provider + model override
                provider = self._providers.get(task_config.provider)
                if provider:
                    return provider, task_config.model
            # Fall through to tier default if override provider unavailable

        # Step 2: Use tier default
        tier_config = config.tiers.get(tier) if task_config else None
        if not task_config and not tier_config:
            # No task override — try to infer tier from task name
            tier = self._infer_tier(task)
            tier_config = config.tiers.get(tier)

        if not tier_config:
            raise ValueError(f"No tier mapping for task '{task}' and no fallback tier found")

        provider = self._providers.get(tier_config.provider)
        if provider:
            return provider, tier_config.model

        # Step 3: Use tier fallback
        fallback = getattr(tier_config, "fallback", None)
        if fallback:
            fb_provider = self._providers.get(fallback.provider)
            if fb_provider:
                return fb_provider, fallback.model

        raise ValueError(
            f"Cannot resolve task '{task}': "
            f"provider '{tier_config.provider}' unavailable and no working fallback"
        )

    def _infer_tier(self, task: str) -> str:
        """Infer a tier from a task name if not explicitly configured."""
        if "generation" in task or "resume" in task:
            return "heavy"
        if "validation" in task or "extraction" in task or "check" in task:
            return "light"
        return "moderate"

    def generate(
        self,
        task: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Generate a response for a given task."""
        provider, model = self.resolve(task)
        request = LLMRequest(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            task=task,
        )
        return provider.generate(request)

    def list_all_models(self, provider_id: str | None = None) -> list[ModelInfo]:
        """List models from all providers or a specific one.

        Merges manually configured models with auto-fetched ones.
        """
        self._init_providers()
        config = self.settings.providers
        if not config:
            return []

        results: list[ModelInfo] = []

        providers_to_query = (
            {provider_id: self._providers[provider_id]} if provider_id
            else self._providers
        )

        for pid, provider in providers_to_query.items():
            pc = self._provider_configs.get(pid)
            if not pc:
                continue

            # Start with manually configured models
            manual_models = {
                m.id: ModelInfo(
                    id=m.id,
                    label=m.label or m.id,
                    provider_id=pid,
                    context_window=getattr(m, "context_window", None),
                    max_output=getattr(m, "max_output", None),
                    tags=getattr(m, "tags", []),
                    source="manual",
                    available=True,
                )
                for m in pc.models
            }

            # Auto-fetch if configured
            if pc.auto_fetch_models:
                try:
                    auto_models = provider.list_models()
                    for am in auto_models:
                        if am.id in manual_models:
                            # Update availability, keep manual tags/label
                            manual_models[am.id].available = am.available
                            manual_models[am.id].fetched_at = am.fetched_at
                        else:
                            # New auto-discovered model
                            am.tags = ["untagged"]
                            manual_models[am.id] = am
                except Exception as e:
                    print(f"Warning: failed to fetch models from '{pid}': {e}")

            results.extend(manual_models.values())

        return results

    def test_all_providers(self) -> list[ProviderHealth]:
        """Test connectivity to all configured providers."""
        self._init_providers()
        results: list[ProviderHealth] = []
        for pid, provider in self._providers.items():
            results.append(provider.test_connection())
        return results
