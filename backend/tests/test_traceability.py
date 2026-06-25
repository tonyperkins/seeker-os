"""Tests for the traceability checker (LLM-judged claim verification).

The ModelRouter is mocked — no real LLM calls are made.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import yaml

from seeker_os.config import Settings, CONFIG_DIR
from seeker_os.validation import ValidationResult, Violation
from seeker_os.validation.traceability import (
    TraceabilityChecker,
    TraceabilityResult,
    ClaimJudgment,
)


@pytest.fixture
def test_settings(tmp_path, monkeypatch):
    """Create settings with a test config dir."""
    import shutil
    test_config = tmp_path / "config"
    test_config.mkdir()
    for f in CONFIG_DIR.iterdir():
        if f.is_file():
            shutil.copy(f, test_config / f.name)

    # Write accuracy_rules.yml with traceability config
    (test_config / "accuracy_rules.yml").write_text(
        yaml.dump({
            "rules": [],
            "traceability": {
                "enabled": True,
                "task": "accuracy_validation",
            },
        }, default_flow_style=False),
        encoding="utf-8",
    )

    monkeypatch.setattr("seeker_os.config.CONFIG_DIR", test_config)
    settings = Settings()
    settings.config_dir = test_config
    return settings


class TestTraceabilityChecker:
    def test_enabled_by_default(self, test_settings):
        checker = TraceabilityChecker(test_settings)
        assert checker.enabled is True

    def test_disabled_via_config(self, tmp_path, monkeypatch):
        """Traceability can be disabled via accuracy_rules.yml."""
        import shutil
        test_config = tmp_path / "config"
        test_config.mkdir()
        for f in CONFIG_DIR.iterdir():
            if f.is_file():
                shutil.copy(f, test_config / f.name)

        (test_config / "accuracy_rules.yml").write_text(
            yaml.dump({
                "rules": [],
                "traceability": {"enabled": False},
            }, default_flow_style=False),
            encoding="utf-8",
        )

        monkeypatch.setattr("seeker_os.config.CONFIG_DIR", test_config)
        settings = Settings()
        settings.config_dir = test_config

        checker = TraceabilityChecker(settings)
        assert checker.enabled is False

    def test_disabled_checker_returns_empty(self, test_settings):
        """When disabled, check() returns empty result with no violations."""
        # Override to disabled
        test_settings.config_dir = test_settings.config_dir  # keep same
        # Rewrite config with disabled
        (test_settings.config_dir / "accuracy_rules.yml").write_text(
            yaml.dump({
                "rules": [],
                "traceability": {"enabled": False},
            }, default_flow_style=False),
            encoding="utf-8",
        )
        checker = TraceabilityChecker(test_settings)
        result = checker.check("Some text", "Master resume", "resume")
        assert len(result.violations) == 0
        assert len(result.claims) == 0

    @patch("seeker_os.llm.router.ModelRouter")
    def test_supported_claims_no_violations(self, mock_router_cls, test_settings):
        """All claims supported → no violations."""
        mock_router = MagicMock()
        mock_router.generate.return_value = MagicMock(
            text=json.dumps({
                "claims": [
                    {"claim": "5 years of Go", "verdict": "supported", "explanation": "Resume mentions Go since 2019", "offending_text": ""},
                    {"claim": "Built CI/CD pipelines", "verdict": "supported", "explanation": "Resume mentions CI/CD at Acme", "offending_text": ""},
                ]
            }),
            provider="test", model="test-model",
            input_tokens=100, output_tokens=200, latency_ms=50,
        )
        mock_router_cls.return_value = mock_router

        checker = TraceabilityChecker(test_settings)
        result = checker.check("Some resume text", "Master resume", "resume")
        assert len(result.claims) == 2
        assert len(result.violations) == 0

    @patch("seeker_os.llm.router.ModelRouter")
    def test_unsupported_claim_produces_high_violation(self, mock_router_cls, test_settings):
        """Unsupported claim → high-severity violation."""
        mock_router = MagicMock()
        mock_router.generate.return_value = MagicMock(
            text=json.dumps({
                "claims": [
                    {"claim": "Expert in Rust", "verdict": "unsupported", "explanation": "Rust not in master resume", "offending_text": "Expert in Rust"},
                    {"claim": "5 years of Go", "verdict": "supported", "explanation": "Resume mentions Go", "offending_text": ""},
                ]
            }),
            provider="test", model="test-model",
            input_tokens=100, output_tokens=200, latency_ms=50,
        )
        mock_router_cls.return_value = mock_router

        checker = TraceabilityChecker(test_settings)
        result = checker.check("Some resume text", "Master resume", "resume")
        assert len(result.claims) == 2
        assert len(result.violations) == 1
        assert result.violations[0].severity == "high"
        assert result.violations[0].rule_id == "traceability_unsupported"
        assert "Expert in Rust" in result.violations[0].violation

    @patch("seeker_os.llm.router.ModelRouter")
    def test_overstated_claim_produces_high_violation(self, mock_router_cls, test_settings):
        """Overstated claim → high-severity violation."""
        mock_router = MagicMock()
        mock_router.generate.return_value = MagicMock(
            text=json.dumps({
                "claims": [
                    {"claim": "Led a team of 20 engineers", "verdict": "overstated", "explanation": "Resume says 'contributed to a team of 20'", "offending_text": "Led a team of 20 engineers"},
                ]
            }),
            provider="test", model="test-model",
            input_tokens=100, output_tokens=200, latency_ms=50,
        )
        mock_router_cls.return_value = mock_router

        checker = TraceabilityChecker(test_settings)
        result = checker.check("Some resume text", "Master resume", "resume")
        assert len(result.violations) == 1
        assert result.violations[0].severity == "high"
        assert result.violations[0].rule_id == "traceability_overstated"

    @patch("seeker_os.llm.router.ModelRouter")
    def test_merge_into_flips_passed_to_false(self, mock_router_cls, test_settings):
        """Merging traceability violations into a passing result should flip it."""
        mock_router = MagicMock()
        mock_router.generate.return_value = MagicMock(
            text=json.dumps({
                "claims": [
                    {"claim": "Blockchain expert", "verdict": "unsupported", "explanation": "Not in resume", "offending_text": "Blockchain expert"},
                ]
            }),
            provider="test", model="test-model",
            input_tokens=100, output_tokens=200, latency_ms=50,
        )
        mock_router_cls.return_value = mock_router

        checker = TraceabilityChecker(test_settings)
        result = checker.check("Some text", "Master resume", "resume")

        validation = ValidationResult(passed=True, violations=[], checked_at="2025-01-01T00:00:00Z")
        result.merge_into(validation)
        assert validation.passed is False
        assert len(validation.violations) == 1

    @patch("seeker_os.llm.router.ModelRouter")
    def test_invalid_json_produces_high_violation(self, mock_router_cls, test_settings):
        """Unparseable LLM response → high-severity violation for manual review."""
        mock_router = MagicMock()
        mock_router.generate.return_value = MagicMock(
            text="This is not JSON at all.",
            provider="test", model="test-model",
            input_tokens=100, output_tokens=200, latency_ms=50,
        )
        mock_router_cls.return_value = mock_router

        checker = TraceabilityChecker(test_settings)
        result = checker.check("Some text", "Master resume", "resume")
        assert len(result.violations) == 1
        assert result.violations[0].severity == "high"
        assert result.violations[0].rule_id == "traceability_parse_error"

    def test_empty_master_fails_closed_when_enabled(self, test_settings):
        """When traceability is ENABLED but master resume is empty, fail closed with a HIGH violation."""
        checker = TraceabilityChecker(test_settings)
        assert checker.enabled is True
        result = checker.check("Some text", "", "resume")
        assert len(result.violations) == 1
        assert result.violations[0].severity == "high"
        assert result.violations[0].rule_id == "traceability_no_master"
        assert len(result.claims) == 0

    def test_empty_master_no_violation_when_disabled(self, tmp_path, monkeypatch):
        """When traceability is DISABLED, empty master resume produces no violations."""
        import shutil
        test_config = tmp_path / "config"
        test_config.mkdir()
        for f in CONFIG_DIR.iterdir():
            if f.is_file():
                shutil.copy(f, test_config / f.name)

        (test_config / "accuracy_rules.yml").write_text(
            yaml.dump({
                "rules": [],
                "traceability": {"enabled": False},
            }, default_flow_style=False),
            encoding="utf-8",
        )

        monkeypatch.setattr("seeker_os.config.CONFIG_DIR", test_config)
        settings = Settings()
        settings.config_dir = test_config

        checker = TraceabilityChecker(settings)
        assert checker.enabled is False
        result = checker.check("Some text", "", "resume")
        assert len(result.violations) == 0
        assert len(result.claims) == 0

    def test_whitespace_master_fails_closed(self, test_settings):
        """Master resume with only whitespace should also fail closed."""
        checker = TraceabilityChecker(test_settings)
        result = checker.check("Some text", "   \n  \t  ", "resume")
        assert len(result.violations) == 1
        assert result.violations[0].severity == "high"
        assert result.violations[0].rule_id == "traceability_no_master"
