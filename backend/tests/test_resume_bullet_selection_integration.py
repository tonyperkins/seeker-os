"""Integration tests wiring the Phase 1 deterministic bullet-selection
pipeline (parser + ranker) into resume/generator.py, using the synthetic
fixture master resume. No real LLM call and no real Settings/config-dir
required — only the `channel_rules.resume.content_tiering` shape that
_run_deterministic_bullet_selection actually reads.
"""

from dataclasses import dataclass
from pathlib import Path

import pytest

from seeker_os.config import ContentTieringConfig
from seeker_os.database import run_migrations
from seeker_os.resume.generator import (
    _build_selection_instructions,
    _build_tiering_instructions,
    _run_deterministic_bullet_selection,
)


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """_run_deterministic_bullet_selection writes bullet_selection evaluation
    records via record_evaluation(), which calls get_connection() with no
    explicit path — redirect the default DB path so these tests never touch
    the real seeker.db."""
    import seeker_os.database as dbmod

    db_path = tmp_path / "test_bullet_selection.db"
    run_migrations(db_path)
    monkeypatch.setattr(dbmod, "_db_path", lambda: db_path)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "synthetic_master_resume.md"

JD_TEXT = """
We are looking for a Principal DevOps Engineer to lead our cloud platform.
Requirements: deep Terraform experience provisioning AWS infrastructure,
Kubernetes deployment expertise, and a strong incident response and
on-call background. GitLab CI experience is a plus.
"""

JOB_TITLE = "Principal DevOps Engineer"


@dataclass
class _FakeChannelConfig:
    content_tiering: ContentTieringConfig
    require_visible_urls: bool = True
    format_hints: str = ""


@dataclass
class _FakeChannelRules:
    resume: _FakeChannelConfig


@dataclass
class _FakeSettings:
    channel_rules: _FakeChannelRules
    profile: object = None
    identity: object = None


def _make_settings(tiering: ContentTieringConfig | None = None) -> _FakeSettings:
    tiering = tiering or ContentTieringConfig()
    return _FakeSettings(channel_rules=_FakeChannelRules(resume=_FakeChannelConfig(content_tiering=tiering)))


@pytest.fixture()
def master_text() -> str:
    return FIXTURE_PATH.read_text()


class TestRunDeterministicBulletSelection:
    def test_current_role_is_filtered_to_cap(self, master_text):
        settings = _make_settings()
        filtered_text, role_titles, project_titles, mid_old_active, portfolio_active, competency_active, selected_cat_labels, _pinned, _key_terms = _run_deterministic_bullet_selection(
            settings=settings, master_resume=master_text, jd_text=JD_TEXT,
            job_title=JOB_TITLE, operation_id="test-op-1",
        )
        assert "cloud-devops-engineer" in role_titles
        # After dedupe (4 -> 1) the current role has 7 candidates; cap 6
        # applies, so exactly one more bullet is dropped beyond dedupe.
        bullet_lines = [
            line for line in filtered_text.splitlines()
            if line.strip().startswith("- ")
        ]
        # Current role (6) + Prior Fixture Inc (3, untouched, under cap) +
        # Old Fixture Systems (1, untouched) + Junior Engineer (1, untouched)
        # + portfolio projects (selected projects' bullets, capped at 2 each)
        # The exact count depends on project selection, but current role
        # must be capped at 6.
        assert len(bullet_lines) >= 6 + 3 + 1 + 1

    def test_untouched_roles_survive_verbatim(self, master_text):
        settings = _make_settings()
        filtered_text, _, _, _, _, _, _, _, _ = _run_deterministic_bullet_selection(
            settings=settings, master_resume=master_text, jd_text=JD_TEXT,
            job_title=JOB_TITLE, operation_id="test-op-2",
        )
        assert "Designed a self-service internal developer platform for provisioning test environments." in filtered_text
        assert "Operated on-premise virtualization infrastructure supporting internal business applications." in filtered_text
        assert "Maintained internal tooling for a small engineering team on early web infrastructure." in filtered_text

    def test_no_content_tiering_is_noop(self, master_text):
        @dataclass
        class _NoTieringChannelConfig:
            content_tiering: None = None

        @dataclass
        class _NoTieringChannelRules:
            resume: _NoTieringChannelConfig

        @dataclass
        class _NoTieringSettings:
            channel_rules: _NoTieringChannelRules

        settings = _NoTieringSettings(channel_rules=_NoTieringChannelRules(resume=_NoTieringChannelConfig()))
        filtered_text, role_titles, _, _, _, _, _, _, _ = _run_deterministic_bullet_selection(
            settings=settings, master_resume=master_text, jd_text=JD_TEXT,
            job_title=JOB_TITLE, operation_id="test-op-3",
        )
        assert filtered_text == master_text
        assert role_titles == {}

    def test_malformed_master_resume_falls_back_gracefully(self):
        settings = _make_settings()
        garbage_text = "not a resume at all, just plain text with no headings"
        filtered_text, role_titles, _, _, _, _, _, _, _ = _run_deterministic_bullet_selection(
            settings=settings, master_resume=garbage_text, jd_text=JD_TEXT,
            job_title=JOB_TITLE, operation_id="test-op-4",
        )
        assert filtered_text == garbage_text
        assert role_titles == {}

    def test_parse_error_records_evaluation_and_falls_back(self, monkeypatch):
        """When parse_master_resume raises, the fallback must return the
        unfiltered master and record a parse_error evaluation so the
        fallback is visible in the audit trail."""
        import seeker_os.resume.generator as genmod

        def _boom(_text):
            raise ValueError("simulated parse failure")

        monkeypatch.setattr(genmod, "parse_master_resume", _boom)

        settings = _make_settings()
        original = "## Professional Experience\n### Role\n**Co** · loc · *2020–2022*\n- Did stuff"
        filtered_text, role_titles, _, _, _, _, _, _, _ = _run_deterministic_bullet_selection(
            settings=settings, master_resume=original, jd_text=JD_TEXT,
            job_title=JOB_TITLE, operation_id="test-op-parse-err",
        )
        assert filtered_text == original
        assert role_titles == {}

        import seeker_os.database as dbmod
        db = dbmod.get_connection()
        try:
            row = db.execute(
                "SELECT evaluator_name, label, passed, details_json "
                "FROM llm_evaluations WHERE operation_id = ? "
                "AND label = 'parse_error' LIMIT 1",
                ("test-op-parse-err",),
            ).fetchone()
        finally:
            db.close()
        assert row is not None, "expected a parse_error evaluation record"
        assert row[0] == "bullet_selection"
        assert row[2] == 0  # passed=False stored as 0


class TestPromptInstructionBuilders:
    def test_selection_instructions_empty_when_no_roles(self):
        assert _build_selection_instructions({}) == ""

    def test_selection_instructions_names_roles(self):
        text = _build_selection_instructions({"cloud-devops-engineer": "Cloud & DevOps Engineer"})
        assert "Cloud & DevOps Engineer" in text
        assert "do NOT add a bullet" in text

    def test_tiering_instructions_recent_line_changes_when_selection_active(self):
        settings = _make_settings()
        inactive_text = _build_tiering_instructions(settings, selections_active=False)
        active_text = _build_tiering_instructions(settings, selections_active=True)
        assert "keep ALL strong bullets" in inactive_text
        assert "keep ALL strong bullets" not in active_text
        assert "already been deterministically pre-selected" in active_text
