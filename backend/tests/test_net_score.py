"""Tests for net score computation — Option B (verdict as a cap, not an addend)."""

from seeker_os.scoring.net_score import compute_net_score


_DEFAULT_CAPS = {
    "APPLY": None,        # no cap — full adjusted score
    "CONDITIONAL": 7.0,   # partial-fit cannot present as top
    "MONITOR": 5.0,
    "SKIP": 3.0,
}


class TestNetScoreClamping:
    def test_base_plus_positive_research_clamps_to_max(self):
        """BUG 1: Net must never exceed max_score."""
        result = compute_net_score(
            base_score=9.5,
            research_delta=1.0,
            analysis_verdict="APPLY",
            verdict_caps=_DEFAULT_CAPS,
            max_score=10.0,
            min_score=0.0,
        )
        assert result == 10.0  # 9.5 + 1.0 = 10.5 → clamped to 10.0

    def test_high_base_high_research_clamps_to_max(self):
        """Even with APPLY (no cap), the adjusted score clamps to max."""
        result = compute_net_score(
            base_score=9.5,
            research_delta=1.0,
            analysis_verdict="APPLY",
            verdict_caps=_DEFAULT_CAPS,
            max_score=10.0,
            min_score=0.0,
        )
        assert result == 10.0  # 9.5 + 1.0 = 10.5 → clamped to 10.0

    def test_negative_sum_clamps_to_min(self):
        """Net must never fall below min_score."""
        result = compute_net_score(
            base_score=1.0,
            research_delta=-3.0,
            analysis_verdict="SKIP",
            verdict_caps=_DEFAULT_CAPS,
            max_score=10.0,
            min_score=0.0,
        )
        # adjusted = 1.0 - 3.0 = -2.0 → clamped to 0.0, then SKIP cap 3.0 → min(0, 3) = 0
        assert result == 0.0


class TestConditionalDoesNotBoost:
    def test_conditional_caps_below_base(self):
        """BUG 2: CONDITIONAL must not raise a score above its base."""
        result = compute_net_score(
            base_score=9.0,
            research_delta=0.0,
            analysis_verdict="CONDITIONAL",
            verdict_caps=_DEFAULT_CAPS,
            max_score=10.0,
            min_score=0.0,
        )
        # adjusted = 9.0, CONDITIONAL cap = 7.0 → min(9.0, 7.0) = 7.0
        assert result == 7.0
        assert result < 9.0  # CONDITIONAL lowered the score, not raised it

    def test_conditional_with_research_still_capped(self):
        """A high base + positive research still gets capped by CONDITIONAL."""
        result = compute_net_score(
            base_score=8.0,
            research_delta=0.5,
            analysis_verdict="CONDITIONAL",
            verdict_caps=_DEFAULT_CAPS,
            max_score=10.0,
            min_score=0.0,
        )
        # adjusted = 8.5, CONDITIONAL cap = 7.0 → min(8.5, 7.0) = 7.0
        assert result == 7.0

    def test_conditional_does_not_raise_above_base(self):
        """Even with a positive research delta, CONDITIONAL net <= base + research."""
        result = compute_net_score(
            base_score=6.0,
            research_delta=0.5,
            analysis_verdict="CONDITIONAL",
            verdict_caps=_DEFAULT_CAPS,
            max_score=10.0,
            min_score=0.0,
        )
        # adjusted = 6.5, CONDITIONAL cap = 7.0 → min(6.5, 7.0) = 6.5
        # Net (6.5) is not raised above adjusted (6.5) — cap only lowers
        assert result == 6.5


class TestVerdictCaps:
    def test_apply_no_cap(self):
        """APPLY (null cap) preserves the full adjusted score."""
        result = compute_net_score(
            base_score=7.0,
            research_delta=0.5,
            analysis_verdict="APPLY",
            verdict_caps=_DEFAULT_CAPS,
            max_score=10.0,
            min_score=0.0,
        )
        assert result == 7.5  # no cap applied

    def test_monitor_caps_at_5(self):
        result = compute_net_score(
            base_score=8.0,
            research_delta=0.0,
            analysis_verdict="MONITOR",
            verdict_caps=_DEFAULT_CAPS,
            max_score=10.0,
            min_score=0.0,
        )
        assert result == 5.0

    def test_skip_caps_at_3(self):
        result = compute_net_score(
            base_score=8.0,
            research_delta=0.0,
            analysis_verdict="SKIP",
            verdict_caps=_DEFAULT_CAPS,
            max_score=10.0,
            min_score=0.0,
        )
        assert result == 3.0

    def test_skip_cap_does_not_raise_low_score(self):
        """If adjusted is already below the SKIP cap, cap doesn't raise it."""
        result = compute_net_score(
            base_score=2.0,
            research_delta=0.0,
            analysis_verdict="SKIP",
            verdict_caps=_DEFAULT_CAPS,
            max_score=10.0,
            min_score=0.0,
        )
        # adjusted = 2.0, SKIP cap = 3.0 → min(2.0, 3.0) = 2.0 (cap only lowers)
        assert result == 2.0

    def test_unknown_verdict_no_cap(self):
        """An unrecognized verdict gets no cap (treated like APPLY)."""
        result = compute_net_score(
            base_score=7.0,
            research_delta=0.0,
            analysis_verdict="UNKNOWN_VERDICT",
            verdict_caps=_DEFAULT_CAPS,
            max_score=10.0,
            min_score=0.0,
        )
        assert result == 7.0


class TestUnanalyzedFallback:
    def test_no_verdict_falls_back_to_adjusted(self):
        """When no analysis exists, Net = base + research_delta (clamped)."""
        result = compute_net_score(
            base_score=7.0,
            research_delta=0.5,
            analysis_verdict=None,
            verdict_caps=_DEFAULT_CAPS,
            max_score=10.0,
            min_score=0.0,
        )
        assert result == 7.5  # just base + research, no verdict cap

    def test_no_verdict_negative_research(self):
        result = compute_net_score(
            base_score=6.0,
            research_delta=-1.5,
            analysis_verdict=None,
            verdict_caps=_DEFAULT_CAPS,
            max_score=10.0,
            min_score=0.0,
        )
        assert result == 4.5

    def test_no_verdict_clamps_to_max(self):
        result = compute_net_score(
            base_score=9.5,
            research_delta=1.0,
            analysis_verdict=None,
            verdict_caps=_DEFAULT_CAPS,
            max_score=10.0,
            min_score=0.0,
        )
        assert result == 10.0

    def test_no_verdict_clamps_to_min(self):
        result = compute_net_score(
            base_score=1.0,
            research_delta=-3.0,
            analysis_verdict=None,
            verdict_caps=_DEFAULT_CAPS,
            max_score=10.0,
            min_score=0.0,
        )
        assert result == 0.0


class TestEmptyCaps:
    def test_empty_caps_no_verdict_effect(self):
        """When verdict_caps is empty, verdict has no effect on score."""
        result = compute_net_score(
            base_score=8.0,
            research_delta=0.0,
            analysis_verdict="SKIP",
            verdict_caps={},
            max_score=10.0,
            min_score=0.0,
        )
        assert result == 8.0  # no cap to apply


class TestPromptInjectionResistance:
    """Verify that an adversarial LLM response (prompt injection producing an
    inflated verdict/score) cannot bypass the deterministic clamping path.

    The LLM's weighted_score is NOT used in net_score computation — only the
    verdict string feeds into verdict_caps. These tests confirm that even if a
    malicious JD tricks the LLM into returning APPLY with a max weighted_score,
    the net_score is still bounded by base_score + research_delta + caps.
    """

    def test_inflated_apply_with_low_base_stays_low(self):
        """LLM returns APPLY + weighted_score 10.0, but base_score is 3.0.
        Net = clamp(3.0 + 0.0, 0, 10) = 3.0 — APPLY has null cap so no further
        clamping, but the LLM's inflated weighted_score is never used."""
        result = compute_net_score(
            base_score=3.0,
            research_delta=0.0,
            analysis_verdict="APPLY",
            verdict_caps=_DEFAULT_CAPS,
            max_score=10.0,
            min_score=0.0,
        )
        assert result == 3.0  # base_score is what matters, not LLM's weighted_score

    def test_inflated_apply_with_positive_research_clamps_to_max(self):
        """Even with APPLY (no cap), base + research cannot exceed max_score."""
        result = compute_net_score(
            base_score=9.5,
            research_delta=2.0,
            analysis_verdict="APPLY",
            verdict_caps=_DEFAULT_CAPS,
            max_score=10.0,
            min_score=0.0,
        )
        assert result == 10.0  # 9.5 + 2.0 = 11.5 → clamped to 10.0

    def test_inflated_conditional_capped_regardless_of_llm_score(self):
        """LLM returns CONDITIONAL with weighted_score 10.0, but base is 9.0.
        Net = min(9.0, 7.0) = 7.0 — the CONDITIONAL cap holds regardless."""
        result = compute_net_score(
            base_score=9.0,
            research_delta=0.0,
            analysis_verdict="CONDITIONAL",
            verdict_caps=_DEFAULT_CAPS,
            max_score=10.0,
            min_score=0.0,
        )
        assert result == 7.0  # CONDITIONAL cap overrides

    def test_skip_verdict_overrides_inflated_base(self):
        """Even if base_score is high (e.g. rubric scored well), SKIP caps it."""
        result = compute_net_score(
            base_score=9.0,
            research_delta=0.0,
            analysis_verdict="SKIP",
            verdict_caps=_DEFAULT_CAPS,
            max_score=10.0,
            min_score=0.0,
        )
        assert result == 3.0  # SKIP cap = 3.0, regardless of base
