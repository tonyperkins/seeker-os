"""Tests for the LLM provider abstraction, router, and model cache."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from seeker_os.llm.models import LLMRequest, LLMResponse, ModelInfo, ProviderHealth, TruncationError
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

    def test_critique_task_resolves_to_moderate_tier(self):
        """Critique task must resolve to moderate tier deliberately, not via silent fallthrough."""
        from seeker_os.config import Settings, ProvidersConfig, ProviderConfig, TierMapping, TaskOverride
        from seeker_os.llm.router import ModelRouter

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

        settings = Settings.__new__(Settings)
        settings.providers = ProvidersConfig(
            providers=[
                ProviderConfig(id="p1", type="anthropic", api_key="x", enabled=True),
            ],
            tiers={
                "heavy": TierMapping(provider="p1", model="big-model"),
                "moderate": TierMapping(provider="p1", model="mid-model"),
                "light": TierMapping(provider="p1", model="small-model"),
            },
            tasks={
                "application_answer_critique": TaskOverride(tier="moderate"),
            },
        )

        router = ModelRouter(settings)
        router._providers = {"p1": MockProvider("p1")}
        router._provider_configs = {"p1": ProviderConfig(id="p1", type="anthropic", api_key="x")}
        router._initialized = True

        provider, model = router.resolve("application_answer_critique")
        assert provider.id == "p1"
        assert model == "mid-model"

    def test_unrecognized_task_logs_warning(self, caplog):
        """Unrecognized task name (no keyword match) must log a warning, not silently fall through."""
        import logging
        from seeker_os.config import Settings, ProvidersConfig, ProviderConfig, TierMapping
        from seeker_os.llm.router import ModelRouter

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

        settings = Settings.__new__(Settings)
        settings.providers = ProvidersConfig(
            providers=[
                ProviderConfig(id="p1", type="anthropic", api_key="x", enabled=True),
            ],
            tiers={
                "moderate": TierMapping(provider="p1", model="mid-model"),
            },
            tasks={},
        )

        router = ModelRouter(settings)
        router._providers = {"p1": MockProvider("p1")}
        router._provider_configs = {"p1": ProviderConfig(id="p1", type="anthropic", api_key="x")}
        router._initialized = True

        with caplog.at_level(logging.WARNING, logger="seeker_os.llm.router"):
            provider, model = router.resolve("totally_unknown_task_xyz")
            assert model == "mid-model"

        assert any(
            "totally_unknown_task_xyz" in record.message and "silently" in record.message
            for record in caplog.records
        ), f"Expected warning about silent fallback, got: {[r.message for r in caplog.records]}"


class TestTruncationDetection:
    """FIX 1 — Truncation detection: stop_reason == length/max_tokens raises TruncationError."""

    def test_truncation_error_raises_on_length_finish_reason(self):
        """A mocked length/max_tokens finish_reason raises TruncationError, not a parse error."""
        from seeker_os.llm.openai_compat_provider import OpenAICompatProvider

        provider = OpenAICompatProvider.__new__(OpenAICompatProvider)
        provider._id = "test"
        provider._client = MagicMock()

        # Simulate a truncated response: finish_reason="length"
        mock_choice = MagicMock()
        mock_choice.message.content = '{"claims": [truncated'
        mock_choice.finish_reason = "length"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.model = "test-model"
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 4000
        provider._client.chat.completions.create.return_value = mock_response

        request = LLMRequest(
            system_prompt="sys", user_prompt="usr", model="m1",
            max_tokens=4000, task="accuracy_validation",
        )

        with pytest.raises(TruncationError, match="truncated"):
            provider.generate(request)

    def test_truncation_error_includes_requested_and_produced_tokens(self):
        """TruncationError must include requested max_tokens and produced output_tokens."""
        from seeker_os.llm.openai_compat_provider import OpenAICompatProvider

        provider = OpenAICompatProvider.__new__(OpenAICompatProvider)
        provider._id = "test"
        provider._client = MagicMock()

        mock_choice = MagicMock()
        mock_choice.message.content = ""
        mock_choice.finish_reason = "length"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.model = "test-model"
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 4000
        provider._client.chat.completions.create.return_value = mock_response

        request = LLMRequest(
            system_prompt="sys", user_prompt="usr", model="m1",
            max_tokens=4000, task="accuracy_validation",
        )

        try:
            provider.generate(request)
            assert False, "Should have raised TruncationError"
        except TruncationError as e:
            assert e.requested_max_tokens == 4000
            assert e.output_tokens == 4000
            assert e.stop_reason == "length"
            assert "accuracy_validation" in str(e)

    def test_normal_completion_does_not_raise_truncation(self):
        """A normal stop_reason='stop' response does not raise TruncationError."""
        from seeker_os.llm.openai_compat_provider import OpenAICompatProvider

        provider = OpenAICompatProvider.__new__(OpenAICompatProvider)
        provider._id = "test"
        provider._client = MagicMock()

        mock_choice = MagicMock()
        mock_choice.message.content = '{"claims": []}'
        mock_choice.finish_reason = "stop"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.model = "test-model"
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 50
        provider._client.chat.completions.create.return_value = mock_response

        request = LLMRequest(
            system_prompt="sys", user_prompt="usr", model="m1",
            max_tokens=4000, task="test",
        )

        response = provider.generate(request)
        assert response.text == '{"claims": []}'
        assert response.stop_reason == "stop"

    def test_truncation_error_message_names_cause_and_fix(self):
        """TruncationError message must name the cause and the fix (raise limit vs fix prompt)."""
        from seeker_os.llm.openai_compat_provider import OpenAICompatProvider

        provider = OpenAICompatProvider.__new__(OpenAICompatProvider)
        provider._id = "test"
        provider._client = MagicMock()

        mock_choice = MagicMock()
        mock_choice.message.content = ""
        mock_choice.finish_reason = "max_tokens"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.model = "test-model"
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 4000
        provider._client.chat.completions.create.return_value = mock_response

        request = LLMRequest(
            system_prompt="sys", user_prompt="usr", model="m1",
            max_tokens=4000, task="test_task",
        )

        with pytest.raises(TruncationError) as exc_info:
            provider.generate(request)

        msg = str(exc_info.value)
        assert "truncated" in msg.lower()
        assert "max_tokens" in msg or "increase" in msg.lower()


class TestMaxOutputCeiling:
    """FIX 2 — Model max_output enforced as ceiling on call-time max_tokens."""

    def _make_router_with_model(self, max_output: int | None):
        """Build a router with a mock provider and a model that has the given max_output."""
        from seeker_os.config import Settings, ProvidersConfig, ProviderConfig, ProviderModel, TierMapping, TaskOverride
        from seeker_os.llm.router import ModelRouter

        class MockProvider:
            def __init__(self, pid):
                self._id = pid
            @property
            def id(self): return self._id
            @property
            def type(self): return "mock"
            def generate(self, request): return LLMResponse(text="ok", model=request.model, provider=self._id, task=request.task)
            def list_models(self): return []
            def test_connection(self): return ProviderHealth(provider_id=self._id, healthy=True)

        model = ProviderModel(id="big-model", label="Big", max_output=max_output, tags=["heavy"])
        settings = Settings.__new__(Settings)
        settings.providers = ProvidersConfig(
            providers=[
                ProviderConfig(id="p1", type="anthropic", api_key="x", enabled=True, models=[model]),
            ],
            tiers={"heavy": TierMapping(provider="p1", model="big-model")},
            tasks={"resume_generation_standard": TaskOverride(tier="heavy")},
        )

        router = ModelRouter(settings)
        router._providers = {"p1": MockProvider("p1")}
        router._provider_configs = {"p1": ProviderConfig(id="p1", type="anthropic", api_key="x", models=[model])}
        router._initialized = True
        return router

    def test_request_within_max_output_succeeds(self):
        """max_tokens <= model max_output should work fine."""
        router = self._make_router_with_model(max_output=16000)
        response = router.generate("resume_generation_standard", "sys", "usr", max_tokens=8000)
        assert response.text == "ok"

    def test_request_exceeding_max_output_raises(self):
        """max_tokens > model max_output must raise a clear ValueError."""
        router = self._make_router_with_model(max_output=8192)
        with pytest.raises(ValueError, match="caps at max_output=8192"):
            router.generate("resume_generation_standard", "sys", "usr", max_tokens=16000)

    def test_none_max_tokens_uses_model_max_output(self):
        """When max_tokens is None, the router should use the model's max_output."""
        router = self._make_router_with_model(max_output=8192)
        # Should not raise — None gets resolved to model's max_output
        response = router.generate("resume_generation_standard", "sys", "usr", max_tokens=None)
        assert response.text == "ok"

    def test_unknown_max_output_passes_through(self):
        """When model max_output is None (unknown), no ceiling is enforced."""
        router = self._make_router_with_model(max_output=None)
        # Should not raise even with a high max_tokens
        response = router.generate("resume_generation_standard", "sys", "usr", max_tokens=999999)
        assert response.text == "ok"


class TestTaskMaxTokensConfig:
    """FIX 3 — Per-task max_tokens is configurable, replacing hardcoded literals."""

    def test_known_task_returns_default(self):
        """A known task returns its default max_tokens from the defaults table."""
        from seeker_os.config import Settings, ProvidersConfig
        from seeker_os.llm.router import ModelRouter

        settings = Settings.__new__(Settings)
        settings.providers = ProvidersConfig()
        router = ModelRouter(settings)
        router._initialized = True

        assert router.get_task_max_tokens("jd_analysis") == 16000
        assert router.get_task_max_tokens("resume_generation_standard") == 16000
        assert router.get_task_max_tokens("accuracy_validation") == 16000
        assert router.get_task_max_tokens("metadata_extraction") == 1000

    def test_unknown_task_returns_fallback(self):
        """An unknown task returns the fallback default."""
        from seeker_os.config import Settings, ProvidersConfig
        from seeker_os.llm.router import ModelRouter

        settings = Settings.__new__(Settings)
        settings.providers = ProvidersConfig()
        router = ModelRouter(settings)
        router._initialized = True

        assert router.get_task_max_tokens("totally_unknown_task") == 4096

    def test_config_override_takes_priority(self):
        """A max_tokens set in providers.yml tasks overrides the built-in default."""
        from seeker_os.config import Settings, ProvidersConfig, TaskOverride
        from seeker_os.llm.router import ModelRouter

        settings = Settings.__new__(Settings)
        settings.providers = ProvidersConfig(
            tasks={"jd_analysis": TaskOverride(tier="moderate", max_tokens=8192)},
        )
        router = ModelRouter(settings)
        router._initialized = True

        assert router.get_task_max_tokens("jd_analysis") == 8192

    def test_no_hardcoded_literal_in_task_functions(self):
        """Verify that task function signatures use max_tokens=None, not hardcoded literals."""
        import inspect
        from seeker_os.analysis.jd_analyzer import analyze_job
        from seeker_os.resume.generator import generate_resume
        from seeker_os.cover_letter.generator import generate_cover_letter
        from seeker_os.application_answers.generator import generate_application_answer, critique_application_answer

        for func in [analyze_job, generate_resume, generate_cover_letter,
                     generate_application_answer, critique_application_answer]:
            sig = inspect.signature(func)
            param = sig.parameters.get("max_tokens")
            assert param is not None, f"{func.__name__} has no max_tokens parameter"
            assert param.default is None, (
                f"{func.__name__} has hardcoded max_tokens={param.default!r}, "
                f"should be None (router resolves from config)"
            )


class TestRateLimitFallback:
    """Cross-provider fallback when the primary provider returns 429."""

    def _make_router(self, primary_generate, fallback_generate=None):
        """Build a router with two mock providers for fallback testing."""
        from seeker_os.config import Settings, ProvidersConfig, ProviderConfig, TierMapping, TaskOverride
        from seeker_os.llm.router import ModelRouter

        class MockProvider:
            def __init__(self, pid, generate_fn):
                self._id = pid
                self._generate_fn = generate_fn
            @property
            def id(self): return self._id
            @property
            def type(self): return "mock"
            def generate(self, request): return self._generate_fn(request)
            def list_models(self): return []
            def test_connection(self): return ProviderHealth(provider_id=self._id, healthy=True)

        settings = Settings.__new__(Settings)
        settings.providers = ProvidersConfig(
            providers=[
                ProviderConfig(id="primary", type="anthropic", api_key="x", enabled=True),
                ProviderConfig(id="fallback", type="openai_compatible", api_key="y",
                               base_url="http://localhost:11434/v1", enabled=True),
            ],
            tiers={
                "heavy": TierMapping(provider="primary", model="big-model"),
                "moderate": TierMapping(provider="primary", model="mid-model"),
                "light": TierMapping(provider="primary", model="small-model"),
            },
            tasks={"jd_analysis": TaskOverride(tier="moderate")},
        )

        router = ModelRouter(settings)
        router._providers = {
            "primary": MockProvider("primary", primary_generate),
        }
        if fallback_generate is not None:
            router._providers["fallback"] = MockProvider("fallback", fallback_generate)
        router._provider_configs = {
            "primary": ProviderConfig(id="primary", type="anthropic", api_key="x"),
            "fallback": ProviderConfig(id="fallback", type="openai_compatible", api_key="y",
                                       base_url="http://localhost:11434/v1"),
        }
        router._initialized = True
        return router

    @staticmethod
    def _make_rate_limit_error():
        """Create a mock rate-limit error that _is_rate_limit_error will detect."""
        e = Exception("Error code: 429")
        e.status_code = 429
        return e

    def test_rate_limit_falls_back_to_second_provider(self):
        """When primary returns 429, router retries on the fallback provider."""
        call_count = {"primary": 0, "fallback": 0}

        def primary_generate(request):
            call_count["primary"] += 1
            raise self._make_rate_limit_error()

        def fallback_generate(request):
            call_count["fallback"] += 1
            return LLMResponse(text="fallback ok", model=request.model, provider="fallback")

        router = self._make_router(primary_generate, fallback_generate)

        response = router.generate("jd_analysis", "sys", "usr")
        assert response.text == "fallback ok"
        assert call_count["primary"] == 1
        assert call_count["fallback"] == 1

    def test_non_rate_limit_error_does_not_fall_back(self):
        """Non-429 errors (e.g. 400 Bad Request) propagate immediately without fallback."""
        call_count = {"primary": 0, "fallback": 0}

        def primary_generate(request):
            call_count["primary"] += 1
            raise ValueError("400 Bad Request — invalid model")

        def fallback_generate(request):
            call_count["fallback"] += 1
            return LLMResponse(text="should not reach", model=request.model, provider="fallback")

        router = self._make_router(primary_generate, fallback_generate)

        with pytest.raises(ValueError, match="400 Bad Request"):
            router.generate("jd_analysis", "sys", "usr")
        assert call_count["primary"] == 1
        assert call_count["fallback"] == 0

    def test_all_providers_rate_limited_raises_last_error(self):
        """When all providers return 429, the last rate-limit error is raised."""
        def primary_generate(request):
            raise self._make_rate_limit_error()

        def fallback_generate(request):
            raise self._make_rate_limit_error()

        router = self._make_router(primary_generate, fallback_generate)

        with pytest.raises(Exception, match="429"):
            router.generate("jd_analysis", "sys", "usr")

    def test_no_fallback_provider_raises_runtime_error(self):
        """When only one provider is available and it's rate-limited, a RuntimeError is raised."""
        def primary_generate(request):
            raise self._make_rate_limit_error()

        router = self._make_router(primary_generate, fallback_generate=None)

        with pytest.raises(RuntimeError, match="no fallback available"):
            router.generate("jd_analysis", "sys", "usr")

    def test_fallback_model_resolved_from_config_tags(self):
        """Fallback provider's model is resolved from configured model tags matching the tier."""
        from seeker_os.config import ProviderModel

        captured_model = {}

        def primary_generate(request):
            raise self._make_rate_limit_error()

        def fallback_generate(request):
            captured_model["model"] = request.model
            return LLMResponse(text="ok", model=request.model, provider="fallback")

        router = self._make_router(primary_generate, fallback_generate)
        # Add a manually configured model on the fallback provider with a 'moderate' tag
        router._provider_configs["fallback"] = router._provider_configs["fallback"].model_copy(
            update={"models": [ProviderModel(id="alt-mid-model", label="Alt Mid", tags=["moderate"])]}
        )

        response = router.generate("jd_analysis", "sys", "usr")
        assert response.text == "ok"
        assert captured_model["model"] == "alt-mid-model"

    def test_is_rate_limit_error_detects_anthropic_pattern(self):
        """_is_rate_limit_error detects anthropic.RateLimitError-like exceptions."""
        from seeker_os.llm.router import ModelRouter

        class FakeRateLimitError(Exception):
            pass

        e = FakeRateLimitError("rate_limit_error")
        assert ModelRouter._is_rate_limit_error(e)

    def test_is_rate_limit_error_detects_status_code_429(self):
        """_is_rate_limit_error detects exceptions with status_code=429."""
        from seeker_os.llm.router import ModelRouter

        e = Exception("Too Many Requests")
        e.status_code = 429
        assert ModelRouter._is_rate_limit_error(e)

    def test_is_rate_limit_error_rejects_non_429(self):
        """_is_rate_limit_error returns False for non-rate-limit exceptions."""
        from seeker_os.llm.router import ModelRouter

        assert not ModelRouter._is_rate_limit_error(ValueError("bad request"))
        assert not ModelRouter._is_rate_limit_error(RuntimeError("timeout"))
