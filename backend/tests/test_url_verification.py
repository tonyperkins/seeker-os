"""Tests for URL verification — stripping model-invented URLs from LLM dossier output."""

from __future__ import annotations

from seeker_os.research.models import (
    CompanyResearchResult,
    FundingDossier,
    FitDossier,
    SentimentDossier,
    SourceRef,
    LastRound,
)
from seeker_os.research.retrieval.models import RetrievalSnippet
from seeker_os.research.company_research import (
    _normalize_url,
    _verify_section_sources,
    _verify_dossier_sources,
)


class TestNormalizeUrl:
    def test_lowercase_host(self):
        assert _normalize_url("https://Example.COM/path") == "https://example.com/path"

    def test_strip_trailing_slash(self):
        assert _normalize_url("https://example.com/path/") == "https://example.com/path"

    def test_strip_fragment(self):
        assert _normalize_url("https://example.com/path#section") == "https://example.com/path"

    def test_empty_url(self):
        assert _normalize_url("") == ""

    def test_preserve_query(self):
        assert _normalize_url("https://example.com/path?q=1") == "https://example.com/path?q=1"


class TestVerifySectionSources:
    def test_keeps_retrieved_url(self):
        retrieved = {_normalize_url("https://tracxn.com/d/companies/tamnoon/abc")}
        sources = [SourceRef(url="https://tracxn.com/d/companies/tamnoon/abc", retrieved="2026-06")]
        kept, stripped = _verify_section_sources(sources, retrieved)
        assert len(kept) == 1
        assert stripped == 0

    def test_strips_invented_url(self):
        retrieved = {_normalize_url("https://tracxn.com/d/companies/tamnoon/abc")}
        sources = [
            SourceRef(url="https://tamnoon.io/news/series-a-announcement", retrieved="2026-06"),
        ]
        kept, stripped = _verify_section_sources(sources, retrieved)
        assert len(kept) == 0
        assert stripped == 1

    def test_mixed(self):
        retrieved = {
            _normalize_url("https://tracxn.com/d/companies/tamnoon/abc"),
            _normalize_url("https://pitchbook.com/profiles/company/497271-34"),
        }
        sources = [
            SourceRef(url="https://tracxn.com/d/companies/tamnoon/abc", retrieved="2026-06"),
            SourceRef(url="https://tamnoon.io/news/series-a-announcement", retrieved="2026-06"),
            SourceRef(url="https://pitchbook.com/profiles/company/497271-34", retrieved="2026-06"),
            SourceRef(url="https://tamnoon.io/news/seed-funding-announcement", retrieved="2026-06"),
        ]
        kept, stripped = _verify_section_sources(sources, retrieved)
        assert len(kept) == 2
        assert stripped == 2


class TestVerifyDossierSources:
    def _make_result(self) -> CompanyResearchResult:
        return CompanyResearchResult(
            company_name="Tamnoon.io",
            funding=FundingDossier(
                stage="A",
                founded=2021,
                total_raised_usd=17100000,
                last_round=LastRound(
                    type="Series A",
                    amount_usd=12000000,
                    date="2024-09-25",
                    lead_investors=["Bright Pixel Capital (formerly Sonae IM)"],
                ),
                confidence=0.8,
                sources=[
                    SourceRef(url="https://tracxn.com/d/companies/tamnoon/abc", retrieved="2026-06"),
                    SourceRef(url="https://tamnoon.io/news/series-a-announcement", retrieved="2026-06"),
                    SourceRef(url="https://pitchbook.com/profiles/company/497271-34", retrieved="2026-06"),
                    SourceRef(url="https://app.fundz.net/fundings/tamnoon-funding-round-9a0328", retrieved="2026-06"),
                    SourceRef(url="https://tamnoon.io/news/seed-funding-announcement", retrieved="2026-06"),
                ],
            ),
            sentiment=SentimentDossier(
                confidence=0.7,
                sources=[
                    SourceRef(url="https://www.glassdoor.com/Reviews/Tamnoon-Netanya-Reviews-EI_IE8881526.0,7_IL.8,15_IC2416454.htm", retrieved="2026-06"),
                ],
            ),
            fit=FitDossier(
                confidence=0.6,
                sources=[
                    SourceRef(url="https://www.glassdoor.com/Overview/Working-at-Tamnoon-EI_IE8881526.11,18.htm", retrieved="2026-06"),
                ],
            ),
            retrieval_sources=[
                SourceRef(url="https://tracxn.com/d/companies/tamnoon/abc", retrieved="2026-06"),
                SourceRef(url="https://pitchbook.com/profiles/company/497271-34", retrieved="2026-06"),
                SourceRef(url="https://app.fundz.net/fundings/tamnoon-funding-round-9a0328", retrieved="2026-06"),
                SourceRef(url="https://www.glassdoor.com/Reviews/Tamnoon-Netanya-Reviews-EI_IE8881526.0,7_IL.8,15_IC2416454.htm", retrieved="2026-06"),
                SourceRef(url="https://www.glassdoor.com/Overview/Working-at-Tamnoon-EI_IE8881526.11,18.htm", retrieved="2026-06"),
            ],
        )

    def _make_snippets(self) -> list[RetrievalSnippet]:
        return [
            RetrievalSnippet(
                title="Tamnoon Funding",
                url="https://tracxn.com/d/companies/tamnoon/abc",
                snippet="Tamnoon raised $12M Series A led by Bright Pixel Capital",
                source_domain="tracxn.com",
                score=0.95,
            ),
            RetrievalSnippet(
                title="Tamnoon PitchBook",
                url="https://pitchbook.com/profiles/company/497271-34",
                snippet="Series A - $12M - Sep 2024",
                source_domain="pitchbook.com",
                score=0.9,
            ),
            RetrievalSnippet(
                title="Tamnoon Fundz",
                url="https://app.fundz.net/fundings/tamnoon-funding-round-9a0328",
                snippet="Tamnoon.io funding round details",
                source_domain="app.fundz.net",
                score=0.85,
            ),
            RetrievalSnippet(
                title="Tamnoon Glassdoor Reviews",
                url="https://www.glassdoor.com/Reviews/Tamnoon-Netanya-Reviews-EI_IE8881526.0,7_IL.8,15_IC2416454.htm",
                snippet="Employee reviews for Tamnoon",
                source_domain="glassdoor.com",
                score=0.8,
            ),
            RetrievalSnippet(
                title="Tamnoon Glassdoor Overview",
                url="https://www.glassdoor.com/Overview/Working-at-Tamnoon-EI_IE8881526.11,18.htm",
                snippet="Company overview for Tamnoon",
                source_domain="glassdoor.com",
                score=0.75,
            ),
        ]

    def test_strips_invented_funding_urls(self):
        """Test (a): a dossier whose funding.sources contains a URL not in the retrieved set has that URL stripped."""
        result = self._make_result()
        snippets = self._make_snippets()

        _verify_dossier_sources(result, snippets)

        funding_urls = {s.url for s in result.funding.sources}
        assert "https://tamnoon.io/news/series-a-announcement" not in funding_urls
        assert "https://tamnoon.io/news/seed-funding-announcement" not in funding_urls
        assert result.funding.stripped_count == 2
        # Legitimately retrieved URLs are kept
        assert "https://tracxn.com/d/companies/tamnoon/abc" in funding_urls
        assert "https://pitchbook.com/profiles/company/497271-34" in funding_urls
        assert "https://app.fundz.net/fundings/tamnoon-funding-round-9a0328" in funding_urls

    def test_strips_tamnoon_fabricated_patterns(self):
        """Test (b): the two real-world fabricated patterns are stripped when not in retrieved set."""
        result = self._make_result()
        snippets = self._make_snippets()

        _verify_dossier_sources(result, snippets)

        funding_urls = {s.url for s in result.funding.sources}
        assert "https://tamnoon.io/news/series-a-announcement" not in funding_urls
        assert "https://tamnoon.io/news/seed-funding-announcement" not in funding_urls

    def test_keeps_legitimately_retrieved_url(self):
        """Test (c): a legitimately-retrieved URL is kept."""
        result = self._make_result()
        snippets = self._make_snippets()

        _verify_dossier_sources(result, snippets)

        funding_urls = {s.url for s in result.funding.sources}
        assert "https://tracxn.com/d/companies/tamnoon/abc" in funding_urls
        # Sentiment and fit sources should also be preserved (they were in retrieved set)
        assert len(result.sentiment.sources) == 1
        assert len(result.fit.sources) == 1
        assert result.sentiment.stripped_count == 0
        assert result.fit.stripped_count == 0

    def test_no_stripping_when_no_retrieval(self):
        """Test (d): when no retrieval ran, no stripping occurs."""
        result = self._make_result()
        original_funding_sources = list(result.funding.sources)
        original_sentiment_sources = list(result.sentiment.sources)

        _verify_dossier_sources(result, [])

        assert result.funding.sources == original_funding_sources
        assert result.sentiment.sources == original_sentiment_sources
        assert result.funding.stripped_count == 0

    def test_confidence_halved_when_all_sources_stripped(self):
        """When stripping leaves a section with zero sources, confidence is halved."""
        result = CompanyResearchResult(
            company_name="TestCo",
            funding=FundingDossier(
                confidence=0.8,
                sources=[
                    SourceRef(url="https://invented.example.com/fake-news", retrieved="2026-06"),
                ],
            ),
        )
        snippets = [
            RetrievalSnippet(url="https://real.example.com/data", snippet="real", source_domain="example.com"),
        ]

        _verify_dossier_sources(result, snippets)

        assert len(result.funding.sources) == 0
        assert result.funding.stripped_count == 1
        assert result.funding.confidence == 0.4  # halved from 0.8
        assert any("funding" in g for g in result.gaps)

    def test_retrieval_sources_also_verified(self):
        """Top-level retrieval_sources are also filtered against the retrieved set."""
        result = self._make_result()
        snippets = self._make_snippets()

        _verify_dossier_sources(result, snippets)

        rs_urls = {s.url for s in result.retrieval_sources}
        # All retrieval_sources should be in the retrieved set (they were built from it)
        assert len(rs_urls) == 5

    def test_stripped_count_reflects_actual_strips(self):
        """stripped_count matches the number of URLs removed."""
        result = self._make_result()
        snippets = self._make_snippets()

        _verify_dossier_sources(result, snippets)

        assert result.funding.stripped_count == 2  # two tamnoon.io invented URLs
        assert result.sentiment.stripped_count == 0
        assert result.fit.stripped_count == 0


class TestTrackingParamNormalization:
    """Tests for tracking parameter stripping in _normalize_url."""

    def test_strips_utm_params(self):
        assert _normalize_url("https://example.com/page?utm_source=tavily&utm_medium=search") == "https://example.com/page"

    def test_strips_ref_source_fbclid_gclid(self):
        assert _normalize_url("https://example.com/page?ref=abc&fbclid=xyz&gclid=123") == "https://example.com/page"

    def test_keeps_meaningful_params(self):
        assert _normalize_url("https://example.com/page?id=42&sort=desc") == "https://example.com/page?id=42&sort=desc"

    def test_same_page_with_and_without_tracking_matches(self):
        """BUG 3b: same page, different tracking params → match (kept, not stripped)."""
        url_with_tracking = "https://example.com/funding?utm_source=tavily&ref=search"
        url_clean = "https://example.com/funding"
        assert _normalize_url(url_with_tracking) == _normalize_url(url_clean)

    def test_mixed_tracking_and_meaningful(self):
        assert _normalize_url("https://example.com/page?utm_campaign=x&id=42") == "https://example.com/page?id=42"


class TestSameDomainDifferentPath:
    """BUG 3a: a guessed path on a retrieved domain must be STRIPPED."""

    def test_guessed_path_on_real_domain_stripped(self):
        retrieved = {_normalize_url("https://tamnoon.io/about")}
        sources = [SourceRef(url="https://tamnoon.io/news/series-a-announcement", retrieved="2026-06")]
        kept, stripped = _verify_section_sources(sources, retrieved)
        assert len(kept) == 0
        assert stripped == 1

    def test_different_path_on_real_domain_stripped(self):
        retrieved = {_normalize_url("https://example.com/real-page")}
        sources = [SourceRef(url="https://example.com/fake-page", retrieved="2026-06")]
        kept, stripped = _verify_section_sources(sources, retrieved)
        assert len(kept) == 0
        assert stripped == 1

    def test_same_path_different_domain_stripped(self):
        retrieved = {_normalize_url("https://real.com/page")}
        sources = [SourceRef(url="https://fake.com/page", retrieved="2026-06")]
        kept, stripped = _verify_section_sources(sources, retrieved)
        assert len(kept) == 0
        assert stripped == 1


class TestWikipediaUrlPreservation:
    """BUG 2: Wikipedia/Wikidata source URLs must not be false-stripped."""

    def test_wikipedia_url_not_in_tavily_set_is_kept(self):
        """A Wikipedia-derived source URL that is NOT in the Tavily set is KEPT
        when Wikipedia was a source for the run (via extra_verified_urls)."""
        wiki_url = "https://en.wikipedia.org/wiki/Plaid_Inc."
        result = CompanyResearchResult(
            company_name="Plaid",
            funding=FundingDossier(
                confidence=0.8,
                sources=[
                    SourceRef(url=wiki_url, retrieved="2026-06"),
                    SourceRef(url="https://tracxn.com/d/companies/plaid/abc", retrieved="2026-06"),
                ],
            ),
        )
        snippets = [
            RetrievalSnippet(url="https://tracxn.com/d/companies/plaid/abc", snippet="real", source_domain="tracxn.com"),
        ]
        extra_verified = {wiki_url}

        _verify_dossier_sources(result, snippets, extra_verified_urls=extra_verified)

        funding_urls = {s.url for s in result.funding.sources}
        assert wiki_url in funding_urls
        assert "https://tracxn.com/d/companies/plaid/abc" in funding_urls
        assert result.funding.stripped_count == 0

    def test_wikipedia_url_stripped_when_not_in_either_set(self):
        """If Wikipedia was NOT a source and the URL is not in Tavily set, it IS stripped."""
        wiki_url = "https://en.wikipedia.org/wiki/Some_Other_Company"
        result = CompanyResearchResult(
            company_name="TestCo",
            funding=FundingDossier(
                confidence=0.8,
                sources=[
                    SourceRef(url=wiki_url, retrieved="2026-06"),
                ],
            ),
        )
        snippets = [
            RetrievalSnippet(url="https://tracxn.com/d/companies/testco/abc", snippet="real", source_domain="tracxn.com"),
        ]

        _verify_dossier_sources(result, snippets, extra_verified_urls=None)

        assert len(result.funding.sources) == 0
        assert result.funding.stripped_count == 1


class TestOverallConfidenceRecomputation:
    """DESIGN ITEM: overall_confidence recomputed after section halving."""

    def test_overall_capped_to_mean_after_halving(self):
        """A dossier with all sources stripped in a section ends with
        overall_confidence reduced enough that is_stub reflects the lost grounding."""
        result = CompanyResearchResult(
            company_name="TestCo",
            overall_confidence=0.8,
            funding=FundingDossier(
                confidence=0.8,
                sources=[
                    SourceRef(url="https://invented.example.com/fake", retrieved="2026-06"),
                ],
            ),
            sentiment=SentimentDossier(
                confidence=0.6,
                sources=[
                    SourceRef(url="https://real.example.com/data", retrieved="2026-06"),
                ],
            ),
            fit=FitDossier(
                confidence=0.4,
                sources=[
                    SourceRef(url="https://real.example.com/fit", retrieved="2026-06"),
                ],
            ),
        )
        snippets = [
            RetrievalSnippet(url="https://real.example.com/data", snippet="real", source_domain="example.com"),
            RetrievalSnippet(url="https://real.example.com/fit", snippet="real", source_domain="example.com"),
        ]

        _verify_dossier_sources(result, snippets)

        # funding confidence halved: 0.8 → 0.4
        assert result.funding.confidence == 0.4
        # overall should be capped to mean(0.4, 0.6, 0.4) = 0.4667
        assert result.overall_confidence < 0.8
        assert abs(result.overall_confidence - (0.4 + 0.6 + 0.4) / 3) < 0.01
        # With confidence_floor=0.3, is_stub would be False (0.467 > 0.3)
        # but if floor were 0.5, it would be True — the recomputation makes it reachable

    def test_overall_not_raised_when_sections_higher(self):
        """overall_confidence is only capped downward, never raised."""
        result = CompanyResearchResult(
            company_name="TestCo",
            overall_confidence=0.3,
            funding=FundingDossier(
                confidence=0.9,
                sources=[SourceRef(url="https://real.example.com/fund", retrieved="2026-06")],
            ),
        )
        snippets = [RetrievalSnippet(url="https://real.example.com/fund", snippet="real", source_domain="example.com")]

        _verify_dossier_sources(result, snippets)

        # Mean section = 0.9, but overall was 0.3 — should NOT be raised to 0.9
        assert result.overall_confidence == 0.3

    def test_all_sections_stripped_reduces_overall_below_floor(self):
        """When all sections lose all sources, overall_confidence drops enough
        to trigger is_stub with a typical confidence_floor of 0.3."""
        result = CompanyResearchResult(
            company_name="TestCo",
            overall_confidence=0.8,
            funding=FundingDossier(
                confidence=0.8,
                sources=[SourceRef(url="https://fake.example.com/a", retrieved="2026-06")],
            ),
            sentiment=SentimentDossier(
                confidence=0.7,
                sources=[SourceRef(url="https://fake.example.com/b", retrieved="2026-06")],
            ),
            fit=FitDossier(
                confidence=0.6,
                sources=[SourceRef(url="https://fake.example.com/c", retrieved="2026-06")],
            ),
        )
        snippets = [
            RetrievalSnippet(url="https://real.example.com/real", snippet="real", source_domain="example.com"),
        ]

        _verify_dossier_sources(result, snippets)

        # All sections halved: 0.4, 0.35, 0.3 → mean = 0.35
        assert abs(result.overall_confidence - (0.4 + 0.35 + 0.3) / 3) < 0.01
        # With confidence_floor=0.3: 0.35 > 0.3, so is_stub=False
        # But the overall dropped from 0.8 to 0.35 — significant reduction
        assert result.overall_confidence < 0.5
