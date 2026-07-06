"""Net score computation — combines base score, research adjustment, and AI verdict.

Option B: The AI verdict acts as a CAP on the composite, not an addend.

    adjusted = clamp(base + research_delta, min_score, max_score)
    Net = min(adjusted, verdict_cap)  if analysis exists
    Net = adjusted                     if no analysis (fallback)

The verdict cap is config-driven (scoring_rubric.yml verdict_caps section).
APPLY → null cap (no ceiling, full adjusted score shows).
CONDITIONAL → cap at configured value (e.g. 7.0) — partial-fit cannot present as top.
MONITOR → cap lower (e.g. 5.0).
SKIP → cap low (e.g. 3.0).

All components (base, research_delta, verdict) are preserved separately for UI display.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def compute_net_score(
    base_score: float,
    research_delta: float,
    analysis_verdict: str | None,
    verdict_caps: dict[str, float | None],
    max_score: float = 10.0,
    min_score: float = 0.0,
    unknown_verdict_cap: float | None = None,
) -> float:
    """Compute the composite Net score.

    Args:
        base_score: The heuristic rubric score (jobs.score).
        research_delta: Signed delta from company research (jobs.research_delta).
        analysis_verdict: AI verdict string ("APPLY", "CONDITIONAL", etc.) or None.
        verdict_caps: Config-driven caps per verdict. null = no cap.
        max_score: Clamp ceiling (from scoring_rubric.yml).
        min_score: Clamp floor (from scoring_rubric.yml).
        unknown_verdict_cap: Cap for unrecognized verdicts. If None, falls back
            to the CONDITIONAL cap value if present in verdict_caps, else no cap
            (preserving legacy behavior when unconfigured).

    Returns:
        Net score, clamped to [min_score, max_score].
    """
    # Step 1: adjusted = base + research_delta, clamped
    adjusted = max(min_score, min(max_score, base_score + research_delta))

    # Step 2: if no analysis, Net = adjusted (verdict only affects Net once analysis exists)
    if analysis_verdict is None:
        return adjusted

    # Step 3: apply verdict cap
    cap = verdict_caps.get(analysis_verdict)
    if cap is not None:
        net = min(adjusted, cap)
    elif analysis_verdict in verdict_caps:
        # Verdict is known but has a null cap (e.g. APPLY) → no ceiling
        net = adjusted
    else:
        # Unknown verdict — not in verdict_caps at all. Log a warning so rogue
        # LLM output (e.g. "CONDITIONAL_PLUS") is visible rather than silently
        # treated as APPLY.
        logger.warning(
            "compute_net_score: unrecognized verdict %r not in verdict_caps %s "
            "— applying conservative cap",
            analysis_verdict,
            list(verdict_caps.keys()),
        )
        # Determine the fallback cap: explicit config, else CONDITIONAL cap, else none
        fallback_cap = unknown_verdict_cap
        if fallback_cap is None:
            fallback_cap = verdict_caps.get("CONDITIONAL")
        if fallback_cap is not None:
            net = min(adjusted, fallback_cap)
        else:
            net = adjusted

    # Step 4: clamp to [min_score, max_score] (belt + suspenders)
    return max(min_score, min(max_score, net))
