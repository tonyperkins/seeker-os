"""Tests for the domain_mismatch negative modifier check type.

The domain_mismatch check fires when the number of DISTINCT off-domain
patterns matching the JD text meets min_distinct_hits. This catches roles
that match the title (e.g. "SRE") but belong to a different engineering
domain (e.g. carrier/network engineering).

Test cases:
1. Realistic carrier-network JD with SRE title + generic cloud keywords
   scores >= 6.0 without the modifier, below post_threshold after it fires.
2. 2 distinct hits below threshold (no fire).
3. Same term repeated many times counts as 1 distinct hit (no fire).
4. Absent config (no domain_mismatch modifier) is a no-op.
"""

import pytest

from seeker_os.config import (
    ScoringConfig, BaseScoreRule, ModifierRule, FreshnessConfig,
    ProfileConfig, UserIdentity, LocationPrefs, CompPrefs,
    ExperiencePrefs, EmploymentPrefs, ResumePrefs, CrossReferencePrefs,
    HardReject,
)
from seeker_os.scoring.engine import score_job, _check_modifier, _domain_mismatch_matches


# --- Fixtures ---

CARRIER_PATTERNS = [
    r"\bcisco\s+ios\b",
    r"\bjuniper\b",
    r"\bbgp\b",
    r"\bospf\b",
    r"sd.?wan",
    r"\bnoc\b",
    r"carrier.?grade",
    r"\bmpls\b",
]

DATA_PLATFORM_PATTERNS = [
    r"\bdbt\b",
    r"\bairflow\b",
    r"\bspark\b",
    r"\bsnowflake\b",
    r"\blakehouse\b",
    r"data.?pipeline",
    r"\betl\b",
    r"data.?warehouse",
    r"\bdatabricks\b",
]


def _make_rubric(with_domain_mismatch: bool = True) -> ScoringConfig:
    neg_mods = [
        ModifierRule(signal="relocation_required", pattern="relocation required", points=-3.0, check="jd"),
    ]
    if with_domain_mismatch:
        neg_mods.append(
            ModifierRule(
                signal="domain_mismatch",
                check="domain_mismatch",
                points=-4.0,
                min_distinct_hits=3,
                patterns=CARRIER_PATTERNS,
            ),
        )
    return ScoringConfig(
        post_threshold=6.0,
        per_company_cap=3,
        max_score=10,
        min_score=0,
        base_scores=[
            BaseScoreRule(pattern="(senior|sr\\.?).*?(sre|site reliability)", score=4.0, label="Senior SRE"),
            BaseScoreRule(score=0, label="No match"),
        ],
        positive_modifiers=[
            ModifierRule(signal="aws", pattern="aws|amazon web services", points=1.0, check="jd"),
            ModifierRule(signal="terraform", pattern="terraform", points=1.0, check="jd"),
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


CARRIER_JD = """
Senior Site Reliability Engineer - Network Infrastructure

We are seeking a Senior SRE to join our network operations team. You will be
responsible for maintaining and scaling our carrier-grade network infrastructure.

Requirements:
- Deep expertise in Cisco IOS and Juniper routing platforms
- Strong knowledge of BGP, OSPF, and MPLS routing protocols
- Experience with SD-WAN deployments and NOC operations
- Familiarity with carrier-grade network management systems
- Experience with AWS cloud infrastructure and Terraform
- CI/CD pipeline experience for network automation
- United States based, remote friendly

You will work with our network engineering team to ensure 99.999% uptime
across our global backbone. This is a remote position within the United States.
"""


# --- Tests ---

class TestDomainMismatchCheck:
    """Tests for the domain_mismatch check type in _check_modifier."""

    def test_fires_when_distinct_hits_meet_threshold(self):
        mod = ModifierRule(
            signal="domain_mismatch",
            check="domain_mismatch",
            points=-4.0,
            min_distinct_hits=3,
            patterns=CARRIER_PATTERNS,
        )
        assert _check_modifier(mod, title="Senior SRE", jd_text=CARRIER_JD, location="Remote, US",
                               comp_min=None, comp_max=None)

    def test_does_not_fire_below_threshold(self):
        """2 distinct hits with min_distinct_hits=3 → no fire."""
        mod = ModifierRule(
            signal="domain_mismatch",
            check="domain_mismatch",
            points=-4.0,
            min_distinct_hits=3,
            patterns=CARRIER_PATTERNS,
        )
        # JD with only 2 carrier terms
        jd = "We use BGP and OSPF for routing. AWS and Terraform experience required. Remote, United States."
        assert not _check_modifier(mod, title="Senior SRE", jd_text=jd, location="Remote, US",
                                   comp_min=None, comp_max=None)

    def test_repeated_term_counts_as_one_distinct_hit(self):
        """Same pattern repeated many times → 1 distinct hit, below threshold."""
        mod = ModifierRule(
            signal="domain_mismatch",
            check="domain_mismatch",
            points=-4.0,
            min_distinct_hits=3,
            patterns=CARRIER_PATTERNS,
        )
        # BGP mentioned 10 times but no other carrier terms
        jd = "BGP BGP BGP BGP BGP BGP BGP BGP BGP BGP. AWS Terraform CI/CD remote United States."
        matched = _domain_mismatch_matches(CARRIER_PATTERNS, jd)
        assert len(matched) == 1
        assert not _check_modifier(mod, title="Senior SRE", jd_text=jd, location="Remote, US",
                                   comp_min=None, comp_max=None)

    def test_no_patterns_is_noop(self):
        """Absent patterns → never fires."""
        mod = ModifierRule(
            signal="domain_mismatch",
            check="domain_mismatch",
            points=-4.0,
            min_distinct_hits=3,
            patterns=None,
        )
        assert not _check_modifier(mod, title="Senior SRE", jd_text=CARRIER_JD, location="Remote, US",
                                   comp_min=None, comp_max=None)

    def test_matched_patterns_recorded(self):
        """_domain_mismatch_matches returns the list of matched patterns."""
        matched = _domain_mismatch_matches(CARRIER_PATTERNS, CARRIER_JD)
        # Should match at least: cisco ios, juniper, bgp, ospf, mpls, sd-wan, noc, carrier-grade
        assert len(matched) >= 6
        assert r"\bcisco\s+ios\b" in matched
        assert r"\bjuniper\b" in matched
        assert r"\bbgp\b" in matched


class TestDomainMismatchScoring:
    """End-to-end scoring tests with domain_mismatch modifier."""

    def test_carrier_jd_scores_below_threshold_with_modifier(self):
        """A carrier-network JD with SRE title + cloud keywords that would
        score >= 6.0 without the modifier must score below post_threshold
        after the modifier fires."""
        rubric = _make_rubric(with_domain_mismatch=True)
        result = score_job(
            title="Senior Site Reliability Engineer",
            jd_text=CARRIER_JD,
            location="Remote, US",
            company="CarrierCo",
            rubric=rubric,
            profile=_make_profile(),
        )
        assert result.score < 6.0, f"Expected score < 6.0, got {result.score}"
        assert "domain_mismatch" in result.fired_modifiers
        # Reason string should include matched patterns
        domain_reasons = [r for r in result.reasons if "domain_mismatch" in r]
        assert len(domain_reasons) == 1
        assert "matched:" in domain_reasons[0]

    def test_carrier_jd_scores_above_threshold_without_modifier(self):
        """Same JD without the domain_mismatch modifier should score >= 6.0,
        confirming the modifier is what brings it down."""
        rubric = _make_rubric(with_domain_mismatch=False)
        result = score_job(
            title="Senior Site Reliability Engineer",
            jd_text=CARRIER_JD,
            location="Remote, US",
            company="CarrierCo",
            rubric=rubric,
            profile=_make_profile(),
        )
        assert result.score >= 6.0, f"Expected score >= 6.0 without modifier, got {result.score}"
        assert "domain_mismatch" not in result.fired_modifiers

    def test_below_threshold_jd_not_affected(self):
        """JD with only 2 carrier terms → modifier doesn't fire, score unchanged."""
        jd = """
        Senior SRE - Cloud Platform

        We use AWS, Terraform, and Kubernetes for our cloud platform.
        CI/CD pipelines with GitHub Actions. Remote, United States.

        Our network uses BGP and OSPF for internal routing. Experience
        with observability tools like Prometheus and Grafana is a plus.
        """
        rubric_with = _make_rubric(with_domain_mismatch=True)
        rubric_without = _make_rubric(with_domain_mismatch=False)
        result_with = score_job(
            title="Senior SRE", jd_text=jd, location="Remote, US",
            company="CloudCo", rubric=rubric_with, profile=_make_profile(),
        )
        result_without = score_job(
            title="Senior SRE", jd_text=jd, location="Remote, US",
            company="CloudCo", rubric=rubric_without, profile=_make_profile(),
        )
        assert result_with.score == result_without.score
        assert "domain_mismatch" not in result_with.fired_modifiers

    def test_absent_config_is_noop(self):
        """No domain_mismatch modifier in rubric → no effect on scoring."""
        rubric = _make_rubric(with_domain_mismatch=False)
        result = score_job(
            title="Senior Site Reliability Engineer",
            jd_text=CARRIER_JD,
            location="Remote, US",
            company="CarrierCo",
            rubric=rubric,
            profile=_make_profile(),
        )
        assert "domain_mismatch" not in result.fired_modifiers
        assert result.score >= 6.0

    def test_reason_records_matched_patterns(self):
        """The score breakdown reason string lists which patterns matched."""
        rubric = _make_rubric(with_domain_mismatch=True)
        result = score_job(
            title="Senior Site Reliability Engineer",
            jd_text=CARRIER_JD,
            location="Remote, US",
            company="CarrierCo",
            rubric=rubric,
            profile=_make_profile(),
        )
        domain_reasons = [r for r in result.reasons if "domain_mismatch" in r]
        assert len(domain_reasons) == 1
        # Should list at least 3 matched patterns
        reason_text = domain_reasons[0]
        assert "matched:" in reason_text
        # Count comma-separated patterns in the parenthetical
        matched_part = reason_text.split("matched: ")[1].rstrip(")")
        matched_list = [p.strip() for p in matched_part.split(",")]
        assert len(matched_list) >= 3


# --- Data-platform domain mismatch acceptance test ---

DATA_PLATFORM_JD = """
Staff Data Platform Engineer

We are seeking a Staff Data Platform Engineer to lead the architecture and
evolution of our data infrastructure. You will own the data platform that
powers analytics and machine learning across the company.

Responsibilities:
- Architect and operate our data warehouse on Snowflake and Databricks
- Build and maintain data pipelines using Airflow and dbt
- Process large-scale datasets with Apache Spark
- Design ETL workflows for ingestion from operational databases
- Own the lakehouse architecture and data quality framework
- Collaborate with platform engineers on AWS infrastructure and Terraform
- Manage Kubernetes workloads for data platform services
- CI/CD pipelines for data platform deployments

Requirements:
- Deep expertise in data warehouse design and data pipeline orchestration
- Strong experience with dbt, Airflow, Spark, and Snowflake
- Proficiency with AWS, Terraform, and Kubernetes
- Remote, United States based

This is a remote position. You will work with our data team to scale
our data platform to support billions of events per day.
"""


def _make_data_platform_rubric(with_domain_mismatch: bool = True) -> ScoringConfig:
    """Rubric with a (principal|staff).*(platform) base pattern and data-platform
    domain mismatch modifier. Positive modifiers include the shared vocabulary
    (aws, terraform, kubernetes) that data-platform JDs also carry."""
    neg_mods: list[ModifierRule] = []
    if with_domain_mismatch:
        neg_mods.append(
            ModifierRule(
                signal="data_platform_domain",
                check="domain_mismatch",
                points=-4.0,
                min_distinct_hits=3,
                patterns=DATA_PLATFORM_PATTERNS,
            ),
        )
    return ScoringConfig(
        post_threshold=6.0,
        per_company_cap=3,
        max_score=10,
        min_score=0,
        base_scores=[
            BaseScoreRule(pattern="(principal|staff).*(sre|site reliability|platform|infra|devops)", score=4.5, label="Principal/Staff SRE/Platform/Infra"),
            BaseScoreRule(pattern="(senior|sr\\.?).*?(sre|site reliability)", score=4.0, label="Senior SRE"),
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


class TestDataPlatformDomainMismatch:
    """Acceptance test: data-platform JD with shared positive vocabulary
    must score below threshold when the domain_mismatch modifier fires."""

    def test_data_platform_jd_scores_below_threshold_with_modifier(self):
        """A data-platform JD with Staff title + platform/aws/terraform/k8s
        keywords that clears the (principal|staff).*(platform) base pattern
        and positive modifiers must score below 6.0 with the modifier active."""
        rubric = _make_data_platform_rubric(with_domain_mismatch=True)
        result = score_job(
            title="Staff Data Platform Engineer",
            jd_text=DATA_PLATFORM_JD,
            location="Remote, US",
            company="DataCo",
            rubric=rubric,
            profile=_make_profile(),
        )
        assert result.score < 6.0, f"Expected score < 6.0 with modifier, got {result.score}"
        assert "data_platform_domain" in result.fired_modifiers

    def test_data_platform_jd_scores_above_threshold_without_modifier(self):
        """Same JD without the modifier should score >= 6.0 — confirms the
        modifier is what brings it down, not some other penalty."""
        rubric = _make_data_platform_rubric(with_domain_mismatch=False)
        result = score_job(
            title="Staff Data Platform Engineer",
            jd_text=DATA_PLATFORM_JD,
            location="Remote, US",
            company="DataCo",
            rubric=rubric,
            profile=_make_profile(),
        )
        assert result.score >= 6.0, f"Expected score >= 6.0 without modifier, got {result.score}"
        assert "data_platform_domain" not in result.fired_modifiers
