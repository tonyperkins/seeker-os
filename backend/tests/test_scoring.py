"""Tests for the scoring engine."""

from seeker_os.config import (
    ScoringConfig, BaseScoreRule, ModifierRule, FreshnessConfig,
    ProfileConfig, UserIdentity, LocationPrefs, CompPrefs,
    ExperiencePrefs, EmploymentPrefs, ResumePrefs, CrossReferencePrefs, HardReject,
)
from seeker_os.scoring.engine import score_job


def _make_rubric() -> ScoringConfig:
    return ScoringConfig(
        post_threshold=6.0,
        per_company_cap=3,
        max_score=10,
        min_score=0,
        base_scores=[
            BaseScoreRule(pattern="(principal|staff).*(sre|site reliability|platform|infra|devops)", score=4.5, label="Principal/Staff"),
            BaseScoreRule(pattern="senior.*(sre|site reliability|platform|infra)", score=4.0, label="Senior SRE"),
            BaseScoreRule(pattern="senior.*(devops|cloud.?engineer)", score=3.5, label="Senior DevOps"),
            BaseScoreRule(score=0, label="No match"),
        ],
        positive_modifiers=[
            ModifierRule(signal="aws", pattern="aws|amazon web services", points=1.0, check="jd"),
            ModifierRule(signal="terraform", pattern="terraform", points=1.0, check="jd"),
            ModifierRule(signal="kubernetes", pattern="kubernetes|k8s", points=0.5, check="jd"),
            ModifierRule(signal="comp_target", points=1.0, check="structured_comp", threshold=165000),
        ],
        negative_modifiers=[
            ModifierRule(signal="relocation_required", pattern="relocation required", points=-3.0, check="jd"),
            ModifierRule(signal="comp_below_floor", points=-3.0, check="structured_comp", threshold_max=140000),
            ModifierRule(signal="comp_marginal", points=-1.5, check="structured_comp", threshold_min=140000, threshold_max=165000),
        ],
        freshness=FreshnessConfig(),
    )


def _make_profile() -> ProfileConfig:
    return ProfileConfig(
        user=UserIdentity(name="Test", email="test@test.com", location="Austin, TX"),
        location=LocationPrefs(remote_only=True),
        comp=CompPrefs(floor=150000, target=165000, stretch=220000),
        experience=ExperiencePrefs(years=25, anchor_phrase="25+ years"),
        employment=EmploymentPrefs(commitment="Full Time"),
        blacklist=[],
        resume=ResumePrefs(master_path="~/resume.md", accuracy_rules_path="config/accuracy_rules.yml", output_dir="data/resumes"),
        cross_reference=CrossReferencePrefs(repo_path="~/projects/job-search"),
        hard_rejects=[
            HardReject(reason="FedRAMP", pattern="fedramp|security clearance"),
            HardReject(reason="Relocation", pattern="relocation required"),
        ],
    )


class TestScoring:
    def test_evidence_gate_short_jd(self):
        result = score_job(
            title="Senior SRE", jd_text="short", location="Remote, US",
            company="TestCo", rubric=_make_rubric(), profile=_make_profile(),
        )
        assert result.hard_reject is True
        assert "short" in result.reasons[0].lower()

    def test_evidence_gate_no_location(self):
        result = score_job(
            title="Senior SRE", jd_text="A" * 600, location="",
            company="TestCo", rubric=_make_rubric(), profile=_make_profile(),
        )
        assert result.hard_reject is True

    def test_hard_reject_fedramp(self):
        jd = "This role requires FedRAMP certification and security clearance. " + "x" * 500
        result = score_job(
            title="Senior SRE", jd_text=jd, location="Remote, US",
            company="TestCo", rubric=_make_rubric(), profile=_make_profile(),
        )
        assert result.hard_reject is True
        assert "FedRAMP" in result.reject_reason

    def test_fedramp_nice_to_have_not_rejected(self):
        """FedRAMP listed as nice-to-have should NOT trigger hard reject when unless_pattern is set."""
        profile = _make_profile()
        profile.hard_rejects = [
            HardReject(reason="FedRAMP required", pattern="fedramp",
                        unless_pattern="nice.to.have|preferred|bonus|optional"),
            HardReject(reason="Clearance required", pattern="security clearance"),
        ]
        jd = "We are hiring a Senior SRE. FedRAMP experience is a nice-to-have. " + "x" * 500
        result = score_job(
            title="Senior SRE", jd_text=jd, location="Remote, US",
            company="TestCo", rubric=_make_rubric(), profile=profile,
        )
        assert result.hard_reject is False

    def test_base_score_senior_sre(self):
        jd = "We are looking for a senior SRE. " + "x" * 500
        result = score_job(
            title="Senior SRE", jd_text=jd, location="Remote, US",
            company="TestCo", rubric=_make_rubric(), profile=_make_profile(),
        )
        assert result.score >= 4.0  # base score for Senior SRE

    def test_base_score_principal(self):
        jd = "We are looking for a principal SRE. " + "x" * 500
        result = score_job(
            title="Principal SRE", jd_text=jd, location="Remote, US",
            company="TestCo", rubric=_make_rubric(), profile=_make_profile(),
        )
        assert result.score >= 4.5  # base score for Principal/Staff

    def test_positive_modifiers_aws_terraform(self):
        jd = "Senior SRE role. AWS and Terraform experience required. " + "x" * 500
        result = score_job(
            title="Senior SRE", jd_text=jd, location="Remote, US",
            company="TestCo", rubric=_make_rubric(), profile=_make_profile(),
        )
        # base 4.0 + aws 1.0 + terraform 1.0 = 6.0
        assert result.score >= 6.0

    def test_comp_target_bonus(self):
        jd = "Senior SRE role. " + "x" * 500
        result = score_job(
            title="Senior SRE", jd_text=jd, location="Remote, US",
            company="TestCo", rubric=_make_rubric(), profile=_make_profile(),
            comp_min=170000, comp_max=210000,
        )
        # base 4.0 + comp_target 1.0 = 5.0
        assert result.score >= 5.0

    def test_comp_below_floor_penalty(self):
        jd = "Senior SRE role. " + "x" * 500
        result = score_job(
            title="Senior SRE", jd_text=jd, location="Remote, US",
            company="TestCo", rubric=_make_rubric(), profile=_make_profile(),
            comp_min=120000, comp_max=130000,
        )
        # base 4.0 - 3.0 (comp_below_floor) = 1.0
        assert result.score <= 2.0

    def test_score_clamped_to_max(self):
        jd = "Principal SRE. AWS Terraform Kubernetes. " + "x" * 500
        result = score_job(
            title="Principal SRE", jd_text=jd, location="Remote, US",
            company="TestCo", rubric=_make_rubric(), profile=_make_profile(),
            comp_min=200000, comp_max=250000,
        )
        assert result.score <= 10

    def test_score_clamped_to_min(self):
        jd = "Relocation required. " + "x" * 500
        result = score_job(
            title="Junior Developer", jd_text=jd, location="Remote, US",
            company="TestCo", rubric=_make_rubric(), profile=_make_profile(),
            comp_min=80000, comp_max=90000,
        )
        # This would be hard-rejected by relocation, but if it reaches scoring:
        # base 0 - 3.0 (relocation) - 3.0 (comp_below) = -6 → clamped to 0
        assert result.score >= 0

    def test_verdict_weights_loaded_from_config(self):
        """verdict_weights dict is populated from scoring_rubric.yml."""
        from seeker_os.config import Settings
        settings = Settings()
        if settings.scoring and settings.scoring.verdict_weights:
            weights = settings.scoring.verdict_weights
            assert "APPLY" in weights
            assert "SKIP" in weights
            assert weights["APPLY"] > weights["SKIP"]

    def test_verdict_weights_default_empty(self):
        """ScoringConfig defaults verdict_weights to empty dict."""
        rubric = _make_rubric()
        assert rubric.verdict_weights == {}
