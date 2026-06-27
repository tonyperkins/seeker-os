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

        # Pre-populate cache (page 0 uses bare URL, no ?page=0)
        cache.set("https://hiring.cafe/jobs/test", _make_mock_html())

        query = SourceQuery(source_id="hiring_cafe", slug="test", label="Test")
        page = adapter.fetch_jobs(query, page=0)

        assert len(page.jobs) == 1
        assert page.jobs[0].title == "Senior SRE"

    def test_search_query_builds_search_state_url(self, tmp_path):
        """When search_query is set, adapter uses /?searchState= URL."""
        cache = DiskCache(tmp_path / "cache", ttl_hours=1)
        adapter = HiringCafeAdapter(_make_config(), cache)

        mock_html = _make_mock_html()
        captured_urls: list[str] = []

        def mock_fetch(url):
            captured_urls.append(url)
            return mock_html

        with patch.object(adapter, "_fetch_html", side_effect=mock_fetch):
            query = SourceQuery(
                source_id="hiring_cafe",
                slug="test-query",
                label="Test",
                search_query="senior sre remote",
            )
            page = adapter.fetch_jobs(query, page=0)

        assert len(captured_urls) == 1
        assert "searchState=" in captured_urls[0]
        assert "/jobs/" not in captured_urls[0]
        assert page.total_count == 2

    def test_search_query_with_date_filter(self, tmp_path):
        """When posted_within_days is set, searchState includes dateFetchedPastNDays."""
        cache = DiskCache(tmp_path / "cache", ttl_hours=1)
        adapter = HiringCafeAdapter(_make_config(), cache)

        mock_html = _make_mock_html()
        captured_urls: list[str] = []

        def mock_fetch(url):
            captured_urls.append(url)
            return mock_html

        with patch.object(adapter, "_fetch_html", side_effect=mock_fetch):
            query = SourceQuery(
                source_id="hiring_cafe",
                slug="test-query",
                label="Test",
                search_query="senior sre remote",
                posted_within_days=3,
            )
            adapter.fetch_jobs(query, page=0)

        assert len(captured_urls) == 1
        # The URL should contain searchState with dateFetchedPastNDays
        from urllib.parse import unquote, parse_qs, urlparse
        parsed = urlparse(captured_urls[0])
        params = parse_qs(parsed.query)
        state_json = json.loads(unquote(params["searchState"][0]))
        assert state_json["searchQuery"] == "senior sre remote"
        assert "dateFetchedPastNDays" in state_json
        # 3 days maps to enum 4
        assert state_json["dateFetchedPastNDays"] == 4

    def test_search_query_without_date_filter(self, tmp_path):
        """When posted_within_days is None, searchState omits dateFetchedPastNDays."""
        cache = DiskCache(tmp_path / "cache", ttl_hours=1)
        adapter = HiringCafeAdapter(_make_config(), cache)

        mock_html = _make_mock_html()
        captured_urls: list[str] = []

        def mock_fetch(url):
            captured_urls.append(url)
            return mock_html

        with patch.object(adapter, "_fetch_html", side_effect=mock_fetch):
            query = SourceQuery(
                source_id="hiring_cafe",
                slug="test-query",
                label="Test",
                search_query="senior sre remote",
                posted_within_days=None,
            )
            adapter.fetch_jobs(query, page=0)

        from urllib.parse import unquote, parse_qs, urlparse
        parsed = urlparse(captured_urls[0])
        params = parse_qs(parsed.query)
        state_json = json.loads(unquote(params["searchState"][0]))
        assert "dateFetchedPastNDays" not in state_json

    def test_backward_compat_slug_url(self, tmp_path):
        """When search_query is absent, adapter falls back to /jobs/{slug} URL."""
        cache = DiskCache(tmp_path / "cache", ttl_hours=1)
        adapter = HiringCafeAdapter(_make_config(), cache)

        mock_html = _make_mock_html()
        captured_urls: list[str] = []

        def mock_fetch(url):
            captured_urls.append(url)
            return mock_html

        with patch.object(adapter, "_fetch_html", side_effect=mock_fetch):
            query = SourceQuery(
                source_id="hiring_cafe",
                slug="senior-sre-remote",
                label="Test",
            )
            adapter.fetch_jobs(query, page=0)

        assert len(captured_urls) == 1
        assert captured_urls[0] == "https://hiring.cafe/jobs/senior-sre-remote"

    def test_search_query_pagination(self, tmp_path):
        """searchState URL with page > 0 uses &page= param."""
        cache = DiskCache(tmp_path / "cache", ttl_hours=1)
        adapter = HiringCafeAdapter(_make_config(), cache)

        mock_html = _make_mock_html()
        captured_urls: list[str] = []

        def mock_fetch(url):
            captured_urls.append(url)
            return mock_html

        with patch.object(adapter, "_fetch_html", side_effect=mock_fetch):
            query = SourceQuery(
                source_id="hiring_cafe",
                slug="test-query",
                label="Test",
                search_query="senior sre remote",
            )
            adapter.fetch_jobs(query, page=1)

        assert len(captured_urls) == 1
        assert "&page=1" in captured_urls[0]

    def test_server_side_workplace_type_filter(self, tmp_path):
        """workplace_types is included in searchState as workplaceTypes."""
        cache = DiskCache(tmp_path / "cache", ttl_hours=1)
        adapter = HiringCafeAdapter(_make_config(), cache)

        captured_urls: list[str] = []
        with patch.object(adapter, "_fetch_html", side_effect=lambda url: (captured_urls.append(url), _make_mock_html())[1]):
            query = SourceQuery(
                source_id="hiring_cafe", slug="test", label="Test",
                search_query="senior sre remote", workplace_types=["Remote"],
            )
            adapter.fetch_jobs(query, page=0)

        from urllib.parse import unquote, parse_qs, urlparse
        state = json.loads(unquote(parse_qs(urlparse(captured_urls[0]).query)["searchState"][0]))
        assert state["workplaceTypes"] == ["Remote"]

    def test_server_side_commitment_filter(self, tmp_path):
        """commitments is included in searchState."""
        cache = DiskCache(tmp_path / "cache", ttl_hours=1)
        adapter = HiringCafeAdapter(_make_config(), cache)

        captured_urls: list[str] = []
        with patch.object(adapter, "_fetch_html", side_effect=lambda url: (captured_urls.append(url), _make_mock_html())[1]):
            query = SourceQuery(
                source_id="hiring_cafe", slug="test", label="Test",
                search_query="senior sre remote", commitments=["Full Time"],
            )
            adapter.fetch_jobs(query, page=0)

        from urllib.parse import unquote, parse_qs, urlparse
        state = json.loads(unquote(parse_qs(urlparse(captured_urls[0]).query)["searchState"][0]))
        assert state["commitments"] == ["Full Time"]

    def test_server_side_seniority_filter(self, tmp_path):
        """seniority_levels is included in searchState as seniorityLevels."""
        cache = DiskCache(tmp_path / "cache", ttl_hours=1)
        adapter = HiringCafeAdapter(_make_config(), cache)

        captured_urls: list[str] = []
        with patch.object(adapter, "_fetch_html", side_effect=lambda url: (captured_urls.append(url), _make_mock_html())[1]):
            query = SourceQuery(
                source_id="hiring_cafe", slug="test", label="Test",
                search_query="senior sre remote", seniority_levels=["Senior Level"],
            )
            adapter.fetch_jobs(query, page=0)

        from urllib.parse import unquote, parse_qs, urlparse
        state = json.loads(unquote(parse_qs(urlparse(captured_urls[0]).query)["searchState"][0]))
        assert state["seniorityLevels"] == ["Senior Level"]

    def test_server_side_role_type_filter(self, tmp_path):
        """role_types is included in searchState as roleTypes."""
        cache = DiskCache(tmp_path / "cache", ttl_hours=1)
        adapter = HiringCafeAdapter(_make_config(), cache)

        captured_urls: list[str] = []
        with patch.object(adapter, "_fetch_html", side_effect=lambda url: (captured_urls.append(url), _make_mock_html())[1]):
            query = SourceQuery(
                source_id="hiring_cafe", slug="test", label="Test",
                search_query="senior sre remote", role_types=["Individual Contributor"],
            )
            adapter.fetch_jobs(query, page=0)

        from urllib.parse import unquote, parse_qs, urlparse
        state = json.loads(unquote(parse_qs(urlparse(captured_urls[0]).query)["searchState"][0]))
        assert state["roleTypes"] == ["Individual Contributor"]

    def test_server_side_filters_omitted_when_none(self, tmp_path):
        """When server-side filter fields are None, they're omitted from searchState."""
        cache = DiskCache(tmp_path / "cache", ttl_hours=1)
        adapter = HiringCafeAdapter(_make_config(), cache)

        captured_urls: list[str] = []
        with patch.object(adapter, "_fetch_html", side_effect=lambda url: (captured_urls.append(url), _make_mock_html())[1]):
            query = SourceQuery(
                source_id="hiring_cafe", slug="test", label="Test",
                search_query="senior sre remote",
            )
            adapter.fetch_jobs(query, page=0)

        from urllib.parse import unquote, parse_qs, urlparse
        state = json.loads(unquote(parse_qs(urlparse(captured_urls[0]).query)["searchState"][0]))
        assert "workplaceTypes" not in state
        assert "commitments" not in state
        assert "seniorityLevels" not in state
        assert "roleTypes" not in state

    def test_server_side_filters_combined(self, tmp_path):
        """All server-side filters can be combined in one searchState."""
        cache = DiskCache(tmp_path / "cache", ttl_hours=1)
        adapter = HiringCafeAdapter(_make_config(), cache)

        captured_urls: list[str] = []
        with patch.object(adapter, "_fetch_html", side_effect=lambda url: (captured_urls.append(url), _make_mock_html())[1]):
            query = SourceQuery(
                source_id="hiring_cafe", slug="test", label="Test",
                search_query="senior sre remote",
                posted_within_days=3,
                workplace_types=["Remote"],
                commitments=["Full Time"],
                seniority_levels=["Senior Level"],
                role_types=["Individual Contributor"],
            )
            adapter.fetch_jobs(query, page=0)

        from urllib.parse import unquote, parse_qs, urlparse
        state = json.loads(unquote(parse_qs(urlparse(captured_urls[0]).query)["searchState"][0]))
        assert state["searchQuery"] == "senior sre remote"
        assert state["dateFetchedPastNDays"] == 4
        assert state["workplaceTypes"] == ["Remote"]
        assert state["commitments"] == ["Full Time"]
        assert state["seniorityLevels"] == ["Senior Level"]
        assert state["roleTypes"] == ["Individual Contributor"]


class TestDaysToHcEnum:
    def test_1_day_maps_to_24h(self):
        from seeker_os.discovery.sources.hiring_cafe import _days_to_hc_enum
        assert _days_to_hc_enum(1) == 2

    def test_3_days_maps_to_3_days(self):
        from seeker_os.discovery.sources.hiring_cafe import _days_to_hc_enum
        assert _days_to_hc_enum(3) == 4

    def test_5_days_maps_to_1_week(self):
        from seeker_os.discovery.sources.hiring_cafe import _days_to_hc_enum
        assert _days_to_hc_enum(5) == 14

    def test_7_days_maps_to_1_week(self):
        from seeker_os.discovery.sources.hiring_cafe import _days_to_hc_enum
        assert _days_to_hc_enum(7) == 14

    def test_14_days_maps_to_1_week(self):
        from seeker_os.discovery.sources.hiring_cafe import _days_to_hc_enum
        assert _days_to_hc_enum(14) == 14

    def test_30_days_maps_to_1_month(self):
        from seeker_os.discovery.sources.hiring_cafe import _days_to_hc_enum
        assert _days_to_hc_enum(30) == 61

    def test_45_days_maps_to_1_month(self):
        from seeker_os.discovery.sources.hiring_cafe import _days_to_hc_enum
        assert _days_to_hc_enum(45) == 61

    def test_365_days_maps_to_1_year(self):
        from seeker_os.discovery.sources.hiring_cafe import _days_to_hc_enum
        assert _days_to_hc_enum(365) == 750

    def test_beyond_3_years_maps_to_all_time(self):
        from seeker_os.discovery.sources.hiring_cafe import _days_to_hc_enum
        assert _days_to_hc_enum(2000) == -1
