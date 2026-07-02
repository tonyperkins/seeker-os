"""Model router — maps tasks to providers and models via config.

Resolution order:
1. Check tasks[task] for per-task override (provider + model)
2. Fall back to tier default (tiers[tier].provider + tiers[tier].model)
3. If resolved provider/model unavailable, use tier fallback
4. If fallback also unavailable, raise
"""

from __future__ import annotations

import logging
import os

from seeker_os.config import Settings, ProviderConfig, ProvidersConfig, ProviderModel
from seeker_os.llm.models import LLMRequest, LLMResponse, ModelInfo, ProviderHealth, TruncationError
from seeker_os.llm.base import LLMProvider

logger = logging.getLogger(__name__)


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
        from seeker_os.llm.anthropic_provider import AnthropicProvider
        return AnthropicProvider(
            provider_id=config.id,
            api_key=api_key,
            base_url=config.base_url,
            label=config.label,
        )
    elif config.type == "openai_compatible":
        from seeker_os.llm.openai_compat_provider import OpenAICompatProvider
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
                # Override provider unavailable — try the override's model
                # on the tier's provider (the model may be available there too)
                tier_config = config.tiers.get(tier)
                if tier_config:
                    tier_provider = self._providers.get(tier_config.provider)
                    if tier_provider:
                        # Check if the override model exists on the tier provider
                        tier_models = tier_provider.list_models() if hasattr(tier_provider, "list_models") else []
                        if task_config.model in {m.id for m in tier_models}:
                            return tier_provider, task_config.model
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
        if "critique" in task or "analysis" in task:
            return "moderate"
        logger.warning(
            "Task '%s' has no explicit tier mapping and no keyword matched in _infer_tier — "
            "silently falling back to 'moderate' tier. Register this task in providers.yml "
            "to avoid silent mis-routing.",
            task,
        )
        return "moderate"

    # --- Per-task max_tokens defaults (FIX 3) ---

    # These are generous defaults used when the task is not explicitly configured
    # in providers.yml. They can be overridden per-task via config.
    _TASK_MAX_TOKENS_DEFAULTS: dict[str, int] = {
        "jd_analysis": 16000,
        "resume_generation_standard": 16000,
        "resume_generation_high_value": 16000,
        "cover_letter_generation": 4000,
        "application_answer_generation": 2000,
        "application_answer_critique": 2000,
        "accuracy_validation": 16000,
        "metadata_extraction": 1000,
        "resume_parsing": 2000,
        "company_dossier_generation": 16000,
        "onboarding_interview": 4096,
    }

    # Fallback for tasks not in the defaults table
    _DEFAULT_MAX_TOKENS = 4096

    def get_task_max_tokens(self, task: str) -> int:
        """Resolve the max_tokens for a task from config, falling back to defaults.

        Priority:
        1. tasks[task].max_tokens (if set in providers.yml)
        2. _TASK_MAX_TOKENS_DEFAULTS[task]
        3. _DEFAULT_MAX_TOKENS
        """
        config = self.settings.providers
        if config:
            task_config = config.tasks.get(task)
            if task_config and task_config.max_tokens is not None:
                return task_config.max_tokens
        return self._TASK_MAX_TOKENS_DEFAULTS.get(task, self._DEFAULT_MAX_TOKENS)

    # --- Model max_output ceiling enforcement (FIX 2) ---

    def _get_model_max_output(self, provider_id: str, model_id: str) -> int | None:
        """Look up a model's max_output from the provider config."""
        config = self.settings.providers
        if not config:
            return None
        pc = config.providers
        for p in pc:
            if p.id != provider_id:
                continue
            for m in p.models:
                if m.id == model_id:
                    return m.max_output
            break
        return None

    def _enforce_max_output_ceiling(
        self,
        task: str,
        provider_id: str,
        model_id: str,
        max_tokens: int | None,
        explicitly_requested: bool = True,
    ) -> int | None:
        """Cap max_tokens at the model's max_output if known.

        If max_tokens exceeds the model's max_output:
        - When explicitly_requested=True: raise a clear error.
        - When explicitly_requested=False (resolved from defaults): cap silently.
        If max_tokens is None, return the model's max_output (or None if unknown).
        """
        model_max = self._get_model_max_output(provider_id, model_id)
        if model_max is None:
            # Unknown ceiling — pass through as-is
            return max_tokens

        if max_tokens is None:
            # Use the model's max_output as the limit
            return model_max

        if max_tokens > model_max:
            if explicitly_requested:
                raise ValueError(
                    f"Task '{task}' requests max_tokens={max_tokens}, but routed model "
                    f"'{model_id}' (provider '{provider_id}') caps at max_output={model_max}. "
                    f"Lower the request in config or route to a higher-capacity model."
                )
            # Resolved from defaults — cap silently
            logger.warning(
                "Task '%s' default max_tokens=%d exceeds model '%s' max_output=%d — capping",
                task, max_tokens, model_id, model_max,
            )
            return model_max

        return max_tokens

    def generate(
        self,
        task: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Generate a response for a given task.

        If max_tokens is None, it is resolved from per-task config/defaults.
        Before the call, the requested max_tokens is checked against the routed
        model's max_output ceiling — raises ValueError if explicitly exceeded,
        caps silently if resolved from defaults.
        """
        provider, model = self.resolve(task)

        # Track whether max_tokens was explicitly provided by the caller
        explicitly_requested = max_tokens is not None

        # Resolve max_tokens from config if not explicitly provided
        if max_tokens is None:
            max_tokens = self.get_task_max_tokens(task)

        # Enforce model max_output ceiling (FIX 2)
        provider_id = provider.id
        max_tokens = self._enforce_max_output_ceiling(
            task, provider_id, model, max_tokens,
            explicitly_requested=explicitly_requested,
        )

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
