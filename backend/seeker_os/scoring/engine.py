"""Tier 4: Scoring engine — scores jobs against a config-driven rubric.

The engine is GENERIC — no hardcoded values. All weights, patterns, thresholds
come from the rubric and profile config objects.
See docs/SCORING_RUBRIC.md for full spec.
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
    workplace_type: str | None = None,
    seniority_level: str | None = None,
    accepted_cities: list[str] | None = None,
    comp_trusted: bool = True,
    location_fallback_patterns: list[str] | None = None,
    never_claim: list[str] | None = None,
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

    elif check == "location_local":
        # Location-local bonus: applies only when the structured location
        # matches one of the user's accepted_cities (from profile config)
        # AND workplace_type is hybrid or on-site (not remote).
        if not location or not accepted_cities:
            return False
        # Remote roles don't get the local bonus — they already get remote_us
        if workplace_type and _check_pattern(workplace_type, "remote"):
            return False
        # Check if the location contains any accepted city
        for city in accepted_cities:
            if city.lower() in location.lower():
                return True
        return False

    elif check == "hybrid_non_local":
        # Penalizes hybrid roles that are NOT in an accepted city.
        # mod.pattern matches the hybrid keyword in JD text.
        # mod.unless excludes remote JD text (remote roles aren't hybrid-non-local).
        # accepted_cities exclusion is structural (from profile config) — no
        # duplicated city list in the rubric. location_local is the sole arbiter
        # of which cities are local.
        if not mod.pattern or not _check_pattern(jd_text, mod.pattern):
            return False
        if mod.unless and _check_pattern(jd_text, mod.unless):
            return False
        _lfp = location_fallback_patterns or ["remote"]
        _combined_lfp = "|".join(f"(?:{p})" for p in _lfp)
        if workplace_type and re.search(_combined_lfp, workplace_type, re.IGNORECASE):
            return False
        if not location:
            return False  # missing_location handles no-location penalty
        if accepted_cities:
            for city in accepted_cities:
                if city.lower() in location.lower():
                    return False
        return True

    elif check == "location_only":
        # Located role that is NOT in an accepted city and NOT remote.
        # This is the city_only_no_remote penalty — fires when:
        # 1. There is a location (not empty)
        # 2. JD does not mention remote (per location_fallback_patterns)
        # 3. workplace_type is not remote (if known)
        # 4. The location does NOT match any accepted_city
        if not location:
            return False
        _lfp = location_fallback_patterns or ["remote"]
        _combined_lfp = "|".join(f"(?:{p})" for p in _lfp)
        if re.search(_combined_lfp, jd_text, re.IGNORECASE):
            return False
        if workplace_type and re.search(_combined_lfp, workplace_type, re.IGNORECASE):
            return False
        # If the location matches an accepted city, this is NOT a city-only-no-remote
        if accepted_cities:
            for city in accepted_cities:
                if city.lower() in location.lower():
                    return False
        return True

    elif check == "structured_comp":
        if mod.threshold is not None:
            # Positive: comp_min >= threshold (e.g. comp_target bonus).
            # Gated on trusted provenance — untrusted comp (parsed/none) cannot
            # earn the bonus. A misparsed 130000000 must not get +1.0.
            if not comp_trusted:
                return False
            return comp_min is not None and comp_min >= mod.threshold
        if mod.threshold_min is not None and mod.threshold_max is not None:
            # Range: threshold_min <= comp < threshold_max
            # Must be checked before threshold_max-only case (which would shadow it).
            effective = comp_max if comp_max is not None else comp_min
            if effective is not None and mod.threshold_min <= effective < mod.threshold_max:
                return True
            return False
        if mod.threshold_max is not None:
            # Negative: comp_max below threshold_max
            if comp_max is not None and comp_max < mod.threshold_max:
                return True
            # Also check comp_min as fallback
            if comp_min is not None and comp_min < mod.threshold_max and comp_max is None:
                return True
            return False
        return False

    elif check == "no_location_no_remote":
        if not location and not _check_pattern(jd_text, "remote|united states"):
            return True
        return False

    elif check == "domain_mismatch":
        # Off-domain pattern density check: fires when the number of DISTINCT
        # patterns from mod.patterns matching the JD text meets min_distinct_hits.
        # This catches roles that match the title (e.g. "SRE") but actually
        # belong to a different engineering domain (e.g. carrier/network engineering).
        if not mod.patterns:
            return False
        matched = _domain_mismatch_matches(mod.patterns, jd_text)
        if len(matched) >= mod.min_distinct_hits:
            return True
        return False

    elif check == "never_claim_density":
        # Scaled penalty for never-claim technology density in the JD.
        # Reads the never_claim list from identity_rules.yml (passed in as
        # never_claim param) — no technology names hardcoded in Python.
        # Fires when at least 1 never-claim tech appears in the JD text.
        # The actual penalty is computed in score_job (not here) because it
        # is dynamic (points_per_hit * distinct_count, clamped at max_penalty,
        # or primary_stack_penalty when a term is in the title or heavily mentioned).
        # Terms in mod.density_exclude are skipped (scoring-layer only; identity
        # never_claim list itself is unchanged and still gates resumes).
        if not never_claim:
            return False
        exclude = set(mod.density_exclude or [])
        effective = [t for t in never_claim if t not in exclude]
        matched = _never_claim_matches(effective, jd_text)
        if matched:
            return True
        return False

    return False


def _domain_mismatch_matches(patterns: list[str], jd_text: str) -> list[str]:
    """Return the list of patterns that match in jd_text (distinct, case-insensitive)."""
    matched = []
    for p in patterns:
        if _check_pattern(jd_text, p):
            matched.append(p)
    return matched


def _never_claim_matches(never_claim: list[str], jd_text: str) -> list[str]:
    """Return the list of never-claim technologies found in jd_text.

    Uses word-boundary, case-insensitive matching. Each technology is counted
    at most once (distinct). Returns the list of matched technology names.
    """
    matched = []
    for tech in never_claim:
        pattern = rf"\b{re.escape(tech)}\b"
        if re.search(pattern, jd_text, re.IGNORECASE):
            matched.append(tech)
    return matched


def _never_claim_jd_mention_count(tech: str, jd_text: str) -> int:
    """Count occurrences of a never-claim tech in JD text (case-insensitive, word-boundary)."""
    pattern = rf"\b{re.escape(tech)}\b"
    return len(re.findall(pattern, jd_text, re.IGNORECASE))


def _compute_never_claim_penalty(
    mod: ModifierRule,
    never_claim: list[str],
    title: str,
    jd_text: str,
) -> tuple[float, list[str], str]:
    """Compute the never_claim_density penalty.

    Returns (penalty, matched_techs, reason_detail).

    Terms in mod.density_exclude are skipped — they don't count toward the
    density count or the primary-stack check. The identity never_claim list
    itself is unchanged (it still gates resumes); density_exclude is a
    scoring-layer override only.

    Logic:
    1. If any (non-excluded) never-claim tech appears in the title → primary_stack_penalty.
    2. If any (non-excluded) never-claim tech appears >= primary_stack_min_mentions times in JD → primary_stack_penalty.
    3. Otherwise → points_per_hit * distinct_count, clamped at max_penalty.
    """
    exclude = set(mod.density_exclude or [])
    effective = [t for t in never_claim if t not in exclude]
    matched = _never_claim_matches(effective, jd_text)
    if not matched:
        return 0.0, [], ""

    # Check for primary stack: title hit or high mention count
    primary_tech = None
    for tech in matched:
        title_pattern = rf"\b{re.escape(tech)}\b"
        if re.search(title_pattern, title, re.IGNORECASE):
            primary_tech = tech
            break
        if _never_claim_jd_mention_count(tech, jd_text) >= mod.primary_stack_min_mentions:
            primary_tech = tech
            break

    if primary_tech and mod.primary_stack_penalty is not None:
        return mod.primary_stack_penalty, matched, f"primary_stack: {primary_tech}"

    # Scaled penalty
    if mod.points_per_hit is not None:
        scaled = mod.points_per_hit * len(matched)
        if mod.max_penalty is not None:
            scaled = max(scaled, mod.max_penalty)  # both negative → max clamps toward zero
        return scaled, matched, f"{len(matched)} distinct: {', '.join(matched)}"

    return 0.0, matched, ""


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
    comp_source: str = "none",
    never_claim: list[str] | None = None,
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
    if len(jd_text) < rubric.min_jd_length:
        return ScoreResult(
            score=0, reasons=[f"Evidence gate: JD too short (<{rubric.min_jd_length} chars)"],
            hard_reject=True, reject_reason="insufficient_jd",
        )

    if not location:
        fallbacks = rubric.location_fallback_patterns
        if fallbacks:
            _combined = "|".join(f"(?:{p})" for p in fallbacks)
            has_location_signal = bool(re.search(_combined, jd_text, re.IGNORECASE))
        else:
            has_location_signal = False
        if not has_location_signal:
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
            # JD matches target-role keywords but no title match.
            # Patterns are configurable via BaseScoreRule.patterns in scoring_rubric.yml.
            # Use _check_pattern (regex, IGNORECASE) for consistency with all other checks.
            if rule.patterns and any(_check_pattern(jd_text, p) for p in rule.patterns):
                base_score = rule.score
                base_label = rule.label
                break
        elif rule.score == 0:
            base_score = rule.score
            base_label = rule.label
            break

    reasons.append(f"Base: {base_label} ({base_score})")

    # Comp provenance: determine trust and apply sanity bound.
    # Trusted sources (structured, manual) can earn comp_target and clear floor.
    # Untrusted sources (parsed, none) cannot earn comp_target; implausible values
    # (above comp_sanity_max) are treated as comp-unknown (None) so they can't
    # clear the floor or earn any comp modifier.
    comp_trusted = comp_source in rubric.trusted_comp_sources
    sanity_max = rubric.comp_sanity_max
    effective_comp_min = comp_min
    effective_comp_max = comp_max
    if comp_min is not None and comp_min > sanity_max:
        if not comp_trusted:
            effective_comp_min = None
            reasons.append(f"Comp sanity: comp_min={comp_min} exceeds sanity_max={sanity_max} (untrusted '{comp_source}') → treated as unknown")
        else:
            reasons.append(f"Comp sanity WARNING: comp_min={comp_min} exceeds sanity_max={sanity_max} (trusted '{comp_source}') — possible data error")
    if comp_max is not None and comp_max > sanity_max:
        if not comp_trusted:
            effective_comp_max = None
            reasons.append(f"Comp sanity: comp_max={comp_max} exceeds sanity_max={sanity_max} (untrusted '{comp_source}') → treated as unknown")
        else:
            reasons.append(f"Comp sanity WARNING: comp_max={comp_max} exceeds sanity_max={sanity_max} (trusted '{comp_source}') — possible data error")

    # Step 4: Positive modifiers (all matching patterns are summed)
    positive_total = 0.0
    fired_modifiers: dict[str, float] = {}
    accepted_cities = profile.location.accepted_cities
    for mod in rubric.positive_modifiers:
        if _check_modifier(mod, title, jd_text, location, effective_comp_min, effective_comp_max,
                           workplace_type=workplace_type, seniority_level=seniority_level,
                           accepted_cities=accepted_cities, comp_trusted=comp_trusted,
                           location_fallback_patterns=rubric.location_fallback_patterns):
            positive_total += mod.points
            fired_modifiers[mod.signal] = mod.points
            reasons.append(f"+{mod.points} {mod.signal}")

    # Step 5: Negative modifiers (all matching patterns are summed)
    negative_total = 0.0
    for mod in rubric.negative_modifiers:
        if _check_modifier(mod, title, jd_text, location, effective_comp_min, effective_comp_max,
                           workplace_type=workplace_type, seniority_level=seniority_level,
                           accepted_cities=accepted_cities, comp_trusted=comp_trusted,
                           location_fallback_patterns=rubric.location_fallback_patterns,
                           never_claim=never_claim):
            if mod.check == "never_claim_density" and never_claim:
                penalty, matched_techs, detail = _compute_never_claim_penalty(
                    mod, never_claim, title, jd_text,
                )
                negative_total += penalty
                fired_modifiers[mod.signal] = penalty
                reasons.append(f"{penalty} {mod.signal} ({detail})")
            elif mod.check == "domain_mismatch" and mod.patterns:
                matched = _domain_mismatch_matches(mod.patterns, jd_text)
                negative_total += mod.points
                fired_modifiers[mod.signal] = mod.points
                reasons.append(f"{mod.points} {mod.signal} (matched: {', '.join(matched)})")
            else:
                negative_total += mod.points
                fired_modifiers[mod.signal] = mod.points
                reasons.append(f"{mod.points} {mod.signal}")

    # Step 6: Clamp
    raw_score = base_score + positive_total + negative_total
    score = max(rubric.min_score, min(rubric.max_score, raw_score))

    return ScoreResult(
        score=score,
        reasons=reasons,
        gaps=gaps,
        hard_reject=False,
        fired_modifiers=fired_modifiers,
    )
