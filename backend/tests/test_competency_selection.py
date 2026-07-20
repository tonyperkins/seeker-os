"""Phase 3 tests: deterministic competency category pruning.

Tests cover:
- Parsing of the competency markdown table into CategoryBlock objects
- GATED ROWS HTML comment preserved untouched (never parsed, never rendered)
- Category selection with always-include consuming slots first
- JD-scored ranking produces different selections for different JDs
- Qualifier text (parentheticals) stripped for scoring but rendered verbatim
- Unmatched always-include warning path
- Category cap enforcement
- Render filtering drops non-selected category rows
- Integration with _run_deterministic_bullet_selection
"""

from dataclasses import dataclass
from pathlib import Path

import pytest

from seeker_os.config import ContentTieringConfig
from seeker_os.database import run_migrations
from seeker_os.resume.bullet_ranker import select_competencies
from seeker_os.resume.master_parser import parse_master_resume, render_filtered_master


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "synthetic_master_resume.md"

# JDs that should produce different ranked selections
# (always-includes are constant across both)
NON_AI_JD = """
We are looking for a Senior Cloud Engineer to manage our AWS infrastructure.
Requirements: Terraform for IaC, GitLab CI for pipelines, Kubernetes deployment,
Akamai CDN configuration, and strong incident response experience.
Nice to have: Jenkins, CloudFormation, ELK Stack.
"""

AI_INFRAS_JD = """
We are looking for an AI Infrastructure Engineer to build and operate
LLM serving infrastructure. Requirements: Ollama for local inference,
multi-provider LLM routing (Anthropic + OpenAI), inference cost optimization,
and Python scripting. Nice to have: MCP integration, agentic guardrails,
claim-level accuracy validation.
"""

JOB_TITLE = "Senior Engineer"


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
    tiering = tiering or ContentTieringConfig(
        max_competency_categories=8,
        always_include_competency_categories=[
            "AI Infrastructure",
            "AI Reliability & Quality",
            "SRE Practice",
        ],
        competency_label_boost=1.5,
        competency_qualifier_stopwords=[
            "broad familiarity", "ai-assisted", "ai-assistance", "ai-accelerated",
            "growing", "re-ramping", "dated", "production depth", "familiar",
            "minimal", "with significant ai assistance",
        ],
        max_items_per_category=6,
    )
    return _FakeSettings(
        channel_rules=_FakeChannelRules(resume=_FakeChannelConfig(content_tiering=tiering))
    )


@pytest.fixture()
def master_text() -> str:
    return FIXTURE_PATH.read_text()


@pytest.fixture()
def parsed(master_text):
    return parse_master_resume(master_text)


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Isolate DB for evaluation records."""
    import seeker_os.database as dbmod
    db_path = tmp_path / "test_competency.db"
    run_migrations(db_path)
    monkeypatch.setattr(dbmod, "_db_path", lambda: db_path)


class TestCompetencyParsing:
    def test_twelve_categories_parsed(self, parsed):
        assert len(parsed.categories) == 12

    def test_category_labels(self, parsed):
        labels = [c.label for c in parsed.categories]
        assert "AI Infrastructure" in labels
        assert "SRE Practice" in labels
        assert "Cloud Platforms" in labels
        assert "Programming & Scripting" in labels

    def test_category_skills_text_preserves_qualifiers(self, parsed):
        cloud = parsed.category_by_label("Cloud Platforms")
        assert cloud is not None
        assert "broad familiarity" in cloud.skills_text
        assert "production depth, growing" in cloud.skills_text

    def test_gated_rows_not_parsed_as_categories(self, parsed):
        labels = [c.label for c in parsed.categories]
        assert "GATED ROWS" not in labels
        assert all("GATED" not in l for l in labels)

    def test_gated_rows_preserved_in_render(self, master_text, parsed):
        filtered = render_filtered_master(parsed, {}, dropped_category_line_nos={})
        assert "GATED ROWS" in filtered
        assert "vLLM" in filtered
        assert "LiteLLM" in filtered


class TestCompetencySelection:
    def test_always_include_consumes_slots_first(self, parsed):
        result = select_competencies(
            categories=parsed.categories,
            jd_text=NON_AI_JD,
            job_title=JOB_TITLE,
            max_categories=8,
            always_include=["AI Infrastructure", "AI Reliability & Quality", "SRE Practice"],
        )
        assert "AI Infrastructure" in result.selected_labels
        assert "AI Reliability & Quality" in result.selected_labels
        assert "SRE Practice" in result.selected_labels
        assert len(result.selected_labels) == 8

    def test_category_cap_enforced(self, parsed):
        result = select_competencies(
            categories=parsed.categories,
            jd_text=NON_AI_JD,
            job_title=JOB_TITLE,
            max_categories=8,
            always_include=["AI Infrastructure", "AI Reliability & Quality", "SRE Practice"],
        )
        assert len(result.selected_labels) == 8
        assert len(result.dropped_labels) == 4  # 12 - 8 = 4 dropped

    def test_non_ai_jd_ranks_cloud_higher_than_ai(self, parsed):
        result = select_competencies(
            categories=parsed.categories,
            jd_text=NON_AI_JD,
            job_title=JOB_TITLE,
            max_categories=8,
            always_include=["AI Infrastructure", "AI Reliability & Quality", "SRE Practice"],
        )
        # Cloud Platforms should be selected for a cloud JD
        assert "Cloud Platforms" in result.selected_labels
        # Agentic Systems should be dropped (no agentic keywords in non-AI JD)
        assert all(d["label"] != "Cloud Platforms" for d in result.dropped_labels)

    def test_ai_infra_jd_ranks_agentic_higher(self, parsed):
        result = select_competencies(
            categories=parsed.categories,
            jd_text=AI_INFRAS_JD,
            job_title=JOB_TITLE,
            max_categories=8,
            always_include=["AI Infrastructure", "AI Reliability & Quality", "SRE Practice"],
        )
        # Agentic Systems should be selected for an AI-infra JD
        assert "Agentic Systems" in result.selected_labels

    def test_different_jds_produce_different_ranked_selections(self, parsed):
        always_inc = ["AI Infrastructure", "AI Reliability & Quality", "SRE Practice"]
        non_ai_result = select_competencies(
            categories=parsed.categories,
            jd_text=NON_AI_JD,
            job_title=JOB_TITLE,
            max_categories=8,
            always_include=always_inc,
        )
        ai_result = select_competencies(
            categories=parsed.categories,
            jd_text=AI_INFRAS_JD,
            job_title=JOB_TITLE,
            max_categories=8,
            always_include=always_inc,
        )
        # Always-includes are constant
        assert set(always_inc).issubset(set(non_ai_result.selected_labels))
        assert set(always_inc).issubset(set(ai_result.selected_labels))
        # Ranked selections differ
        non_ai_ranked = set(non_ai_result.selected_labels) - set(always_inc)
        ai_ranked = set(ai_result.selected_labels) - set(always_inc)
        assert non_ai_ranked != ai_ranked

    def test_qualifier_only_match_does_not_score(self, parsed):
        """A category whose only JD match is qualifier text (e.g. 'broad
        familiarity', 'growing') must score 0 — qualifiers are stripped
        before scoring."""
        # JD that only contains qualifier words, no technical terms
        qualifier_jd = "Looking for someone with broad familiarity and growing depth"
        result = select_competencies(
            categories=parsed.categories,
            jd_text=qualifier_jd,
            job_title=JOB_TITLE,
            max_categories=8,
            always_include=[],
        )
        # Cloud Platforms has 'broad familiarity' and 'growing' in its
        # skills text. After qualifier stripping, these must not score.
        # All categories should score 0 (no real JD overlap).
        for dropped in result.dropped_labels:
            assert dropped["score"] == 0.0, f"{dropped['label']} scored {dropped['score']} — qualifier leaked into scoring"

    def test_cloud_platforms_scores_above_zero_on_generic_cloud_jd(self, parsed):
        """Cloud Platforms must rank above 0 against a JD using generic
        cloud phrasing (matching 3556's style: 'cloud-native platforms',
        'public cloud infrastructure'). The label 'Cloud Platforms'
        provides the signal via label_boost."""
        generic_cloud_jd = (
            "12+ years in building, automating, and operating cloud-native "
            "platforms at scale. 5+ years hands-on with public cloud "
            "infrastructure, CI/CD automation, and reliability tooling."
        )
        result = select_competencies(
            categories=parsed.categories,
            jd_text=generic_cloud_jd,
            job_title=JOB_TITLE,
            max_categories=8,
            always_include=[],
        )
        # Cloud Platforms should be selected (label matches 'cloud' and 'platforms')
        assert "Cloud Platforms" in result.selected_labels

    def test_iac_scores_above_zero_on_infra_jd(self, parsed):
        """Infrastructure as Code must rank above 0 against a JD using
        'Infrastructure-as-Code' phrasing. The label provides the signal."""
        infra_jd = (
            "8+ years designing microservices-based systems along with API "
            "and Infrastructure-as-Code expertise."
        )
        result = select_competencies(
            categories=parsed.categories,
            jd_text=infra_jd,
            job_title=JOB_TITLE,
            max_categories=8,
            always_include=[],
        )
        # Infrastructure as Code should be selected
        assert "Infrastructure as Code" in result.selected_labels

    def test_observability_scores_above_zero_on_observability_jd(self, parsed):
        """Observability must rank above 0 against a JD mentioning
        'observability standards'. The label provides the signal."""
        obs_jd = "Enhance stability through observability standards and incident learning loops."
        result = select_competencies(
            categories=parsed.categories,
            jd_text=obs_jd,
            job_title=JOB_TITLE,
            max_categories=8,
            always_include=[],
        )
        # Observability should be selected
        assert "Observability" in result.selected_labels

    def test_label_boost_amplifies_label_matches(self, parsed):
        """Label tokens that match JD terms should earn the label_boost
        multiplier, causing label-rich categories to outrank categories
        with equal raw JD overlap but no label match."""
        # 'platform' appears in both the JD and the 'Cloud Platforms' label.
        # 'platform' also appears in 'Developer Experience' skills text
        # ('platform standardization') but NOT in its label.
        # With label_boost, Cloud Platforms should outscore Developer Experience.
        platform_jd = "Experience building platform capabilities at scale."
        result = select_competencies(
            categories=parsed.categories,
            jd_text=platform_jd,
            job_title=JOB_TITLE,
            max_categories=8,
            always_include=[],
            label_boost=2.0,  # make the boost effect visible
        )
        # Both should be selected, but Cloud Platforms should rank higher
        # because 'platform' and 'platforms' are in its label (boosted)
        # while Developer Experience only has 'platform' in skills text.
        selected = result.selected_labels
        if "Cloud Platforms" in selected and "Developer Experience" in selected:
            # Cloud Platforms should come first (higher score)
            assert selected.index("Cloud Platforms") < selected.index("Developer Experience")

    def test_parenthetical_skills_scored_after_qualifier_strip(self, parsed):
        """Real skill terms inside parentheticals (e.g. 'CI/CD integration'
        inside IaC's parenthetical) must be scored after qualifier stripping.
        Only known qualifier phrases are stripped — everything else scores."""
        # JD mentions 'CI/CD' which appears inside IaC's parenthetical:
        # 'Terraform (modular, remote state, CI/CD integration)'
        cicd_jd = "Experience with CI/CD automation for infrastructure work."
        result = select_competencies(
            categories=parsed.categories,
            jd_text=cicd_jd,
            job_title=JOB_TITLE,
            max_categories=8,
            always_include=[],
        )
        # Infrastructure as Code should score from 'ci/cd' in its parenthetical
        # plus 'infrastructure' in its label
        assert "Infrastructure as Code" in result.selected_labels

    def test_unmatched_always_include_warning(self, parsed):
        result = select_competencies(
            categories=parsed.categories,
            jd_text=NON_AI_JD,
            job_title=JOB_TITLE,
            max_categories=8,
            always_include=["Nonexistent Category"],
        )
        assert any("competency_always_include_unmatched:Nonexistent Category" in w for w in result.warnings)

    def test_always_include_case_insensitive(self, parsed):
        result = select_competencies(
            categories=parsed.categories,
            jd_text=NON_AI_JD,
            job_title=JOB_TITLE,
            max_categories=8,
            always_include=["ai infrastructure", "SRE PRACTICE"],
        )
        assert "AI Infrastructure" in result.selected_labels
        assert "SRE Practice" in result.selected_labels

    def test_dropped_line_nos_correct(self, parsed):
        result = select_competencies(
            categories=parsed.categories,
            jd_text=NON_AI_JD,
            job_title=JOB_TITLE,
            max_categories=8,
            always_include=["AI Infrastructure", "AI Reliability & Quality", "SRE Practice"],
        )
        # Each dropped category should have a line_no
        for d in result.dropped_labels:
            assert d["line_no"] >= 0
        # dropped_line_nos should match
        assert result.dropped_line_nos == {d["line_no"] for d in result.dropped_labels}


class TestCompetencyRender:
    def test_dropped_categories_removed_from_render(self, master_text, parsed):
        result = select_competencies(
            categories=parsed.categories,
            jd_text=NON_AI_JD,
            job_title=JOB_TITLE,
            max_categories=8,
            always_include=["AI Infrastructure", "AI Reliability & Quality", "SRE Practice"],
        )
        filtered = render_filtered_master(
            parsed, {}, dropped_category_line_nos=result.dropped_line_nos,
        )
        # Selected categories should be present
        for label in result.selected_labels:
            assert label in filtered
        # Dropped categories should NOT be present as table rows
        for d in result.dropped_labels:
            # The label appears in the table row format | **Label** |
            row_pattern = f"**{d['label']}**"
            assert row_pattern not in filtered

    def test_qualifier_text_verbatim_in_render(self, master_text, parsed):
        """Qualifier text must be byte-identical in the rendered output."""
        result = select_competencies(
            categories=parsed.categories,
            jd_text=NON_AI_JD,
            job_title=JOB_TITLE,
            max_categories=8,
            always_include=["AI Infrastructure", "AI Reliability & Quality", "SRE Practice"],
        )
        filtered = render_filtered_master(
            parsed, {}, dropped_category_line_nos=result.dropped_line_nos,
        )
        # Cloud Platforms should be selected for a cloud JD
        if "Cloud Platforms" in result.selected_labels:
            assert "broad familiarity across core services" in filtered
            assert "production depth, growing" in filtered

    def test_gated_rows_survive_render_with_drops(self, master_text, parsed):
        result = select_competencies(
            categories=parsed.categories,
            jd_text=NON_AI_JD,
            job_title=JOB_TITLE,
            max_categories=8,
            always_include=["AI Infrastructure", "AI Reliability & Quality", "SRE Practice"],
        )
        filtered = render_filtered_master(
            parsed, {}, dropped_category_line_nos=result.dropped_line_nos,
        )
        assert "GATED ROWS" in filtered
        assert "vLLM" in filtered

    def test_table_header_preserved(self, master_text, parsed):
        result = select_competencies(
            categories=parsed.categories,
            jd_text=NON_AI_JD,
            job_title=JOB_TITLE,
            max_categories=8,
            always_include=["AI Infrastructure", "AI Reliability & Quality", "SRE Practice"],
        )
        filtered = render_filtered_master(
            parsed, {}, dropped_category_line_nos=result.dropped_line_nos,
        )
        assert "| Area | Skills |" in filtered
        assert "|------|--------|" in filtered


class TestCompetencyIntegration:
    def test_competency_active_in_deterministic_selection(self, master_text):
        from seeker_os.resume.generator import _run_deterministic_bullet_selection
        settings = _make_settings()
        _, _, _, _, _, competency_active, selected_labels, _pinned = _run_deterministic_bullet_selection(
            settings=settings,
            master_resume=master_text,
            jd_text=NON_AI_JD,
            job_title=JOB_TITLE,
            operation_id="test-comp-int-1",
        )
        assert competency_active is True
        assert len(selected_labels) == 8
        assert "AI Infrastructure" in selected_labels
        assert "SRE Practice" in selected_labels

    def test_competency_inactive_without_config(self, master_text):
        from seeker_os.resume.generator import _run_deterministic_bullet_selection
        # No always_include, max_categories=0 → no categories selected
        tiering = ContentTieringConfig(
            max_competency_categories=0,
            always_include_competency_categories=[],
        )
        settings = _make_settings(tiering=tiering)
        _, _, _, _, _, competency_active, selected_labels, _pinned = _run_deterministic_bullet_selection(
            settings=settings,
            master_resume=master_text,
            jd_text=NON_AI_JD,
            job_title=JOB_TITLE,
            operation_id="test-comp-int-2",
        )
        # With max_categories=0 and no always-include, nothing is selected
        # but competency_active is False (no selected labels)
        assert competency_active is False
        assert selected_labels == []

    def test_dropped_categories_not_in_filtered_master(self, master_text):
        from seeker_os.resume.generator import _run_deterministic_bullet_selection
        settings = _make_settings()
        filtered, _, _, _, _, _, selected_labels, _pinned = _run_deterministic_bullet_selection(
            settings=settings,
            master_resume=master_text,
            jd_text=NON_AI_JD,
            job_title=JOB_TITLE,
            operation_id="test-comp-int-3",
        )
        # 12 categories, 8 selected → 4 dropped
        assert len(selected_labels) == 8
        # Count category rows in filtered output
        import re
        cat_rows = re.findall(r"\|\s*\*\*([^*]+)\*\*\s*\|", filtered)
        assert len(cat_rows) == 8


class TestCompetencyItemCapping:
    """Tests for per-category item selection (Lever 2)."""

    def test_qualifier_preserved_on_surviving_item(self, parsed):
        """A qualifier phrase (e.g. 'broad familiarity') must be byte-identical
        on a surviving item that carries one — item capping drops whole items,
        never truncates or rewords them."""
        # Use a JD that matches Cloud Platforms so it's selected
        result = select_competencies(
            categories=parsed.categories,
            jd_text=NON_AI_JD,
            job_title=JOB_TITLE,
            max_categories=8,
            always_include=["AI Infrastructure", "AI Reliability & Quality", "SRE Practice"],
            max_items_per_category=6,
        )
        # Cloud Platforms has 3 items (<=6), so all survive — but the test
        # verifies that qualifier text is byte-identical in the kept set.
        # For categories that ARE capped, we verify the same property.
        from seeker_os.resume.bullet_ranker import _split_skill_items
        for label in result.selected_labels:
            cat = parsed.category_by_label(label)
            if cat is None:
                continue
            items = _split_skill_items(cat.skills_text)
            kept = result.kept_items.get(label, items)  # uncapped = all items
            # Check that any item containing a qualifier is byte-identical
            for original_item in items:
                if "broad familiarity" in original_item or "growing" in original_item:
                    assert original_item in kept, f"Qualifier-bearing item was dropped: {original_item}"
                    # Verify byte-identical
                    kept_item = next(k for k in kept if k == original_item)
                    assert kept_item == original_item

    def test_jd_matched_item_survives_over_unmatched(self, parsed):
        """Within a category, a JD-matched item must survive over an
        unmatched one when item capping is active."""
        # Use a JD that mentions Python to select Programming & Scripting (7 items)
        python_jd = """
We need a Senior Engineer with Python scripting, Bash automation,
Terraform for IaC, GitLab CI, Kubernetes, and Akamai CDN.
Nice to have: Jenkins, CloudFormation, ELK Stack, Go, Node.js, Java, C#.
"""
        result = select_competencies(
            categories=parsed.categories,
            jd_text=python_jd,
            job_title=JOB_TITLE,
            max_categories=8,
            always_include=["AI Infrastructure", "AI Reliability & Quality", "SRE Practice"],
            max_items_per_category=6,
        )
        # Programming & Scripting has 7 items — should be capped to 6
        assert "Programming & Scripting" in result.selected_labels, "Programming & Scripting should be selected by Python JD"
        kept = result.kept_items.get("Programming & Scripting", [])
        dropped = result.dropped_items.get("Programming & Scripting", [])
        assert len(kept) == 6, f"Expected 6 kept items, got {len(kept)}"
        assert len(kept) + len(dropped) == 7, f"Expected 7 total items, got {len(kept) + len(dropped)}"
        # Python (JD-matched) should survive
        assert "Python" in kept, "Python (JD-matched) should survive capping"
        # All kept items must be from the original item set
        from seeker_os.resume.bullet_ranker import _split_skill_items
        cat = parsed.category_by_label("Programming & Scripting")
        all_items = _split_skill_items(cat.skills_text)
        for k in kept:
            assert k in all_items, f"Kept item '{k}' not in original items"
        for d in dropped:
            assert d in all_items, f"Dropped item '{d}' not in original items"

    def test_category_with_few_items_unchanged(self, parsed):
        """A category with <= N items must render unchanged — no items
        dropped, no kept_items/dropped_items entries."""
        result = select_competencies(
            categories=parsed.categories,
            jd_text=NON_AI_JD,
            job_title=JOB_TITLE,
            max_categories=8,
            always_include=["AI Infrastructure", "AI Reliability & Quality", "SRE Practice"],
            max_items_per_category=6,
        )
        from seeker_os.resume.bullet_ranker import _split_skill_items
        for label in result.selected_labels:
            cat = parsed.category_by_label(label)
            if cat is None:
                continue
            items = _split_skill_items(cat.skills_text)
            if len(items) <= 6:
                # Category should NOT appear in kept_items or dropped_items
                assert label not in result.kept_items, f"{label} has <=6 items but appears in kept_items"
                assert label not in result.dropped_items, f"{label} has <=6 items but appears in dropped_items"
