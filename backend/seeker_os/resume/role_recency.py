"""Deterministic recency bucketing for master-resume roles.

Parses the end date out of a role's `dates_raw` string (e.g. "June 2019 –
December 2022" or "January 2023 – Present") to determine how many years ago
the role ended. No LLM involved.
"""

from __future__ import annotations

import re
from datetime import date

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
    "june": 6, "july": 7, "august": 8, "september": 9, "october": 10,
    "november": 11, "december": 12,
}

_DATE_RANGE_RE = re.compile(
    r"(?P<start_month>[A-Za-z]+)?\s*(?P<start_year>\d{4})\s*[-–—]\s*"
    r"(?P<end_month>[A-Za-z]+)?\s*(?P<end>Present|present|\d{4})"
)


def parse_end_date(dates_raw: str, today: date | None = None) -> date | None:
    """Return the effective end date of a role's date range.

    "Present" resolves to `today`. Returns None if the string can't be
    parsed — callers should treat an unparseable date conservatively (e.g.
    as recent), never as a reason to drop a role's bullets.
    """
    today = today or date.today()
    match = _DATE_RANGE_RE.search(dates_raw)
    if not match:
        return None

    end_raw = match.group("end")
    if end_raw.lower() == "present":
        return today

    end_year = int(end_raw)
    end_month_name = match.group("end_month")
    end_month = _MONTHS.get(end_month_name.lower(), 12) if end_month_name else 12
    return date(end_year, end_month, 1)


def years_since_end(dates_raw: str, today: date | None = None) -> float | None:
    """Years between today and the role's end date. None if unparseable."""
    end_date = parse_end_date(dates_raw, today)
    if end_date is None:
        return None
    today = today or date.today()
    return (today - end_date).days / 365.25
