"""Tests for the LLM provider abstraction, router, and model cache."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from seeker_os.llm.models import LLMRequest, LLMResponse, ModelInfo, ProviderHealth
from seeker_os.llm.cache import save_cached_models, get_cached_models, clear_cache, CACHE_DIR


class TestLLMModels:
    def test_llm_request_defaults(self):
        req = LLMRequest(system_prompt="sys", user_prompt="usr", model="m1")
        assert req.temperature == 0.7
        assert req.max_tokens is None
        assert req.stream is False
        assert req.task == ""

    def test_llm_response(self):
        resp = LLMResponse(text="hello", model="m1", provider="p1", input_tokens=10, output_tokens=5)
        assert resp.text == "hello"
        assert resp.input_tokens == 10

    def test_model_info_defaults(self):
        mi = ModelInfo(id="m1", label="Model 1", provider_id="p1")
        assert mi.tags == []
        assert mi.source == "manual"
        assert mi.available is True


class TestModelCache:
    def test_save_and_get_cache(self):
        models = [
            ModelInfo(id="m1", label="Model 1", provider_id="test_provider", tags=["heavy"]),
            ModelInfo(id="m2", label="Model 2", provider_id="test_provider", tags=["light"]),
        ]
        save_cached_models("test_provider", models)

        cached = get_cached_models("test_provider")
        assert cached is not None
        assert len(cached) == 2
        assert cached[0].id == "m1"
        assert cached[1].tags == ["light"]

        clear_cache("test_provider")

    def test_get_cache_missing(self):
        result = get_cached_models("nonexistent_provider_xyz")
        assert result is None

    def test_clear_cache(self):
        models = [ModelInfo(id="m1", label="M1", provider_id="test_clear")]
        save_cached_models("test_clear", models)
        clear_cache("test_clear")
        assert get_cached_models("test_clear") is None


class TestRouterResolution:
    """Test router task resolution without making real API calls."""

    def test_resolve_env(self):
        from seeker_os.llm.router import _resolve_env
        os.environ["TEST_LLM_KEY"] = "secret123"
        assert _resolve_env("${TEST_LLM_KEY}") == "secret123"
        assert _resolve_env("literal_value") == "literal_value"
        del os.environ["TEST_LLM_KEY"]

    def test_create_provider_anthropic(self):
        from seeker_os.config import ProviderConfig
        from seeker_os.llm.router import create_provider
        from seeker_os.llm.anthropic_provider import AnthropicProvider

        config = ProviderConfig(id="test", type="anthropic", api_key="sk-test")
        provider = create_provider(config)
        assert isinstance(provider, AnthropicProvider)
        assert provider.id == "test"
        assert provider.type == "anthropic"

    def test_create_provider_openai_compat(self):
        from seeker_os.config import ProviderConfig
        from seeker_os.llm.router import create_provider
        from seeker_os.llm.openai_compat_provider import OpenAICompatProvider

        config = ProviderConfig(
            id="test_oai", type="openai_compatible",
            api_key="sk-test", base_url="http://localhost:11434/v1",
        )
        provider = create_provider(config)
        assert isinstance(provider, OpenAICompatProvider)
        assert provider.id == "test_oai"

    def test_create_provider_unknown_type(self):
        from seeker_os.config import ProviderConfig
        from seeker_os.llm.router import create_provider

        config = ProviderConfig(id="bad", type="unknown", api_key="x")
        with pytest.raises(ValueError, match="Unknown provider type"):
            create_provider(config)

    def test_router_resolve_task(self):
        """Test that the router resolves tasks correctly using mock providers."""
        from seeker_os.config import Settings, ProvidersConfig, ProviderConfig, TierMapping, TaskOverride
        from seeker_os.llm.router import ModelRouter
        from seeker_os.llm.base import LLMProvider
        from seeker_os.llm.models import LLMRequest, LLMResponse, ModelInfo, ProviderHealth

        # Create a mock provider
        class MockProvider:
            def __init__(self, pid):
                self._id = pid
            @property
            def id(self): return self._id
            @property
            def type(self): return "mock"
            def generate(self, request): return LLMResponse(text="mock", model=request.model, provider=self._id)
            def list_models(self): return []
            def test_connection(self): return ProviderHealth(provider_id=self._id, healthy=True)

        # Build settings with mock config
        settings = Settings.__new__(Settings)
        settings.providers = ProvidersConfig(
            providers=[
                ProviderConfig(id="p1", type="anthropic", api_key="x", enabled=True),
            ],
            tiers={
                "heavy": TierMapping(provider="p1", model="big-model"),
                "light": TierMapping(provider="p1", model="small-model"),
            },
            tasks={
                "resume_generation": TaskOverride(tier="heavy"),
            },
        )

        router = ModelRouter(settings)
        router._providers = {"p1": MockProvider("p1")}
        router._provider_configs = {"p1": ProviderConfig(id="p1", type="anthropic", api_key="x")}
        router._initialized = True

        # Test task resolution
        provider, model = router.resolve("resume_generation")
        assert provider.id == "p1"
        assert model == "big-model"

        # Test generate
        response = router.generate("resume_generation", "sys", "usr")
        assert response.text == "mock"
        assert response.provider == "p1"
        assert response.model == "big-model"

    def test_router_no_providers(self):
        from seeker_os.config import Settings
        from seeker_os.llm.router import ModelRouter

        settings = Settings.__new__(Settings)
        settings.providers = None

        router = ModelRouter(settings)
        with pytest.raises(RuntimeError, match="No providers configured"):
            router.resolve("any_task")
