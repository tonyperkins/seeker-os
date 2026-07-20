"""Tests for config.py warning logic — unresolved env refs and literal secrets."""

import warnings
from unittest.mock import patch, MagicMock
from pathlib import Path

import pytest

from seeker_os.config import (
    _check_unresolved_env_refs,
    _check_literal_secrets,
    resolve_env_vars,
)


class TestUnresolvedEnvRefWarnings:
    def test_warns_on_unresolved_env_var(self):
        """An unresolved ${VAR} reference should emit a warning naming the var."""
        data = {"api_key": "${NONEXISTENT_TEST_VAR_12345}"}
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _check_unresolved_env_refs(data, "test.yml")
        assert len(w) == 1
        assert "NONEXISTENT_TEST_VAR_12345" in str(w[0].message)
        assert "test.yml" in str(w[0].message)

    def test_no_warning_when_env_var_is_set(self, monkeypatch):
        """A resolved ${VAR} reference should not emit a warning."""
        monkeypatch.setenv("TEST_VAR_SET_12345", "some-value")
        data = {"api_key": "${TEST_VAR_SET_12345}"}
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _check_unresolved_env_refs(data, "test.yml")
        assert len(w) == 0

    def test_no_warning_for_plain_strings(self):
        """Non-${VAR} strings should not trigger unresolved-ref warnings."""
        data = {"label": "My Provider", "type": "anthropic"}
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _check_unresolved_env_refs(data, "test.yml")
        assert len(w) == 0

    def test_warning_does_not_print_value(self):
        """The warning must not include the value, only the var name."""
        data = {"api_key": "${SOME_SECRET_VAR}"}
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _check_unresolved_env_refs(data, "test.yml")
        msg = str(w[0].message)
        assert "SOME_SECRET_VAR" in msg
        # The warning should not contain any value-like content
        assert "sk-" not in msg
        assert "password" not in msg.lower()

    def test_nested_unresolved_ref(self):
        """Unresolved refs in nested dicts should be caught."""
        data = {"providers": [{"api_key": "${DEEP_UNSET_VAR}"}]}
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _check_unresolved_env_refs(data, "providers.yml")
        assert len(w) == 1
        assert "DEEP_UNSET_VAR" in str(w[0].message)


class TestLiteralSecretWarnings:
    def test_warns_on_literal_api_key(self):
        """A literal value in an api_key field should warn."""
        data = {"api_key": "sk-ant-literal-key-value"}
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _check_literal_secrets(data, "providers.yml")
        assert len(w) == 1
        assert "api_key" in str(w[0].message)
        assert "providers.yml" in str(w[0].message)

    def test_no_warning_for_env_var_reference(self):
        """A ${VAR} reference in api_key should not warn."""
        data = {"api_key": "${ANTHROPIC_API_KEY}"}
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _check_literal_secrets(data, "providers.yml")
        assert len(w) == 0

    def test_no_warning_for_empty_api_key(self):
        """An empty api_key should not warn (nothing to protect)."""
        data = {"api_key": ""}
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _check_literal_secrets(data, "providers.yml")
        assert len(w) == 0

    def test_warns_on_literal_token(self):
        """A literal value in a token field should warn."""
        data = {"token": "ghp_literal_token_value"}
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _check_literal_secrets(data, "test.yml")
        assert len(w) == 1
        assert "token" in str(w[0].message)

    def test_warning_does_not_print_value(self):
        """The literal-secret warning must not include the actual value."""
        data = {"api_key": "sk-super-secret-never-print-this"}
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _check_literal_secrets(data, "test.yml")
        msg = str(w[0].message)
        assert "sk-super-secret" not in msg
        assert "never-print" not in msg

    def test_nested_literal_secret(self):
        """Literal secrets in nested structures should be caught."""
        data = {"providers": [{"id": "test", "api_key": "literal-key-123"}]}
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _check_literal_secrets(data, "providers.yml")
        assert len(w) == 1
        assert "api_key" in str(w[0].message)


class TestProvidersConfigFreeTierGuard:
    """Tests for the ProvidersConfig model_validator that enforces
    allowlist-primary model policy with denylist as second layer."""

    _APPROVED = [
        "openai/gpt-5.6-terra",
        "openai/gpt-5.6-luna",
        "anthropic/claude-haiku-4.5",
    ]

    def _make_config(self, tiers=None, tasks=None, approved_models=None):
        from seeker_os.config import ProvidersConfig, ProviderConfig
        return ProvidersConfig(
            providers=[ProviderConfig(id="kilo", type="openai_compatible")],
            tiers=tiers or {},
            tasks=tasks or {},
            approved_models=approved_models if approved_models is not None else self._APPROVED,
        )

    def test_rejects_kilo_auto_free_in_tier(self):
        with pytest.raises(ValueError, match="kilo-auto"):
            self._make_config(tiers={
                "heavy": {"provider": "kilo", "model": "kilo-auto/free"}
            })

    def test_rejects_stepfun_free_in_tier(self):
        with pytest.raises(ValueError, match=":free"):
            self._make_config(tiers={
                "light": {"provider": "kilo", "model": "stepfun/step-3.7-flash:free"}
            })

    def test_rejects_big_model_in_tier(self):
        with pytest.raises(ValueError, match="big-model"):
            self._make_config(tiers={
                "heavy": {"provider": "p1", "model": "big-model"}
            })

    def test_rejects_kilo_auto_efficient_in_task(self):
        with pytest.raises(ValueError, match="auto/efficient"):
            self._make_config(tasks={
                "metadata_extraction": {
                    "tier": "light", "provider": "kilo",
                    "model": "kilo-auto/efficient"
                }
            })

    def test_rejects_free_tier_in_task_override(self):
        with pytest.raises(ValueError, match=":free"):
            self._make_config(tasks={
                "resume_generation_standard": {
                    "tier": "heavy", "provider": "kilo",
                    "model": "stepfun/step-3.7-flash:free"
                }
            })

    def test_accepts_explicit_premium_models(self):
        cfg = self._make_config(
            tiers={
                "heavy": {"provider": "kilo", "model": "openai/gpt-5.6-terra"},
                "moderate": {"provider": "kilo", "model": "openai/gpt-5.6-luna"},
                "light": {"provider": "kilo", "model": "anthropic/claude-haiku-4.5"},
            },
            tasks={
                "resume_generation_standard": {
                    "tier": "heavy", "provider": "kilo",
                    "model": "openai/gpt-5.6-luna"
                },
                "accuracy_validation": {
                    "tier": "light", "provider": "kilo",
                    "model": "anthropic/claude-haiku-4.5"
                },
            },
        )
        assert cfg.tiers["heavy"].model == "openai/gpt-5.6-terra"

    def test_rejects_unlisted_but_innocuous_looking_model(self):
        """A model that looks legitimate but isn't on the approved_models
        list must be rejected — this is the allowlist's primary purpose."""
        with pytest.raises(ValueError, match="not in approved_models"):
            self._make_config(tiers={
                "heavy": {"provider": "kilo", "model": "openai/gpt-5.6-sol"}
            })

    def test_rejects_unlisted_model_in_task_override(self):
        with pytest.raises(ValueError, match="not in approved_models"):
            self._make_config(tasks={
                "resume_generation_standard": {
                    "tier": "heavy", "provider": "kilo",
                    "model": "anthropic/claude-sonnet-4-6"
                }
            })

    def test_error_message_lists_all_offenders(self):
        with pytest.raises(ValueError) as exc_info:
            self._make_config(
                tiers={
                    "heavy": {"provider": "kilo", "model": "kilo-auto/free"}
                },
                tasks={
                    "resume_generation_standard": {
                        "tier": "heavy", "provider": "kilo",
                        "model": "stepfun/step-3.7-flash:free"
                    }
                },
            )
        msg = str(exc_info.value)
        assert "tier 'heavy'" in msg
        assert "task 'resume_generation_standard'" in msg

    def test_empty_approved_models_skips_allowlist_but_denylist_still_active(self):
        """If approved_models is empty, allowlist is skipped but denylist
        patterns are still enforced — defense in depth."""
        cfg = self._make_config(
            tiers={"heavy": {"provider": "kilo", "model": "openai/gpt-5.6-terra"}},
            approved_models=[],
        )
        assert cfg.tiers["heavy"].model == "openai/gpt-5.6-terra"

        with pytest.raises(ValueError, match="kilo-auto"):
            self._make_config(
                tiers={"heavy": {"provider": "kilo", "model": "kilo-auto/free"}},
                approved_models=[],
            )
