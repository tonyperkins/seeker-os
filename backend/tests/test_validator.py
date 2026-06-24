"""Tests for the accuracy validator."""

import pytest

from seeker_os.config import Settings
from seeker_os.resume.validator import AccuracyValidator, ValidationResult, Violation


@pytest.fixture
def validator():
    """Create a validator with the real config."""
    return AccuracyValidator(Settings())


class TestValidator:
    def test_clean_resume_passes(self, validator):
        clean = """
        # Tony Perkins
        25+ years building and shipping software.
        https://example.com | https://linkedin.com/in/example | https://github.com/example

        ## Experience
        - Senior SRE at Hilton (Collierville, TN)
        - Platform Engineer at Accelya
        """
        result = validator.validate(clean)
        assert result.passed is True
        assert len(result.violations) == 0

    def test_disallowed_phrase_aws(self, validator):
        text = "Deep AWS expertise with 25+ years of experience.\nhttps://example.com | https://linkedin.com/in/example | https://github.com/example"
        result = validator.validate(text)
        assert not result.passed
        aws_violations = [v for v in result.violations if v.rule_id == "aws_depth"]
        assert len(aws_violations) > 0

    def test_forbidden_technology(self, validator):
        text = "Uses ArgoCD and Helm for deployments.\nhttps://example.com | https://linkedin.com/in/example | https://github.com/example"
        result = validator.validate(text)
        assert not result.passed
        tech_violations = [v for v in result.violations if v.rule_id == "never_claim_tech"]
        assert len(tech_violations) >= 2  # ArgoCD + Helm

    def test_missing_required_phrase(self, validator):
        text = "25+ years of experience.\nhttps://example.com"
        result = validator.validate(text)
        # Missing linkedin and github URLs
        url_violations = [v for v in result.violations if v.rule_id == "contact_urls_visible"]
        assert len(url_violations) >= 2

    def test_experience_anchor_violation(self, validator):
        text = "30+ years in software.\nhttps://example.com | https://linkedin.com/in/example | https://github.com/example"
        result = validator.validate(text)
        anchor_violations = [v for v in result.violations if v.rule_id == "experience_anchor"]
        assert len(anchor_violations) > 0
        # Medium severity — shouldn't block pass
        assert all(v.severity == "medium" for v in anchor_violations)

    def test_education_omission(self, validator):
        text = "BS in Electronics Engineering Technology from DeVry.\nhttps://example.com | https://linkedin.com/in/example | https://github.com/example"
        result = validator.validate(text)
        edu_violations = [v for v in result.violations if v.rule_id == "education_omission"]
        assert len(edu_violations) > 0

    def test_k8s_depth_violation(self, validator):
        text = "Kubernetes admin with deep K8s expertise.\nhttps://example.com | https://linkedin.com/in/example | https://github.com/example"
        result = validator.validate(text)
        k8s_violations = [v for v in result.violations if v.rule_id == "k8s_depth"]
        assert len(k8s_violations) >= 2  # "kubernetes admin" + "deep k8s"

    def test_case_insensitive_matching(self, validator):
        text = "DEEP AWS EXPERTISE\nhttps://example.com | https://linkedin.com/in/example | https://github.com/example"
        result = validator.validate(text)
        assert not result.passed

    def test_word_boundary_for_tech(self, validator):
        # "Helmets" should not match "Helm"
        text = "Wore helmets on construction sites.\nhttps://example.com | https://linkedin.com/in/example | https://github.com/example"
        result = validator.validate(text)
        helm_violations = [v for v in result.violations if "Helm" in v.matched_text]
        assert len(helm_violations) == 0

    def test_high_severity_blocks_pass(self, validator):
        text = "Deep AWS expertise.\nhttps://example.com | https://linkedin.com/in/example | https://github.com/example"
        result = validator.validate(text)
        assert not result.passed
        assert result.has_high_severity

    def test_medium_severity_only_does_not_block(self, validator):
        # Only medium violations (experience anchor + missing URLs)
        text = "30+ years of experience.\nhttps://example.com | https://linkedin.com/in/example | https://github.com/example"
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
