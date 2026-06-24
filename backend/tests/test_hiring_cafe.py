"""Tests for the hiring.cafe adapter (mocked HTTP)."""

import json
from unittest.mock import MagicMock, patch

from seeker_os.config import SourceConfig
from seeker_os.discovery.cache import DiskCache
from seeker_os.discovery.sources.hiring_cafe import HiringCafeAdapter
from seeker_os.models import SourceQuery


def _make_config() -> SourceConfig:
    return SourceConfig(
        id="hiring_cafe",
        type="hiring_cafe",
        base_url="https://hiring.cafe",
        source_map={"grnhse": "greenhouse", "hiring_cafe_pin": "SKIP"},
        request_delay_seconds=0,  # no delay in tests
        user_agent="test-agent",
        max_retries=1,
        timeout_seconds=5,
    )


def _make_mock_html() -> str:
    """Create mock HTML with __NEXT_DATA__ containing one job."""
    next_data = {
        "props": {
            "pageProps": {
                "ssrHits": [
                    {
                        "id": "grnhse___testco___123",
                        "source": "grnhse",
                        "board_token": "testco",
                        "apply_url": "https://boards.greenhouse.io/testco/jobs/123",
                        "is_hc_pinned": False,
                        "job_information": {"title": "Senior SRE"},
                        "v5_processed_job_data": {
                            "core_job_title": "Senior SRE",
                            "formatted_workplace_location": "Remote, US",
                            "workplace_countries": ["US"],
                            "workplace_type": "Remote",
                            "commitment": ["Full Time"],
                            "yearly_min_compensation": 160000,
                            "yearly_max_compensation": 200000,
                            "listed_compensation_currency": "USD",
                            "seniority_level": "Senior Level",
                            "role_type": "Individual Contributor",
                            "technical_tools": ["AWS", "Terraform"],
                            "requirements_summary": "Senior SRE with AWS",
                            "estimated_publish_date": "2026-06-20T00:00:00Z",
                            "company_name": "TestCo",
                        },
                        "enriched_company_data": {
                            "name": "TestCo",
                            "homepage_uri": "testco.com",
                        },
                    },
                    {
                        "id": "hiring_cafe_pin___sponsored___999",
                        "source": "hiring_cafe_pin",
                        "apply_url": "https://hiring.cafe/sponsored/999",
                        "is_hc_pinned": True,
                        "job_information": {"title": "Sponsored Job"},
                        "v5_processed_job_data": {
                            "company_name": "SponsoredCo",
                        },
                    },
                ],
                "ssrTotalCount": 2,
                "ssrIsLastPage": True,
            }
        }
    }
    return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(next_data)}</script>'


class TestHiringCafeAdapter:
    def test_fetch_jobs_parses_cards(self, tmp_path):
        cache = DiskCache(tmp_path / "cache", ttl_hours=1)
        adapter = HiringCafeAdapter(_make_config(), cache)

        mock_html = _make_mock_html()
        with patch.object(adapter, "_fetch_html", return_value=mock_html):
            query = SourceQuery(source_id="hiring_cafe", slug="test-query", label="Test")
            page = adapter.fetch_jobs(query, page=0)

        assert page.total_count == 2
        assert page.is_last_page is True
        assert len(page.jobs) == 1  # pinned job filtered out

        job = page.jobs[0]
        assert job.title == "Senior SRE"
        assert job.company == "TestCo"
        assert job.ats_source == "greenhouse"  # mapped from grnhse
        assert job.ats_board_token == "testco"
        assert job.comp_min == 160000
        assert job.comp_max == 200000
        assert job.is_pinned is False

    def test_pinned_job_filtered(self, tmp_path):
        cache = DiskCache(tmp_path / "cache", ttl_hours=1)
        adapter = HiringCafeAdapter(_make_config(), cache)

        mock_html = _make_mock_html()
        with patch.object(adapter, "_fetch_html", return_value=mock_html):
            query = SourceQuery(source_id="hiring_cafe", slug="test", label="Test")
            page = adapter.fetch_jobs(query, page=0)

        # Only 1 job (pinned one should be filtered)
        assert len(page.jobs) == 1
        assert all(not j.is_pinned for j in page.jobs)

    def test_source_map_skip(self, tmp_path):
        """source_map value 'SKIP' should filter out the job."""
        cache = DiskCache(tmp_path / "cache", ttl_hours=1)
        adapter = HiringCafeAdapter(_make_config(), cache)

        mock_html = _make_mock_html()
        with patch.object(adapter, "_fetch_html", return_value=mock_html):
            query = SourceQuery(source_id="hiring_cafe", slug="test", label="Test")
            page = adapter.fetch_jobs(query, page=0)

        # The hiring_cafe_pin job should be filtered (both by is_hc_pinned and source_map SKIP)
        assert len(page.jobs) == 1
        assert page.jobs[0].source_id == "hiring_cafe"

    def test_cache_hit_avoids_fetch(self, tmp_path):
        cache = DiskCache(tmp_path / "cache", ttl_hours=1)
        adapter = HiringCafeAdapter(_make_config(), cache)

        # Pre-populate cache
        cache.set("https://hiring.cafe/jobs/test?page=0", _make_mock_html())

        query = SourceQuery(source_id="hiring_cafe", slug="test", label="Test")
        page = adapter.fetch_jobs(query, page=0)

        assert len(page.jobs) == 1
        assert page.jobs[0].title == "Senior SRE"
