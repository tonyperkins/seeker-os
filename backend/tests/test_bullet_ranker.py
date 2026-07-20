"""Tests for deterministic bullet ranking, near-duplicate collapse, and
selection (Phase 1). No LLM/embeddings involved — pure lexical scoring.
"""

from pathlib import Path

import pytest

from seeker_os.resume.bullet_ranker import (
    collapse_near_duplicates,
    score_bullets,
    scope_jd_text,
    select_bullets_for_role,
)
from seeker_os.resume.master_parser import BulletUnit, parse_master_resume

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "synthetic_master_resume.md"

JD_TEXT = """
We are looking for a Principal DevOps Engineer to lead our cloud platform.
Requirements: deep Terraform experience provisioning AWS infrastructure,
Kubernetes deployment expertise, and a strong incident response and
on-call background. GitLab CI experience is a plus.
"""

JOB_TITLE = "Principal DevOps Engineer"

DEFAULT_TITLE_STOPWORDS = frozenset({
    "principal", "senior", "staff", "lead", "engineer", "engineering",
    "architect", "director", "manager", "specialist", "associate",
    "junior", "chief", "head",
})


@pytest.fixture()
def current_role_bullets():
    text = FIXTURE_PATH.read_text()
    parsed = parse_master_resume(text)
    role = parsed.role_by_id("cloud-devops-engineer")
    return role.bullets


class TestNearDuplicateCollapse:
    def test_accelya_style_cluster_collapses_to_one(self, current_role_bullets):
        """The four 'Built and maintained GitLab CI pipelines...' bullets
        (indices 0-3) differ only in their trailing object noun and must
        collapse to a single kept bullet at the default 0.6 threshold —
        this is the motivating real-world case (Accelya pattern)."""
        scored = score_bullets(
            current_role_bullets, JD_TEXT, JOB_TITLE,
            title_stopwords=DEFAULT_TITLE_STOPWORDS,
        )
        kept, dropped = collapse_near_duplicates(scored, threshold=0.6)

        cluster_indices = {0, 1, 2, 3}
        kept_cluster_indices = {sb.bullet.bullet_index for sb in kept if sb.bullet.bullet_index in cluster_indices}
        dropped_cluster_indices = {d["index"] for d in dropped if d["index"] in cluster_indices}

        assert len(kept_cluster_indices) == 1, (
            f"expected exactly 1 survivor from the GitLab CI cluster, got {kept_cluster_indices}"
        )
        assert dropped_cluster_indices == cluster_indices - kept_cluster_indices
        assert all(d["reason"] == "deduped" for d in dropped if d["index"] in cluster_indices)

    def test_distinct_bullets_are_not_collapsed(self, current_role_bullets):
        scored = score_bullets(
            current_role_bullets, JD_TEXT, JOB_TITLE,
            title_stopwords=DEFAULT_TITLE_STOPWORDS,
        )
        kept, dropped = collapse_near_duplicates(scored, threshold=0.6)
        # Terraform bullet (idx 4) and incident-response bullet (idx 5) are
        # unrelated claims and must both survive collapse.
        kept_indices = {sb.bullet.bullet_index for sb in kept}
        assert 4 in kept_indices
        assert 5 in kept_indices


class TestNormalizationBias:
    """Addition A: sqrt-normalized scoring must not penalize a longer bullet
    that matches more JD terms in favor of a terse single-match bullet."""

    def test_multi_match_bullet_outranks_single_match_short_bullet(self):
        from seeker_os.resume.master_parser import BulletUnit

        long_multi_match = BulletUnit(
            role_id="r", bullet_index=0,
            text="Implemented Terraform modules to provision AWS infrastructure "
                 "and led incident response improvements across the platform team",
        )
        short_single_match = BulletUnit(
            role_id="r", bullet_index=1,
            text="Wrote Terraform documentation",
        )

        jd_text = (
            "Requirements: Terraform, AWS infrastructure provisioning, and "
            "incident response experience."
        )
        scored = score_bullets([long_multi_match, short_single_match], jd_text, "DevOps Engineer")
        scores = {s.bullet.bullet_index: s.score for s in scored}

        assert scores[0] > scores[1], (
            f"longer multi-term-match bullet (score={scores[0]}) should outrank "
            f"the short single-term-match bullet (score={scores[1]}) under sqrt normalization"
        )


class TestTitleBoost:
    def test_seniority_terms_get_no_boost(self):
        """Bullets are constructed with identical token counts and each
        matches exactly one JD term, so the ONLY variable is whether that
        term earns the title-match boost. Bullet A's match ("principal") is
        a title-stopword and gets no boost; Bullet B's match ("devops") is
        a real domain term from the title and gets the 1.5x boost. B must
        outrank A despite both matching a title word."""
        from seeker_os.resume.master_parser import BulletUnit

        bullet_a = BulletUnit(role_id="r", bullet_index=0, text="Acted as principal liaison for executive teams")
        bullet_b = BulletUnit(role_id="r", bullet_index=1, text="Acted as devops liaison for executive teams")

        jd_text = "Looking for a Principal DevOps Engineer with strong technical skills."
        job_title = "Principal DevOps Engineer"

        scored = score_bullets(
            [bullet_a, bullet_b], jd_text, job_title,
            title_boost=1.5, title_stopwords=DEFAULT_TITLE_STOPWORDS,
        )
        scores = {s.bullet.bullet_index: s.score for s in scored}
        assert scores[1] > scores[0]


class TestSelectBulletsForRole:
    def test_full_pipeline_accounts_for_every_candidate(self, current_role_bullets):
        result = select_bullets_for_role(
            bullets=current_role_bullets,
            jd_text=JD_TEXT,
            job_title=JOB_TITLE,
            cap=6,
            near_duplicate_threshold=0.6,
            title_stopwords=DEFAULT_TITLE_STOPWORDS,
        )
        assert result.candidate_count == 10
        # 4-bullet cluster collapses to 1 -> 7 post-dedupe candidates.
        assert result.post_dedupe_count == 7
        assert len(result.selected) == 6
        # Every candidate is accounted for exactly once (selected or dropped).
        assert len(result.selected) + len(result.dropped) == result.candidate_count
        reasons = {d["reason"] for d in result.dropped}
        assert "deduped" in reasons
        assert "capped" in reasons

    def test_role_under_cap_needs_no_selection(self):
        # Genuinely distinct claims (no shared 3-grams), well under the cap.
        distinct_texts = [
            "Migrated the payment reconciliation service to a new provider",
            "Redesigned the customer onboarding flow for faster signups",
            "Audited quarterly compliance reports for accuracy",
        ]
        bullets = [
            BulletUnit(role_id="r", bullet_index=i, text=text)
            for i, text in enumerate(distinct_texts)
        ]
        result = select_bullets_for_role(
            bullets=bullets, jd_text=JD_TEXT, job_title=JOB_TITLE,
            cap=6, near_duplicate_threshold=0.6,
        )
        assert result.candidate_count == 3
        assert len(result.dropped) == 0
        assert len(result.selected) == 3


class TestPinnedBullets:
    """Phase 1c: pinned bullets bypass ranking, fill cap slots first, and
    are exempt from near-duplicate collapse."""

    def test_pinned_bullet_survives_despite_low_jd_overlap(self, current_role_bullets):
        """The fixture's idx-8 bullet ('Presented quarterly infrastructure
        cost reviews...') has a pin marker and near-zero JD overlap. It must
        survive selection and be tagged 'pinned'."""
        result = select_bullets_for_role(
            bullets=current_role_bullets,
            jd_text=JD_TEXT,
            job_title=JOB_TITLE,
            cap=6,
            near_duplicate_threshold=0.6,
            title_stopwords=DEFAULT_TITLE_STOPWORDS,
        )
        selected_indices = {s["index"] for s in result.selected}
        assert 8 in selected_indices, "pinned bullet (idx 8) must survive selection"
        pinned_entry = next(s for s in result.selected if s["index"] == 8)
        assert pinned_entry["reason"] == "pinned"

    def test_pinned_bullets_never_dedupe_dropped(self):
        """A pinned bullet that is a near-duplicate of another bullet must
        never be dropped by dedupe — the unpinned duplicate is dropped instead."""
        bullets = [
            BulletUnit(role_id="r", bullet_index=0, text="Built and maintained GitLab CI pipelines that automated build and deployment workflows for internal services"),
            BulletUnit(role_id="r", bullet_index=1, text="Built and maintained GitLab CI pipelines that automated build and deployment workflows for client services", pinned=True),
        ]
        result = select_bullets_for_role(
            bullets=bullets, jd_text=JD_TEXT, job_title=JOB_TITLE,
            cap=6, near_duplicate_threshold=0.6,
            title_stopwords=DEFAULT_TITLE_STOPWORDS,
        )
        selected_indices = {s["index"] for s in result.selected}
        assert 1 in selected_indices, "pinned bullet must survive dedupe"
        # The unpinned bullet (idx 0) should be deduped into the pinned one.
        deduped = [d for d in result.dropped if d["reason"] == "deduped"]
        assert any(d["index"] == 0 for d in deduped), "unpinned duplicate should be dropped"

    def test_pinned_exceeds_cap_warning(self):
        """When pinned count > cap, all pinned bullets are kept and a
        pinned_exceeds_cap warning is recorded."""
        bullets = [
            BulletUnit(role_id="r", bullet_index=i, text=f"Distinct achievement number {i} with unique keywords", pinned=True)
            for i in range(5)
        ]
        result = select_bullets_for_role(
            bullets=bullets, jd_text=JD_TEXT, job_title=JOB_TITLE,
            cap=3, near_duplicate_threshold=0.6,
            title_stopwords=DEFAULT_TITLE_STOPWORDS,
        )
        assert len(result.selected) == 5, "all pinned bullets kept despite cap=3"
        assert "pinned_exceeds_cap" in result.warnings
        assert all(s["reason"] == "pinned" for s in result.selected)

    def test_pinned_fills_cap_first_then_ranked(self):
        """Pinned bullets consume cap slots first; remaining slots go to
        ranked bullets by score."""
        bullets = [
            BulletUnit(role_id="r", bullet_index=0, text="Implemented Terraform modules for AWS infrastructure provisioning", pinned=True),
            BulletUnit(role_id="r", bullet_index=1, text="Led incident response improvements cutting mean time to resolution"),
            BulletUnit(role_id="r", bullet_index=2, text="Built GitLab CI pipelines for Kubernetes deployment automation"),
            BulletUnit(role_id="r", bullet_index=3, text="Wrote onboarding documentation for new hires"),
        ]
        result = select_bullets_for_role(
            bullets=bullets, jd_text=JD_TEXT, job_title=JOB_TITLE,
            cap=2, near_duplicate_threshold=0.6,
            title_stopwords=DEFAULT_TITLE_STOPWORDS,
        )
        assert len(result.selected) == 2
        # Pinned bullet (idx 0) takes slot 1.
        assert result.selected[0]["index"] == 0
        assert result.selected[0]["reason"] == "pinned"
        # Highest-scored ranked bullet takes slot 2.
        assert result.selected[1]["reason"] == "ranked"


class TestBusinessStopwords:
    """Phase 1c: generic-business stopwords must never appear in
    matched_terms or contribute to scores."""

    def test_business_stopwords_excluded_from_matched_terms(self):
        bullet = BulletUnit(
            role_id="r", bullet_index=0,
            text="Partnered with client team across years to ensure strong support",
        )
        jd_text = "Looking for a candidate with client team experience and strong support skills"
        scored = score_bullets([bullet], jd_text, "Engineer")
        assert scored[0].matched_terms == [], (
            f"business stopwords must not appear in matched_terms, got {scored[0].matched_terms}"
        )
        assert scored[0].score == 0.0

    def test_real_terms_still_match_despite_business_stopwords(self):
        bullet = BulletUnit(
            role_id="r", bullet_index=0,
            text="Provisioned Terraform modules for AWS infrastructure",
        )
        jd_text = "Requirements: Terraform, AWS infrastructure, Kubernetes"
        scored = score_bullets([bullet], jd_text, "DevOps Engineer")
        assert "terraform" in scored[0].matched_terms
        assert "aws" in scored[0].matched_terms
        assert scored[0].score > 0.0


class TestJDSectionScoping:
    """Phase 1c: JD section scoping extracts terms only from
    responsibility/qualification sections, not boilerplate."""

    def test_section_headers_isolate_relevant_content(self):
        jd = """Principal Platform Engineer
Ladders
United States

About the Role:
We are seeking a Principal Platform Engineer to join our team.

Responsibilities:
- Design and operate Kubernetes-based platform infrastructure
- Implement Terraform IaC for multi-cloud provisioning
- Lead incident response and on-call rotations

Qualifications:
- Deep AWS and Kubernetes experience
- Terraform expertise
- Strong communication skills

Benefits:
- Health insurance, 401k, and generous PTO
- Remote work opportunity
- Equal opportunity employer
"""
        scoped, mode = scope_jd_text(jd)
        assert mode == "section_headers"
        # Benefits/EEO terms must not appear in scoped text.
        assert "401k" not in scoped.lower()
        assert "health insurance" not in scoped.lower()
        assert "equal opportunity" not in scoped.lower()
        # Responsibility/qualification terms must be present.
        assert "kubernetes" in scoped.lower()
        assert "terraform" in scoped.lower()
        assert "incident response" in scoped.lower()

    def test_no_headers_falls_back_to_boilerplate_filter(self):
        jd = """We need a DevOps engineer with Terraform and AWS skills.
You will build CI/CD pipelines using GitHub Actions and manage Kubernetes clusters.
Experience with Prometheus, Grafana, and Datadog for observability is required.
Equal opportunity employer. Benefits include 401k and health insurance.
Remote work available. Compensation range: $150k-$200k.
"""
        scoped, mode = scope_jd_text(jd)
        assert mode == "full_text_filtered"
        assert "terraform" in scoped.lower()
        assert "401k" not in scoped.lower()
        assert "equal opportunity" not in scoped.lower()

    def test_jd_scope_mode_recorded_in_selection_result(self, current_role_bullets):
        result = select_bullets_for_role(
            bullets=current_role_bullets,
            jd_text=JD_TEXT,
            job_title=JOB_TITLE,
            cap=6,
            near_duplicate_threshold=0.6,
            title_stopwords=DEFAULT_TITLE_STOPWORDS,
        )
        assert result.jd_scope_mode in ("section_headers", "full_text_filtered", "full_text")

    def test_bare_line_benefits_header_excluded(self):
        """Replicates Ladders_3224's exact JD structure: bare 'Benefits'
        line without a colon, bare 'Responsibilities'/'Qualifications' lines.
        The Benefits section and EEO line must not enter the scoped text."""
        jd = """Principal Platform Engineer, DevOps/Developer Experience
Ladders
United States

For our client, we are seeking a Principal Platform Engineer to join the team.

Location: Remote - US based candidates only
Compensation: $180,000 – $210,000 annually

Responsibilities
- Lead high-priority initiatives, clarifying approaches and ensuring quality outcomes
- Define clear interfaces to minimize cross-team friction and enable parallel work
- Establish engineering best practices including design documentation and effective testing
- Promote API-first principles and create reusable platform capabilities
- Implement automation to enhance operational efficiency and delivery speed
- Enhance stability through observability standards and incident learning loops

Qualifications
- Bachelor's in Computer Science or related field, or equivalent experience
- 12+ years in building, automating, and operating cloud-native platforms at scale
- 5+ years hands-on with Kubernetes, public cloud infrastructure, CI/CD automation, and reliability tooling
- Experience with production systems, incident response, and reliability improvements

Benefits
- Flexible Vacation Policy for personal time and relaxation
- 80 hours of Paid Sick, Safe, and Caregiver Leave annually

Our client is an equal opportunity employer. We encourage you to apply even if you don't meet every qualification.

Seniority level: Mid-Senior level
Employment type: Full-time
Job function: Engineering and Information Technology
Industries: Hospitals and Health Care
"""
        scoped, mode = scope_jd_text(jd)
        assert mode == "section_headers"
        # Benefits/EEO terms must not appear in scoped text.
        assert "flexible" not in scoped.lower()
        assert "vacation" not in scoped.lower()
        assert "paid sick" not in scoped.lower()
        assert "caregiver" not in scoped.lower()
        assert "equal opportunity" not in scoped.lower()
        assert "seniority level" not in scoped.lower()
        assert "industries" not in scoped.lower()
        # Responsibility/qualification terms must be present.
        assert "kubernetes" in scoped.lower()
        assert "incident" in scoped.lower()
        assert "reliability" in scoped.lower()
        assert "engineering" in scoped.lower()

        # Verify the scoped text does NOT include the Benefits header or
        # anything after it.
        scoped_lines = scoped.splitlines()
        benefits_idx = next(
            (i for i, l in enumerate(scoped_lines) if l.strip() == "Benefits"),
            None,
        )
        assert benefits_idx is None, "Benefits header must not appear in scoped text"
