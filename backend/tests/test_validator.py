"""Tests for the accuracy validator."""

import pytest
import yaml

from seeker_os.config import Settings, CONFIG_DIR
from seeker_os.resume.validator import AccuracyValidator, ValidationResult, Violation


TEST_RULES = [
    {"id": "aws_depth", "description": "Never claim deep AWS expertise",
     "type": "disallowed_phrases", "phrases": ["deep aws expertise", "aws expert"], "severity": "high"},
    {"id": "k8s_depth", "description": "Never claim Kubernetes admin depth",
     "type": "disallowed_phrases", "phrases": ["kubernetes admin", "deep k8s"], "severity": "high"},
    {"id": "never_claim_tech", "description": "Forbidden technologies",
     "type": "forbidden_technologies", "technologies": ["ArgoCD", "Helm"], "severity": "high"},
    {"id": "contact_urls_visible", "description": "Required contact URLs",
     "type": "required_phrases", "phrases": ["https://example.com", "https://linkedin.com/in/test"], "severity": "medium"},
    {"id": "experience_anchor", "description": "Non-standard year counts",
     "type": "experience_anchor", "patterns": [r"(20|30)\+\s*years"], "severity": "medium"},
    {"id": "education_omission", "description": "Omit education",
     "type": "education_omission", "patterns": [r"(?i)\bdevry\b"], "severity": "medium"},
]


@pytest.fixture
def validator(tmp_path, monkeypatch):
    """Create a validator with a test-specific accuracy_rules.yml.

    Uses a temporary config directory so tests don't depend on the user's
    real accuracy_rules.yml (which may have personal values or be empty).
    """
    test_config = tmp_path / "config"
    test_config.mkdir()

    # Copy required config files from the real config dir
    import shutil
    for f in CONFIG_DIR.iterdir():
        if f.is_file():
            shutil.copy(f, test_config / f.name)

    # Write test accuracy rules
    (test_config / "accuracy_rules.yml").write_text(
        yaml.dump({"rules": TEST_RULES}, default_flow_style=False),
        encoding="utf-8",
    )

    # Patch CONFIG_DIR and Settings to use the temp dir
    monkeypatch.setattr("seeker_os.config.CONFIG_DIR", test_config)
    monkeypatch.setattr("seeker_os.config_writer.CONFIG_DIR", test_config)

    settings = Settings()
    settings.config_dir = test_config
    return AccuracyValidator(settings)


class TestValidator:
    def test_clean_resume_passes(self, validator):
        clean = """
        # Test User
        25+ years building software.
        https://example.com | https://linkedin.com/in/test

        ## Experience
        - Senior SRE at Acme Corp
        """
        result = validator.validate(clean)
        assert result.passed is True
        assert len(result.violations) == 0

    def test_disallowed_phrase_aws(self, validator):
        text = "Deep AWS expertise with 25+ years of experience.\nhttps://example.com | https://linkedin.com/in/test"
        result = validator.validate(text)
        assert not result.passed
        aws_violations = [v for v in result.violations if v.rule_id == "aws_depth"]
        assert len(aws_violations) > 0

    def test_forbidden_technology(self, validator):
        text = "Uses ArgoCD and Helm for deployments.\nhttps://example.com | https://linkedin.com/in/test"
        result = validator.validate(text)
        assert not result.passed
        tech_violations = [v for v in result.violations if v.rule_id == "never_claim_tech"]
        assert len(tech_violations) >= 2  # ArgoCD + Helm

    def test_missing_required_phrase(self, validator):
        text = "25+ years of experience.\nhttps://example.com"
        result = validator.validate(text)
        # Missing linkedin URL
        url_violations = [v for v in result.violations if v.rule_id == "contact_urls_visible"]
        assert len(url_violations) >= 1

    def test_experience_anchor_violation(self, validator):
        text = "30+ years in software.\nhttps://example.com | https://linkedin.com/in/test"
        result = validator.validate(text)
        anchor_violations = [v for v in result.violations if v.rule_id == "experience_anchor"]
        assert len(anchor_violations) > 0
        # Medium severity — shouldn't block pass
        assert all(v.severity == "medium" for v in anchor_violations)

    def test_education_omission(self, validator):
        text = "BS from DeVry University.\nhttps://example.com | https://linkedin.com/in/test"
        result = validator.validate(text)
        edu_violations = [v for v in result.violations if v.rule_id == "education_omission"]
        assert len(edu_violations) > 0

    def test_k8s_depth_violation(self, validator):
        text = "Kubernetes admin with deep K8s expertise.\nhttps://example.com | https://linkedin.com/in/test"
        result = validator.validate(text)
        k8s_violations = [v for v in result.violations if v.rule_id == "k8s_depth"]
        assert len(k8s_violations) >= 2  # "kubernetes admin" + "deep k8s"

    def test_case_insensitive_matching(self, validator):
        text = "DEEP AWS EXPERTISE\nhttps://example.com | https://linkedin.com/in/test"
        result = validator.validate(text)
        assert not result.passed

    def test_word_boundary_for_tech(self, validator):
        # "Helmets" should not match "Helm"
        text = "Wore helmets on construction sites.\nhttps://example.com | https://linkedin.com/in/test"
        result = validator.validate(text)
        helm_violations = [v for v in result.violations if "Helm" in v.matched_text]
        assert len(helm_violations) == 0

    def test_disallowed_phrase_word_boundary(self, tmp_path, monkeypatch):
        """A short disallowed phrase must not match inside a longer word.

        'aws expert' should NOT match 'sawsexpert' (no word boundary).
        'aws expert' SHOULD match 'I am an aws expert' (word-bounded).
        Multi-word phrases must still match across spaces.
        """
        import shutil
        from seeker_os.config import CONFIG_DIR

        test_config = tmp_path / "config"
        test_config.mkdir()
        for f in CONFIG_DIR.iterdir():
            if f.is_file():
                shutil.copy(f, test_config / f.name)

        (test_config / "accuracy_rules.yml").write_text(
            yaml.dump({"rules": [
                {"id": "aws_short", "description": "No claiming aws expert",
                 "type": "disallowed_phrases", "phrases": ["aws expert"], "severity": "high"},
            ]}, default_flow_style=False),
            encoding="utf-8",
        )

        monkeypatch.setattr("seeker_os.config.CONFIG_DIR", test_config)
        monkeypatch.setattr("seeker_os.config_writer.CONFIG_DIR", test_config)
        settings = Settings()
        settings.config_dir = test_config
        v = AccuracyValidator(settings)

        # Should NOT match inside a longer word (no word boundary)
        result_neg = v.validate("Sawsexpert at work\nhttps://example.com | https://linkedin.com/in/test")
        aws_violations = [x for x in result_neg.violations if x.rule_id == "aws_short"]
        assert len(aws_violations) == 0

        # SHOULD match as a whole phrase
        result_pos = v.validate("I am an aws expert\nhttps://example.com | https://linkedin.com/in/test")
        aws_violations = [x for x in result_pos.violations if x.rule_id == "aws_short"]
        assert len(aws_violations) == 1

    def test_high_severity_blocks_pass(self, validator):
        text = "Deep AWS expertise.\nhttps://example.com | https://linkedin.com/in/test"
        result = validator.validate(text)
        assert not result.passed
        assert result.has_high_severity

    def test_medium_severity_only_does_not_block(self, validator):
        # Only medium violations (experience anchor)
        text = "30+ years of experience.\nhttps://example.com | https://linkedin.com/in/test"
        result = validator.validate(text)
        # 30+ years is medium severity
        assert result.passed  # no high-severity violations
        assert not result.has_high_severity

    def test_validation_result_to_dict(self):
        result = ValidationResult(
            passed=False,
            violations=[
                Violation(rule_id="test", description="Test rule", violation="Test violation", severity="high"),
            ],
            checked_at="2025-01-01T00:00:00Z",
        )
        d = result.to_dict()
        assert d["passed"] is False
        assert len(d["violations"]) == 1
        assert d["violations"][0]["rule_id"] == "test"

    def test_unknown_rule_type_warns(self, tmp_path, monkeypatch, caplog):
        """Unknown rule types should log a warning at load time, not be silently ignored."""
        import logging
        import shutil
        from seeker_os.config import CONFIG_DIR

        test_config = tmp_path / "config"
        test_config.mkdir()
        for f in CONFIG_DIR.iterdir():
            if f.is_file():
                shutil.copy(f, test_config / f.name)

        rules_with_unknown = TEST_RULES + [
            {"id": "bogus_rule", "description": "Nonexistent type",
             "type": "nonexistent_type", "severity": "high"},
        ]
        (test_config / "accuracy_rules.yml").write_text(
            yaml.dump({"rules": rules_with_unknown}, default_flow_style=False),
            encoding="utf-8",
        )

        monkeypatch.setattr("seeker_os.config.CONFIG_DIR", test_config)
        monkeypatch.setattr("seeker_os.config_writer.CONFIG_DIR", test_config)

        settings = Settings()
        settings.config_dir = test_config

        with caplog.at_level(logging.WARNING, logger="seeker_os.resume.validator"):
            validator = AccuracyValidator(settings)

        # The warning should mention the unknown type and rule id
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("nonexistent_type" in r.getMessage() for r in warnings)
        assert any("bogus_rule" in r.getMessage() for r in warnings)

    def test_experience_anchor_uses_identity_phrase(self, tmp_path, monkeypatch):
        """Validator experience_anchor message should use identity_rules.yml anchor phrase."""
        import shutil
        from seeker_os.config import CONFIG_DIR

        test_config = tmp_path / "config"
        test_config.mkdir()
        for f in CONFIG_DIR.iterdir():
            if f.is_file():
                shutil.copy(f, test_config / f.name)

        # Write accuracy rules with experience_anchor but no hardcoded patterns
        (test_config / "accuracy_rules.yml").write_text(
            yaml.dump({"rules": [
                {"id": "exp_anchor", "description": "Non-standard anchor",
                 "type": "experience_anchor", "patterns": [], "severity": "high"},
            ]}, default_flow_style=False),
            encoding="utf-8",
        )

        # Write identity rules with anchor phrase and disallowed_variants
        (test_config / "identity_rules.yml").write_text(
            yaml.dump({"identity": {
                "positioning": "Test positioning",
                "experience_anchor": {
                    "phrase": "NN+ years in software",
                    "applies_to": "overall career",
                    "disallowed_variants": [r"(40|50)\+\s*years"],
                },
                "honest_qualifiers": [],
                "never_claim": [],
            }}, default_flow_style=False),
            encoding="utf-8",
        )

        monkeypatch.setattr("seeker_os.config.CONFIG_DIR", test_config)
        settings = Settings()
        settings.config_dir = test_config

        validator = AccuracyValidator(settings)
        # Text with a disallowed variant should trigger violation
        result = validator.validate("40+ years of experience.\nhttps://example.com")
        anchor_violations = [v for v in result.violations if v.rule_id == "exp_anchor"]
        assert len(anchor_violations) > 0
        # Message should contain the configured anchor phrase
        assert "NN+ years in software" in anchor_violations[0].violation

    def test_experience_anchor_no_identity_no_variants(self, tmp_path, monkeypatch):
        """When no identity_rules.yml configured, only accuracy_rules patterns are checked."""
        import shutil
        from seeker_os.config import CONFIG_DIR

        test_config = tmp_path / "config"
        test_config.mkdir()
        for f in CONFIG_DIR.iterdir():
            if f.is_file():
                shutil.copy(f, test_config / f.name)

        # Accuracy rules with a specific pattern
        (test_config / "accuracy_rules.yml").write_text(
            yaml.dump({"rules": [
                {"id": "exp_anchor", "description": "Non-standard anchor",
                 "type": "experience_anchor", "patterns": [r"(99)\+\s*years"], "severity": "high"},
            ]}, default_flow_style=False),
            encoding="utf-8",
        )

        # Remove identity_rules.yml so no anchor phrase is configured
        (test_config / "identity_rules.yml").unlink(missing_ok=True)

        monkeypatch.setattr("seeker_os.config.CONFIG_DIR", test_config)
        settings = Settings()
        settings.config_dir = test_config

        validator = AccuracyValidator(settings)
        result = validator.validate("99+ years of experience.\nhttps://example.com")
        anchor_violations = [v for v in result.violations if v.rule_id == "exp_anchor"]
        assert len(anchor_violations) > 0
        # No anchor phrase configured, so message should not include one
        assert "must be" not in anchor_violations[0].violation

    def test_experience_anchor_both_empty_no_violation(self, tmp_path, monkeypatch):
        """Both patterns=[] and disallowed_variants=[] — merged list is empty,
        so the check must iterate nothing and produce zero violations.

        Guards against a future refactor (e.g. combined regex) that could
        silently produce a match-everything bug from empty input.
        """
        import shutil
        from seeker_os.config import CONFIG_DIR

        test_config = tmp_path / "config"
        test_config.mkdir()
        for f in CONFIG_DIR.iterdir():
            if f.is_file():
                shutil.copy(f, test_config / f.name)

        # accuracy_rules.yml: experience_anchor with empty patterns
        (test_config / "accuracy_rules.yml").write_text(
            yaml.dump({"rules": [
                {"id": "exp_anchor", "description": "Non-standard anchor",
                 "type": "experience_anchor", "patterns": [], "severity": "high"},
            ]}, default_flow_style=False),
            encoding="utf-8",
        )

        # Remove identity_rules.yml so _load_identity_anchor() returns ("", [])
        (test_config / "identity_rules.yml").unlink(missing_ok=True)

        monkeypatch.setattr("seeker_os.config.CONFIG_DIR", test_config)
        settings = Settings()
        settings.config_dir = test_config

        validator = AccuracyValidator(settings)
        # Resume contains a year count that WOULD match if a regex existed
        result = validator.validate("20+ years of experience.\nhttps://example.com")
        anchor_violations = [v for v in result.violations if v.rule_id == "exp_anchor"]
        assert len(anchor_violations) == 0

    def test_experience_anchor_phrase_only_no_violation(self, tmp_path, monkeypatch):
        """Anchor phrase configured but disallowed_variants=[] and patterns=[].

        A configured "correct" anchor is not itself a disallowed pattern.
        The check must produce zero violations.
        """
        import shutil
        from seeker_os.config import CONFIG_DIR

        test_config = tmp_path / "config"
        test_config.mkdir()
        for f in CONFIG_DIR.iterdir():
            if f.is_file():
                shutil.copy(f, test_config / f.name)

        # accuracy_rules.yml: experience_anchor with empty patterns
        (test_config / "accuracy_rules.yml").write_text(
            yaml.dump({"rules": [
                {"id": "exp_anchor", "description": "Non-standard anchor",
                 "type": "experience_anchor", "patterns": [], "severity": "high"},
            ]}, default_flow_style=False),
            encoding="utf-8",
        )

        # identity_rules.yml: phrase set but disallowed_variants empty
        (test_config / "identity_rules.yml").write_text(
            yaml.dump({"identity": {
                "positioning": "Test positioning",
                "experience_anchor": {
                    "phrase": "NN+ years in engineering",
                    "applies_to": "overall career",
                    "disallowed_variants": [],
                },
                "honest_qualifiers": [],
                "never_claim": [],
            }}, default_flow_style=False),
            encoding="utf-8",
        )

        monkeypatch.setattr("seeker_os.config.CONFIG_DIR", test_config)
        settings = Settings()
        settings.config_dir = test_config

        validator = AccuracyValidator(settings)
        result = validator.validate("20+ years of experience.\nhttps://example.com")
        anchor_violations = [v for v in result.violations if v.rule_id == "exp_anchor"]
        assert len(anchor_violations) == 0
