"""Tests for the never_claim_density negative modifier check type.

The never_claim_density check reads the never_claim list from
identity_rules.yml (no technology names hardcoded in Python or the rubric),
counts DISTINCT never-claim technologies in the JD text (word-boundary,
case-insensitive), and applies a scaled penalty:
  - points_per_hit * distinct_count, clamped at max_penalty
  - OR primary_stack_penalty when a term appears in the title or
    >= primary_stack_min_mentions times in the JD

Test cases:
1. Zero hits — no never-claim tech in JD → no fire.
2. Single incidental mention — 1 distinct hit → scaled penalty.
3. Laundry-list JD with 5 distinct never-claim techs → clamps at max_penalty.
4. Title hit — never-claim term in title → primary_stack_penalty wins.
5. High mention count — term >= primary_stack_min_mentions in JD → primary_stack_penalty.
6. Empty/missing never_claim config → no-op, no crash.
7. ArgoCD+Helm interaction — JD that nets positive via kubernetes/cicd/platform
   keywords must score below post_threshold after the modifier fires.
"""

from seeker_os.config import (
    ScoringConfig, BaseScoreRule, ModifierRule, FreshnessConfig,
    ProfileConfig, UserIdentity, LocationPrefs, CompPrefs,
    ExperiencePrefs, EmploymentPrefs, ResumePrefs, CrossReferencePrefs,
    HardReject,
)
from seeker_os.scoring.engine import (
    score_job, _check_modifier, _never_claim_matches,
    _never_claim_jd_mention_count, _compute_never_claim_penalty,
)


# --- Fixtures ---

NEVER_CLAIM = ["ArgoCD", "Helm", "Kargo", "Consul", "Vault", "Rust", "Temporal", "Ansible"]


def _make_never_claim_mod() -> ModifierRule:
    return ModifierRule(
        signal="never_claim_density",
        check="never_claim_density",
        points_per_hit=-0.5,
        max_penalty=-2.5,
        primary_stack_penalty=-3.0,
        primary_stack_min_mentions=3,
    )


def _make_rubric(with_never_claim: bool = True) -> ScoringConfig:
    neg_mods: list[ModifierRule] = []
    if with_never_claim:
        neg_mods.append(_make_never_claim_mod())
    return ScoringConfig(
        post_threshold=6.0,
        per_company_cap=3,
        max_score=10,
        min_score=0,
        base_scores=[
            BaseScoreRule(pattern="(principal|staff).*(sre|site reliability|platform|infra|devops)", score=4.5, label="Principal/Staff"),
            BaseScoreRule(pattern="(senior|sr\\.?).*?(sre|site reliability|platform|infra)", score=4.0, label="Senior SRE/Platform"),
            BaseScoreRule(score=0, label="No match"),
        ],
        positive_modifiers=[
            ModifierRule(signal="aws", pattern="aws|amazon web services", points=1.0, check="jd"),
            ModifierRule(signal="terraform", pattern="terraform", points=1.0, check="jd"),
            ModifierRule(signal="kubernetes", pattern="kubernetes|k8s", points=0.5, check="jd"),
            ModifierRule(signal="cicd", pattern="ci/cd|cicd|continuous integration", points=0.5, check="jd"),
            ModifierRule(signal="remote_us", pattern="remote", points=1.0, check="jd", requires="united states|us.?based"),
        ],
        negative_modifiers=neg_mods,
        freshness=FreshnessConfig(),
    )


def _make_profile() -> ProfileConfig:
    return ProfileConfig(
        user=UserIdentity(name="Test", email="test@test.com", location="Austin, TX"),
        location=LocationPrefs(remote_only=True, accepted_cities=["austin"]),
        comp=CompPrefs(floor=150000, target=165000, stretch=220000),
        experience=ExperiencePrefs(years=25, anchor_phrase="25+ years"),
        employment=EmploymentPrefs(commitment="Full Time", role_type="Individual Contributor"),
        blacklist=[],
        resume=ResumePrefs(master_path="~/resume.md", accuracy_rules_path="config/accuracy_rules.yml", output_dir="data/resumes"),
        cross_reference=CrossReferencePrefs(repo_path="~/projects/job-search"),
        hard_rejects=[],
    )


# --- _check_modifier and helper unit tests ---

class TestNeverClaimCheck:
    def test_zero_hits_no_fire(self):
        """JD with no never-claim techs → check does not fire."""
        mod = _make_never_claim_mod()
        jd = "Senior SRE role using AWS, Terraform, and Kubernetes. Remote, United States. " + "x" * 500
        assert not _check_modifier(mod, title="Senior SRE", jd_text=jd, location="Remote, US",
                                   comp_min=None, comp_max=None, never_claim=NEVER_CLAIM)

    def test_single_incidental_mention_fires(self):
        """1 distinct never-claim tech → check fires (scaled penalty computed in score_job)."""
        mod = _make_never_claim_mod()
        jd = "Senior SRE role. Experience with Helm for package management. AWS, Terraform. " + "x" * 500
        assert _check_modifier(mod, title="Senior SRE", jd_text=jd, location="Remote, US",
                               comp_min=None, comp_max=None, never_claim=NEVER_CLAIM)

    def test_empty_never_claim_no_fire(self):
        """Empty never_claim list → no fire, no crash."""
        mod = _make_never_claim_mod()
        jd = "Senior SRE role. ArgoCD Helm Kubernetes. " + "x" * 500
        assert not _check_modifier(mod, title="Senior SRE", jd_text=jd, location="Remote, US",
                                   comp_min=None, comp_max=None, never_claim=[])
        assert not _check_modifier(mod, title="Senior SRE", jd_text=jd, location="Remote, US",
                                   comp_min=None, comp_max=None, never_claim=None)

    def test_never_claim_matches_returns_distinct(self):
        """_never_claim_matches returns each matched tech once."""
        jd = "We use ArgoCD and Helm. Also ArgoCD again and Helm again."
        matched = _never_claim_matches(NEVER_CLAIM, jd)
        assert "ArgoCD" in matched
        assert "Helm" in matched
        assert len(matched) == 2  # no duplicates

    def test_never_claim_matches_case_insensitive(self):
        """Matching is case-insensitive."""
        jd = "Experience with argocd and HELM required."
        matched = _never_claim_matches(NEVER_CLAIM, jd)
        assert "ArgoCD" in matched
        assert "Helm" in matched

    def test_never_claim_matches_word_boundary(self):
        """Matching uses word boundaries."""
        jd = "We use Helmets for safety and Kargos for transport."
        matched = _never_claim_matches(NEVER_CLAIM, jd)
        assert "Helm" not in matched
        assert "Kargo" not in matched


# --- _compute_never_claim_penalty tests ---

class TestNeverClaimPenalty:
    def test_single_hit_scaled(self):
        """1 distinct hit → points_per_hit * 1."""
        mod = _make_never_claim_mod()
        jd = "Experience with Helm required."
        penalty, matched, detail = _compute_never_claim_penalty(mod, NEVER_CLAIM, "Senior SRE", jd)
        assert penalty == -0.5
        assert matched == ["Helm"]
        assert "1 distinct" in detail

    def test_five_hits_clamp_at_max_penalty(self):
        """5 distinct hits → points_per_hit * 5 = -2.5, clamped at max_penalty = -2.5."""
        mod = _make_never_claim_mod()
        jd = "We use ArgoCD, Helm, Kargo, Consul, and Vault in our stack."
        penalty, matched, detail = _compute_never_claim_penalty(mod, NEVER_CLAIM, "Senior SRE", jd)
        # -0.5 * 5 = -2.5, max_penalty = -2.5, max(-2.5, -2.5) = -2.5
        assert penalty == -2.5
        assert len(matched) == 5
        assert "5 distinct" in detail

    def test_six_hits_clamp_at_max_penalty(self):
        """6 distinct hits → -0.5 * 6 = -3.0, clamped at max_penalty = -2.5."""
        mod = _make_never_claim_mod()
        jd = "We use ArgoCD, Helm, Kargo, Consul, Vault, and Ansible."
        penalty, matched, detail = _compute_never_claim_penalty(mod, NEVER_CLAIM, "Senior SRE", jd)
        assert penalty == -2.5  # clamped
        assert len(matched) == 6

    def test_title_hit_primary_stack(self):
        """Never-claim term in title → primary_stack_penalty."""
        mod = _make_never_claim_mod()
        jd = "We use ArgoCD and Helm for deployments. " + "x" * 500
        penalty, matched, detail = _compute_never_claim_penalty(mod, NEVER_CLAIM, "Senior ArgoCD Engineer", jd)
        assert penalty == -3.0
        assert "primary_stack: ArgoCD" in detail

    def test_high_mention_count_primary_stack(self):
        """Never-claim term >= primary_stack_min_mentions in JD → primary_stack_penalty."""
        mod = _make_never_claim_mod()
        jd = "We use Helm. Helm is core. Helm Helm Helm. Also some ArgoCD."
        penalty, matched, detail = _compute_never_claim_penalty(mod, NEVER_CLAIM, "Senior SRE", jd)
        assert penalty == -3.0
        assert "primary_stack: Helm" in detail

    def test_mention_below_threshold_scaled(self):
        """Never-claim term mentioned < primary_stack_min_mentions → scaled, not primary."""
        mod = _make_never_claim_mod()
        jd = "We use Helm. Helm is nice. Also ArgoCD."
        penalty, matched, detail = _compute_never_claim_penalty(mod, NEVER_CLAIM, "Senior SRE", jd)
        # 2 distinct hits, neither >= 3 mentions → scaled
        assert penalty == -1.0  # -0.5 * 2
        assert "2 distinct" in detail

    def test_empty_never_claim_penalty_zero(self):
        """Empty never_claim → zero penalty, no crash."""
        mod = _make_never_claim_mod()
        penalty, matched, detail = _compute_never_claim_penalty(mod, [], "Senior SRE", "ArgoCD Helm")
        assert penalty == 0.0
        assert matched == []


# --- End-to-end scoring tests ---

class TestNeverClaimScoring:
    def test_zero_hits_no_effect(self):
        """JD with no never-claim techs → score unchanged with/without modifier."""
        jd = "Senior SRE role using AWS, Terraform, Kubernetes. CI/CD pipelines. Remote, United States. " + "x" * 500
        rubric_with = _make_rubric(with_never_claim=True)
        rubric_without = _make_rubric(with_never_claim=False)
        result_with = score_job(
            title="Senior SRE", jd_text=jd, location="Remote, US",
            company="CloudCo", rubric=rubric_with, profile=_make_profile(),
            never_claim=NEVER_CLAIM,
        )
        result_without = score_job(
            title="Senior SRE", jd_text=jd, location="Remote, US",
            company="CloudCo", rubric=rubric_without, profile=_make_profile(),
            never_claim=NEVER_CLAIM,
        )
        assert result_with.score == result_without.score
        assert "never_claim_density" not in result_with.fired_modifiers

    def test_single_incidental_mention_scaled_penalty(self):
        """1 never-claim tech → -0.5 penalty applied, recorded in fired_modifiers."""
        jd = "Senior SRE role. Experience with Helm for package management. AWS, Terraform, Kubernetes. CI/CD. Remote, United States. " + "x" * 500
        rubric = _make_rubric(with_never_claim=True)
        result = score_job(
            title="Senior SRE", jd_text=jd, location="Remote, US",
            company="CloudCo", rubric=rubric, profile=_make_profile(),
            never_claim=NEVER_CLAIM,
        )
        assert "never_claim_density" in result.fired_modifiers
        assert result.fired_modifiers["never_claim_density"] == -0.5

    def test_laundry_list_clamps_at_max_penalty(self):
        """5 distinct never-claim techs → penalty clamps at max_penalty (-2.5)."""
        jd = "Senior SRE role. We use ArgoCD, Helm, Kargo, Consul, and Vault. AWS, Terraform, Kubernetes. CI/CD. Remote, United States. " + "x" * 500
        rubric = _make_rubric(with_never_claim=True)
        result = score_job(
            title="Senior SRE", jd_text=jd, location="Remote, US",
            company="CloudCo", rubric=rubric, profile=_make_profile(),
            never_claim=NEVER_CLAIM,
        )
        assert result.fired_modifiers["never_claim_density"] == -2.5

    def test_title_hit_primary_stack_penalty(self):
        """Never-claim term in title → primary_stack_penalty (-3.0)."""
        jd = "We use ArgoCD and Helm for deployments. AWS, Terraform, Kubernetes. CI/CD. Remote, United States. " + "x" * 500
        rubric = _make_rubric(with_never_claim=True)
        result = score_job(
            title="Senior ArgoCD Engineer", jd_text=jd, location="Remote, US",
            company="CloudCo", rubric=rubric, profile=_make_profile(),
            never_claim=NEVER_CLAIM,
        )
        assert result.fired_modifiers["never_claim_density"] == -3.0

    def test_empty_never_claim_is_noop(self):
        """Empty never_claim → modifier is a no-op, no crash."""
        jd = "Senior SRE role. ArgoCD Helm Kargo. AWS, Terraform. Remote, United States. " + "x" * 500
        rubric = _make_rubric(with_never_claim=True)
        result = score_job(
            title="Senior SRE", jd_text=jd, location="Remote, US",
            company="CloudCo", rubric=rubric, profile=_make_profile(),
            never_claim=[],
        )
        assert "never_claim_density" not in result.fired_modifiers

        # Also test None
        result_none = score_job(
            title="Senior SRE", jd_text=jd, location="Remote, US",
            company="CloudCo", rubric=rubric, profile=_make_profile(),
            never_claim=None,
        )
        assert "never_claim_density" not in result_none.fired_modifiers

    def test_reason_records_matched_techs(self):
        """Score breakdown reason string lists matched technologies."""
        jd = "Senior SRE role. We use ArgoCD and Helm. AWS, Terraform, Kubernetes. CI/CD. Remote, United States. " + "x" * 500
        rubric = _make_rubric(with_never_claim=True)
        result = score_job(
            title="Senior SRE", jd_text=jd, location="Remote, US",
            company="CloudCo", rubric=rubric, profile=_make_profile(),
            never_claim=NEVER_CLAIM,
        )
        nc_reasons = [r for r in result.reasons if "never_claim_density" in r]
        assert len(nc_reasons) == 1
        assert "ArgoCD" in nc_reasons[0]
        assert "Helm" in nc_reasons[0]

    def test_argocd_helm_jd_scores_below_threshold(self):
        """Critical interaction: a JD centered on ArgoCD + Helm that nets
        POSITIVE points via kubernetes/cicd/platform keyword modifiers must
        score below the post threshold after the never_claim_density modifier fires.

        This is the key acceptance test — ArgoCD and Helm are in the never_claim
        list, and a JD that is centered on them (2+ distinct hits) should be
        penalized enough to drop below 6.0 even though it carries positive
        vocabulary like kubernetes, CI/CD, and platform."""
        jd = """
        Senior Platform Engineer - GitOps Infrastructure

        We are seeking a Senior Platform Engineer to own our GitOps
        infrastructure. You will be the primary maintainer of our ArgoCD
        deployment system and Helm chart catalog.

        Responsibilities:
        - Manage ArgoCD application sets and Helm chart deployments across
          Kubernetes clusters
        - Build CI/CD pipelines for infrastructure automation
        - Maintain our internal platform for developer self-service
        - Work with AWS infrastructure and Terraform modules
        - Ensure platform reliability and observability

        Requirements:
        - Deep expertise in ArgoCD and Helm
        - Strong Kubernetes experience
        - AWS and Terraform proficiency
        - CI/CD pipeline design
        - Remote, United States based

        This is a remote position. You will own the ArgoCD and Helm
        platform that powers all our deployments.
        """
        rubric = _make_rubric(with_never_claim=True)
        result = score_job(
            title="Senior Platform Engineer",
            jd_text=jd,
            location="Remote, US",
            company="GitOpsCo",
            rubric=rubric,
            profile=_make_profile(),
            never_claim=NEVER_CLAIM,
        )
        assert result.score < 6.0, f"Expected score < 6.0 with never_claim_density, got {result.score}"
        assert "never_claim_density" in result.fired_modifiers

    def test_argocd_helm_jd_scores_above_threshold_without_modifier(self):
        """Same JD without the never_claim_density modifier should score >= 6.0,
        confirming the modifier is what brings it down."""
        jd = """
        Senior Platform Engineer - GitOps Infrastructure

        We are seeking a Senior Platform Engineer to own our GitOps
        infrastructure. You will be the primary maintainer of our ArgoCD
        deployment system and Helm chart catalog.

        Responsibilities:
        - Manage ArgoCD application sets and Helm chart deployments across
          Kubernetes clusters
        - Build CI/CD pipelines for infrastructure automation
        - Maintain our internal platform for developer self-service
        - Work with AWS infrastructure and Terraform modules
        - Ensure platform reliability and observability

        Requirements:
        - Deep expertise in ArgoCD and Helm
        - Strong Kubernetes experience
        - AWS and Terraform proficiency
        - CI/CD pipeline design
        - Remote, United States based

        This is a remote position. You will own the ArgoCD and Helm
        platform that powers all our deployments.
        """
        rubric = _make_rubric(with_never_claim=False)
        result = score_job(
            title="Senior Platform Engineer",
            jd_text=jd,
            location="Remote, US",
            company="GitOpsCo",
            rubric=rubric,
            profile=_make_profile(),
            never_claim=NEVER_CLAIM,
        )
        assert result.score >= 6.0, f"Expected score >= 6.0 without modifier, got {result.score}"
        assert "never_claim_density" not in result.fired_modifiers


# --- density_exclude tests ---

class TestDensityExclude:
    """Tests for the density_exclude config field on never_claim_density.

    Excluded terms are skipped by the density count and the primary-stack
    check. The identity never_claim list itself is unchanged (it still gates
    resumes); density_exclude is a scoring-layer override only.
    """

    def test_excluded_term_ignored_in_count(self):
        """An excluded term that appears in the JD does not count toward
        the density count or the penalty."""
        mod = ModifierRule(
            signal="never_claim_density",
            check="never_claim_density",
            points_per_hit=-0.5,
            max_penalty=-2.5,
            primary_stack_penalty=-3.0,
            primary_stack_min_mentions=3,
            density_exclude=["Helm"],
        )
        # Only Helm appears → excluded → no match → no fire
        jd = "We use Helm extensively. " + "x" * 500
        assert not _check_modifier(mod, title="Senior SRE", jd_text=jd, location="Remote, US",
                                   comp_min=None, comp_max=None,
                                   never_claim=NEVER_CLAIM)

    def test_excluded_term_does_not_block_other_matches(self):
        """Excluded term is skipped but other non-excluded terms still count."""
        mod = ModifierRule(
            signal="never_claim_density",
            check="never_claim_density",
            points_per_hit=-0.5,
            max_penalty=-2.5,
            primary_stack_penalty=-3.0,
            primary_stack_min_mentions=3,
            density_exclude=["Helm"],
        )
        # Helm excluded, ArgoCD still counts → 1 distinct hit → fires
        jd = "We use ArgoCD and Helm. " + "x" * 500
        assert _check_modifier(mod, title="Senior SRE", jd_text=jd, location="Remote, US",
                               comp_min=None, comp_max=None,
                               never_claim=NEVER_CLAIM)
        # Penalty should be -0.5 (only ArgoCD, Helm excluded)
        penalty, matched, detail = _compute_never_claim_penalty(
            mod, NEVER_CLAIM, "Senior SRE", jd,
        )
        assert penalty == -0.5
        assert matched == ["ArgoCD"]
        assert "Helm" not in matched

    def test_excluded_term_in_title_no_primary_stack(self):
        """An excluded term in the title does NOT trigger primary_stack_penalty.
        Only non-excluded terms can trigger primary_stack."""
        mod = ModifierRule(
            signal="never_claim_density",
            check="never_claim_density",
            points_per_hit=-0.5,
            max_penalty=-2.5,
            primary_stack_penalty=-3.0,
            primary_stack_min_mentions=3,
            density_exclude=["Helm"],
        )
        # Helm in title but excluded → no primary_stack from Helm.
        # ArgoCD in JD (1 mention, < 3) → scaled penalty.
        jd = "We use ArgoCD and Helm. " + "x" * 500
        penalty, matched, detail = _compute_never_claim_penalty(
            mod, NEVER_CLAIM, "Senior Helm Engineer", jd,
        )
        assert penalty == -0.5  # scaled, not -3.0
        assert "primary_stack" not in detail

    def test_excluded_term_high_mentions_no_primary_stack(self):
        """An excluded term with high JD mentions does NOT trigger primary_stack."""
        mod = ModifierRule(
            signal="never_claim_density",
            check="never_claim_density",
            points_per_hit=-0.5,
            max_penalty=-2.5,
            primary_stack_penalty=-3.0,
            primary_stack_min_mentions=3,
            density_exclude=["Helm"],
        )
        # Helm mentioned 5 times but excluded → no primary_stack from Helm.
        # ArgoCD mentioned once → scaled.
        jd = "Helm Helm Helm Helm Helm. ArgoCD. " + "x" * 500
        penalty, matched, detail = _compute_never_claim_penalty(
            mod, NEVER_CLAIM, "Senior SRE", jd,
        )
        assert penalty == -0.5  # scaled, not -3.0
        assert "primary_stack" not in detail

    def test_no_density_exclude_is_noop(self):
        """Absent density_exclude (None) → all terms count normally."""
        mod = ModifierRule(
            signal="never_claim_density",
            check="never_claim_density",
            points_per_hit=-0.5,
            max_penalty=-2.5,
            primary_stack_penalty=-3.0,
            primary_stack_min_mentions=3,
            # density_exclude not set
        )
        jd = "We use ArgoCD and Helm. " + "x" * 500
        penalty, matched, detail = _compute_never_claim_penalty(
            mod, NEVER_CLAIM, "Senior SRE", jd,
        )
        assert penalty == -1.0  # 2 distinct × -0.5
        assert len(matched) == 2

    def test_exclude_all_terms_no_fire(self):
        """All never-claim terms excluded → no fire, no crash."""
        mod = ModifierRule(
            signal="never_claim_density",
            check="never_claim_density",
            points_per_hit=-0.5,
            max_penalty=-2.5,
            primary_stack_penalty=-3.0,
            primary_stack_min_mentions=3,
            density_exclude=NEVER_CLAIM,  # exclude everything
        )
        jd = "We use ArgoCD, Helm, Kargo, Consul, Vault. " + "x" * 500
        assert not _check_modifier(mod, title="Senior SRE", jd_text=jd, location="Remote, US",
                                   comp_min=None, comp_max=None,
                                   never_claim=NEVER_CLAIM)


# --- points validation tests ---

class TestPointsValidation:
    """Tests for fail-loud validation of the points field on ModifierRule.

    points is required on non-dynamic check types. Only check types that
    compute penalty dynamically (currently never_claim_density) may omit it.
    """

    def test_normal_modifier_without_points_fails(self):
        """A jd-check modifier without points raises ValueError on construction."""
        import pytest
        with pytest.raises(ValueError, match="missing required 'points'"):
            ModifierRule(
                signal="relocation_required",
                pattern="relocation required",
                check="jd",
            )

    def test_domain_mismatch_without_points_fails(self):
        """A domain_mismatch modifier without points also fails (it uses fixed points)."""
        import pytest
        with pytest.raises(ValueError, match="missing required 'points'"):
            ModifierRule(
                signal="domain_mismatch",
                check="domain_mismatch",
                min_distinct_hits=3,
                patterns=[r"\bbgp\b"],
            )

    def test_never_claim_density_without_points_loads_fine(self):
        """never_claim_density computes penalty dynamically — points not required."""
        mod = ModifierRule(
            signal="never_claim_density",
            check="never_claim_density",
            points_per_hit=-0.5,
            max_penalty=-2.5,
            primary_stack_penalty=-3.0,
            primary_stack_min_mentions=3,
        )
        assert mod.points is None  # not set, not defaulted to 0

    def test_normal_modifier_with_points_loads_fine(self):
        """A jd-check modifier with points loads normally."""
        mod = ModifierRule(
            signal="relocation_required",
            pattern="relocation required",
            points=-3.0,
            check="jd",
        )
        assert mod.points == -3.0
