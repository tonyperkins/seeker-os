"""Phase 1d tests: portfolio project selection, mid/old tier deterministic
enforcement, and render_filtered_master extensions.

Covers:
  * Portfolio parsing (project blocks, stack lines, zero-bullet projects)
  * Project cap enforcement (max_projects)
  * Always-include matching (case-insensitive, heading text before dash)
  * Always-include unmatched audit warning
  * Bullet caps per project (max_bullets_per_project)
  * Pin behavior in portfolio bullets
  * Verbatim stack-line preservation
  * Zero-bullet project suppression from render (still parsed, not counted)
  * Mean-top-K project ranking (2-bullet high-relevance > 4-bullet low-relevance)
  * Mid/old tier deterministic bullet caps
  * Early Career non-bullet line preservation (before and after bullets)
"""

import pytest

from seeker_os.resume.bullet_ranker import select_projects, select_bullets_for_role
from seeker_os.resume.master_parser import parse_master_resume, render_filtered_master

FIXTURE_PATH = pytest.importorskip("pathlib").Path(__file__).parent / "fixtures" / "synthetic_master_resume.md"

JD_TEXT = """
We are looking for a Principal DevOps Engineer to join our platform team.
Requirements: deep Terraform experience provisioning AWS infrastructure,
Kubernetes deployment expertise, and a strong incident response and
on-call background. GitLab CI experience is a plus. Experience with
accuracy validation and deterministic scoring pipelines is highly valued.
"""

JOB_TITLE = "Principal DevOps Engineer"

DEFAULT_TITLE_STOPWORDS = frozenset({
    "principal", "senior", "staff", "lead", "engineer", "engineering",
    "architect", "director", "manager", "specialist", "associate",
    "junior", "chief", "head",
})


@pytest.fixture()
def parsed():
    return parse_master_resume(FIXTURE_PATH.read_text())


@pytest.fixture()
def fixture_text():
    return FIXTURE_PATH.read_text()


class TestPortfolioParsing:
    """Verify the parser correctly extracts project blocks from the
    Portfolio Projects section."""

    def test_six_projects_parsed(self, parsed):
        assert len(parsed.projects) == 6

    def test_project_ids_and_titles(self, parsed):
        titles = {p.title for p in parsed.projects}
        assert any("Seeker OS" in t for t in titles)
        assert any("telemetry-gcp" in t for t in titles)
        assert any("forge + muster" in t for t in titles)
        assert any("Broadlink Manager v2" in t for t in titles)
        assert any("perkinslab" in t for t in titles)
        assert any("Writing" in t for t in titles)

    def test_project_bullets_parsed(self, parsed):
        seeker = next(p for p in parsed.projects if "Seeker OS" in p.title)
        assert len(seeker.bullets) == 2
        assert seeker.bullets[0].pinned is True
        assert seeker.bullets[0].project_id == seeker.project_id

    def test_stack_lines_preserved(self, parsed):
        seeker = next(p for p in parsed.projects if "Seeker OS" in p.title)
        assert len(seeker.stack_lines) >= 1
        # Stack line should contain the tech stack text
        stack_text = " ".join(seeker.stack_lines)
        assert "Python/FastAPI" in stack_text
        assert "SQLite" in stack_text

    def test_multi_line_stack_block(self, parsed):
        """Broadlink Manager v2 has a multi-line stack block."""
        broadlink = None
        for p in parsed.projects:
            if "Broadlink" in p.title:
                broadlink = p
                break
        assert broadlink is not None
        assert len(broadlink.stack_lines) >= 1
        stack_text = " ".join(broadlink.stack_lines)
        assert "Vue 3" in stack_text
        assert "pytest" in stack_text

    def test_zero_bullet_project(self, parsed):
        writing = None
        for p in parsed.projects:
            if "Writing" in p.title:
                writing = p
                break
        assert writing is not None
        assert not writing.has_bullets
        assert len(writing.bullets) == 0


class TestProjectSelection:
    """Test select_projects with the fixture."""

    def _select(self, parsed, **kwargs):
        defaults = dict(
            projects=parsed.projects,
            jd_text=JD_TEXT,
            job_title=JOB_TITLE,
            max_projects=3,
            max_bullets_per_project=2,
            always_include=["Seeker OS"],
            near_duplicate_threshold=0.6,
            title_stopwords=DEFAULT_TITLE_STOPWORDS,
        )
        defaults.update(kwargs)
        return select_projects(**defaults)

    def test_always_include_consumes_slot_first(self, parsed):
        result = self._select(parsed)
        seeker = next(p for p in parsed.projects if "Seeker OS" in p.title)
        assert seeker.project_id in result.selected_project_ids
        # Seeker OS should be first (always-include)
        assert result.selected_project_ids[0] == seeker.project_id

    def test_project_cap_enforced(self, parsed):
        result = self._select(parsed)
        # 5 bullet-projects, max_projects=3, 1 always-include → 2 ranked slots
        assert len(result.selected_project_ids) == 3
        assert len(result.dropped_project_ids) == 2

    def test_dropped_projects_are_non_selected(self, parsed):
        result = self._select(parsed)
        all_ids = {p.project_id for p in parsed.projects if p.has_bullets}
        selected_set = set(result.selected_project_ids)
        dropped_set = set(result.dropped_project_ids)
        assert selected_set | dropped_set == all_ids
        assert selected_set & dropped_set == set()

    def test_zero_bullet_project_not_counted(self, parsed):
        """The Writing project (zero bullets) must not appear in selected
        or dropped — it's pass-through."""
        result = self._select(parsed)
        writing_id = None
        for p in parsed.projects:
            if "Writing" in p.title:
                writing_id = p.project_id
                break
        assert writing_id not in result.selected_project_ids
        assert writing_id not in result.dropped_project_ids

    def test_bullet_cap_per_project(self, parsed):
        """Each selected project should have at most max_bullets_per_project
        bullets selected."""
        result = self._select(parsed, max_bullets_per_project=1)
        for pid, bullet_result in result.per_project.items():
            assert len(bullet_result.selected) <= 1

    def test_pinned_bullet_survives_in_portfolio(self, parsed):
        """Seeker OS has a pinned bullet (idx 0) — it must survive selection."""
        result = self._select(parsed, max_bullets_per_project=1)
        seeker = next(p for p in parsed.projects if "Seeker OS" in p.title)
        seeker_id = seeker.project_id
        assert seeker_id in result.per_project
        bullet_result = result.per_project[seeker_id]
        selected_indices = {s["index"] for s in bullet_result.selected}
        assert 0 in selected_indices, "pinned portfolio bullet must survive"
        pinned_entry = next(s for s in bullet_result.selected if s["index"] == 0)
        assert pinned_entry["reason"] == "pinned"

    def test_always_include_unmatched_warning(self, parsed):
        """When an always_include entry matches no project, an audit warning
        is recorded."""
        result = self._select(parsed, always_include=["Nonexistent Project"])
        warnings = [w for w in result.warnings if w.startswith("always_include_unmatched")]
        assert len(warnings) == 1
        assert "Nonexistent Project" in warnings[0]

    def test_always_include_case_insensitive(self, parsed):
        """Matching is case-insensitive against heading text before dash."""
        result = self._select(parsed, always_include=["seeker os"])
        seeker = next(p for p in parsed.projects if "Seeker OS" in p.title)
        assert seeker.project_id in result.selected_project_ids

    def test_mean_top_k_ranking(self):
        """A 2-bullet high-relevance project must outrank a 4-bullet
        low-relevance project under mean-top-K scoring."""
        from seeker_os.resume.master_parser import BulletUnit, ProjectBlock

        high_rel = ProjectBlock(
            project_id="high",
            title="High Relevance Project",
            heading_line=0,
            bullets=[
                BulletUnit(role_id="", bullet_index=0, text="Terraform AWS infrastructure provisioning", project_id="high"),
                BulletUnit(role_id="", bullet_index=1, text="Kubernetes deployment with GitLab CI pipelines", project_id="high"),
            ],
        )
        low_rel = ProjectBlock(
            project_id="low",
            title="Low Relevance Project",
            heading_line=1,
            bullets=[
                BulletUnit(role_id="", bullet_index=0, text="Wrote onboarding documentation for new hires", project_id="low"),
                BulletUnit(role_id="", bullet_index=1, text="Organized team building events and offsites", project_id="low"),
                BulletUnit(role_id="", bullet_index=2, text="Maintained internal wiki pages and documentation", project_id="low"),
                BulletUnit(role_id="", bullet_index=3, text="Created presentation slides for quarterly reviews", project_id="low"),
            ],
        )
        result = select_projects(
            projects=[high_rel, low_rel],
            jd_text=JD_TEXT,
            job_title=JOB_TITLE,
            max_projects=1,
            max_bullets_per_project=2,
            always_include=[],
            near_duplicate_threshold=0.6,
            title_stopwords=DEFAULT_TITLE_STOPWORDS,
        )
        assert "high" in result.selected_project_ids
        assert "low" in result.dropped_project_ids


class TestRenderFilteredMaster:
    """Test render_filtered_master with project drops and non-bullet
    line preservation."""

    def test_dropped_project_block_removed(self, parsed, fixture_text):
        """Dropped projects should have heading, stack lines, and bullets
        all removed from the rendered output."""
        tele = next(p for p in parsed.projects if "telemetry-gcp" in p.title)
        dropped = {tele.project_id}
        rendered = render_filtered_master(parsed, {}, dropped)
        assert "telemetry-gcp" not in rendered
        assert "Azure→GCP" not in rendered

    def test_zero_bullet_project_suppressed_from_render(self, parsed, fixture_text):
        """Zero-bullet project blocks are omitted from rendered output to
        avoid empty placeholder sections consuming vertical space. The
        project remains in the parse (test_zero_bullet_project checks that)
        but is absent from the rendered text."""
        writing = None
        for p in parsed.projects:
            if "Writing" in p.title:
                writing = p
                break
        assert writing is not None
        assert not writing.has_bullets
        rendered = render_filtered_master(parsed, {})
        # Writing block should be absent from rendered output
        assert "Writing" not in rendered
        assert "https://example.com/posts" not in rendered

    def test_selected_project_bullets_filtered(self, parsed, fixture_text):
        """For a selected project, only selected bullets should appear;
        non-selected bullets should be dropped."""
        seeker = next(p for p in parsed.projects if "Seeker OS" in p.title)
        selections = {seeker.project_id: [0]}  # keep only bullet 0
        rendered = render_filtered_master(parsed, selections)
        # Bullet 0 text should be present
        assert "Config-driven pipeline" in rendered
        # Bullet 1 text should be absent
        assert "Claim-level accuracy enforcement" not in rendered

    def test_stack_lines_preserved_in_render(self, parsed, fixture_text):
        """Stack lines for a selected project must appear verbatim in
        the rendered output."""
        seeker = next(p for p in parsed.projects if "Seeker OS" in p.title)
        selections = {seeker.project_id: [0, 1]}
        rendered = render_filtered_master(parsed, selections)
        assert "Python/FastAPI" in rendered
        assert "SQLite" in rendered

    def test_pin_markers_stripped_from_output(self, parsed, fixture_text):
        """Pin markers must never appear in the filtered output."""
        seeker = next(p for p in parsed.projects if "Seeker OS" in p.title)
        selections = {seeker.project_id: [0, 1]}
        rendered = render_filtered_master(parsed, selections)
        assert "<!-- pin -->" not in rendered
        assert "<!--pin-->" not in rendered

    def test_early_career_non_bullet_lines_preserved(self, parsed, fixture_text):
        """Non-bullet lines in Early Career role blocks (intro paragraph
        before bullets, trailing italic paragraph after bullets) must be
        preserved by render_filtered_master."""
        # Select only bullet 0 for the Junior Engineer role
        junior = parsed.roles_in_section("Early Career")
        assert len(junior) == 1
        role_id = junior[0].role_id
        selections = {role_id: [0]}
        rendered = render_filtered_master(parsed, selections)
        # Intro paragraph (before bullets)
        assert "Early-career role predating the cloud era" in rendered
        # Trailing italic paragraph (after bullets)
        assert "The company wound down in 2001" in rendered
        # Bullet 0 should be present
        assert "Maintained internal tooling" in rendered


class TestMidOldTierEnforcement:
    """Test deterministic mid/old tier bullet caps via select_bullets_for_role
    on mid and old tier roles from the fixture."""

    def test_mid_tier_role_capped(self, parsed):
        """The Senior Platform Engineer role (June 2019 – December 2022)
        is mid-tier (~3-4 years old as of 2026). It has 3 bullets.
        With cap=2, selection should reduce to 2."""
        role = parsed.role_by_id("senior-platform-engineer")
        assert role is not None
        assert len(role.bullets) == 3

        result = select_bullets_for_role(
            bullets=role.bullets,
            jd_text=JD_TEXT,
            job_title=JOB_TITLE,
            cap=2,
            near_duplicate_threshold=0.6,
            title_stopwords=DEFAULT_TITLE_STOPWORDS,
        )
        assert len(result.selected) == 2
        assert len(result.dropped) >= 1

    def test_old_tier_role_capped(self, parsed):
        """The Systems Engineer role (March 2010 – May 2015) is old-tier
        (~11 years old). It has 1 bullet. With cap=1, no selection needed."""
        role = parsed.role_by_id("systems-engineer")
        assert role is not None
        assert len(role.bullets) == 1

        result = select_bullets_for_role(
            bullets=role.bullets,
            jd_text=JD_TEXT,
            job_title=JOB_TITLE,
            cap=1,
            near_duplicate_threshold=0.6,
            title_stopwords=DEFAULT_TITLE_STOPWORDS,
        )
        assert len(result.selected) == 1

    def test_early_career_role_capped(self, parsed):
        """The Junior Engineer role (Feb 1998 – Aug 2003) is in Early Career.
        It has 1 bullet. With cap=1, no selection needed — but the intro
        paragraph and trailing italic must be preserved by render."""
        role = parsed.roles_in_section("Early Career")
        assert len(role) == 1
        assert len(role[0].bullets) == 1

        # With cap=1, all bullets fit
        result = select_bullets_for_role(
            bullets=role[0].bullets,
            jd_text=JD_TEXT,
            job_title=JOB_TITLE,
            cap=1,
            near_duplicate_threshold=0.6,
            title_stopwords=DEFAULT_TITLE_STOPWORDS,
        )
        assert len(result.selected) == 1
        assert len(result.dropped) == 0
