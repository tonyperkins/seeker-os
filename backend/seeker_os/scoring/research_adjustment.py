"""Research-adjusted scoring — deterministic, confidence-gated modifiers derived
from the company research dossier.

This module does NOT re-derive a score via LLM. It takes the deterministic base
score from the rubric engine and applies signed, confidence-gated deltas based
on dossier fields. The base score is never mutated — both base_score and
adjusted_score are preserved for the UI.

All modifier magnitudes and thresholds come from config (scoring_rubric.yml
research_modifiers section), not hardcoded in Python.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel

from seeker_os.research.models import (
    CompanyResearchResult,
    FundingDossier,
    SentimentDossier,
    FitDossier,
)


class ResearchModifierRule(BaseModel):
    """A single research-adjustment rule from config."""
    factor: str
    delta: float
    confidence_threshold: float = 0.5
    source_section: str  # "funding" | "sentiment" | "fit"
    # Optional cutoffs for headcount-based factors
    headcount_max: int | None = None
    headcount_min: int | None = None
    # Optional: base-modifier signal to suppress when this factor fires
    suppresses: str | None = None


class ResearchBreakdownItem(BaseModel):
    """One applied modifier in the breakdown."""
    factor: str
    delta: float
    confidence: float
    source_section: str


class ResearchAdjustmentResult(BaseModel):
    """Result of computing research adjustment."""
    base_score: float
    research_delta: float = 0.0
    adjusted_score: float = 0.0
    breakdown: list[ResearchBreakdownItem] = []
    applied: bool = False  # False when no grounding (stub, no retrieval)


def _normalize_company_name(name: str) -> str:
    """Normalize company name for matching."""
    return (name or "").strip().lower()


def _is_recent_layoff(layoff_date: str | None, within_days: int = 180) -> bool:
    """Check if a layoff date is within the recent window."""
    if not layoff_date:
        return True  # If date is unknown but layoff exists, treat as recent
    try:
        parsed = datetime.fromisoformat(layoff_date.replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - parsed).days
        return age <= within_days
    except (ValueError, TypeError):
        return True  # Unparseable date — treat as recent


def _has_down_round_signals(funding: FundingDossier) -> bool:
    """Detect down round or runway risk signals."""
    if funding.financial_health:
        health = funding.financial_health.lower()
        if any(w in health for w in ("down round", "distressed", "bankruptcy", "runway risk")):
            return True
    if funding.last_round and funding.last_round.type:
        rtype = funding.last_round.type.lower()
        if "down" in rtype:
            return True
    return False


def _has_healthy_runway(funding: FundingDossier) -> bool:
    """Detect fresh raise / healthy runway signals."""
    if funding.financial_health:
        health = funding.financial_health.lower()
        if any(w in health for w in ("healthy", "strong", "profitable", "well-capitalized")):
            return True
    if funding.last_round and funding.last_round.date:
        try:
            parsed = datetime.fromisoformat(funding.last_round.date.replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - parsed).days
            if age_days <= 365 and funding.last_round.amount_usd and funding.last_round.amount_usd > 0:
                return True
        except (ValueError, TypeError):
            pass
    return False


def _has_remote_walkback(fit: FitDossier) -> bool:
    """Detect RTO / remote walkback signals."""
    if fit.remote_walkback:
        return True
    if fit.remote_policy:
        policy = fit.remote_policy.lower()
        if policy in ("onsite", "in-office", "hybrid") and "remote" not in policy:
            return True
    return False


def _has_strong_negative_theme(sentiment: SentimentDossier) -> bool:
    """Detect high-frequency recurring negative themes (not thin-sample ratings)."""
    for neg in sentiment.negatives:
        if neg.frequency in ("high", "med") and neg.paraphrase:
            return True
    return False


def _is_right_size_company(
    funding: FundingDossier, fit: FitDossier, rule: ResearchModifierRule
) -> bool:
    """Company is small/right-size.

    Headcount is authoritative when present: headcount ≤ cutoff → yes, headcount > cutoff → no.
    Only falls back to fit.size_bucket when headcount is None.
    """
    if funding.headcount is not None and rule.headcount_max is not None:
        return funding.headcount <= rule.headcount_max
    # Headcount unknown — fall back to size_bucket signal
    if fit.size_bucket:
        bucket = fit.size_bucket.lower()
        if any(w in bucket for w in ("small", "startup")):
            return True
    return False


def _is_large_company_confirmed(
    funding: FundingDossier, fit: FitDossier, rule: ResearchModifierRule
) -> bool:
    """Company is large.

    Headcount is authoritative when present: headcount ≥ cutoff → yes, headcount < cutoff → no.
    Only falls back to public + large size_bucket when headcount is None.
    """
    if funding.headcount is not None and rule.headcount_min is not None:
        return funding.headcount >= rule.headcount_min
    # Headcount unknown — fall back to public + large size_bucket signal
    if funding.public and fit.size_bucket:
        bucket = fit.size_bucket.lower()
        if any(w in bucket for w in ("large", "enterprise")):
            return True
    return False


# Map of factor name → evaluation function
# Each function receives (funding, sentiment, fit, rule) and returns bool.
_FACTOR_CHECKS = {
    "recent_layoffs": lambda f, s, ft, r: len(f.layoffs) > 0 and _is_recent_layoff(
        f.layoffs[0].date if f.layoffs else None
    ),
    "down_round_runway_risk": lambda f, s, ft, r: _has_down_round_signals(f),
    "healthy_runway": lambda f, s, ft, r: _has_healthy_runway(f),
    "remote_walkback_rto": lambda f, s, ft, r: _has_remote_walkback(ft),
    "strong_negative_sentiment": lambda f, s, ft, r: _has_strong_negative_theme(s),
    "right_size_company": lambda f, s, ft, r: _is_right_size_company(f, ft, r),
    "large_company_confirmed": lambda f, s, ft, r: _is_large_company_confirmed(f, ft, r),
}


def compute_research_adjustment(
    base_score: float,
    dossier: CompanyResearchResult,
    rules: list[ResearchModifierRule],
    max_score: float = 10.0,
    min_score: float = 0.0,
    base_modifiers: dict[str, float] | None = None,
) -> ResearchAdjustmentResult:
    """Compute research-adjusted score from base score + dossier.

    Returns base_score, research_delta, adjusted_score, and a breakdown.
    If the dossier is a stub or retrieval didn't run, returns zero adjustment.
    """
    # No grounding → no adjustment
    if dossier.is_stub or not dossier.retrieval_used:
        return ResearchAdjustmentResult(
            base_score=base_score,
            research_delta=0.0,
            adjusted_score=base_score,
            applied=False,
        )

    funding = dossier.funding
    sentiment = dossier.sentiment
    fit = dossier.fit

    # Need at least one section to apply modifiers
    if not funding and not sentiment and not fit:
        return ResearchAdjustmentResult(
            base_score=base_score,
            research_delta=0.0,
            adjusted_score=base_score,
            applied=False,
        )

    breakdown: list[ResearchBreakdownItem] = []
    total_delta = 0.0

    for rule in rules:
        # Confidence gate: check the relevant section's confidence
        section_conf = 0.0
        if rule.source_section == "funding" and funding:
            section_conf = funding.confidence
        elif rule.source_section == "sentiment" and sentiment:
            section_conf = sentiment.confidence
        elif rule.source_section == "fit" and fit:
            section_conf = fit.confidence
        else:
            continue  # Section not available

        if section_conf < rule.confidence_threshold:
            continue  # Below threshold — skip this modifier

        # Check if the factor condition is met
        check_fn = _FACTOR_CHECKS.get(rule.factor)
        if check_fn is None:
            continue  # Unknown factor — skip

        if not check_fn(funding or FundingDossier(), sentiment or SentimentDossier(), fit or FitDossier(), rule):
            continue

        # Apply the modifier
        total_delta += rule.delta
        breakdown.append(ResearchBreakdownItem(
            factor=rule.factor,
            delta=rule.delta,
            confidence=section_conf,
            source_section=rule.source_section,
        ))

        # Suppress double-count: if this rule suppresses a base modifier,
        # add a compensating delta to undo the base modifier's effect on base_score.
        if rule.suppresses and base_modifiers and rule.suppresses in base_modifiers:
            suppressed_delta = -base_modifiers[rule.suppresses]
            total_delta += suppressed_delta
            breakdown.append(ResearchBreakdownItem(
                factor=f"suppressed_{rule.suppresses}",
                delta=suppressed_delta,
                confidence=section_conf,
                source_section=rule.source_section,
            ))

    adjusted = max(min_score, min(max_score, base_score + total_delta))

    return ResearchAdjustmentResult(
        base_score=base_score,
        research_delta=total_delta,
        adjusted_score=adjusted,
        breakdown=breakdown,
        applied=True,
    )
