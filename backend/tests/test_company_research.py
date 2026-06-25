"""Tests for company research module."""

from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest

from seeker_os.research.models import (
    CompanyResearchResult,
    FundingDossier,
    FitDossier,
    SentimentDossier,
    SourceRef,
    VerdictFlags,
    WikipediaInfo,
)
from seeker_os.research.company_research import (
    fetch_wikipedia_info,
    fetch_wikidata_info,
    fetch_llm_dossier,
    research_company,
)


class TestWikipediaAdapter:
    """Tests for the Wikipedia adapter."""

    @patch("seeker_os.research.company_research.httpx.get")
    def test_search_and_summary_success(self, mock_get):
        """Should return WikipediaInfo when API returns data."""
        search_response = MagicMock()
        search_response.status_code = 200
        search_response.json.return_value = {
            "query": {
                "search": [{"title": "Stripe, Inc."}]
            }
        }
        search_response.raise_for_status = MagicMock()

        summary_response = MagicMock()
        summary_response.status_code = 200
        summary_response.json.return_value = {
            "title": "Stripe, Inc.",
            "description": "Financial services company",
            "extract": "Stripe is a payment processing company.",
            "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Stripe,_Inc."}},
            "thumbnail": {"source": "https://upload.wikimedia.org/thumb.jpg"},
        }

        mock_get.side_effect = [search_response, summary_response]

        result = fetch_wikipedia_info("Stripe")
        assert result is not None
        assert result.title == "Stripe, Inc."
        assert result.description == "Financial services company"
        assert "payment processing" in result.extract
        assert result.url == "https://en.wikipedia.org/wiki/Stripe,_Inc."
        assert result.thumbnail == "https://upload.wikimedia.org/thumb.jpg"

    @patch("seeker_os.research.company_research.httpx.get")
    def test_search_no_results(self, mock_get):
        """Should return None when Wikipedia search has no results."""
        search_response = MagicMock()
        search_response.status_code = 200
        search_response.json.return_value = {"query": {"search": []}}
        search_response.raise_for_status = MagicMock()

        mock_get.return_value = search_response

        result = fetch_wikipedia_info("NonexistentCompanyXYZ123")
        assert result is None

    @patch("seeker_os.research.company_research.httpx.get")
    def test_network_error(self, mock_get):
        """Should return None on network errors."""
        mock_get.side_effect = Exception("Network error")
        result = fetch_wikipedia_info("Stripe")
        assert result is None


class TestWikidataAdapter:
    """Tests for the Wikidata adapter."""

    @patch("seeker_os.research.company_research.httpx.get")
    def test_fetch_wikidata_success(self, mock_get):
        """Should return FundingDossier with founded year and headcount from Wikidata."""
        id_response = MagicMock()
        id_response.status_code = 200
        id_response.json.return_value = {
            "query": {
                "pages": {
                    "1": {"pageprops": {"wikibase_item": "Q7624104"}}
                }
            }
        }
        id_response.raise_for_status = MagicMock()

        entity_response = MagicMock()
        entity_response.status_code = 200
        entity_response.json.return_value = {
            "entities": {
                "Q7624104": {
                    "claims": {
                        "P571": [{"mainsnak": {"datavalue": {"value": {"time": "+2010-00-00T00:00:00Z"}}}}],
                        "P1128": [{"mainsnak": {"datavalue": {"value": {"amount": "+2500"}}}}],
                    }
                }
            }
        }

        mock_get.side_effect = [id_response, entity_response]

        result = fetch_wikidata_info("Stripe", wikipedia_title="Stripe, Inc.")
        assert result is not None
        assert result.founded == 2010
        assert result.headcount == 2500
        assert result.confidence == 0.6
        assert len(result.sources) == 1
        assert "wikidata.org" in result.sources[0].url

    @patch("seeker_os.research.company_research.httpx.get")
    def test_fetch_wikidata_no_item_id(self, mock_get):
        """Should return None when no Wikidata item is found."""
        id_response = MagicMock()
        id_response.status_code = 200
        id_response.json.return_value = {"query": {"pages": {"1": {"pageprops": {}}}}}
        id_response.raise_for_status = MagicMock()

        mock_get.return_value = id_response

        result = fetch_wikidata_info("Unknown", wikipedia_title="Unknown")
        assert result is None

    @patch("seeker_os.research.company_research.httpx.get")
    def test_fetch_wikidata_no_useful_data(self, mock_get):
        """Should return None when Wikidata has no founded year or employees."""
        id_response = MagicMock()
        id_response.status_code = 200
        id_response.json.return_value = {
            "query": {"pages": {"1": {"pageprops": {"wikibase_item": "Q123"}}}}
        }
        id_response.raise_for_status = MagicMock()

        entity_response = MagicMock()
        entity_response.status_code = 200
        entity_response.json.return_value = {
            "entities": {"Q123": {"claims": {}}}
        }

        mock_get.side_effect = [id_response, entity_response]

        result = fetch_wikidata_info("Test", wikipedia_title="Test")
        assert result is None


class TestResearchCompany:
    """Tests for the research_company orchestrator."""

    @patch("seeker_os.research.company_research.fetch_llm_dossier")
    @patch("seeker_os.research.company_research.fetch_wikidata_info")
    @patch("seeker_os.research.company_research.fetch_wikipedia_info")
    def test_wikipedia_and_wikidata_succeed(self, mock_wiki, mock_wikidata, mock_llm_dossier):
        """Should aggregate data from Wikipedia and Wikidata when LLM unavailable."""
        mock_wiki.return_value = WikipediaInfo(
            title="Stripe, Inc.",
            description="Financial services company",
            extract="Stripe is a payment processing company.",
        )
        mock_wikidata.return_value = FundingDossier(
            founded=2010,
            headcount=2500,
            confidence=0.6,
            sources=[SourceRef(url="https://www.wikidata.org/wiki/Q7624104", retrieved="2024-01-01T00:00:00Z")],
        )
        mock_llm_dossier.return_value = None

        result = research_company("Stripe", company_homepage="https://stripe.com")

        assert result.company_name == "Stripe"
        assert result.company_homepage == "https://stripe.com"
        assert result.wikipedia is not None
        assert result.funding is not None
        assert result.funding.founded == 2010
        assert result.funding.headcount == 2500
        assert "wikipedia" in result.sources_used
        assert "wikidata" in result.sources_used

    @patch("seeker_os.research.company_research.fetch_llm_dossier")
    @patch("seeker_os.research.company_research.fetch_wikidata_info")
    @patch("seeker_os.research.company_research.fetch_wikipedia_info")
    def test_llm_dossier_succeeds(self, mock_wiki, mock_wikidata, mock_llm_dossier):
        """Should use LLM dossier when it returns data, merging Wikidata context."""
        mock_wiki.return_value = WikipediaInfo(
            title="Stripe, Inc.",
            extract="Stripe is a payment processing company.",
        )
        mock_wikidata.return_value = FundingDossier(
            founded=2010,
            headcount=2500,
            confidence=0.6,
            sources=[SourceRef(url="https://www.wikidata.org/wiki/Q7624104", retrieved="2024-01-01T00:00:00Z")],
        )
        mock_llm_dossier.return_value = CompanyResearchResult(
            company_name="Stripe",
            researched_at="2024-06-01T00:00:00Z",
            overall_confidence=0.75,
            summary="Series D fintech, healthy runway, positive sentiment.",
            verdict_flags=VerdictFlags(green=["remote-first"], red=[], watch=["headcount growth slowing"]),
            funding=FundingDossier(
                founded=2010,
                stage="Series D",
                total_raised_usd=1500000000,
                headcount=7000,
                financial_health="healthy",
                confidence=0.8,
            ),
            sentiment=SentimentDossier(
                overall_rating_estimate=4.1,
                confidence=0.6,
            ),
            fit=FitDossier(
                remote_policy="fully remote",
                confidence=0.5,
            ),
            gaps=["valuation not disclosed"],
            sources_used=["llm_dossier"],
        )

        result = research_company("Stripe", company_homepage="https://stripe.com")

        assert result.wikipedia is not None
        assert result.funding is not None
        assert result.funding.stage == "Series D"
        assert result.funding.founded == 2010  # from LLM
        assert result.sentiment is not None
        assert result.sentiment.overall_rating_estimate == 4.1
        assert result.fit is not None
        assert result.fit.remote_policy == "fully remote"
        assert result.overall_confidence == 0.75
        assert "wikipedia" in result.sources_used
        assert "wikidata" in result.sources_used
        assert "llm_dossier" in result.sources_used
        assert "valuation not disclosed" in result.gaps

    @patch("seeker_os.research.company_research.fetch_llm_dossier")
    @patch("seeker_os.research.company_research.fetch_wikidata_info")
    @patch("seeker_os.research.company_research.fetch_wikipedia_info")
    def test_partial_sources(self, mock_wiki, mock_wikidata, mock_llm_dossier):
        """Should work when some sources return None."""
        mock_wiki.return_value = WikipediaInfo(
            title="Stripe, Inc.",
            extract="Stripe is a payment processing company.",
        )
        mock_wikidata.return_value = None
        mock_llm_dossier.return_value = None

        result = research_company("Stripe", enable_llm=True)

        assert result.wikipedia is not None
        assert result.funding is None
        assert result.sentiment is None
        assert "wikipedia" in result.sources_used
        assert "wikidata" not in result.sources_used

    @patch("seeker_os.research.company_research.fetch_llm_dossier")
    @patch("seeker_os.research.company_research.fetch_wikidata_info")
    @patch("seeker_os.research.company_research.fetch_wikipedia_info")
    def test_no_sources(self, mock_wiki, mock_wikidata, mock_llm_dossier):
        """Should return result with no data when all sources fail."""
        mock_wiki.return_value = None
        mock_wikidata.return_value = None
        mock_llm_dossier.return_value = None

        result = research_company("UnknownCompany")

        assert result.wikipedia is None
        assert result.funding is None
        assert result.sentiment is None
        assert result.sources_used == []

    @patch("seeker_os.research.company_research.fetch_llm_dossier")
    @patch("seeker_os.research.company_research.fetch_wikidata_info")
    @patch("seeker_os.research.company_research.fetch_wikipedia_info")
    def test_llm_disabled(self, mock_wiki, mock_wikidata, mock_llm_dossier):
        """Should skip LLM when enable_llm=False."""
        mock_wiki.return_value = WikipediaInfo(title="Test", extract="Test")
        mock_wikidata.return_value = None

        result = research_company("Test", enable_llm=False)

        assert result.sentiment is None
        assert "llm_dossier" not in result.sources_used
        mock_llm_dossier.assert_not_called()


class TestCompanyResearchModels:
    """Tests for Pydantic model serialization."""

    def test_company_research_result_serialization(self):
        """Should serialize to JSON and back correctly."""
        result = CompanyResearchResult(
            company_name="Stripe",
            company_homepage="https://stripe.com",
            wikipedia=WikipediaInfo(
                title="Stripe, Inc.",
                extract="Payment processing company.",
            ),
            overall_confidence=0.75,
            summary="Series D fintech, healthy runway.",
            verdict_flags=VerdictFlags(green=["remote-first"], red=["layoffs 2023"], watch=[]),
            funding=FundingDossier(
                founded=2010,
                stage="Series D",
                total_raised_usd=1500000000,
                headcount=7000,
                confidence=0.8,
            ),
            sentiment=SentimentDossier(
                overall_rating_estimate=4.1,
                confidence=0.6,
            ),
            fit=FitDossier(
                remote_policy="fully remote",
                confidence=0.5,
            ),
            gaps=["valuation not disclosed"],
            sources_used=["wikipedia", "wikidata", "llm_dossier"],
        )

        data = result.model_dump()
        assert data["company_name"] == "Stripe"
        assert data["wikipedia"]["title"] == "Stripe, Inc."
        assert data["funding"]["stage"] == "Series D"
        assert data["sentiment"]["overall_rating_estimate"] == 4.1
        assert data["fit"]["remote_policy"] == "fully remote"
        assert data["verdict_flags"]["green"] == ["remote-first"]
        assert "valuation not disclosed" in data["gaps"]

        restored = CompanyResearchResult(**data)
        assert restored.company_name == "Stripe"
        assert restored.wikipedia is not None
        assert restored.wikipedia.title == "Stripe, Inc."
        assert restored.funding is not None
        assert restored.funding.stage == "Series D"
        assert restored.sentiment is not None
        assert restored.sentiment.overall_rating_estimate == 4.1
        assert restored.fit is not None
        assert restored.fit.remote_policy == "fully remote"


class TestServerTimestamp:
    """Tests that server clock wins over model-emitted timestamps."""

    @patch("seeker_os.llm.router.ModelRouter")
    @patch("seeker_os.config.Settings")
    def test_dossier_uses_server_time_not_model_time(self, mock_settings_cls, mock_router_cls):
        """researched_at must be server-generated now(), not the LLM's value."""
        from datetime import datetime, timezone
        from seeker_os.research.company_research import fetch_llm_dossier

        bogus_date = "1999-01-01T00:00:00Z"

        mock_settings = MagicMock()
        mock_settings.providers = MagicMock()
        mock_settings.providers.providers = ["fake"]
        mock_settings_cls.return_value = mock_settings

        mock_router = MagicMock()
        mock_router.generate.return_value = MagicMock(
            text=json.dumps({
                "company": "TestCo",
                "researched_at": bogus_date,
                "overall_confidence": 0.5,
                "summary": "Test summary.",
                "verdict_flags": {"green": [], "red": [], "watch": []},
                "funding": None,
                "sentiment": None,
                "fit": None,
                "gaps": [],
            })
        )
        mock_router_cls.return_value = mock_router

        before = datetime.now(timezone.utc).isoformat()
        result = fetch_llm_dossier(company="TestCo")
        after = datetime.now(timezone.utc).isoformat()

        assert result is not None
        assert result.researched_at != bogus_date
        # researched_at should be between before and after (server time)
        assert before <= result.researched_at <= after

    @patch("seeker_os.llm.router.ModelRouter")
    @patch("seeker_os.config.Settings")
    def test_dossier_prompt_includes_jd_text(self, mock_settings_cls, mock_router_cls):
        """JD text must appear in the LLM prompt when provided."""
        from seeker_os.research.company_research import fetch_llm_dossier

        mock_settings = MagicMock()
        mock_settings.providers = MagicMock()
        mock_settings.providers.providers = ["fake"]
        mock_settings_cls.return_value = mock_settings

        mock_router = MagicMock()
        mock_router.generate.return_value = MagicMock(
            text=json.dumps({
                "company": "TestCo",
                "overall_confidence": 0.5,
                "summary": "Test.",
                "verdict_flags": {"green": [], "red": [], "watch": []},
                "funding": None, "sentiment": None, "fit": None, "gaps": [],
            })
        )
        mock_router_cls.return_value = mock_router

        jd = "We are a Series B company backed by Sequoia. Fully remote."
        fetch_llm_dossier(company="TestCo", jd_text=jd)

        call_args = mock_router.generate.call_args
        user_prompt = call_args.kwargs["user_prompt"]
        assert "Job description" in user_prompt
        assert jd in user_prompt

    @patch("seeker_os.llm.router.ModelRouter")
    @patch("seeker_os.config.Settings")
    def test_dossier_prompt_without_jd_text(self, mock_settings_cls, mock_router_cls):
        """When no JD is provided, the prompt should not include a JD section."""
        from seeker_os.research.company_research import fetch_llm_dossier

        mock_settings = MagicMock()
        mock_settings.providers = MagicMock()
        mock_settings.providers.providers = ["fake"]
        mock_settings_cls.return_value = mock_settings

        mock_router = MagicMock()
        mock_router.generate.return_value = MagicMock(
            text=json.dumps({
                "company": "TestCo",
                "overall_confidence": 0.5,
                "summary": "Test.",
                "verdict_flags": {"green": [], "red": [], "watch": []},
                "funding": None, "sentiment": None, "fit": None, "gaps": [],
            })
        )
        mock_router_cls.return_value = mock_router

        fetch_llm_dossier(company="TestCo")

        call_args = mock_router.generate.call_args
        user_prompt = call_args.kwargs["user_prompt"]
        assert "Job description" not in user_prompt
