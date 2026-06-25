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
        assert result.overall_confidence == (0.8 + 0.6 + 0.5) / 3  # capped to mean of section confidences
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


class TestPhase3RetrievalAndThresholds:
    """Tests for Phase 3: live retrieval, staleness, confidence floor, no-provider degradation."""

    def test_retrieval_snippets_injected_into_llm_prompt(self):
        """When retrieval snippets are provided, their URLs appear in the LLM prompt."""
        from seeker_os.research.retrieval.models import RetrievalSnippet
        from seeker_os.research.company_research import fetch_llm_dossier

        snippets = [
            RetrievalSnippet(
                title="Stripe raises $6.5B Series D",
                url="https://techcrunch.com/stripe-series-d",
                snippet="Stripe raised $6.5 billion in a Series D round led by Thrive Capital.",
                source_domain="techcrunch.com",
            ),
            RetrievalSnippet(
                title="Stripe employee reviews",
                url="https://glassdoor.com/stripe-reviews",
                snippet="Employees rate Stripe 4.1 out of 5 stars.",
                source_domain="glassdoor.com",
            ),
        ]

        with patch("seeker_os.llm.router.ModelRouter") as mock_router_cls, \
             patch("seeker_os.config.Settings") as mock_settings_cls:
            mock_settings = MagicMock()
            mock_settings.providers = MagicMock()
            mock_settings.providers.providers = ["fake"]
            mock_settings_cls.return_value = mock_settings

            mock_router = MagicMock()
            mock_router.generate.return_value = MagicMock(
                text=json.dumps({
                    "company": "Stripe",
                    "overall_confidence": 0.7,
                    "summary": "Test.",
                    "verdict_flags": {"green": [], "red": [], "watch": []},
                    "funding": None, "sentiment": None, "fit": None, "gaps": [],
                })
            )
            mock_router_cls.return_value = mock_router

            fetch_llm_dossier(company="Stripe", retrieval_snippets=snippets)

            call_args = mock_router.generate.call_args
            user_prompt = call_args.kwargs["user_prompt"]
            # Both URLs must appear in the prompt
            assert "https://techcrunch.com/stripe-series-d" in user_prompt
            assert "https://glassdoor.com/stripe-reviews" in user_prompt
            # The anti-hallucination instruction must be present
            assert "MUST attach the corresponding URL" in user_prompt

    @patch("seeker_os.research.company_research.fetch_llm_dossier")
    @patch("seeker_os.research.company_research.fetch_wikidata_info")
    @patch("seeker_os.research.company_research.fetch_wikipedia_info")
    @patch("seeker_os.config.Settings")
    def test_stale_sentiment_flagged(
        self, mock_settings_cls, mock_wiki, mock_wikidata, mock_llm_dossier
    ):
        """Sentiment themes older than staleness_months must be flagged stale."""
        from seeker_os.config import CompanyResearchConfig
        from seeker_os.research.models import SentimentTheme

        mock_settings = MagicMock()
        mock_settings.company_research = CompanyResearchConfig(staleness_months=12)
        mock_settings_cls.return_value = mock_settings

        mock_wiki.return_value = None
        mock_wikidata.return_value = None
        mock_llm_dossier.return_value = CompanyResearchResult(
            company_name="TestCo",
            researched_at="2024-01-01T00:00:00Z",
            overall_confidence=0.6,
            summary="Test.",
            sentiment=SentimentDossier(
                overall_rating_estimate=4.0,
                confidence=0.5,
                positives=[
                    SentimentTheme(theme="good culture", age_months=6),
                ],
                negatives=[
                    SentimentTheme(theme="poor management", age_months=24),
                    SentimentTheme(theme="burnout", age_months=20),
                ],
            ),
        )

        result = research_company("TestCo")

        assert result.sentiment is not None
        assert result.sentiment.staleness_warning is not None
        assert "poor management" in result.sentiment.staleness_warning
        assert "burnout" in result.sentiment.staleness_warning
        # The 6-month-old positive should NOT be in the warning
        assert "good culture" not in result.sentiment.staleness_warning
        assert "12 months" in result.sentiment.staleness_warning

    @patch("seeker_os.research.company_research.fetch_llm_dossier")
    @patch("seeker_os.research.company_research.fetch_wikidata_info")
    @patch("seeker_os.research.company_research.fetch_wikipedia_info")
    @patch("seeker_os.config.Settings")
    def test_confidence_below_floor_marks_stub(
        self, mock_settings_cls, mock_wiki, mock_wikidata, mock_llm_dossier
    ):
        """When overall_confidence < confidence_floor, is_stub must be True."""
        from seeker_os.config import CompanyResearchConfig

        mock_settings = MagicMock()
        mock_settings.company_research = CompanyResearchConfig(confidence_floor=0.4)
        mock_settings_cls.return_value = mock_settings

        mock_wiki.return_value = None
        mock_wikidata.return_value = None
        mock_llm_dossier.return_value = CompanyResearchResult(
            company_name="SmallCo",
            researched_at="2024-01-01T00:00:00Z",
            overall_confidence=0.2,
            summary="Very little data available.",
        )

        result = research_company("SmallCo")

        assert result.is_stub is True
        assert result.overall_confidence < 0.4

    @patch("seeker_os.research.company_research.fetch_llm_dossier")
    @patch("seeker_os.research.company_research.fetch_wikidata_info")
    @patch("seeker_os.research.company_research.fetch_wikipedia_info")
    @patch("seeker_os.config.Settings")
    def test_confidence_above_floor_not_stub(
        self, mock_settings_cls, mock_wiki, mock_wikidata, mock_llm_dossier
    ):
        """When overall_confidence >= confidence_floor, is_stub must be False."""
        from seeker_os.config import CompanyResearchConfig

        mock_settings = MagicMock()
        mock_settings.company_research = CompanyResearchConfig(confidence_floor=0.3)
        mock_settings_cls.return_value = mock_settings

        mock_wiki.return_value = None
        mock_wikidata.return_value = None
        mock_llm_dossier.return_value = CompanyResearchResult(
            company_name="GoodCo",
            researched_at="2024-01-01T00:00:00Z",
            overall_confidence=0.75,
            summary="Well-sourced dossier.",
        )

        result = research_company("GoodCo")

        assert result.is_stub is False

    @patch("seeker_os.research.company_research.fetch_llm_dossier")
    @patch("seeker_os.research.company_research.fetch_wikidata_info")
    @patch("seeker_os.research.company_research.fetch_wikipedia_info")
    @patch("seeker_os.config.Settings")
    def test_no_retrieval_provider_matches_pre_phase3(
        self, mock_settings_cls, mock_wiki, mock_wikidata, mock_llm_dossier
    ):
        """When no retrieval provider is configured, behavior matches pre-Phase-3."""
        from seeker_os.config import CompanyResearchConfig

        mock_settings = MagicMock()
        # No retrieval type configured
        mock_settings.company_research = CompanyResearchConfig()
        mock_settings_cls.return_value = mock_settings

        mock_wiki.return_value = WikipediaInfo(title="Test", extract="Test extract")
        mock_wikidata.return_value = None
        mock_llm_dossier.return_value = CompanyResearchResult(
            company_name="TestCo",
            researched_at="2024-01-01T00:00:00Z",
            overall_confidence=0.6,
            summary="Test.",
        )

        result = research_company("TestCo")

        # No retrieval should have been used
        assert result.retrieval_used is False
        assert "retrieval" not in result.sources_used
        assert result.retrieval_sources == []
        # The LLM call should NOT have received retrieval snippets
        call_args = mock_llm_dossier.call_args
        assert call_args.kwargs.get("retrieval_snippets") is None

    @patch("seeker_os.research.company_research.fetch_llm_dossier")
    @patch("seeker_os.research.company_research.fetch_wikidata_info")
    @patch("seeker_os.research.company_research.fetch_wikipedia_info")
    @patch("seeker_os.config.Settings")
    def test_retrieval_snippets_passed_to_llm_and_urls_in_sources(
        self, mock_settings_cls, mock_wiki, mock_wikidata, mock_llm_dossier
    ):
        """When retrieval adapter is configured, snippets are fetched and URLs appear in sources."""
        from seeker_os.config import CompanyResearchConfig, RetrievalProviderConfig
        from seeker_os.research.retrieval.models import RetrievalSnippet

        mock_settings = MagicMock()
        mock_settings.company_research = CompanyResearchConfig(
            retrieval=RetrievalProviderConfig(type="tavily", api_key="fake-key"),
        )
        mock_settings_cls.return_value = mock_settings

        mock_wiki.return_value = None
        mock_wikidata.return_value = None
        mock_llm_dossier.return_value = CompanyResearchResult(
            company_name="Stripe",
            researched_at="2024-01-01T00:00:00Z",
            overall_confidence=0.7,
            summary="Test.",
        )

        mock_adapter = MagicMock()
        mock_adapter.search.return_value = [
            RetrievalSnippet(
                title="Stripe Series D",
                url="https://techcrunch.com/stripe-series-d",
                snippet="Stripe raised $6.5B.",
                source_domain="techcrunch.com",
            ),
        ]

        with patch(
            "seeker_os.research.retrieval.registry.build_retrieval_adapter",
            return_value=mock_adapter,
        ):
            result = research_company("Stripe")

        # Retrieval was used
        assert result.retrieval_used is True
        assert "retrieval" in result.sources_used
        # The retrieval URL is in retrieval_sources
        assert any(
            "techcrunch.com/stripe-series-d" in src.url
            for src in result.retrieval_sources
        )
        # The LLM was called with retrieval snippets
        call_args = mock_llm_dossier.call_args
        snippets_arg = call_args.kwargs.get("retrieval_snippets")
        assert snippets_arg is not None
        assert len(snippets_arg) >= 1
        assert snippets_arg[0].url == "https://techcrunch.com/stripe-series-d"

    def test_tavily_adapter_search_returns_snippets_with_urls(self):
        """TavilyAdapter.search should parse API response into RetrievalSnippets with URLs."""
        from seeker_os.research.retrieval.tavily import TavilyAdapter

        adapter = TavilyAdapter(api_key="fake-key")

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {
                    "title": "Stripe raises $6.5B",
                    "url": "https://techcrunch.com/stripe-raises",
                    "content": "Stripe raised $6.5 billion in Series D.",
                    "score": 0.95,
                },
                {
                    "title": "No URL result",
                    "url": "",
                    "content": "Should be skipped.",
                },
            ]
        }

        with patch("seeker_os.research.retrieval.tavily.httpx.post", return_value=mock_response):
            snippets = adapter.search("Stripe funding")

        assert len(snippets) == 1
        assert snippets[0].url == "https://techcrunch.com/stripe-raises"
        assert snippets[0].source_domain == "techcrunch.com"
        assert snippets[0].title == "Stripe raises $6.5B"
        assert snippets[0].score == 0.95

    def test_tavily_adapter_no_key_returns_empty(self):
        """TavilyAdapter with no API key should return empty results, not crash."""
        from seeker_os.research.retrieval.tavily import TavilyAdapter

        adapter = TavilyAdapter(api_key="")
        snippets = adapter.search("test query")
        assert snippets == []

    def test_build_retrieval_adapter_unknown_type_returns_none(self):
        """Unknown adapter type should return None with a warning."""
        from seeker_os.research.retrieval.registry import build_retrieval_adapter

        result = build_retrieval_adapter({"type": "unknown_provider", "api_key": "x"})
        assert result is None

    def test_build_retrieval_adapter_no_key_returns_none(self):
        """Adapter with no API key should return None."""
        from seeker_os.research.retrieval.registry import build_retrieval_adapter

        result = build_retrieval_adapter({"type": "tavily", "api_key": ""})
        assert result is None

    def test_build_retrieval_adapter_tavily(self):
        """Valid Tavily config should build a TavilyAdapter."""
        from seeker_os.research.retrieval.registry import build_retrieval_adapter
        from seeker_os.research.retrieval.tavily import TavilyAdapter

        result = build_retrieval_adapter({"type": "tavily", "api_key": "test-key"})
        assert result is not None
        assert isinstance(result, TavilyAdapter)


class TestSourceTrustOrderRanking:
    """Tests for source_trust_order — ranking only, no filtering or inflation."""

    def test_rank_sources_by_trust_basic(self):
        """Sources from trusted domains sort first, unlisted last, stable."""
        from seeker_os.research.company_research import _rank_sources_by_trust

        sources = [
            SourceRef(url="https://random-blog.com/post", retrieved="2024-01-01"),
            SourceRef(url="https://techcrunch.com/stripe-series-d", retrieved="2024-01-01"),
            SourceRef(url="https://crunchbase.com/org/stripe", retrieved="2024-01-01"),
            SourceRef(url="https://other-site.com/page", retrieved="2024-01-01"),
        ]
        trust_order = ["crunchbase.com", "techcrunch.com"]

        ranked = _rank_sources_by_trust(sources, trust_order)

        # crunchbase first, techcrunch second, then unlisted in original order
        assert ranked[0].url == "https://crunchbase.com/org/stripe"
        assert ranked[1].url == "https://techcrunch.com/stripe-series-d"
        assert ranked[2].url == "https://random-blog.com/post"
        assert ranked[3].url == "https://other-site.com/page"

    def test_rank_sources_subdomain_tolerant(self):
        """Subdomain URLs match their parent domain in trust order."""
        from seeker_os.research.company_research import _rank_sources_by_trust

        sources = [
            SourceRef(url="https://news.crunchbase.com/article", retrieved="2024-01-01"),
            SourceRef(url="https://blog.example.com/post", retrieved="2024-01-01"),
        ]
        trust_order = ["crunchbase.com"]

        ranked = _rank_sources_by_trust(sources, trust_order)

        assert ranked[0].url == "https://news.crunchbase.com/article"
        assert ranked[1].url == "https://blog.example.com/post"

    def test_rank_sources_case_insensitive(self):
        """Domain matching is case-insensitive."""
        from seeker_os.research.company_research import _rank_sources_by_trust

        sources = [
            SourceRef(url="https://TechCrunch.com/article", retrieved="2024-01-01"),
            SourceRef(url="https://other.com/page", retrieved="2024-01-01"),
        ]
        trust_order = ["techcrunch.com"]

        ranked = _rank_sources_by_trust(sources, trust_order)

        assert ranked[0].url == "https://TechCrunch.com/article"

    def test_rank_sources_empty_trust_order_no_change(self):
        """Empty trust_order returns sources unchanged (no reordering)."""
        from seeker_os.research.company_research import _rank_sources_by_trust

        sources = [
            SourceRef(url="https://z.com", retrieved="2024-01-01"),
            SourceRef(url="https://a.com", retrieved="2024-01-01"),
        ]

        ranked = _rank_sources_by_trust(sources, [])
        assert ranked == sources  # same order, same items

    def test_rank_sources_nothing_added_or_removed(self):
        """Ranking must not add or remove any sources — ordering only."""
        from seeker_os.research.company_research import _rank_sources_by_trust

        sources = [
            SourceRef(url="https://a.com/1", retrieved="2024-01-01"),
            SourceRef(url="https://b.com/2", retrieved="2024-01-01"),
            SourceRef(url="https://c.com/3", retrieved="2024-01-01"),
            SourceRef(url="https://d.com/4", retrieved="2024-01-01"),
        ]
        trust_order = ["b.com", "d.com"]

        ranked = _rank_sources_by_trust(sources, trust_order)

        assert len(ranked) == len(sources)
        original_urls = {s.url for s in sources}
        ranked_urls = {s.url for s in ranked}
        assert original_urls == ranked_urls

    @patch("seeker_os.research.company_research.fetch_llm_dossier")
    @patch("seeker_os.research.company_research.fetch_wikidata_info")
    @patch("seeker_os.research.company_research.fetch_wikipedia_info")
    @patch("seeker_os.config.Settings")
    def test_retrieval_sources_ranked_in_research_company(
        self, mock_settings_cls, mock_wiki, mock_wikidata, mock_llm_dossier
    ):
        """research_company should rank retrieval_sources by trust order end-to-end."""
        from seeker_os.config import CompanyResearchConfig, RetrievalProviderConfig
        from seeker_os.research.retrieval.models import RetrievalSnippet

        mock_settings = MagicMock()
        mock_settings.company_research = CompanyResearchConfig(
            retrieval=RetrievalProviderConfig(type="tavily", api_key="fake-key"),
            source_trust_order=["crunchbase.com", "techcrunch.com"],
        )
        mock_settings_cls.return_value = mock_settings

        mock_wiki.return_value = None
        mock_wikidata.return_value = None
        mock_llm_dossier.return_value = CompanyResearchResult(
            company_name="Stripe",
            researched_at="2024-01-01T00:00:00Z",
            overall_confidence=0.7,
            summary="Test.",
        )

        mock_adapter = MagicMock()
        mock_adapter.search.return_value = [
            RetrievalSnippet(
                title="Random blog post",
                url="https://random-blog.com/stripe",
                snippet="Stripe is a company.",
                source_domain="random-blog.com",
            ),
            RetrievalSnippet(
                title="Stripe Series D",
                url="https://techcrunch.com/stripe-series-d",
                snippet="Stripe raised $6.5B.",
                source_domain="techcrunch.com",
            ),
            RetrievalSnippet(
                title="Stripe profile",
                url="https://crunchbase.com/org/stripe",
                snippet="Stripe company profile.",
                source_domain="crunchbase.com",
            ),
        ]

        with patch(
            "seeker_os.research.retrieval.registry.build_retrieval_adapter",
            return_value=mock_adapter,
        ):
            result = research_company("Stripe")

        # Mock returns 3 snippets per call, 2 calls = 6 total (duplicates)
        # After trust ranking: crunchbase first, techcrunch second, random-blog last
        urls = [src.url for src in result.retrieval_sources]
        assert len(urls) == 6
        # First two should be crunchbase (rank 0), next two techcrunch (rank 1), last two random-blog
        assert urls[0] == "https://crunchbase.com/org/stripe"
        assert urls[1] == "https://crunchbase.com/org/stripe"
        assert urls[2] == "https://techcrunch.com/stripe-series-d"
        assert urls[3] == "https://techcrunch.com/stripe-series-d"
        assert urls[4] == "https://random-blog.com/stripe"
        assert urls[5] == "https://random-blog.com/stripe"


class TestQueryTemplatesFromConfig:
    """Tests for config-driven retrieval query templates."""

    @patch("seeker_os.research.company_research.fetch_llm_dossier")
    @patch("seeker_os.research.company_research.fetch_wikidata_info")
    @patch("seeker_os.research.company_research.fetch_wikipedia_info")
    @patch("seeker_os.config.Settings")
    def test_custom_funding_query_template_sent_to_adapter(
        self, mock_settings_cls, mock_wiki, mock_wikidata, mock_llm_dossier
    ):
        """A custom funding_query_template in config is the query sent to the adapter."""
        from seeker_os.config import CompanyResearchConfig, RetrievalProviderConfig

        mock_settings = MagicMock()
        mock_settings.company_research = CompanyResearchConfig(
            retrieval=RetrievalProviderConfig(
                type="tavily",
                api_key="fake-key",
                funding_query_template="{company} Y Combinator seed funding",
                sentiment_query_template="{company} employee reviews culture",
            ),
        )
        mock_settings_cls.return_value = mock_settings

        mock_wiki.return_value = None
        mock_wikidata.return_value = None
        mock_llm_dossier.return_value = CompanyResearchResult(
            company_name="Rally",
            researched_at="2024-01-01T00:00:00Z",
            overall_confidence=0.7,
            summary="Test.",
        )

        mock_adapter = MagicMock()
        mock_adapter.search.return_value = []

        with patch(
            "seeker_os.research.retrieval.registry.build_retrieval_adapter",
            return_value=mock_adapter,
        ):
            research_company("Rally")

        # The first search call should use the custom funding template
        first_call_args = mock_adapter.search.call_args_list[0]
        first_query = first_call_args.args[0]
        assert first_query == "Rally Y Combinator seed funding"

        # The second search call should use the custom sentiment template
        second_call_args = mock_adapter.search.call_args_list[1]
        second_query = second_call_args.args[0]
        assert second_query == "Rally employee reviews culture"

    @patch("seeker_os.research.company_research.fetch_llm_dossier")
    @patch("seeker_os.research.company_research.fetch_wikidata_info")
    @patch("seeker_os.research.company_research.fetch_wikipedia_info")
    @patch("seeker_os.config.Settings")
    def test_default_query_templates_when_config_absent(
        self, mock_settings_cls, mock_wiki, mock_wikidata, mock_llm_dossier
    ):
        """When query templates are not in config, defaults are used."""
        from seeker_os.config import CompanyResearchConfig, RetrievalProviderConfig

        mock_settings = MagicMock()
        mock_settings.company_research = CompanyResearchConfig(
            retrieval=RetrievalProviderConfig(type="tavily", api_key="fake-key"),
        )
        mock_settings_cls.return_value = mock_settings

        mock_wiki.return_value = None
        mock_wikidata.return_value = None
        mock_llm_dossier.return_value = CompanyResearchResult(
            company_name="Stripe",
            researched_at="2024-01-01T00:00:00Z",
            overall_confidence=0.7,
            summary="Test.",
        )

        mock_adapter = MagicMock()
        mock_adapter.search.return_value = []

        with patch(
            "seeker_os.research.retrieval.registry.build_retrieval_adapter",
            return_value=mock_adapter,
        ):
            research_company("Stripe")

        first_call_args = mock_adapter.search.call_args_list[0]
        first_query = first_call_args.args[0]
        assert first_query == "Stripe funding round investors valuation"

        second_call_args = mock_adapter.search.call_args_list[1]
        second_query = second_call_args.args[0]
        assert second_query == "Stripe employee reviews sentiment glassdoor culture"

    def test_query_template_without_company_placeholder(self):
        """A template without {company} should be used as-is without crashing."""
        from seeker_os.research.company_research import _run_retrieval_queries
        from seeker_os.research.retrieval.models import RetrievalSnippet

        mock_adapter = MagicMock()
        mock_adapter.search.return_value = []

        _run_retrieval_queries(
            mock_adapter,
            company="Rally",
            funding_query_template="latest startup funding news",
            sentiment_query_template="startup employee sentiment",
        )

        first_call_args = mock_adapter.search.call_args_list[0]
        assert first_call_args.args[0] == "latest startup funding news"


class TestUserAgent:
    """Tests for de-personalized, configurable User-Agent (per-call, no global mutation)."""

    def test_default_user_agent_has_no_personal_handle(self):
        """The default User-Agent must not contain a personal GitHub handle."""
        from seeker_os.research.company_research import _build_headers, _DEFAULT_USER_AGENT
        ua = _build_headers(None)["User-Agent"]
        assert ua == _DEFAULT_USER_AGENT
        assert "github.com/" not in ua.lower()

    def test_config_user_agent_used_in_headers(self, tmp_path, monkeypatch):
        """company_research.yml user_agent should appear in per-call headers."""
        import shutil
        import yaml
        from seeker_os.config import CONFIG_DIR, CompanyResearchConfig

        test_config = tmp_path / "config"
        test_config.mkdir()
        for f in CONFIG_DIR.iterdir():
            if f.is_file():
                shutil.copy(f, test_config / f.name)

        custom_ua = "MyProduct/1.0 (contact: ops@mycompany.com)"
        (test_config / "company_research.yml").write_text(
            yaml.dump({
                "user_agent": custom_ua,
                "confidence_floor": 0.3,
                "staleness_months": 18,
            }, default_flow_style=False),
            encoding="utf-8",
        )

        monkeypatch.setattr("seeker_os.config.CONFIG_DIR", test_config)

        from seeker_os.config import Settings
        settings = Settings()
        cr_config = settings.company_research

        from seeker_os.research.company_research import _build_headers
        headers = _build_headers(cr_config)
        assert headers["User-Agent"] == custom_ua
        assert "github.com/" not in headers["User-Agent"].lower()

    def test_config_model_default_has_no_personal_handle(self):
        """CompanyResearchConfig default user_agent must not contain personal handles."""
        from seeker_os.config import CompanyResearchConfig
        cfg = CompanyResearchConfig()
        assert "github.com/" not in cfg.user_agent.lower()

    def test_no_ua_leak_across_calls(self, tmp_path, monkeypatch):
        """Two research_company calls with different configs must not leak UA.

        Call 1: config with user_agent='UA-ONE' → Wikipedia request uses 'UA-ONE'.
        Call 2: config with NO user_agent → Wikipedia request falls back to default,
                NOT 'UA-ONE' leaking forward.
        """
        import shutil
        import yaml
        from seeker_os.config import CONFIG_DIR

        # --- Config 1: custom user_agent ---
        test_config_1 = tmp_path / "config1"
        test_config_1.mkdir()
        for f in CONFIG_DIR.iterdir():
            if f.is_file():
                shutil.copy(f, test_config_1 / f.name)
        (test_config_1 / "company_research.yml").write_text(
            yaml.dump({
                "user_agent": "UA-ONE",
                "confidence_floor": 0.3,
                "staleness_months": 18,
            }, default_flow_style=False),
            encoding="utf-8",
        )

        # --- Config 2: no user_agent (default) ---
        test_config_2 = tmp_path / "config2"
        test_config_2.mkdir()
        for f in CONFIG_DIR.iterdir():
            if f.is_file():
                shutil.copy(f, test_config_2 / f.name)
        (test_config_2 / "company_research.yml").write_text(
            yaml.dump({
                "confidence_floor": 0.3,
                "staleness_months": 18,
            }, default_flow_style=False),
            encoding="utf-8",
        )

        from seeker_os.research.company_research import (
            research_company,
            _DEFAULT_USER_AGENT,
        )

        # --- Call 1: config with UA-ONE ---
        monkeypatch.setattr("seeker_os.config.CONFIG_DIR", test_config_1)
        captured_headers_1: list[dict] = []

        def capture_get_1(url, **kwargs):
            captured_headers_1.append(kwargs.get("headers", {}))
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"query": {"search": []}}
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

        with patch("seeker_os.research.company_research.httpx.get", side_effect=capture_get_1), \
             patch("seeker_os.research.company_research.fetch_llm_dossier", return_value=None):
            research_company("CompanyOne")

        # --- Call 2: config with NO user_agent (default) ---
        monkeypatch.setattr("seeker_os.config.CONFIG_DIR", test_config_2)
        captured_headers_2: list[dict] = []

        def capture_get_2(url, **kwargs):
            captured_headers_2.append(kwargs.get("headers", {}))
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"query": {"search": []}}
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

        with patch("seeker_os.research.company_research.httpx.get", side_effect=capture_get_2), \
             patch("seeker_os.research.company_research.fetch_llm_dossier", return_value=None):
            research_company("CompanyTwo")

        # Assert call 1 used UA-ONE
        assert any(h.get("User-Agent") == "UA-ONE" for h in captured_headers_1), \
            f"Call 1 should use UA-ONE, got: {[h.get('User-Agent') for h in captured_headers_1]}"

        # Assert call 2 fell back to default — NOT UA-ONE leaking forward
        assert any(h.get("User-Agent") == _DEFAULT_USER_AGENT for h in captured_headers_2), \
            f"Call 2 should use default UA, got: {[h.get('User-Agent') for h in captured_headers_2]}"
        assert not any(h.get("User-Agent") == "UA-ONE" for h in captured_headers_2), \
            "UA-ONE leaked forward into call 2 — global mutation bug!"
