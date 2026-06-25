"""Tests for research-adjusted scoring and company-keyed research caching."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from seeker_os.research.models import (
    CompanyResearchResult,
    FundingDossier,
    SentimentDossier,
    FitDossier,
    LayoffEvent,
    LastRound,
    SentimentTheme,
    SourceRef,
)
from seeker_os.scoring.research_adjustment import (
    ResearchModifierRule,
    compute_research_adjustment,
)


def _default_rules() -> list[ResearchModifierRule]:
    return [
        ResearchModifierRule(factor="recent_layoffs", delta=-1.5, confidence_threshold=0.5, source_section="funding"),
        ResearchModifierRule(factor="down_round_runway_risk", delta=-2.0, confidence_threshold=0.5, source_section="funding"),
        ResearchModifierRule(factor="healthy_runway", delta=0.5, confidence_threshold=0.5, source_section="funding"),
        ResearchModifierRule(factor="remote_walkback_rto", delta=-1.5, confidence_threshold=0.5, source_section="fit"),
        ResearchModifierRule(factor="strong_negative_sentiment", delta=-1.0, confidence_threshold=0.6, source_section="sentiment"),
    ]


def _make_grounded_dossier(**kwargs) -> CompanyResearchResult:
    """A dossier with retrieval_used=True and is_stub=False (grounded)."""
    defaults = dict(
        company_name="TestCo",
        overall_confidence=0.7,
        retrieval_used=True,
        is_stub=False,
        funding=FundingDossier(confidence=0.8),
        sentiment=SentimentDossier(confidence=0.6),
        fit=FitDossier(confidence=0.5),
    )
    defaults.update(kwargs)
    return CompanyResearchResult(**defaults)


class TestResearchAdjustedScore:
    def test_high_confidence_layoff_lowers_score(self):
        """A high-confidence layoff dossier lowers the adjusted score; base unchanged."""
        dossier = _make_grounded_dossier(
            funding=FundingDossier(
                confidence=0.8,
                layoffs=[LayoffEvent(date="2024-01-15", pct=10.0, count=50)],
            ),
        )
        result = compute_research_adjustment(7.0, dossier, _default_rules())

        assert result.base_score == 7.0
        assert result.adjusted_score == 5.5  # 7.0 - 1.5
        assert result.research_delta == -1.5
        assert result.applied is True
        # Breakdown lists the factor with its confidence
        assert len(result.breakdown) == 1
        assert result.breakdown[0].factor == "recent_layoffs"
        assert result.breakdown[0].delta == -1.5
        assert result.breakdown[0].confidence == 0.8
        assert result.breakdown[0].source_section == "funding"

    def test_low_confidence_dossier_zero_adjustment(self):
        """A low-confidence / is_stub dossier produces ZERO adjustment."""
        dossier = _make_grounded_dossier(is_stub=True)
        result = compute_research_adjustment(7.0, dossier, _default_rules())

        assert result.adjusted_score == 7.0
        assert result.research_delta == 0.0
        assert result.applied is False
        assert len(result.breakdown) == 0

    def test_no_retrieval_zero_adjustment(self):
        """When retrieval didn't run, no adjustment."""
        dossier = _make_grounded_dossier(retrieval_used=False)
        result = compute_research_adjustment(7.0, dossier, _default_rules())

        assert result.adjusted_score == 7.0
        assert result.research_delta == 0.0
        assert result.applied is False

    def test_thin_sample_sentiment_does_not_move_score(self):
        """Thin-sample sentiment rating (low confidence) does NOT move the score."""
        dossier = _make_grounded_dossier(
            sentiment=SentimentDossier(
                confidence=0.3,  # below threshold of 0.6
                overall_rating_estimate=1.5,  # very negative rating
                negatives=[SentimentTheme(theme="toxic culture", frequency="low", paraphrase="bad place")],
            ),
        )
        result = compute_research_adjustment(7.0, dossier, _default_rules())

        # Sentiment modifier not applied (confidence 0.3 < 0.6)
        sentiment_factors = [b for b in result.breakdown if b.source_section == "sentiment"]
        assert len(sentiment_factors) == 0
        assert result.research_delta == 0.0

    def test_high_confidence_recurring_negative_theme_moves_score(self):
        """A high-confidence recurring negative theme DOES move the score."""
        dossier = _make_grounded_dossier(
            sentiment=SentimentDossier(
                confidence=0.75,  # above threshold of 0.6
                overall_rating_estimate=2.0,
                negatives=[SentimentTheme(theme="toxic culture", frequency="high", paraphrase="recurring complaints")],
            ),
        )
        result = compute_research_adjustment(7.0, dossier, _default_rules())

        sentiment_factors = [b for b in result.breakdown if b.source_section == "sentiment"]
        assert len(sentiment_factors) == 1
        assert sentiment_factors[0].factor == "strong_negative_sentiment"
        assert sentiment_factors[0].delta == -1.0
        assert result.adjusted_score == 6.0  # 7.0 - 1.0

    def test_low_frequency_theme_does_not_move_score(self):
        """A low-frequency theme (even with high confidence) does NOT trigger the modifier."""
        dossier = _make_grounded_dossier(
            sentiment=SentimentDossier(
                confidence=0.8,
                negatives=[SentimentTheme(theme="minor issue", frequency="low", paraphrase="one person complained")],
            ),
        )
        result = compute_research_adjustment(7.0, dossier, _default_rules())

        sentiment_factors = [b for b in result.breakdown if b.source_section == "sentiment"]
        assert len(sentiment_factors) == 0

    def test_healthy_runway_bonus(self):
        """Fresh raise / healthy runway gives a small bonus."""
        recent_date = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        dossier = _make_grounded_dossier(
            funding=FundingDossier(
                confidence=0.8,
                financial_health="healthy",
                last_round=LastRound(type="Series B", amount_usd=20000000, date=recent_date),
            ),
        )
        result = compute_research_adjustment(6.0, dossier, _default_rules())

        assert result.research_delta == 0.5
        assert result.adjusted_score == 6.5

    def test_remote_walkback_penalty(self):
        """Remote walkback / RTO signal gives a penalty."""
        dossier = _make_grounded_dossier(
            fit=FitDossier(
                confidence=0.6,
                remote_walkback="Company mandated return to office",
            ),
        )
        result = compute_research_adjustment(7.0, dossier, _default_rules())

        assert result.research_delta == -1.5
        assert result.adjusted_score == 5.5

    def test_down_round_penalty(self):
        """Down round / runway risk gives a penalty."""
        dossier = _make_grounded_dossier(
            funding=FundingDossier(
                confidence=0.7,
                financial_health="down round, runway risk",
            ),
        )
        result = compute_research_adjustment(7.0, dossier, _default_rules())

        assert result.research_delta == -2.0
        assert result.adjusted_score == 5.0

    def test_clamped_to_max(self):
        """Adjusted score is clamped to max_score."""
        dossier = _make_grounded_dossier(
            funding=FundingDossier(
                confidence=0.8,
                financial_health="healthy",
                last_round=LastRound(type="Series B", amount_usd=20000000, date=datetime.now(timezone.utc).isoformat()),
            ),
        )
        result = compute_research_adjustment(10.0, dossier, _default_rules(), max_score=10.0)
        assert result.adjusted_score == 10.0

    def test_clamped_to_min(self):
        """Adjusted score is clamped to min_score."""
        dossier = _make_grounded_dossier(
            funding=FundingDossier(
                confidence=0.8,
                layoffs=[LayoffEvent(date="2024-01-15")],
                financial_health="down round, distressed",
            ),
        )
        result = compute_research_adjustment(1.0, dossier, _default_rules(), min_score=0.0)
        # 1.0 - 1.5 - 2.0 = -2.5 → clamped to 0
        assert result.adjusted_score == 0.0

    def test_base_score_never_mutated(self):
        """The base_score field always reflects the original score, even after adjustment."""
        dossier = _make_grounded_dossier(
            funding=FundingDossier(
                confidence=0.8,
                layoffs=[LayoffEvent(date="2024-01-15")],
            ),
        )
        result = compute_research_adjustment(7.0, dossier, _default_rules())
        assert result.base_score == 7.0
        assert result.adjusted_score != result.base_score

    def test_multiple_modifiers_sum(self):
        """Multiple applicable modifiers sum together."""
        dossier = _make_grounded_dossier(
            funding=FundingDossier(
                confidence=0.8,
                layoffs=[LayoffEvent(date="2024-01-15")],
            ),
            fit=FitDossier(
                confidence=0.6,
                remote_walkback="RTO mandated",
            ),
        )
        result = compute_research_adjustment(7.0, dossier, _default_rules())
        # -1.5 (layoffs) + -1.5 (walkback) = -3.0
        assert result.research_delta == -3.0
        assert result.adjusted_score == 4.0
        assert len(result.breakdown) == 2

    def test_confidence_below_threshold_skips_modifier(self):
        """A modifier whose section confidence is below threshold is skipped."""
        dossier = _make_grounded_dossier(
            funding=FundingDossier(
                confidence=0.3,  # below 0.5 threshold
                layoffs=[LayoffEvent(date="2024-01-15")],
            ),
        )
        result = compute_research_adjustment(7.0, dossier, _default_rules())
        assert result.research_delta == 0.0
        assert len(result.breakdown) == 0


class TestCompanyKeyedCaching:
    """Tests for company-keyed research caching with TTL reuse."""

    def test_second_job_same_company_reuses_within_ttl(self):
        """Second job at the same company REUSES the cached dossier (no new Tavily call) within TTL."""
        from seeker_os.api.company_research import _find_fresh_dossier
        from seeker_os.dedup.normalize import normalize_company
        from seeker_os.database import get_connection, json_encode, run_migrations
        import tempfile, os

        # Use a temp DB
        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, "test.db")
        run_migrations(db_path)
        db = get_connection(db_path)

        # Insert a job
        db.execute(
            "INSERT INTO jobs (id, title, company, status) VALUES (?, ?, ?, ?)",
            (1, "SRE", "Stripe", "discovered"),
        )
        db.commit()

        # Insert a company_research record for job 1, company "Stripe"
        company_norm = normalize_company("Stripe")
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            """INSERT INTO company_research (
                job_id, company_name, company_homepage, overall_confidence,
                summary, sources_used, errors, researched_at, created_at,
                company_norm
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (1, "Stripe", "https://stripe.com", 0.8, "Test", "[]", "[]", now, now, company_norm),
        )
        db.commit()

        # Look up by company_norm — should find the fresh dossier
        row, age_days = _find_fresh_dossier(db, company_norm, ttl_days=30)
        assert row is not None
        assert age_days is not None
        assert age_days <= 1  # just created

        db.close()

        # Cleanup
        os.unlink(db_path)
        os.rmdir(tmpdir)

    def test_stale_dossier_triggers_refresh(self):
        """A stale dossier (older than TTL) is NOT reused — returns None."""
        from seeker_os.api.company_research import _find_fresh_dossier
        from seeker_os.dedup.normalize import normalize_company
        from seeker_os.database import get_connection, json_encode, run_migrations
        import tempfile, os

        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, "test.db")
        run_migrations(db_path)
        db = get_connection(db_path)

        db.execute(
            "INSERT INTO jobs (id, title, company, status) VALUES (?, ?, ?, ?)",
            (1, "SRE", "OldCo", "discovered"),
        )
        db.commit()

        # Insert a research record with an old researched_at (60 days ago)
        old_date = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        company_norm = normalize_company("OldCo")
        db.execute(
            """INSERT INTO company_research (
                job_id, company_name, company_homepage, overall_confidence,
                summary, sources_used, errors, researched_at, created_at,
                company_norm
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (1, "OldCo", None, 0.5, "Old", "[]", "[]", old_date, old_date, company_norm),
        )
        db.commit()

        # TTL is 30 days — 60-day-old dossier should NOT be reused
        row, age_days = _find_fresh_dossier(db, company_norm, ttl_days=30)
        assert row is None
        assert age_days == 60

        db.close()
        os.unlink(db_path)
        os.rmdir(tmpdir)

    def test_different_company_not_reused(self):
        """A dossier for a different company is not reused."""
        from seeker_os.api.company_research import _find_fresh_dossier
        from seeker_os.dedup.normalize import normalize_company
        from seeker_os.database import get_connection, run_migrations
        import tempfile, os

        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, "test.db")
        run_migrations(db_path)
        db = get_connection(db_path)

        now = datetime.now(timezone.utc).isoformat()
        company_norm = normalize_company("Stripe")
        db.execute(
            "INSERT INTO jobs (id, title, company, status) VALUES (?, ?, ?, ?)",
            (1, "SRE", "Stripe", "discovered"),
        )
        db.commit()
        db.execute(
            """INSERT INTO company_research (
                job_id, company_name, overall_confidence, summary,
                sources_used, errors, researched_at, created_at, company_norm
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (1, "Stripe", 0.8, "Test", "[]", "[]", now, now, company_norm),
        )
        db.commit()

        # Look up a different company
        row, age_days = _find_fresh_dossier(db, "plaid", ttl_days=30)
        assert row is None

        db.close()
        os.unlink(db_path)
        os.rmdir(tmpdir)

    def test_endpoint_reuses_cache_no_second_research_call(self, monkeypatch):
        """Calling run_company_research twice for same company: second call reuses cache,
        research_company is called only once."""
        import tempfile, os
        from seeker_os.api import company_research as cr_api
        from seeker_os.database import get_connection, run_migrations
        from seeker_os.research.models import CompanyResearchResult

        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, "test.db")
        run_migrations(db_path)
        db = get_connection(db_path)

        # Insert two jobs at the same company
        db.execute(
            "INSERT INTO jobs (id, title, company, status) VALUES (?, ?, ?, ?)",
            (1, "SRE", "Stripe", "discovered"),
        )
        db.execute(
            "INSERT INTO jobs (id, title, company, status) VALUES (?, ?, ?, ?)",
            (2, "Platform Engineer", "Stripe", "discovered"),
        )
        db.commit()

        # Mock research_company to avoid real Tavily/LLM calls
        call_count = 0

        def mock_research_company(company, **kwargs):
            nonlocal call_count
            call_count += 1
            return CompanyResearchResult(
                company_name=company,
                overall_confidence=0.7,
                summary="Test dossier",
                researched_at=datetime.now(timezone.utc).isoformat(),
                sources_used=["wikipedia"],
                retrieval_used=True,
            )

        monkeypatch.setattr(cr_api, "research_company", mock_research_company)
        # Also patch the DB path so the API uses our temp DB
        monkeypatch.setattr(cr_api, "get_connection", lambda: get_connection(db_path))

        # First call — should run research
        response1 = cr_api.run_company_research(job_id=1)
        assert response1.reused_from_cache is False
        assert call_count == 1

        # Second call — should reuse cache, NOT call research_company again
        response2 = cr_api.run_company_research(job_id=2)
        assert response2.reused_from_cache is True
        assert call_count == 1  # research_company still only called once

        db.close()
        os.unlink(db_path)
        os.rmdir(tmpdir)

    def test_name_variants_resolve_to_same_company_norm(self):
        """Two name variants of the same company resolve to the SAME company_norm."""
        from seeker_os.dedup.normalize import normalize_company

        norm1 = normalize_company("Stripe")
        norm2 = normalize_company("Stripe, Inc.")
        norm3 = normalize_company("Stripe Inc")

        assert norm1 == norm2 == norm3 == "stripe"

    def test_name_variants_share_cache(self, monkeypatch):
        """Two jobs with name variants of the same company share the cache."""
        import tempfile, os
        from seeker_os.api import company_research as cr_api
        from seeker_os.database import get_connection, run_migrations
        from seeker_os.research.models import CompanyResearchResult

        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, "test.db")
        run_migrations(db_path)
        db = get_connection(db_path)

        # Insert two jobs with different name variants
        db.execute(
            "INSERT INTO jobs (id, title, company, status) VALUES (?, ?, ?, ?)",
            (1, "SRE", "Stripe", "discovered"),
        )
        db.execute(
            "INSERT INTO jobs (id, title, company, status) VALUES (?, ?, ?, ?)",
            (2, "Platform Engineer", "Stripe, Inc.", "discovered"),
        )
        db.commit()

        call_count = 0

        def mock_research_company(company, **kwargs):
            nonlocal call_count
            call_count += 1
            return CompanyResearchResult(
                company_name=company,
                overall_confidence=0.7,
                summary="Test dossier",
                researched_at=datetime.now(timezone.utc).isoformat(),
                sources_used=["wikipedia"],
                retrieval_used=True,
            )

        monkeypatch.setattr(cr_api, "research_company", mock_research_company)
        monkeypatch.setattr(cr_api, "get_connection", lambda: get_connection(db_path))

        # First call with "Stripe" — runs research
        response1 = cr_api.run_company_research(job_id=1)
        assert response1.reused_from_cache is False
        assert call_count == 1

        # Second call with "Stripe, Inc." — should reuse cache (same company_norm)
        response2 = cr_api.run_company_research(job_id=2)
        assert response2.reused_from_cache is True
        assert call_count == 1

        db.close()
        os.unlink(db_path)
        os.rmdir(tmpdir)
