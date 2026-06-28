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
    VerificationState,
    WikipediaInfo,
)
from seeker_os.research.retrieval.models import RetrievalSnippet
from seeker_os.research.company_research import (
    fetch_wikipedia_info,
    fetch_wikidata_info,
    fetch_llm_dossier,
    research_company,
    _domains_match,
    _extract_host,
    _is_generic_host,
)


class TestDomainMatching:
    """Tests for domain extraction and matching helpers."""

    def test_extract_host_strips_www(self):
        assert _extract_host("https://www.acme.com/page") == "acme.com"

    def test_extract_host_bare_domain(self):
        assert _extract_host("https://acme.com") == "acme.com"

    def test_extract_host_subdomain(self):
        assert _extract_host("https://news.acme.com/article") == "news.acme.com"

    def test_extract_host_none(self):
        assert _extract_host("") is None
        assert _extract_host("not-a-url") is None  # no scheme → empty netloc

    def test_domains_match_exact(self):
        assert _domains_match("https://acme.com", "https://acme.com") is True

    def test_domains_match_www_vs_bare(self):
        assert _domains_match("https://www.acme.com", "https://acme.com") is True

    def test_domains_match_subdomain(self):
        assert _domains_match("https://news.acme.com", "https://acme.com") is True

    def test_domains_match_different_tld(self):
        assert _domains_match("https://acme.com", "https://acme.io") is False

    def test_domains_match_none_input(self):
        assert _domains_match(None, "https://acme.com") is False
        assert _domains_match("https://acme.com", None) is False

    def test_is_generic_host_shared_platforms(self):
        assert _is_generic_host("acme.notion.site") is True
        assert _is_generic_host("acme.webflow.io") is True
        assert _is_generic_host("acme.github.io") is True
        assert _is_generic_host("blog.medium.com") is True

    def test_is_generic_host_real_domain(self):
        assert _is_generic_host("acme.com") is False
        assert _is_generic_host("stripe.com") is False
        assert _is_generic_host("news.acme.com") is False

    def test_is_generic_host_none(self):
        assert _is_generic_host(None) is True


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
                        "P856": [{"mainsnak": {"datavalue": {"value": "https://stripe.com"}}}],
                    }
                }
            }
        }

        mock_get.side_effect = [id_response, entity_response]

        dossier, official_website = fetch_wikidata_info("Stripe", wikipedia_title="Stripe, Inc.")
        assert dossier is not None
        assert dossier.founded == 2010
        assert dossier.headcount == "2500"
        assert dossier.confidence == 0.6
        assert len(dossier.sources) == 1
        assert "wikidata.org" in dossier.sources[0].url
        assert official_website == "https://stripe.com"

    @patch("seeker_os.research.company_research.httpx.get")
    def test_fetch_wikidata_no_item_id(self, mock_get):
        """Should return None when no Wikidata item is found."""
        id_response = MagicMock()
        id_response.status_code = 200
        id_response.json.return_value = {"query": {"pages": {"1": {"pageprops": {}}}}}
        id_response.raise_for_status = MagicMock()

        mock_get.return_value = id_response

        dossier, official_website = fetch_wikidata_info("Unknown", wikipedia_title="Unknown")
        assert dossier is None
        assert official_website is None

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

        dossier, official_website = fetch_wikidata_info("Test", wikipedia_title="Test")
        assert dossier is None
        assert official_website is None


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
        mock_wikidata.return_value = (
            FundingDossier(
                founded=2010,
                headcount="2500",
                confidence=0.6,
                sources=[SourceRef(url="https://www.wikidata.org/wiki/Q7624104", retrieved="2024-01-01T00:00:00Z")],
            ),
            "https://stripe.com",
        )
        mock_llm_dossier.return_value = None

        result = research_company("Stripe", company_homepage="https://stripe.com")

        assert result.company_name == "Stripe"
        assert result.company_homepage == "https://stripe.com"
        assert result.wikipedia is not None
        assert result.funding is not None
        assert result.funding.founded == 2010
        assert result.funding.headcount == "2500"
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
        mock_wikidata.return_value = (
            FundingDossier(
                founded=2010,
                headcount="2500",
                confidence=0.6,
                sources=[SourceRef(url="https://www.wikidata.org/wiki/Q7624104", retrieved="2024-01-01T00:00:00Z")],
            ),
            "https://stripe.com",
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
                headcount="7000",
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
        mock_wikidata.return_value = (None, None)
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
    @patch("seeker_os.config.Settings")
    def test_no_sources(self, mock_settings_cls, mock_wiki, mock_wikidata, mock_llm_dossier):
        """Should return result with no data when all sources fail."""
        from seeker_os.config import CompanyResearchConfig

        mock_settings = MagicMock()
        mock_settings.company_research = CompanyResearchConfig()  # no retrieval
        mock_settings_cls.return_value = mock_settings

        mock_wiki.return_value = None
        mock_wikidata.return_value = (None, None)
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
        mock_wikidata.return_value = (None, None)

        result = research_company("Test", enable_llm=False)

        assert result.sentiment is None
        assert "llm_dossier" not in result.sources_used
        mock_llm_dossier.assert_not_called()

    @patch("seeker_os.research.company_research.fetch_llm_dossier")
    @patch("seeker_os.research.company_research.fetch_wikidata_info")
    @patch("seeker_os.research.company_research.fetch_wikipedia_info")
    def test_entity_disambiguation_domain_match(self, mock_wiki, mock_wikidata, mock_llm_dossier):
        """When P856 matches company_homepage, Wikipedia/Wikidata data is trusted."""
        mock_wiki.return_value = WikipediaInfo(
            title="Stripe, Inc.",
            extract="Stripe is a payment processing company.",
        )
        mock_wikidata.return_value = (
            FundingDossier(
                founded=2010,
                headcount="2500",
                confidence=0.6,
                sources=[SourceRef(url="https://www.wikidata.org/wiki/Q1", retrieved="2024-01-01")],
            ),
            "https://stripe.com",
        )
        mock_llm_dossier.return_value = None

        result = research_company("Stripe", company_homepage="https://stripe.com")

        assert result.wikipedia is not None
        assert result.funding is not None
        assert result.funding.founded == 2010
        assert "wikipedia" in result.sources_used
        assert "wikidata" in result.sources_used
        assert not any("domain mismatch" in g for g in result.gaps)

    @patch("seeker_os.research.company_research.fetch_llm_dossier")
    @patch("seeker_os.research.company_research.fetch_wikidata_info")
    @patch("seeker_os.research.company_research.fetch_wikipedia_info")
    def test_entity_disambiguation_domain_mismatch(self, mock_wiki, mock_wikidata, mock_llm_dossier):
        """When P856 does NOT match company_homepage, Wikipedia/Wikidata is discarded."""
        mock_wiki.return_value = WikipediaInfo(
            title="Evermore, Inc.",
            extract="Evermore is a gaming company.",
        )
        mock_wikidata.return_value = (
            FundingDossier(
                founded=2015,
                headcount="500",
                confidence=0.6,
                sources=[SourceRef(url="https://www.wikidata.org/wiki/Q2", retrieved="2024-01-01")],
            ),
            "https://evermore-gaming.com",
        )
        mock_llm_dossier.return_value = None

        result = research_company("Evermore", company_homepage="https://evermore-travel.com")

        assert result.wikipedia is None
        assert result.funding is None
        assert "wikipedia" not in result.sources_used
        assert "wikidata" not in result.sources_used
        assert any("domain mismatch" in g for g in result.gaps)

    @patch("seeker_os.research.company_research.fetch_llm_dossier")
    @patch("seeker_os.research.company_research.fetch_wikidata_info")
    @patch("seeker_os.research.company_research.fetch_wikipedia_info")
    def test_entity_disambiguation_no_p856(self, mock_wiki, mock_wikidata, mock_llm_dossier):
        """When P856 is absent but company_homepage is present, data is kept but unverified."""
        mock_wiki.return_value = WikipediaInfo(
            title="Acme Corp",
            extract="Acme makes widgets.",
        )
        mock_wikidata.return_value = (
            FundingDossier(
                founded=2010,
                headcount="100",
                confidence=0.6,
                sources=[SourceRef(url="https://www.wikidata.org/wiki/Q3", retrieved="2024-01-01")],
            ),
            None,  # no P856 on the entity
        )
        mock_llm_dossier.return_value = None

        result = research_company("Acme", company_homepage="https://acme.com")

        # Data is kept (can't verify, but can't disprove either)
        assert result.wikipedia is not None
        assert result.funding is not None
        assert "wikipedia" in result.sources_used
        assert "wikidata" in result.sources_used
        assert not any("domain mismatch" in g for g in result.gaps)

    @patch("seeker_os.research.company_research.fetch_llm_dossier")
    @patch("seeker_os.research.company_research.fetch_wikidata_info")
    @patch("seeker_os.research.company_research.fetch_wikipedia_info")
    def test_entity_disambiguation_no_company_domain(self, mock_wiki, mock_wikidata, mock_llm_dossier):
        """When company_homepage is absent (manual-add), name-only retrieval is kept."""
        mock_wiki.return_value = WikipediaInfo(
            title="Acme Corp",
            extract="Acme makes widgets.",
        )
        mock_wikidata.return_value = (
            FundingDossier(
                founded=2010,
                headcount="100",
                confidence=0.6,
                sources=[SourceRef(url="https://www.wikidata.org/wiki/Q4", retrieved="2024-01-01")],
            ),
            "https://acme.com",
        )
        mock_llm_dossier.return_value = None

        result = research_company("Acme")

        # No domain to verify against — data kept, unverified
        assert result.wikipedia is not None
        assert result.funding is not None
        assert "wikipedia" in result.sources_used
        assert "wikidata" in result.sources_used
        assert not any("domain mismatch" in g for g in result.gaps)

    @patch("seeker_os.research.company_research.fetch_llm_dossier")
    @patch("seeker_os.research.company_research.fetch_wikidata_info")
    @patch("seeker_os.research.company_research.fetch_wikipedia_info")
    def test_entity_disambiguation_subdomain_match(self, mock_wiki, mock_wikidata, mock_llm_dossier):
        """Subdomain of the same registrable domain should match (www vs bare)."""
        mock_wiki.return_value = WikipediaInfo(title="Acme", extract="Acme.")
        mock_wikidata.return_value = (
            FundingDossier(
                founded=2010,
                headcount="100",
                confidence=0.6,
                sources=[SourceRef(url="https://www.wikidata.org/wiki/Q5", retrieved="2024-01-01")],
            ),
            "https://www.acme.com",
        )
        mock_llm_dossier.return_value = None

        result = research_company("Acme", company_homepage="https://acme.com")

        assert result.wikipedia is not None
        assert result.funding is not None
        assert not any("domain mismatch" in g for g in result.gaps)


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
                headcount="7000",
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
        mock_wikidata.return_value = (None, None)
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
        mock_wikidata.return_value = (None, None)
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
        mock_wikidata.return_value = (None, None)
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
        mock_wikidata.return_value = (None, None)
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
        mock_wikidata.return_value = (None, None)
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
        ), patch("seeker_os.discovery.cache.DiskCache") as mock_cache_cls:
            mock_cache = MagicMock()
            mock_cache.get.return_value = None
            mock_cache_cls.return_value = mock_cache
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
        mock_wikidata.return_value = (None, None)
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
        ), patch("seeker_os.discovery.cache.DiskCache") as mock_cache_cls:
            mock_cache = MagicMock()
            mock_cache.get.return_value = None
            mock_cache_cls.return_value = mock_cache
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
        mock_wikidata.return_value = (None, None)
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
        ), patch("seeker_os.discovery.cache.DiskCache") as mock_cache_cls:
            mock_cache = MagicMock()
            mock_cache.get.return_value = None
            mock_cache_cls.return_value = mock_cache
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
        mock_wikidata.return_value = (None, None)
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
        ), patch("seeker_os.discovery.cache.DiskCache") as mock_cache_cls:
            mock_cache = MagicMock()
            mock_cache.get.return_value = None
            mock_cache_cls.return_value = mock_cache
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

        with patch("seeker_os.discovery.cache.DiskCache") as mock_cache_cls:
            mock_cache = MagicMock()
            mock_cache.get.return_value = None
            mock_cache_cls.return_value = mock_cache
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


class TestRetrievalQueryCaching:
    """Tests for disk caching of Tavily retrieval queries."""

    def test_cache_hit_avoids_adapter_call(self, tmp_path):
        """When a cached result exists, the adapter is not called."""
        from seeker_os.research.company_research import _run_retrieval_queries
        from seeker_os.research.retrieval.models import RetrievalSnippet

        # Pre-populate the cache with a known query result
        from seeker_os.discovery.cache import DiskCache
        cache = DiskCache(cache_dir=tmp_path / "retrieval_cache", ttl_hours=168)

        funding_query = "Stripe funding round investors valuation"
        sentiment_query = "Stripe employee reviews sentiment glassdoor culture"
        cached_snippets = [
            {"title": "Cached", "url": "https://example.com/cached",
             "snippet": "Cached snippet", "source_domain": "example.com", "score": 0.9},
        ]
        cache.set(funding_query, json.dumps(cached_snippets))
        cache.set(sentiment_query, json.dumps(cached_snippets))

        mock_adapter = MagicMock()
        mock_adapter.search.return_value = []

        with patch("seeker_os.discovery.cache.DiskCache") as mock_cache_cls:
            mock_cache_cls.return_value = cache
            result = _run_retrieval_queries(
                mock_adapter, "Stripe",
                cache_ttl_days=7,
                force_refresh=False,
            )

        # Adapter should NOT have been called — cache hit
        mock_adapter.search.assert_not_called()
        # Cached snippets should be returned
        assert len(result) == 2
        assert result[0].url == "https://example.com/cached"

    def test_force_refresh_bypasses_cache(self, tmp_path):
        """When force_refresh=True, the adapter is called even if cache exists."""
        from seeker_os.research.company_research import _run_retrieval_queries
        from seeker_os.discovery.cache import DiskCache

        cache = DiskCache(cache_dir=tmp_path / "retrieval_cache", ttl_hours=168)

        funding_query = "Stripe funding round investors valuation"
        sentiment_query = "Stripe employee reviews sentiment glassdoor culture"
        cache.set(funding_query, json.dumps([{"title": "Old", "url": "https://old.com",
                  "snippet": "Old", "source_domain": "old.com", "score": 0.5}]))

        fresh_snippet = RetrievalSnippet(
            title="Fresh", url="https://fresh.com",
            snippet="Fresh result", source_domain="fresh.com", score=0.95,
        )
        mock_adapter = MagicMock()
        mock_adapter.search.return_value = [fresh_snippet]

        with patch("seeker_os.discovery.cache.DiskCache") as mock_cache_cls:
            mock_cache_cls.return_value = cache
            result = _run_retrieval_queries(
                mock_adapter, "Stripe",
                cache_ttl_days=7,
                force_refresh=True,
            )

        # Adapter SHOULD have been called — force_refresh bypasses cache
        assert mock_adapter.search.call_count == 2
        # Fresh results returned, not cached
        assert all(r.url == "https://fresh.com" for r in result)

    def test_cache_miss_calls_adapter_and_stores(self, tmp_path):
        """When no cached result exists, the adapter is called and results are cached."""
        from seeker_os.research.company_research import _run_retrieval_queries
        from seeker_os.discovery.cache import DiskCache

        cache = DiskCache(cache_dir=tmp_path / "retrieval_cache", ttl_hours=168)

        fresh_snippet = RetrievalSnippet(
            title="Fresh", url="https://fresh.com",
            snippet="Fresh result", source_domain="fresh.com", score=0.95,
        )
        mock_adapter = MagicMock()
        mock_adapter.search.return_value = [fresh_snippet]

        with patch("seeker_os.discovery.cache.DiskCache") as mock_cache_cls:
            mock_cache_cls.return_value = cache
            _run_retrieval_queries(
                mock_adapter, "Stripe",
                cache_ttl_days=7,
                force_refresh=False,
            )

        # Adapter was called for both queries
        assert mock_adapter.search.call_count == 2
        # Results should now be in the cache
        funding_query = "Stripe funding round investors valuation"
        cached = cache.get(funding_query)
        assert cached is not None
        cached_data = json.loads(cached)
        assert cached_data[0]["url"] == "https://fresh.com"


class TestPhase2DomainScoping:
    """Tests for Tavily domain-scoping in retrieval queries."""

    @patch("seeker_os.research.company_research.fetch_llm_dossier")
    @patch("seeker_os.research.company_research.fetch_wikidata_info")
    @patch("seeker_os.research.company_research.fetch_wikipedia_info")
    @patch("seeker_os.config.Settings")
    def test_funding_query_gets_domain_appended(
        self, mock_settings_cls, mock_wiki, mock_wikidata, mock_llm_dossier
    ):
        """When company_domain is present, the funding query has the domain appended."""
        from seeker_os.config import CompanyResearchConfig, RetrievalProviderConfig

        mock_settings = MagicMock()
        mock_settings.company_research = CompanyResearchConfig(
            retrieval=RetrievalProviderConfig(type="tavily", api_key="fake-key"),
        )
        mock_settings_cls.return_value = mock_settings

        mock_wiki.return_value = None
        mock_wikidata.return_value = (None, None)
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
        ), patch("seeker_os.discovery.cache.DiskCache") as mock_cache_cls:
            mock_cache = MagicMock()
            mock_cache.get.return_value = None
            mock_cache_cls.return_value = mock_cache
            research_company("Stripe", company_homepage="https://stripe.com")

        # First call = funding query, should have domain appended
        first_call = mock_adapter.search.call_args_list[0]
        funding_query = first_call.args[0]
        assert "stripe.com" in funding_query
        assert "Stripe" in funding_query

    @patch("seeker_os.research.company_research.fetch_llm_dossier")
    @patch("seeker_os.research.company_research.fetch_wikidata_info")
    @patch("seeker_os.research.company_research.fetch_wikipedia_info")
    @patch("seeker_os.config.Settings")
    def test_sentiment_query_not_modified_by_domain(
        self, mock_settings_cls, mock_wiki, mock_wikidata, mock_llm_dossier
    ):
        """Sentiment query must NOT have the domain appended — preserves review recall."""
        from seeker_os.config import CompanyResearchConfig, RetrievalProviderConfig

        mock_settings = MagicMock()
        mock_settings.company_research = CompanyResearchConfig(
            retrieval=RetrievalProviderConfig(type="tavily", api_key="fake-key"),
        )
        mock_settings_cls.return_value = mock_settings

        mock_wiki.return_value = None
        mock_wikidata.return_value = (None, None)
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
        ), patch("seeker_os.discovery.cache.DiskCache") as mock_cache_cls:
            mock_cache = MagicMock()
            mock_cache.get.return_value = None
            mock_cache_cls.return_value = mock_cache
            research_company("Stripe", company_homepage="https://stripe.com")

        # Second call = sentiment query, should NOT have domain
        second_call = mock_adapter.search.call_args_list[1]
        sentiment_query = second_call.args[0]
        assert "stripe.com" not in sentiment_query
        assert "Stripe" in sentiment_query

    @patch("seeker_os.research.company_research.fetch_llm_dossier")
    @patch("seeker_os.research.company_research.fetch_wikidata_info")
    @patch("seeker_os.research.company_research.fetch_wikipedia_info")
    @patch("seeker_os.config.Settings")
    def test_domain_absent_no_query_modification(
        self, mock_settings_cls, mock_wiki, mock_wikidata, mock_llm_dossier
    ):
        """When company_domain is absent, neither query is modified."""
        from seeker_os.config import CompanyResearchConfig, RetrievalProviderConfig

        mock_settings = MagicMock()
        mock_settings.company_research = CompanyResearchConfig(
            retrieval=RetrievalProviderConfig(type="tavily", api_key="fake-key"),
        )
        mock_settings_cls.return_value = mock_settings

        mock_wiki.return_value = None
        mock_wikidata.return_value = (None, None)
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
        ), patch("seeker_os.discovery.cache.DiskCache") as mock_cache_cls:
            mock_cache = MagicMock()
            mock_cache.get.return_value = None
            mock_cache_cls.return_value = mock_cache
            research_company("Stripe")  # no company_homepage

        first_call = mock_adapter.search.call_args_list[0]
        funding_query = first_call.args[0]
        assert funding_query == "Stripe funding round investors valuation"

        second_call = mock_adapter.search.call_args_list[1]
        sentiment_query = second_call.args[0]
        assert sentiment_query == "Stripe employee reviews sentiment glassdoor culture"

    def test_tavily_adapter_passes_include_domains(self):
        """TavilyAdapter should pass include_domains to the API payload."""
        from seeker_os.research.retrieval.tavily import TavilyAdapter

        adapter = TavilyAdapter(api_key="fake-key")

        with patch("seeker_os.research.retrieval.tavily.httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {"results": []}
            mock_post.return_value = mock_resp

            adapter.search("test query", include_domains=["example.com"])

            call_args = mock_post.call_args
            payload = call_args.kwargs["json"]
            assert payload["include_domains"] == ["example.com"]

    def test_tavily_adapter_no_include_domains_omits_field(self):
        """TavilyAdapter should not include include_domains in payload when not provided."""
        from seeker_os.research.retrieval.tavily import TavilyAdapter

        adapter = TavilyAdapter(api_key="fake-key")

        with patch("seeker_os.research.retrieval.tavily.httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {"results": []}
            mock_post.return_value = mock_resp

            adapter.search("test query")

            call_args = mock_post.call_args
            payload = call_args.kwargs["json"]
            assert "include_domains" not in payload


class TestPhase3VerificationDegradation:
    """Integration tests proving entity_verified drives confidence and score."""

    @patch("seeker_os.research.company_research.fetch_llm_dossier")
    @patch("seeker_os.research.company_research.fetch_wikidata_info")
    @patch("seeker_os.research.company_research.fetch_wikipedia_info")
    @patch("seeker_os.config.Settings")
    def test_mismatch_degrades_confidence_below_modifier_threshold(
        self, mock_settings_cls, mock_wiki, mock_wikidata, mock_llm_dossier
    ):
        """Score-8 bug: ambiguous name + mismatched domain → research discarded,
        confidence degraded, modifiers don't fire."""
        from seeker_os.config import CompanyResearchConfig

        mock_settings = MagicMock()
        mock_settings.company_research = CompanyResearchConfig(
            mismatch_confidence=0.2,
            confidence_floor=0.3,
        )
        mock_settings_cls.return_value = mock_settings

        mock_wiki.return_value = WikipediaInfo(
            title="Evermore, Inc.",
            extract="Evermore is a gaming company.",
        )
        mock_wikidata.return_value = (
            FundingDossier(
                founded=2015,
                headcount="500",
                confidence=0.6,
                sources=[SourceRef(url="https://www.wikidata.org/wiki/Q2", retrieved="2024-01-01")],
            ),
            "https://evermore-gaming.com",  # P856 mismatch
        )
        # LLM returns high-confidence dossier about the WRONG entity
        mock_llm_dossier.return_value = CompanyResearchResult(
            company_name="Evermore",
            researched_at="2024-01-01T00:00:00Z",
            overall_confidence=0.85,
            summary="Large enterprise, 5000 employees, healthy runway.",
            funding=FundingDossier(
                founded=2015,
                headcount="5000",
                stage="Series D",
                financial_health="healthy",
                confidence=0.8,
            ),
            sentiment=SentimentDossier(
                overall_rating_estimate=4.2,
                confidence=0.7,
            ),
            fit=FitDossier(
                size_bucket="large enterprise",
                confidence=0.6,
            ),
        )

        result = research_company("Evermore", company_homepage="https://evermore-travel.com")

        # Wikipedia/Wikidata discarded
        assert result.wikipedia is None
        assert "wikipedia" not in result.sources_used
        assert "wikidata" not in result.sources_used
        # Section confidence degraded below 0.5 (modifier threshold)
        assert result.funding is not None
        assert result.funding.confidence <= 0.2
        assert result.sentiment is not None
        assert result.sentiment.confidence <= 0.2
        assert result.fit is not None
        assert result.fit.confidence <= 0.2
        # Overall confidence degraded → is_stub
        assert result.overall_confidence <= 0.2 + 1e-9  # float tolerance
        assert result.is_stub is True

    @patch("seeker_os.research.company_research.fetch_llm_dossier")
    @patch("seeker_os.research.company_research.fetch_wikidata_info")
    @patch("seeker_os.research.company_research.fetch_wikipedia_info")
    @patch("seeker_os.config.Settings")
    def test_matching_domain_scores_normally(
        self, mock_settings_cls, mock_wiki, mock_wikidata, mock_llm_dossier
    ):
        """Mirror test: matching domain → no degradation, research applies normally."""
        from seeker_os.config import CompanyResearchConfig

        mock_settings = MagicMock()
        mock_settings.company_research = CompanyResearchConfig(
            mismatch_confidence=0.2,
            confidence_floor=0.3,
        )
        mock_settings_cls.return_value = mock_settings

        mock_wiki.return_value = WikipediaInfo(
            title="Stripe, Inc.",
            extract="Stripe is a payment processing company.",
        )
        mock_wikidata.return_value = (
            FundingDossier(
                founded=2010,
                headcount="7000",
                confidence=0.6,
                sources=[SourceRef(url="https://www.wikidata.org/wiki/Q1", retrieved="2024-01-01")],
            ),
            "https://stripe.com",  # P856 match
        )
        mock_llm_dossier.return_value = CompanyResearchResult(
            company_name="Stripe",
            researched_at="2024-01-01T00:00:00Z",
            overall_confidence=0.85,
            summary="Series D fintech, healthy runway.",
            funding=FundingDossier(
                founded=2010,
                headcount="7000",
                stage="Series D",
                financial_health="healthy",
                confidence=0.8,
            ),
            sentiment=SentimentDossier(
                overall_rating_estimate=4.1,
                confidence=0.7,
            ),
            fit=FitDossier(
                size_bucket="large",
                confidence=0.6,
            ),
        )

        result = research_company("Stripe", company_homepage="https://stripe.com")

        # No degradation — confidence preserved
        assert result.funding is not None
        assert result.funding.confidence == 0.8  # unchanged
        assert result.sentiment is not None
        assert result.sentiment.confidence == 0.7  # unchanged
        assert result.fit is not None
        assert result.fit.confidence == 0.6  # unchanged
        assert result.is_stub is False

    @patch("seeker_os.research.company_research.fetch_llm_dossier")
    @patch("seeker_os.research.company_research.fetch_wikidata_info")
    @patch("seeker_os.research.company_research.fetch_wikipedia_info")
    @patch("seeker_os.config.Settings")
    def test_domain_absent_unverified_no_degradation(
        self, mock_settings_cls, mock_wiki, mock_wikidata, mock_llm_dossier
    ):
        """Domain absent (manual-add) → UNVERIFIED, small-company modifiers still allowed."""
        from seeker_os.config import CompanyResearchConfig

        mock_settings = MagicMock()
        mock_settings.company_research = CompanyResearchConfig(
            mismatch_confidence=0.2,
            confidence_floor=0.3,
        )
        mock_settings_cls.return_value = mock_settings

        mock_wiki.return_value = WikipediaInfo(
            title="SmallCo",
            extract="SmallCo makes widgets.",
        )
        mock_wikidata.return_value = (
            FundingDossier(
                founded=2018,
                headcount="50",
                confidence=0.6,
                sources=[SourceRef(url="https://www.wikidata.org/wiki/Q3", retrieved="2024-01-01")],
            ),
            None,  # no P856
        )
        mock_llm_dossier.return_value = CompanyResearchResult(
            company_name="SmallCo",
            researched_at="2024-01-01T00:00:00Z",
            overall_confidence=0.7,
            summary="Small startup, 50 employees.",
            funding=FundingDossier(
                founded=2018,
                headcount="50",
                stage="Seed",
                confidence=0.6,
            ),
            sentiment=SentimentDossier(
                overall_rating_estimate=4.0,
                confidence=0.5,
            ),
            fit=FitDossier(
                size_bucket="small startup",
                confidence=0.5,
            ),
        )

        result = research_company("SmallCo")  # no company_homepage

        # UNVERIFIED — no degradation, confidence preserved
        assert result.funding is not None
        assert result.funding.confidence == 0.6  # unchanged, above 0.5 threshold
        assert result.sentiment is not None
        assert result.sentiment.confidence == 0.5  # unchanged, at threshold
        assert result.fit is not None
        assert result.fit.confidence == 0.5  # unchanged
        assert result.is_stub is False
        # Modifiers CAN fire (confidence >= 0.5)

    @patch("seeker_os.research.company_research.fetch_llm_dossier")
    @patch("seeker_os.research.company_research.fetch_wikidata_info")
    @patch("seeker_os.research.company_research.fetch_wikipedia_info")
    @patch("seeker_os.config.Settings")
    def test_tavily_only_verification(
        self, mock_settings_cls, mock_wiki, mock_wikidata, mock_llm_dossier
    ):
        """Wikidata absent but Tavily returned snippets from company's domain → VERIFIED."""
        from seeker_os.config import CompanyResearchConfig, RetrievalProviderConfig

        mock_settings = MagicMock()
        mock_settings.company_research = CompanyResearchConfig(
            retrieval=RetrievalProviderConfig(type="tavily", api_key="fake-key"),
            mismatch_confidence=0.2,
        )
        mock_settings_cls.return_value = mock_settings

        mock_wiki.return_value = None
        mock_wikidata.return_value = (None, None)  # no Wikidata
        mock_llm_dossier.return_value = CompanyResearchResult(
            company_name="NewStartup",
            researched_at="2024-01-01T00:00:00Z",
            overall_confidence=0.7,
            summary="Early-stage startup.",
            funding=FundingDossier(
                founded=2023,
                headcount="20",
                confidence=0.6,
            ),
        )

        mock_adapter = MagicMock()
        mock_adapter.search.return_value = [
            RetrievalSnippet(
                title="NewStartup funding",
                url="https://newstartup.com/about",
                snippet="NewStartup raised seed.",
                source_domain="newstartup.com",
            ),
        ]

        with patch(
            "seeker_os.research.retrieval.registry.build_retrieval_adapter",
            return_value=mock_adapter,
        ), patch("seeker_os.discovery.cache.DiskCache") as mock_cache_cls:
            mock_cache = MagicMock()
            mock_cache.get.return_value = None
            mock_cache_cls.return_value = mock_cache
            result = research_company("NewStartup", company_homepage="https://newstartup.com")

        # Tavily snippet from newstartup.com → VERIFIED, no degradation
        assert result.funding is not None
        assert result.funding.confidence == 0.6  # unchanged
        assert result.is_stub is False

    @patch("seeker_os.research.company_research.fetch_llm_dossier")
    @patch("seeker_os.research.company_research.fetch_wikidata_info")
    @patch("seeker_os.research.company_research.fetch_wikipedia_info")
    @patch("seeker_os.config.Settings")
    def test_generic_host_not_appended_to_funding_query(
        self, mock_settings_cls, mock_wiki, mock_wikidata, mock_llm_dossier
    ):
        """A generic/shared-host homepage (e.g. *.webflow.io) should not inject
        a misleading domain token into the funding query."""
        from seeker_os.config import CompanyResearchConfig, RetrievalProviderConfig

        mock_settings = MagicMock()
        mock_settings.company_research = CompanyResearchConfig(
            retrieval=RetrievalProviderConfig(type="tavily", api_key="fake-key"),
        )
        mock_settings_cls.return_value = mock_settings

        mock_wiki.return_value = None
        mock_wikidata.return_value = (None, None)
        mock_llm_dossier.return_value = CompanyResearchResult(
            company_name="Acme",
            researched_at="2024-01-01T00:00:00Z",
            overall_confidence=0.7,
            summary="Test.",
        )

        mock_adapter = MagicMock()
        mock_adapter.search.return_value = []

        with patch(
            "seeker_os.research.retrieval.registry.build_retrieval_adapter",
            return_value=mock_adapter,
        ), patch("seeker_os.discovery.cache.DiskCache") as mock_cache_cls:
            mock_cache = MagicMock()
            mock_cache.get.return_value = None
            mock_cache_cls.return_value = mock_cache
            research_company("Acme", company_homepage="https://acme.webflow.io")

        # Funding query should NOT contain "webflow.io"
        first_call = mock_adapter.search.call_args_list[0]
        funding_query = first_call.args[0]
        assert "webflow.io" not in funding_query
        assert "Acme" in funding_query

    @patch("seeker_os.research.company_research.fetch_llm_dossier")
    @patch("seeker_os.research.company_research.fetch_wikidata_info")
    @patch("seeker_os.research.company_research.fetch_wikipedia_info")
    @patch("seeker_os.config.Settings")
    def test_mismatch_confidence_composition_arithmetic(
        self, mock_settings_cls, mock_wiki, mock_wikidata, mock_llm_dossier
    ):
        """Worst case: mismatch + zero-surviving-sources → one coherent bounded value.

        LLM returns funding.confidence=0.8.
        _verify_dossier_sources strips all URLs → 0.8 * 0.5 = 0.4.
        _apply_verification_degradation → min(0.4, 0.2) = 0.2.
        overall_confidence = mean(0.2, 0.2, 0.2) = 0.2.
        is_stub: 0.2 < 0.3 → True.
        Modifier gate: 0.2 < 0.5 → modifier skipped.

        Result: 0.2. One coherent number. Not 0.05 via three multiplications.
        """
        from seeker_os.config import CompanyResearchConfig

        mock_settings = MagicMock()
        mock_settings.company_research = CompanyResearchConfig(
            mismatch_confidence=0.2,
            confidence_floor=0.3,
        )
        mock_settings_cls.return_value = mock_settings

        mock_wiki.return_value = WikipediaInfo(
            title="AmbiguousCo",
            extract="AmbiguousCo is a company.",
        )
        mock_wikidata.return_value = (
            FundingDossier(
                founded=2010,
                headcount="1000",
                confidence=0.6,
                sources=[SourceRef(url="https://www.wikidata.org/wiki/Q9", retrieved="2024-01-01")],
            ),
            "https://wrong-entity.com",  # P856 mismatch
        )
        # LLM returns high-confidence dossier with sources that will be stripped
        # (URLs not in retrieval_snippets and not in extra_verified)
        mock_llm_dossier.return_value = CompanyResearchResult(
            company_name="AmbiguousCo",
            researched_at="2024-01-01T00:00:00Z",
            overall_confidence=0.9,
            summary="Large company.",
            funding=FundingDossier(
                founded=2010,
                headcount="5000",
                confidence=0.8,
                sources=[SourceRef(url="https://invented-url.com/fake", retrieved="2024-01-01")],
            ),
            sentiment=SentimentDossier(
                overall_rating_estimate=3.5,
                confidence=0.7,
                sources=[SourceRef(url="https://invented-url.com/fake2", retrieved="2024-01-01")],
            ),
            fit=FitDossier(
                size_bucket="large",
                confidence=0.6,
                sources=[SourceRef(url="https://invented-url.com/fake3", retrieved="2024-01-01")],
            ),
        )

        result = research_company("AmbiguousCo", company_homepage="https://right-entity.com")

        # All sections should be at exactly mismatch_confidence (0.2)
        assert result.funding is not None
        assert result.funding.confidence == 0.2
        assert result.sentiment is not None
        assert result.sentiment.confidence == 0.2
        assert result.fit is not None
        assert result.fit.confidence == 0.2
        # Overall = mean(0.2, 0.2, 0.2) = 0.2
        assert result.overall_confidence == pytest.approx(0.2)
        assert result.is_stub is True
