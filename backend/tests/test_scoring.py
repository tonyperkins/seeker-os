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
        location=LocationPrefs(remote_only=True, accepted_cities=["austin", "leander", "cedar park", "round rock", "georgetown", "pflugerville", "taylor"]),
        comp=CompPrefs(floor=150000, target=165000, stretch=220000),
        experience=ExperiencePrefs(years=25, anchor_phrase="25+ years"),
        employment=EmploymentPrefs(commitment="Full Time", role_type="Individual Contributor"),
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

    def test_verdict_caps_loaded_from_config(self):
        """verdict_caps dict is populated from scoring_rubric.yml."""
        from seeker_os.config import Settings
        settings = Settings()
        if settings.scoring and settings.scoring.verdict_caps:
            caps = settings.scoring.verdict_caps
            assert "APPLY" in caps
            assert "SKIP" in caps
            # APPLY has no cap (null), SKIP has a low cap
            assert caps["APPLY"] is None
            assert caps["SKIP"] is not None

    def test_verdict_caps_default_empty(self):
        """ScoringConfig defaults verdict_caps to empty dict."""
        rubric = _make_rubric()
        assert rubric.verdict_caps == {}

    # --- Phase 1: company size from JD text ---

    def _make_rubric_with_company_size(self) -> ScoringConfig:
        """Rubric that includes large_enterprise (JD-text stopgap) but NOT small_company."""
        return ScoringConfig(
            post_threshold=6.0,
            per_company_cap=3,
            max_score=10,
            min_score=0,
            base_scores=[
                BaseScoreRule(pattern="senior.*(sre|site reliability|platform|infra)", score=4.0, label="Senior SRE"),
                BaseScoreRule(score=0, label="No match"),
            ],
            positive_modifiers=[
                ModifierRule(signal="aws", pattern="aws|amazon web services", points=1.0, check="jd"),
            ],
            negative_modifiers=[
                ModifierRule(
                    signal="large_enterprise",
                    pattern=r"fortune\s*(?:500|100|50)|\b\d{1,3},000\+?\s*employees",
                    points=-0.5,
                    check="jd",
                    unless="our customers|customers include|customers range|client.*fortune|fortune.*customer",
                ),
            ],
            freshness=FreshnessConfig(),
        )

    def test_small_company_modifier_removed(self):
        """small_company JD-pattern modifier no longer exists in positive_modifiers."""
        rubric = self._make_rubric_with_company_size()
        signals = [m.signal for m in rubric.positive_modifiers]
        assert "small_company" not in signals

    def test_large_enterprise_widened_catches_7k(self):
        """Widened large_enterprise regex catches '7,000 employees' (1k-9k range)."""
        rubric = self._make_rubric_with_company_size()
        jd = "Senior SRE role at a startup culture. 7,000+ employees. " + "x" * 500
        result = score_job(
            title="Senior SRE", jd_text=jd, location="Remote, US",
            company="TestCo", rubric=rubric, profile=_make_profile(),
        )
        # base 4.0 + aws 0 (not in JD) + large_enterprise -0.5 = 3.5
        assert any("large_enterprise" in r for r in result.reasons)
        assert result.score == 3.5

    def test_large_enterprise_magnitude_is_half_point(self):
        """large_enterprise JD-text stopgap magnitude is -0.5 (weakened guess)."""
        rubric = self._make_rubric_with_company_size()
        # Find the large_enterprise modifier in negative_modifiers
        le = [m for m in rubric.negative_modifiers if m.signal == "large_enterprise"]
        assert len(le) == 1
        assert le[0].points == -0.5

    def test_7k_startup_no_small_bonus(self):
        """A 7k-employee company with 'startup' in JD does NOT net the small bonus
        (small_company removed from positive_modifiers)."""
        rubric = self._make_rubric_with_company_size()
        jd = "Senior SRE. We are a startup culture. AWS required. " + "x" * 500
        result = score_job(
            title="Senior SRE", jd_text=jd, location="Remote, US",
            company="TestCo", rubric=rubric, profile=_make_profile(),
        )
        # base 4.0 + aws 1.0 = 5.0 — no small_company bonus, no large_enterprise (no employee count)
        assert result.score == 5.0
        assert not any("small_company" in r for r in result.reasons)

    def test_7k_with_employee_count_gets_large_penalty(self):
        """A 7k-employee company with 'startup' in JD AND employee count gets
        large_enterprise JD-text penalty but NOT small_company bonus."""
        rubric = self._make_rubric_with_company_size()
        jd = "Senior SRE. Startup culture. 7,000 employees. AWS. " + "x" * 500
        result = score_job(
            title="Senior SRE", jd_text=jd, location="Remote, US",
            company="TestCo", rubric=rubric, profile=_make_profile(),
        )
        # base 4.0 + aws 1.0 + large_enterprise -0.5 = 4.5
        assert any("large_enterprise" in r for r in result.reasons)
        assert not any("small_company" in r for r in result.reasons)
        assert result.score == 4.5

    def test_fired_modifiers_structured_data(self):
        """score_job emits fired_modifiers as structured data (signal → points),
        not just display strings. This is what research-adjustment suppression reads."""
        rubric = self._make_rubric_with_company_size()
        jd = "Senior SRE. 7,000 employees. AWS. " + "x" * 500
        result = score_job(
            title="Senior SRE", jd_text=jd, location="Remote, US",
            company="TestCo", rubric=rubric, profile=_make_profile(),
        )
        # fired_modifiers is a dict with signal → points
        assert isinstance(result.fired_modifiers, dict)
        assert "aws" in result.fired_modifiers
        assert result.fired_modifiers["aws"] == 1.0
        assert "large_enterprise" in result.fired_modifiers
        assert result.fired_modifiers["large_enterprise"] == -0.5

    def test_fired_modifiers_excludes_non_fired(self):
        """fired_modifiers only includes modifiers that actually matched — not the full configured list."""
        rubric = self._make_rubric_with_company_size()
        jd = "Senior SRE. AWS required. " + "x" * 500  # no employee count
        result = score_job(
            title="Senior SRE", jd_text=jd, location="Remote, US",
            company="TestCo", rubric=rubric, profile=_make_profile(),
        )
        assert "aws" in result.fired_modifiers
        assert "large_enterprise" not in result.fired_modifiers  # didn't match

    def test_fired_modifiers_empty_when_no_modifiers_match(self):
        """fired_modifiers is empty dict when no modifiers fire."""
        rubric = self._make_rubric_with_company_size()
        jd = "Senior SRE. No keywords here. " + "x" * 500
        result = score_job(
            title="Senior SRE", jd_text=jd, location="Remote, US",
            company="TestCo", rubric=rubric, profile=_make_profile(),
        )
        assert result.fired_modifiers == {}

    # --- Phase 2: location_local + location_only fix ---

    def _make_rubric_with_location(self) -> ScoringConfig:
        """Rubric with austin_area (location_local), remote_us (jd), and city_only_no_remote (location_only)."""
        return ScoringConfig(
            post_threshold=6.0,
            per_company_cap=3,
            max_score=10,
            min_score=0,
            base_scores=[
                BaseScoreRule(pattern="senior.*(sre|site reliability|platform|infra)", score=4.0, label="Senior SRE"),
                BaseScoreRule(score=0, label="No match"),
            ],
            positive_modifiers=[
                ModifierRule(signal="austin_area", points=1.5, check="location_local"),
                ModifierRule(signal="remote_us", pattern="remote", points=1.0, check="jd",
                             requires="united states|us.?based|within the us"),
                ModifierRule(signal="aws", pattern="aws|amazon web services", points=1.0, check="jd"),
            ],
            negative_modifiers=[
                ModifierRule(signal="city_only_no_remote", points=-2.0, check="location_only"),
            ],
            freshness=FreshnessConfig(),
        )

    def test_remote_us_texas_not_austin_area(self):
        """Remote - US listing with Texas in JD → remote_us, NOT austin_area.
        Remote roles don't get the local bonus even if Texas is mentioned."""
        rubric = self._make_rubric_with_location()
        jd = "Senior SRE. Remote within the United States. Texas-based. AWS. " + "x" * 500
        result = score_job(
            title="Senior SRE", jd_text=jd, location="Remote, US",
            company="TestCo", rubric=rubric, profile=_make_profile(),
            workplace_type="Remote",
        )
        assert "remote_us" in result.fired_modifiers
        assert result.fired_modifiers["remote_us"] == 1.0
        assert "austin_area" not in result.fired_modifiers
        assert not any("austin_area" in r for r in result.reasons)

    def test_hybrid_austin_gets_austin_area(self):
        """Hybrid · Austin, TX → austin_area bonus applies (hybrid/onsite in accepted city)."""
        rubric = self._make_rubric_with_location()
        jd = "Senior SRE. AWS required. " + "x" * 500
        result = score_job(
            title="Senior SRE", jd_text=jd, location="Austin, TX",
            company="TestCo", rubric=rubric, profile=_make_profile(),
            workplace_type="Hybrid",
        )
        assert "austin_area" in result.fired_modifiers
        assert result.fired_modifiers["austin_area"] == 1.5
        assert any("austin_area" in r for r in result.reasons)

    def test_onsite_austin_gets_austin_area(self):
        """On-Site · Austin, TX → austin_area bonus applies."""
        rubric = self._make_rubric_with_location()
        jd = "Senior SRE. AWS required. " + "x" * 500
        result = score_job(
            title="Senior SRE", jd_text=jd, location="Austin, TX",
            company="TestCo", rubric=rubric, profile=_make_profile(),
            workplace_type="On-Site",
        )
        assert "austin_area" in result.fired_modifiers

    def test_remote_austin_no_austin_area(self):
        """Remote role with Austin in location → no austin_area (workplace_type is Remote)."""
        rubric = self._make_rubric_with_location()
        jd = "Senior SRE. Remote. AWS. " + "x" * 500
        result = score_job(
            title="Senior SRE", jd_text=jd, location="Austin, TX",
            company="TestCo", rubric=rubric, profile=_make_profile(),
            workplace_type="Remote",
        )
        assert "austin_area" not in result.fired_modifiers

    def test_hybrid_non_accepted_city_no_austin_area(self):
        """Hybrid in a non-accepted city → no austin_area bonus."""
        rubric = self._make_rubric_with_location()
        jd = "Senior SRE. AWS required. " + "x" * 500
        result = score_job(
            title="Senior SRE", jd_text=jd, location="San Francisco, CA",
            company="TestCo", rubric=rubric, profile=_make_profile(),
            workplace_type="Hybrid",
        )
        assert "austin_area" not in result.fired_modifiers

    def test_city_only_no_remote_not_firing_on_accepted_city(self):
        """A located non-remote role in an accepted city does NOT fire city_only_no_remote.
        Previously, location_only returned True for any non-empty location."""
        rubric = self._make_rubric_with_location()
        jd = "Senior SRE. AWS required. " + "x" * 500
        result = score_job(
            title="Senior SRE", jd_text=jd, location="Austin, TX",
            company="TestCo", rubric=rubric, profile=_make_profile(),
            workplace_type="Hybrid",
        )
        assert "city_only_no_remote" not in result.fired_modifiers

    def test_city_only_no_remote_fires_on_non_accepted_city(self):
        """A located non-remote role in a non-accepted city DOES fire city_only_no_remote."""
        rubric = self._make_rubric_with_location()
        jd = "Senior SRE. AWS required. " + "x" * 500
        result = score_job(
            title="Senior SRE", jd_text=jd, location="Denver, CO",
            company="TestCo", rubric=rubric, profile=_make_profile(),
            workplace_type="On-Site",
        )
        assert "city_only_no_remote" in result.fired_modifiers
        assert result.fired_modifiers["city_only_no_remote"] == -2.0

    def test_city_only_no_remote_not_firing_on_remote_role(self):
        """A remote role with a non-accepted city in location does NOT fire city_only_no_remote."""
        rubric = self._make_rubric_with_location()
        jd = "Senior SRE. Remote. AWS. " + "x" * 500
        result = score_job(
            title="Senior SRE", jd_text=jd, location="Denver, CO",
            company="TestCo", rubric=rubric, profile=_make_profile(),
            workplace_type="Remote",
        )
        assert "city_only_no_remote" not in result.fired_modifiers

    def test_hybrid_georgetown_no_hybrid_non_local(self):
        """Hybrid role in Georgetown (accepted city NOT in old 3-city unless list)
        gets austin_area +1.5 but NOT hybrid_non_local -3.0.
        Previously, hybrid_non_local's unless only listed austin|leander|cedar park|remote,
        so Georgetown got both +1.5 and -3.0 = net -1.5 for a local role."""
        rubric = ScoringConfig(
            post_threshold=6.0, per_company_cap=3, max_score=10, min_score=0,
            base_scores=[
                BaseScoreRule(pattern="senior.*(sre|site reliability|platform|infra)", score=4.0, label="Senior SRE"),
                BaseScoreRule(score=0, label="No match"),
            ],
            positive_modifiers=[
                ModifierRule(signal="austin_area", points=1.5, check="location_local"),
                ModifierRule(signal="aws", pattern="aws|amazon web services", points=1.0, check="jd"),
            ],
            negative_modifiers=[
                ModifierRule(signal="hybrid_non_local", pattern="hybrid", points=-3.0,
                             check="hybrid_non_local", unless="remote"),
            ],
            freshness=FreshnessConfig(),
        )
        jd = "Senior SRE. Hybrid schedule. AWS required. " + "x" * 500
        result = score_job(
            title="Senior SRE", jd_text=jd, location="Georgetown, TX",
            company="TestCo", rubric=rubric, profile=_make_profile(),
            workplace_type="Hybrid",
        )
        assert "austin_area" in result.fired_modifiers
        assert result.fired_modifiers["austin_area"] == 1.5
        assert "hybrid_non_local" not in result.fired_modifiers
        # Net: base 4.0 + aws 1.0 + austin_area 1.5 = 6.5 (no -3.0)
        assert result.score == 6.5

    def test_hybrid_non_accepted_city_gets_hybrid_non_local(self):
        """Hybrid role in a non-accepted city DOES get hybrid_non_local -3.0."""
        rubric = ScoringConfig(
            post_threshold=6.0, per_company_cap=3, max_score=10, min_score=0,
            base_scores=[
                BaseScoreRule(pattern="senior.*(sre|site reliability|platform|infra)", score=4.0, label="Senior SRE"),
                BaseScoreRule(score=0, label="No match"),
            ],
            positive_modifiers=[
                ModifierRule(signal="austin_area", points=1.5, check="location_local"),
                ModifierRule(signal="aws", pattern="aws|amazon web services", points=1.0, check="jd"),
            ],
            negative_modifiers=[
                ModifierRule(signal="hybrid_non_local", pattern="hybrid", points=-3.0,
                             check="hybrid_non_local", unless="remote"),
            ],
            freshness=FreshnessConfig(),
        )
        jd = "Senior SRE. Hybrid schedule. AWS required. " + "x" * 500
        result = score_job(
            title="Senior SRE", jd_text=jd, location="Denver, CO",
            company="TestCo", rubric=rubric, profile=_make_profile(),
            workplace_type="Hybrid",
        )
        assert "austin_area" not in result.fired_modifiers
        assert "hybrid_non_local" in result.fired_modifiers
        assert result.fired_modifiers["hybrid_non_local"] == -3.0

    def test_hybrid_remote_jd_no_hybrid_non_local(self):
        """Hybrid keyword in JD but JD also says remote → no hybrid_non_local penalty."""
        rubric = ScoringConfig(
            post_threshold=6.0, per_company_cap=3, max_score=10, min_score=0,
            base_scores=[
                BaseScoreRule(pattern="senior.*(sre|site reliability|platform|infra)", score=4.0, label="Senior SRE"),
                BaseScoreRule(score=0, label="No match"),
            ],
            positive_modifiers=[
                ModifierRule(signal="aws", pattern="aws|amazon web services", points=1.0, check="jd"),
            ],
            negative_modifiers=[
                ModifierRule(signal="hybrid_non_local", pattern="hybrid", points=-3.0,
                             check="hybrid_non_local", unless="remote"),
                ModifierRule(signal="missing_location", points=-1.5, check="no_location_no_remote"),
            ],
            freshness=FreshnessConfig(),
        )
        jd = "Senior SRE. Hybrid or remote. AWS. " + "x" * 500
        result = score_job(
            title="Senior SRE", jd_text=jd, location="Denver, CO",
            company="TestCo", rubric=rubric, profile=_make_profile(),
            workplace_type="Remote",
        )
        assert "hybrid_non_local" not in result.fired_modifiers

    def test_hybrid_no_location_no_double_stack(self):
        """Hybrid JD with no location → hybrid_non_local does NOT fire.
        missing_location handles the no-location penalty (-1.5).
        They must not co-fire (-3.0 + -1.5 = -4.5 would be a double-stack)."""
        rubric = ScoringConfig(
            post_threshold=6.0, per_company_cap=3, max_score=10, min_score=0,
            base_scores=[
                BaseScoreRule(pattern="senior.*(sre|site reliability|platform|infra)", score=4.0, label="Senior SRE"),
                BaseScoreRule(score=0, label="No match"),
            ],
            positive_modifiers=[
                ModifierRule(signal="aws", pattern="aws|amazon web services", points=1.0, check="jd"),
            ],
            negative_modifiers=[
                ModifierRule(signal="hybrid_non_local", pattern="hybrid", points=-3.0,
                             check="hybrid_non_local", unless="remote"),
                ModifierRule(signal="missing_location", points=-1.5, check="no_location_no_remote"),
            ],
            freshness=FreshnessConfig(),
        )
        # JD mentions "us" (passes evidence gate) but not "remote" or "united states"
        jd = "Senior SRE. Hybrid schedule. Based in US. AWS. " + "x" * 500
        result = score_job(
            title="Senior SRE", jd_text=jd, location="",
            company="TestCo", rubric=rubric, profile=_make_profile(),
            workplace_type="Hybrid",
        )
        assert "hybrid_non_local" not in result.fired_modifiers
        assert "missing_location" in result.fired_modifiers

    # --- Phase 3b: Director base-score tier ---

    def _make_rubric_with_director(self) -> ScoringConfig:
        """Rubric with the director base-score tier and people_management penalty."""
        return ScoringConfig(
            post_threshold=6.0, per_company_cap=3, max_score=10, min_score=0,
            base_scores=[
                BaseScoreRule(pattern="(principal|staff).*(sre|site reliability|platform|infra|devops|infrastructure)", score=4.5, label="Principal/Staff"),
                BaseScoreRule(pattern="director.*(sre|site reliability|platform|infra|infrastructure|devops|engineering)", score=4.0, label="Director"),
                BaseScoreRule(pattern="senior.*(sre|site reliability|platform|infra)", score=4.0, label="Senior SRE"),
                BaseScoreRule(score=0, label="No match"),
            ],
            positive_modifiers=[
                ModifierRule(signal="aws", pattern="aws|amazon web services", points=1.0, check="jd"),
                ModifierRule(signal="remote_us", pattern="remote", points=1.0, check="jd",
                             requires="united states|us.?based|within the us"),
            ],
            negative_modifiers=[
                ModifierRule(signal="people_management", pattern="performance review|headcount|hiring decision|manage.*team of", points=-2.0, check="jd"),
            ],
            freshness=FreshnessConfig(),
        )

    def test_director_platform_engineering_scores_4_tier(self):
        """Director, Platform Engineering matches the new director base-score tier (4.0)."""
        rubric = self._make_rubric_with_director()
        jd = "Director of Platform Engineering. AWS. Remote within the United States. " + "x" * 500
        result = score_job(
            title="Director, Platform Engineering", jd_text=jd, location="Remote, US",
            company="TestCo", rubric=rubric, profile=_make_profile(),
            workplace_type="Remote",
        )
        assert result.score == 6.0  # base 4.0 + aws 1.0 + remote_us 1.0
        assert any("Director" in r for r in result.reasons)

    def test_director_engineering_people_management_penalty(self):
        """Director, Engineering with heavy people-management JD takes people_management -2.0.
        The existing penalty + verdict cap separate technical-leadership directors from pure people-managers."""
        rubric = self._make_rubric_with_director()
        jd = ("Director of Engineering. You will oversee performance reviews, "
              "manage headcount planning, and make hiring decisions for the team. "
              "AWS. Remote within the United States. " + "x" * 500)
        result = score_job(
            title="Director, Engineering", jd_text=jd, location="Remote, US",
            company="TestCo", rubric=rubric, profile=_make_profile(),
            workplace_type="Remote",
        )
        # base 4.0 + aws 1.0 + remote_us 1.0 - people_management 2.0 = 4.0
        assert "people_management" in result.fired_modifiers
        assert result.fired_modifiers["people_management"] == -2.0
        assert result.score == 4.0

    def test_director_does_not_match_senior_pattern(self):
        """Director title matches the director tier, not the senior tier (first match wins)."""
        rubric = self._make_rubric_with_director()
        jd = "Director, SRE. AWS. " + "x" * 500
        result = score_job(
            title="Director, SRE", jd_text=jd, location="Remote, US",
            company="TestCo", rubric=rubric, profile=_make_profile(),
            workplace_type="Remote",
        )
        # Should match director tier (4.0), not senior SRE tier (also 4.0 but director is first)
        assert any("Director" in r for r in result.reasons)
        assert not any("Senior SRE" in r for r in result.reasons)
