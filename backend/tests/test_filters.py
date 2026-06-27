"""Tests for Tier 2 hard filters."""

from seeker_os.config import (
    FilterConfig, ProfileConfig, TitleFilters,
    UserIdentity, LocationPrefs, CompPrefs, ExperiencePrefs,
    EmploymentPrefs, ResumePrefs, CrossReferencePrefs,
)
from seeker_os.filtering.hard_filters import apply_filters
from seeker_os.filtering.title_patterns import title_matches
from seeker_os.models import JobCard


def _make_profile() -> ProfileConfig:
    return ProfileConfig(
        user=UserIdentity(name="Test", email="test@test.com", location="Austin, TX"),
        location=LocationPrefs(remote_only=True, accepted_cities=["austin"]),
        comp=CompPrefs(floor=150000, target=165000, stretch=220000),
        experience=ExperiencePrefs(years=25, anchor_phrase="25+ years"),
        employment=EmploymentPrefs(commitment="Full Time", role_type="Individual Contributor"),
        blacklist=["badcompany"],
        resume=ResumePrefs(master_path="~/resume.md", accuracy_rules_path="config/accuracy_rules.yml", output_dir="data/resumes"),
        cross_reference=CrossReferencePrefs(repo_path="~/projects/job-search"),
    )


def _make_filters() -> FilterConfig:
    return FilterConfig(
        remote_only=True,
        us_only=True,
        seniority_floor=["Senior Level"],
        seniority_reject=["Mid Level", "Entry Level", "Junior", "Associate"],
        seniority_unknown_passes=True,
        freshness_days=30,
        commitment_required="Full Time",
    )


def _make_title_filters() -> TitleFilters:
    return TitleFilters(
        positive=["devops", "sre", "platform engineer"],
        negative=["manager", "director", "frontend"],
    )


def _make_job(**kwargs) -> JobCard:
    defaults = dict(
        source_id="hiring_cafe",
        source_job_id="grnhse___board___123",
        apply_url="https://example.com/job/123",
        title="Senior SRE",
        core_title="Senior SRE",
        company="GoodCo",
        location="Remote, US",
        workplace_type="Remote",
        workplace_countries=["US"],
        seniority_level="Senior Level",
        commitment=["Full Time"],
        comp_min=160000,
        comp_max=200000,
        date_posted="2026-06-20T00:00:00Z",
        discovered_query="senior-sre-remote",
    )
    defaults.update(kwargs)
    return JobCard(**defaults)


class TestTitlePatterns:
    def test_positive_match(self):
        assert title_matches("Senior DevOps Engineer", ["devops"], ["manager"]) is True

    def test_negative_match_rejects(self):
        assert title_matches("Engineering Manager", ["engineer"], ["manager"]) is False

    def test_no_positive_match(self):
        assert title_matches("Sales Rep", ["devops"], ["manager"]) is False

    def test_case_insensitive(self):
        assert title_matches("SENIOR SRE", ["sre"], ["manager"]) is True


class TestHardFilters:
    def test_passes_good_job(self):
        job = _make_job()
        result = apply_filters(job, _make_profile(), _make_filters(), _make_title_filters())
        assert result.passed is True

    def test_rejects_non_remote(self):
        job = _make_job(workplace_type="On-Site")
        result = apply_filters(job, _make_profile(), _make_filters(), _make_title_filters())
        assert result.passed is False
        assert "remote" in result.reason.lower()

    def test_rejects_non_us(self):
        job = _make_job(workplace_countries=["DE"])
        result = apply_filters(job, _make_profile(), _make_filters(), _make_title_filters())
        assert result.passed is False
        assert "us" in result.reason.lower()

    def test_rejects_mid_level(self):
        job = _make_job(seniority_level="Mid Level")
        result = apply_filters(job, _make_profile(), _make_filters(), _make_title_filters())
        assert result.passed is False
        assert "seniority" in result.reason.lower()

    def test_passes_unknown_seniority(self):
        job = _make_job(seniority_level=None)
        result = apply_filters(job, _make_profile(), _make_filters(), _make_title_filters())
        assert result.passed is True

    def test_rejects_comp_below_floor(self):
        job = _make_job(comp_max=140000)
        result = apply_filters(job, _make_profile(), _make_filters(), _make_title_filters())
        assert result.passed is False
        assert "comp" in result.reason.lower()

    def test_passes_comp_max_above_floor_with_low_min(self):
        """comp_max >= floor but comp_min < floor should pass (scoring handles marginal)."""
        job = _make_job(comp_min=140000, comp_max=160000)
        result = apply_filters(job, _make_profile(), _make_filters(), _make_title_filters())
        assert result.passed is True

    def test_passes_null_comp(self):
        job = _make_job(comp_min=None, comp_max=None)
        result = apply_filters(job, _make_profile(), _make_filters(), _make_title_filters())
        assert result.passed is True

    def test_rejects_blacklisted(self):
        job = _make_job(company="BadCompany")
        result = apply_filters(job, _make_profile(), _make_filters(), _make_title_filters())
        assert result.passed is False
        assert "blacklist" in result.reason.lower()

    def test_rejects_title_negative(self):
        job = _make_job(title="Engineering Manager", core_title="Engineering Manager")
        result = apply_filters(job, _make_profile(), _make_filters(), _make_title_filters())
        assert result.passed is False

    def test_rejects_wrong_commitment(self):
        job = _make_job(commitment=["Part Time"])
        result = apply_filters(job, _make_profile(), _make_filters(), _make_title_filters())
        assert result.passed is False
        assert "commitment" in result.reason.lower()
