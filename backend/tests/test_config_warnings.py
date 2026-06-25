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

    def test_no_warning_for_oauth_token_path(self):
        """oauth_token_path is a safe field — should not warn even with a literal."""
        data = {"oauth_token_path": "data/.anthropic_oauth.json"}
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _check_literal_secrets(data, "providers.yml")
        assert len(w) == 0

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
