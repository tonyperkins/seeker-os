"""Pydantic models for company research data.

The schema mirrors the Company Research Agent prompt output: a structured
dossier with funding, sentiment, and fit sections, each carrying confidence
scores and source references.
"""

from __future__ import annotations

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Shared sub-models
# ---------------------------------------------------------------------------

class SourceRef(BaseModel):
    """A source URL with retrieval date."""
    url: str = ""
    retrieved: str = ""


# ---------------------------------------------------------------------------
# Wikipedia (free context source — not part of the dossier schema but kept
# for display and as LLM context)
# ---------------------------------------------------------------------------

class WikipediaInfo(BaseModel):
    """Company information from Wikipedia."""
    title: str = ""
    description: str = ""
    extract: str = ""
    url: str | None = None
    thumbnail: str | None = None


# ---------------------------------------------------------------------------
# Funding dossier
# ---------------------------------------------------------------------------

class LayoffEvent(BaseModel):
    """A single layoff event."""
    date: str | None = None
    pct: float | None = None
    count: int | None = None
    source: str | None = None


class LastRound(BaseModel):
    """Most recent funding round."""
    type: str | None = None
    amount_usd: int | None = None
    date: str | None = None
    lead_investors: list[str] = []


class FundingDossier(BaseModel):
    """Funding / company stage section of the dossier."""
    founded: int | None = None
    hq: str | None = None
    public: bool = False
    stage: str | None = None
    total_raised_usd: int | None = None
    valuation_usd: int | None = None
    last_round: LastRound | None = None
    headcount: int | None = None
    headcount_trend: str | None = None
    layoffs: list[LayoffEvent] = []
    financial_health: str | None = None
    confidence: float = 0.0
    sources: list[SourceRef] = []
    stripped_count: int = 0  # URLs removed by verification (model-invented)


# ---------------------------------------------------------------------------
# Sentiment dossier
# ---------------------------------------------------------------------------

class SentimentTheme(BaseModel):
    """A recurring positive or negative theme in employee sentiment."""
    theme: str = ""
    frequency: str = "low"  # low|med|high
    paraphrase: str = ""
    source: str = ""
    age_months: int | None = None


class SentimentDossier(BaseModel):
    """Employee sentiment section of the dossier."""
    overall_rating_estimate: float | None = None
    rating_scale: str = "out of 5"
    ceo_approval_pct: float | None = None
    recommend_pct: float | None = None
    positives: list[SentimentTheme] = []
    negatives: list[SentimentTheme] = []
    staleness_warning: str | None = None
    confidence: float = 0.0
    sources: list[SourceRef] = []
    stripped_count: int = 0  # URLs removed by verification (model-invented)


# ---------------------------------------------------------------------------
# Fit dossier
# ---------------------------------------------------------------------------

class FitDossier(BaseModel):
    """Fit signals section of the dossier."""
    remote_policy: str | None = None
    remote_walkback: str | None = None
    size_bucket: str | None = None
    ic_vs_mgmt_culture: str | None = None
    comp_band: str | None = None
    clearance_required: bool = False
    confidence: float = 0.0
    sources: list[SourceRef] = []
    stripped_count: int = 0  # URLs removed by verification (model-invented)


# ---------------------------------------------------------------------------
# Verdict flags
# ---------------------------------------------------------------------------

class VerdictFlags(BaseModel):
    """Green / red / watch flags for the company."""
    green: list[str] = []
    red: list[str] = []
    watch: list[str] = []


# ---------------------------------------------------------------------------
# Top-level result
# ---------------------------------------------------------------------------

class CompanyResearchResult(BaseModel):
    """Aggregated company research dossier."""
    company_name: str
    company_homepage: str | None = None

    # Wikipedia (context source, kept for display)
    wikipedia: WikipediaInfo | None = None

    # Dossier sections
    overall_confidence: float = 0.0
    summary: str = ""
    verdict_flags: VerdictFlags = VerdictFlags()
    funding: FundingDossier | None = None
    sentiment: SentimentDossier | None = None
    fit: FitDossier | None = None
    gaps: list[str] = []

    # Metadata
    researched_at: str = ""
    sources_used: list[str] = []
    errors: list[str] = []

    # Phase 3: threshold flags
    is_stub: bool = False  # True when overall_confidence < confidence_floor
    retrieval_used: bool = False  # True when live retrieval contributed snippets
    retrieval_sources: list[SourceRef] = []  # URLs from retrieval, for display
    retrieval_snippets: list[dict] = []  # Raw snippets: [{url, title, snippet, source_domain, score}]
