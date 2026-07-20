"""Tests for deterministic role-date recency parsing (Phase 1)."""

from datetime import date

from seeker_os.resume.role_recency import parse_end_date, years_since_end


class TestParseEndDate:
    def test_present_resolves_to_today(self):
        today = date(2026, 7, 19)
        assert parse_end_date("January 2023 – Present", today) == today

    def test_month_year_end_parsed(self):
        assert parse_end_date("June 2019 – December 2022") == date(2022, 12, 1)

    def test_year_only_end_parsed(self):
        assert parse_end_date("March 2010 – 2015") == date(2015, 12, 1)

    def test_unparseable_returns_none(self):
        assert parse_end_date("not a date range") is None


class TestYearsSinceEnd:
    def test_present_role_is_zero_years_ago(self):
        today = date(2026, 7, 19)
        assert years_since_end("January 2023 – Present", today) == 0.0

    def test_past_role_years_computed(self):
        today = date(2026, 7, 19)
        years = years_since_end("June 2019 – December 2022", today)
        assert 3.5 < years < 4.0

    def test_unparseable_returns_none(self):
        assert years_since_end("garbage") is None
