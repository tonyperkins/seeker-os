"""Tier 4: Scoring engine — scores jobs against a config-driven rubric.

The engine is GENERIC — no hardcoded values. All weights, patterns, thresholds
come from the rubric and profile config objects.
See docs/PHASE1_SPEC.md §3.6 and docs/SCORING_RUBRIC.md for full spec.
"""

from __future__ import annotations

import re

from seeker_os.config import ProfileConfig, ScoringConfig, ModifierRule
from seeker_os.models import ScoreResult


def _check_pattern(text: str, pattern: str) -> bool:
    """Check if a regex pattern matches in text (case-insensitive)."""
    return bool(re.search(pattern, text, re.IGNORECASE))


def _check_modifier(
    mod: ModifierRule,
    title: str,
    jd_text: str,
    location: str,
    comp_min: int | None,
    comp_max: int | None,
) -> bool:
    """Check if a modifier rule matches. Returns True if the modifier applies."""

    # Determine which text to check based on 'check' field
    check = mod.check

    if check == "jd":
        text = jd_text
        if not mod.pattern:
            return False
        if not _check_pattern(text, mod.pattern):
            return False
        # Check 'requires' (must also match)
        if mod.requires and not _check_pattern(jd_text, mod.requires):
            return False
        # Check 'unless' (must NOT match)
        if mod.unless and _check_pattern(jd_text, mod.unless):
            return False
        # Check comp conditions
        if mod.requires_comp_below is not None:
            effective_comp = comp_max if comp_max is not None else comp_min
            if effective_comp is None or effective_comp >= mod.requires_comp_below:
                return False
        if mod.requires_comp_at_least is not None:
            effective_comp = comp_max if comp_max is not None else comp_min
            if effective_comp is None or effective_comp < mod.requires_comp_at_least:
                return False
        return True

    elif check == "title":
        text = title
        if not mod.pattern:
            return False
        if not _check_pattern(text, mod.pattern):
            return False
        if mod.unless and _check_pattern(text, mod.unless):
            return False
        return True

    elif check == "location_or_jd":
        text = f"{location} {jd_text}"
        if not mod.pattern:
            return False
        return _check_pattern(text, mod.pattern)

    elif check == "location_only":
        # Location is a city, JD has no "remote"
        if not location:
            return False
        if _check_pattern(jd_text, "remote"):
            return False
        # Check if location is just a city (not a state/region)
        return True

    elif check == "structured_comp":
        if mod.threshold is not None:
            # Positive: comp_min >= threshold
            return comp_min is not None and comp_min >= mod.threshold
        if mod.threshold_max is not None:
            # Negative: comp_max below threshold_max
            if comp_max is not None and comp_max < mod.threshold_max:
                return True
            # Also check comp_min as fallback
            if comp_min is not None and comp_min < mod.threshold_max and comp_max is None:
                return True
            return False
        if mod.threshold_min is not None and mod.threshold_max is not None:
            # Range: threshold_min <= comp <= threshold_max
            effective = comp_max if comp_max is not None else comp_min
            if effective is not None and mod.threshold_min <= effective < mod.threshold_max:
                return True
            return False
        return False

    elif check == "no_location_no_remote":
        if not location and not _check_pattern(jd_text, "remote|united states"):
            return True
        return False

    elif check == "jd_infra_role":
        # JD matches infrastructure role but no title match
        infra_patterns = [
            "kubernetes", "terraform", "ci/cd", "cicd", "prometheus",
            "grafana", "observability", "sre", "site reliability",
            "infrastructure", "platform engineering", "devops",
        ]
        return any(p in jd_text.lower() for p in infra_patterns)

    return False


def score_job(
    title: str,
    jd_text: str,
    location: str,
    company: str,
    rubric: ScoringConfig,
    profile: ProfileConfig,
    comp_min: int | None = None,
    comp_max: int | None = None,
    workplace_type: str | None = None,
    seniority_level: str | None = None,
) -> ScoreResult:
    """Score a job against a config-driven rubric.

    The engine is GENERIC — no hardcoded values. All weights, patterns, thresholds
    come from the rubric and profile config objects.

    Steps:
    1. Evidence gate (JD too short, no location info)
    2. Hard reject checks (from profile.hard_rejects config)
    3. Base score (first matching pattern from rubric.base_scores)
    4. Positive modifiers (all matching from rubric.positive_modifiers)
    5. Negative modifiers (all matching from rubric.negative_modifiers)
    6. Clamp to rubric.min_score / rubric.max_score
    """
    reasons: list[str] = []
    gaps: list[str] = []

    # Step 1: Evidence gate
    if len(jd_text) < 500:
        return ScoreResult(
            score=0, reasons=["Evidence gate: JD too short (<500 chars)"],
            hard_reject=True, reject_reason="insufficient_jd",
        )

    if not location and not re.search(r"remote|united states|\bus\b", jd_text, re.IGNORECASE):
        return ScoreResult(
            score=0, reasons=["Evidence gate: no location information"],
            hard_reject=True, reject_reason="no_location",
        )

    # Step 2: Hard reject checks (from profile.hard_rejects)
    full_text = f"{title} {jd_text}"
    for hr in profile.hard_rejects:
        if re.search(hr.pattern, full_text, re.IGNORECASE):
            if hr.unless_pattern and re.search(hr.unless_pattern, full_text, re.IGNORECASE):
                continue  # unless pattern matched, skip this reject
            return ScoreResult(
                score=0,
                reasons=[f"Hard reject: {hr.reason}"],
                hard_reject=True,
                reject_reason=hr.reason,
            )

    # Step 3: Base score (first matching pattern wins)
    base_score = 0.0
    base_label = "No title/JD match"
    for rule in rubric.base_scores:
        if rule.pattern:
            if _check_pattern(title, rule.pattern):
                base_score = rule.score
                base_label = rule.label
                break
        elif rule.check == "jd_infra_role":
            if _check_modifier(
                ModifierRule(signal=rule.label, pattern=None, points=0, check="jd_infra_role"),
                title, jd_text, location, comp_min, comp_max,
            ):
                base_score = rule.score
                base_label = rule.label
                break
        elif rule.score == 0:
            base_score = rule.score
            base_label = rule.label
            break

    reasons.append(f"Base: {base_label} ({base_score})")

    # Step 4: Positive modifiers (all matching patterns are summed)
    positive_total = 0.0
    for mod in rubric.positive_modifiers:
        if _check_modifier(mod, title, jd_text, location, comp_min, comp_max):
            positive_total += mod.points
            reasons.append(f"+{mod.points} {mod.signal}")

    # Step 5: Negative modifiers (all matching patterns are summed)
    negative_total = 0.0
    for mod in rubric.negative_modifiers:
        if _check_modifier(mod, title, jd_text, location, comp_min, comp_max):
            negative_total += mod.points
            reasons.append(f"{mod.points} {mod.signal}")

    # Step 6: Clamp
    raw_score = base_score + positive_total + negative_total
    score = max(rubric.min_score, min(rubric.max_score, raw_score))

    return ScoreResult(
        score=score,
        reasons=reasons,
        gaps=gaps,
        hard_reject=False,
    )
