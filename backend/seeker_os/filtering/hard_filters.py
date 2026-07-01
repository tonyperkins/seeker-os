"""Tier 2: Card-level hard filters using config-driven thresholds.

The filter engine is GENERIC — all thresholds and lists come from config.
See docs/PHASE1_SPEC.md §3.4 for the full spec.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import logging

from seeker_os.config import FilterConfig, ProfileConfig, TitleFilters
from seeker_os.filtering.title_patterns import title_matches
from seeker_os.models import JobCard, FilterResult

logger = logging.getLogger(__name__)


def _parse_date(date_str: str) -> datetime | None:
    """Parse an ISO timestamp. Returns None if unparseable."""
    if not date_str:
        return None
    try:
        # Handle Z suffix
        ds = date_str.replace("Z", "+00:00")
        return datetime.fromisoformat(ds)
    except (ValueError, TypeError):
        return None


def _title_has_override(title_lower: str, keywords: list[str]) -> bool:
    """Check if title contains any seniority override keyword (word-boundary match).

    Uses \\b word boundaries so 'staff' doesn't match 'staffing', etc.
    """
    for kw in keywords:
        if re.search(rf"\b{re.escape(kw.lower())}\b", title_lower):
            return True
    return False


def apply_filters(
    job: JobCard,
    profile: ProfileConfig,
    filters: FilterConfig,
    title_filters: TitleFilters,
) -> FilterResult:
    """Apply all Tier 2 hard filters using config-driven thresholds.

    Accepts a JobCard (from discovery). The runner can also use this with a
    Job-like object that exposes the same structured fields.

    Checks (in order, short-circuit on first failure):
    1. Pinned check (belt-and-suspenders)
    2. Remote only: workplace_type == 'Remote'
    3. US only: 'US' in workplace_countries
    4. Location exclude: location not in excluded list
    5. Seniority floor: seniority_level in filters.seniority_floor
       (with title-based override and fallback if None/unrecognized)
    6. Comp ceiling floor: comp_max >= effective floor (with margin)
    7. Title match: core_title matches positive pattern, not negative
    8. Blacklist: company not in profile.blacklist
    9. Commitment: profile.employment.commitment in job.commitment
    10. Visa sponsorship: if required, job must offer it
    11. Freshness: date_posted within filters.freshness_days
    """
    # 1. Pinned check
    if job.is_pinned:
        return FilterResult(passed=False, reason="Pinned job (should have been filtered earlier)")

    # 2. Remote only
    if filters.remote_only:
        if job.workplace_type and job.workplace_type.lower() != "remote":
            return FilterResult(passed=False, reason=f"Not remote (workplace_type={job.workplace_type})")

    # 3. US only
    if filters.us_only:
        countries = [c.upper() for c in job.workplace_countries]
        if countries and "US" not in countries:
            return FilterResult(passed=False, reason=f"Not US (countries={job.workplace_countries})")

    # 4. Location exclude
    if filters.location_exclude:
        location_lower = (job.location or "").lower()
        for excl in filters.location_exclude:
            if excl.lower() in location_lower:
                return FilterResult(passed=False, reason=f"Location excluded ({excl})")

    # 5. Seniority floor (with title override)
    title_lower = (job.core_title or job.title or "").lower()
    sen = job.seniority_level
    if sen:
        if sen in filters.seniority_reject:
            # Check title override — if title contains a senior keyword, pass anyway
            if filters.seniority_title_override:
                if _title_has_override(title_lower, filters.seniority_title_override):
                    pass  # title overrides the seniority tag
                else:
                    return FilterResult(passed=False, reason=f"Seniority below floor ({sen})")
            else:
                return FilterResult(passed=False, reason=f"Seniority below floor ({sen})")
        elif sen not in filters.seniority_floor:
            # Unrecognized seniority value
            if not filters.seniority_unknown_passes:
                # Check title override
                if not (filters.seniority_title_override and
                        _title_has_override(title_lower, filters.seniority_title_override)):
                    return FilterResult(passed=False, reason=f"Unrecognized seniority ({sen})")
            # else: passes through to scoring
    else:
        # seniority_level is None — title-based fallback
        if not filters.seniority_unknown_passes:
            # Check title override first
            has_override = (filters.seniority_title_override and
                            _title_has_override(title_lower, filters.seniority_title_override))
            if not has_override:
                junior_patterns = filters.junior_title_patterns
                if any(p in title_lower for p in junior_patterns):
                    return FilterResult(passed=False, reason="Title indicates junior level (no seniority tag)")
                # If no junior signal and unknown_passes, let it through

    # 6. Comp ceiling floor (with margin)
    # Sanity bound: comp above comp_sanity_max is implausible regardless of
    # source. Treat as comp-unknown so it can't clear the floor. This is the
    # universal guard — the $130,000 → 130000000 misfire must not pass.
    sanity_max = filters.comp_sanity_max
    effective_comp_max = job.comp_max
    if effective_comp_max is not None and effective_comp_max > sanity_max:
        effective_comp_max = None  # treat as unknown

    if effective_comp_max is not None:
        effective_floor = profile.comp.floor
        if filters.comp_floor_margin_pct > 0:
            effective_floor = int(effective_floor * (1 - filters.comp_floor_margin_pct / 100))
        if effective_comp_max < effective_floor:
            return FilterResult(
                passed=False,
                reason=f"Comp ceiling below floor (comp_max={job.comp_max} < floor={effective_floor})",
            )
    else:
        # comp is null or implausible (sanity-bounded)
        if not filters.comp_unknown_passes:
            return FilterResult(passed=False, reason="Comp not listed (comp_unknown_passes=False)")

    # 7. Title match
    if not title_matches(job.core_title or job.title, title_filters.positive, title_filters.negative):
        # Check if any negative pattern matched
        neg_match = [n for n in title_filters.negative if n in title_lower]
        if neg_match:
            return FilterResult(passed=False, reason=f"Title negative match ({neg_match[0]})")
        return FilterResult(passed=False, reason="Title doesn't match positive patterns")

    # 8. Defense blocklist
    company_lower = (job.company or "").lower()
    for dc in profile.defense_blocklist:
        if dc.lower() in company_lower:
            return FilterResult(passed=False, reason=f"Defense contractor (company blocklist)")

    # 9. Blacklist
    for bl in profile.blacklist:
        if bl.lower() in company_lower:
            return FilterResult(passed=False, reason=f"Blacklisted company ({job.company})")

    # 10. Commitment
    if filters.commitment_required:
        commitments = [c.lower() for c in job.commitment]
        required = filters.commitment_required.lower()
        if commitments and required not in commitments:
            return FilterResult(passed=False, reason=f"Commitment mismatch (need {filters.commitment_required})")

    # 11. Visa sponsorship
    if filters.visa_sponsorship_required:
        # JobCard doesn't have visa_sponsorship field yet — filter is a no-op.
        # Log once so the user knows the setting has no effect rather than
        # silently passing all jobs through.
        logger.warning(
            "visa_sponsorship_required is configured but cannot be enforced — "
            "visa_sponsorship field is not yet available in job data. "
            "All jobs pass this check until the field is populated."
        )

    # 12. Freshness
    if filters.freshness_days > 0:
        posted = _parse_date(job.date_posted)
        if posted:
            age_days = (datetime.now(timezone.utc) - posted).days
            if age_days > filters.freshness_days:
                return FilterResult(passed=False, reason=f"Freshness expired ({age_days} days old)")

    return FilterResult(passed=True)
