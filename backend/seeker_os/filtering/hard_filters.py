"""Tier 2: Card-level hard filters using config-driven thresholds.

The filter engine is GENERIC — all thresholds and lists come from config.
See docs/PHASE1_SPEC.md §3.4 for the full spec.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from seeker_os.config import FilterConfig, ProfileConfig, TitleFilters
from seeker_os.filtering.title_patterns import title_matches
from seeker_os.models import JobCard, FilterResult


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
    4. Seniority floor: seniority_level in filters.seniority_floor
       (with title-based fallback if None/unrecognized)
    5. Comp ceiling floor: comp_max >= profile.comp.floor (if comp_max is not None)
    6. Title match: core_title matches positive pattern, not negative
    7. Blacklist: company not in profile.blacklist
    8. Commitment: profile.employment.commitment in job.commitment
    9. Freshness: date_posted within filters.freshness_days
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

    # 4. Seniority floor
    sen = job.seniority_level
    if sen:
        if sen in filters.seniority_reject:
            return FilterResult(passed=False, reason=f"Seniority below floor ({sen})")
        if sen not in filters.seniority_floor:
            # Unrecognized seniority value
            if not filters.seniority_unknown_passes:
                return FilterResult(passed=False, reason=f"Unrecognized seniority ({sen})")
            # else: passes through to scoring
    else:
        # seniority_level is None — title-based fallback
        if not filters.seniority_unknown_passes:
            title_lower = (job.core_title or job.title or "").lower()
            junior_patterns = ["junior", "entry", "associate", "intern", "new grad", "early career"]
            if any(p in title_lower for p in junior_patterns):
                return FilterResult(passed=False, reason="Title indicates junior level (no seniority tag)")
            # If no junior signal and unknown_passes, let it through

    # 5. Comp ceiling floor
    if job.comp_max is not None:
        if job.comp_max < profile.comp.floor:
            return FilterResult(
                passed=False,
                reason=f"Comp ceiling below floor (comp_max={job.comp_max} < floor={profile.comp.floor})",
            )

    # 6. Title match
    if not title_matches(job.core_title or job.title, title_filters.positive, title_filters.negative):
        # Check if any negative pattern matched
        title_lower = (job.core_title or job.title or "").lower()
        neg_match = [n for n in title_filters.negative if n in title_lower]
        if neg_match:
            return FilterResult(passed=False, reason=f"Title negative match ({neg_match[0]})")
        return FilterResult(passed=False, reason="Title doesn't match positive patterns")

    # 7. Blacklist
    company_lower = (job.company or "").lower()
    for bl in profile.blacklist:
        if bl.lower() in company_lower:
            return FilterResult(passed=False, reason=f"Blacklisted company ({job.company})")

    # 8. Commitment
    if filters.commitment_required:
        commitments = [c.lower() for c in job.commitment]
        required = filters.commitment_required.lower()
        if commitments and required not in commitments:
            return FilterResult(passed=False, reason=f"Commitment mismatch (need {filters.commitment_required})")

    # 9. Freshness
    if filters.freshness_days > 0:
        posted = _parse_date(job.date_posted)
        if posted:
            age_days = (datetime.now(timezone.utc) - posted).days
            if age_days > filters.freshness_days:
                return FilterResult(passed=False, reason=f"Freshness expired ({age_days} days old)")

    return FilterResult(passed=True)
