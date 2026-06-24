"""Company research module — aggregates data from multiple free sources.

Sources:
  - Wikipedia REST API (free, no auth) — company description, industry, founding
  - Wikidata API (free, no auth) — structured data: founded year, industry, employees, HQ
  - LLM analysis (when providers are configured) — funding info + employee sentiment

All source adapters are pluggable. Adding a new source (e.g. Glassdoor if a free
API becomes available) means adding a new fetch function and including it in
research_company().
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

import httpx

from seeker_os.research.models import (
    CompanyResearchResult,
    FundingDossier,
    FitDossier,
    LastRound,
    SentimentDossier,
    SourceRef,
    VerdictFlags,
    WikipediaInfo,
)


# ---------------------------------------------------------------------------
# Wikipedia adapter (free, no auth)
# ---------------------------------------------------------------------------

WIKIPEDIA_SEARCH_URL = "https://en.wikipedia.org/w/api.php"
WIKIPEDIA_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"

# Wikipedia requires a User-Agent header per their robot policy.
HTTP_HEADERS = {
    "User-Agent": "SeekerOS/0.1 (https://github.com/example/seeker-os)",
}


def _search_wikipedia(company: str, timeout: int = 10) -> str | None:
    """Search Wikipedia for a company page title. Returns the best-matching title or None."""
    params = {
        "action": "query",
        "list": "search",
        "srsearch": f"{company} company",
        "srlimit": "5",
        "format": "json",
    }
    try:
        resp = httpx.get(WIKIPEDIA_SEARCH_URL, params=params, headers=HTTP_HEADERS, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        search_results = data.get("query", {}).get("search", [])
        if not search_results:
            return None
        # Return the first result — Wikipedia search is usually good at ranking
        return search_results[0]["title"]
    except Exception:
        return None


def fetch_wikipedia_info(company: str, timeout: int = 10) -> WikipediaInfo | None:
    """Fetch company information from Wikipedia.

    1. Search for the company page
    2. Fetch the page summary via REST API
    3. Return structured info
    """
    title = _search_wikipedia(company, timeout=timeout)
    if not title:
        return None

    url = WIKIPEDIA_SUMMARY_URL.format(title=title.replace(" ", "_"))
    try:
        resp = httpx.get(url, headers=HTTP_HEADERS, timeout=timeout)
        if resp.status_code != 200:
            return None
        data = resp.json()
        return WikipediaInfo(
            title=data.get("title", ""),
            description=data.get("description", ""),
            extract=data.get("extract", ""),
            url=data.get("content_urls", {}).get("desktop", {}).get("page"),
            thumbnail=data.get("thumbnail", {}).get("source") if data.get("thumbnail") else None,
        )
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Wikidata adapter (free, no auth) — structured company data
# ---------------------------------------------------------------------------

WIKIDATA_ENTITY_URL = "https://www.wikidata.org/wiki/Special:EntityData/{item_id}.json"


def _get_wikidata_item_id(title: str, timeout: int = 10) -> str | None:
    """Get the Wikidata item ID for a Wikipedia page title."""
    params = {
        "action": "query",
        "prop": "pageprops",
        "ppprop": "wikibase_item",
        "titles": title,
        "format": "json",
    }
    try:
        resp = httpx.get(WIKIPEDIA_SEARCH_URL, params=params, headers=HTTP_HEADERS, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        pages = data.get("query", {}).get("pages", {})
        for _pid, page in pages.items():
            wb_item = page.get("pageprops", {}).get("wikibase_item")
            if wb_item:
                return wb_item
    except Exception:
        pass
    return None


def _extract_wikidata_value(claim: dict) -> str | int | None:
    """Extract a simple value from a Wikidata claim."""
    try:
        dv = claim["mainsnak"]["datavalue"]["value"]
        if isinstance(dv, dict):
            if "time" in dv:
                return dv["time"]
            if "amount" in dv:
                return int(float(dv["amount"]))
            if "id" in dv:
                return dv["id"]
            if "text" in dv:
                return dv["text"]
        return str(dv)
    except (KeyError, TypeError, ValueError):
        return None


def fetch_wikidata_info(
    company: str,
    wikipedia_title: str | None = None,
    timeout: int = 10,
) -> FundingDossier | None:
    """Fetch structured company data from Wikidata.

    Returns a partial FundingDossier with founded year and headcount populated
    from Wikidata claims. These values are used as context for the LLM dossier
    call and as fallback when no LLM is configured.
    """
    if not wikipedia_title:
        wikipedia_title = _search_wikipedia(company, timeout=timeout)
    if not wikipedia_title:
        return None

    item_id = _get_wikidata_item_id(wikipedia_title, timeout=timeout)
    if not item_id:
        return None

    try:
        resp = httpx.get(
            WIKIDATA_ENTITY_URL.format(item_id=item_id),
            headers=HTTP_HEADERS,
            timeout=timeout,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        entity = data.get("entities", {}).get(item_id, {})
        claims = entity.get("claims", {})

        # P571 = inception/founded date
        founded_year = None
        if "P571" in claims:
            founded_val = _extract_wikidata_value(claims["P571"][0])
            if isinstance(founded_val, str) and founded_val.startswith("+"):
                try:
                    founded_year = int(founded_val[1:5])
                except ValueError:
                    pass

        # P452 = industry (we could resolve the ID but just note it exists)
        # P159 = headquarters location
        # P1128 = number of employees
        employees = None
        if "P1128" in claims:
            emp_val = _extract_wikidata_value(claims["P1128"][0])
            if isinstance(emp_val, int):
                employees = emp_val

        # Only return if we found something useful
        if founded_year or employees:
            wikidata_url = f"https://www.wikidata.org/wiki/{item_id}"
            now = datetime.now(timezone.utc).isoformat()
            return FundingDossier(
                founded=founded_year,
                headcount=employees,
                confidence=0.6,
                sources=[SourceRef(url=wikidata_url, retrieved=now)],
            )
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# LLM dossier generation (uses configured LLM providers)
# ---------------------------------------------------------------------------

DOSSIER_SYSTEM_PROMPT = """You are a research agent producing a structured company dossier for a job-search
pipeline. Output is ingested into a database and rendered on a dashboard, so you
MUST return valid JSON matching the schema below and nothing else. No prose
outside the JSON.

## Hard rules
1. NEVER fabricate. If a value cannot be sourced, set it to null and lower the
   confidence score. Inferred values must be flagged inferred:true with reasoning.
2. Every non-trivial claim carries a source URL and a retrieved date. No URL = treat
   as unverified, confidence <= 0.4.
3. Prefer primary/original sources (company blog, SEC, Crunchbase, press releases,
   official funding announcements) over aggregators and SEO content.
4. Sentiment data is mostly paywalled (Glassdoor, Blind). Do NOT invent ratings.
   Use what is visible in search snippets, SERP rating badges, cached pages, and
   open aggregators, and TRIANGULATE across multiple sources. State explicitly when
   a number is a snippet-derived estimate vs. a confirmed figure.
5. Recency matters. Tag the age of every sentiment signal. Flag anything older than
   ~18 months as stale. Layoffs, RTO mandates, and leadership churn override older
   positive signals.

## Funding / company stage (priority 1)
Resolve: founding year, HQ, public vs private, current stage
(bootstrapped/seed/A/B/C/D/E/late/public), total raised, last round
(amount + date + lead investors), post-money valuation if disclosed, headcount and
headcount trend (growing/flat/shrinking), and any layoff events with dates and
percentages. Note runway/financial-health signals (recent raise = healthy; long gap
since last raise + layoffs = risk; down round = red flag).
Sources to mine: Crunchbase, PitchBook snippets, SEC EDGAR, TechCrunch, company
press, LinkedIn headcount, layoffs.fyi.

## Employee sentiment (priority 1 — weight equally with funding)
Triangulate across: Glassdoor (SERP rating badge + visible snippets), Blind,
Reddit (r/cscareerquestions, company subs), Indeed reviews, Comparably, Levels.fyi,
recent news on culture/leadership/turnover.
Capture: overall rating estimate (with source and confidence), CEO approval if
visible, recommend-to-friend if visible, and the recurring THEMES — separate
positives from negatives, each with how often it recurs and a representative
paraphrase (do NOT quote review text verbatim; summarize). Specifically surface:
layoffs/instability, RTO or remote-policy changes, management/leadership problems,
burnout/work-life, comp competitiveness, glue-work/management-heavy culture vs
hands-on IC respect.

## Fit signals (priority 2 — tailored to my search)
Flag against my constraints: remote policy (fully remote / hybrid / onsite — and any
walkback of remote), company size bucket (favor 200–500, Series E and below),
IC-vs-management culture, comp banding if discoverable, and any
clearance/citizenship requirements.

## Output schema
{
  "company": "string",
  "researched_at": "ISO8601",
  "overall_confidence": 0.0,
  "summary": "3-4 sentence plain-English verdict: stage, health, sentiment, fit",
  "verdict_flags": { "green": ["..."], "red": ["..."], "watch": ["..."] },
  "funding": {
    "founded": null, "hq": null, "public": false, "stage": null,
    "total_raised_usd": null, "valuation_usd": null,
    "last_round": { "type": null, "amount_usd": null, "date": null, "lead_investors": [] },
    "headcount": null, "headcount_trend": null,
    "layoffs": [ { "date": null, "pct": null, "count": null, "source": null } ],
    "financial_health": null,
    "confidence": 0.0, "sources": [ { "url": "", "retrieved": "" } ]
  },
  "sentiment": {
    "overall_rating_estimate": null, "rating_scale": "out of 5",
    "ceo_approval_pct": null, "recommend_pct": null,
    "positives": [ { "theme": "", "frequency": "low|med|high", "paraphrase": "", "source": "", "age_months": null } ],
    "negatives": [ { "theme": "", "frequency": "low|med|high", "paraphrase": "", "source": "", "age_months": null } ],
    "staleness_warning": null,
    "confidence": 0.0, "sources": [ { "url": "", "retrieved": "" } ]
  },
  "fit": {
    "remote_policy": null, "remote_walkback": null,
    "size_bucket": null, "ic_vs_mgmt_culture": null,
    "comp_band": null, "clearance_required": false,
    "confidence": 0.0, "sources": [ { "url": "", "retrieved": "" } ]
  },
  "gaps": ["list fields that could not be sourced"]
}"""


def _strip_code_fences(text: str) -> str:
    """Strip markdown code fences from LLM response text."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    return text


def fetch_llm_dossier(
    company: str,
    company_domain: str | None = None,
    careers_url: str | None = None,
    wikipedia_extract: str = "",
    wikidata_founded: int | None = None,
    wikidata_headcount: int | None = None,
) -> CompanyResearchResult | None:
    """Generate a full company dossier using the configured LLM.

    This is a single comprehensive LLM call that produces the entire dossier:
    funding, sentiment, fit, verdict flags, and gaps. When no LLM providers
    are configured, returns None.

    Context from Wikipedia/Wikidata is passed to the LLM to improve accuracy.
    """
    try:
        from seeker_os.llm.router import ModelRouter
        from seeker_os.config import Settings
    except ImportError:
        return None

    try:
        settings = Settings()
        if not settings.providers or not settings.providers.providers:
            return None
        router = ModelRouter(settings)
    except Exception:
        return None

    context_parts: list[str] = []
    if wikipedia_extract:
        context_parts.append(f"Company description: {wikipedia_extract}")
    if wikidata_founded:
        context_parts.append(f"Founded: {wikidata_founded}")
    if wikidata_headcount:
        context_parts.append(f"Headcount (Wikidata): {wikidata_headcount}")
    if company_domain:
        context_parts.append(f"Domain: {company_domain}")
    if careers_url:
        context_parts.append(f"Careers URL: {careers_url}")
    context = "\n".join(context_parts) if context_parts else "No additional context available."

    user_prompt = f"""## Input
- company_name: {company}
- company_domain: {company_domain or "N/A"}
- careers_url: {careers_url or "N/A"}

## Additional context gathered from free sources
{context}

Produce the dossier now. Return ONLY valid JSON matching the output schema."""

    try:
        response = router.generate(
            task="company_dossier_generation",
            system_prompt=DOSSIER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.3,
        )
        text = _strip_code_fences(response.text)
        data = json.loads(text)

        # Build the result from LLM output
        now = datetime.now(timezone.utc).isoformat()

        # Parse funding
        funding = None
        f = data.get("funding")
        if f:
            last_round = None
            lr = f.get("last_round")
            if lr:
                last_round = LastRound(
                    type=lr.get("type"),
                    amount_usd=lr.get("amount_usd"),
                    date=lr.get("date"),
                    lead_investors=lr.get("lead_investors", []),
                )
            funding = FundingDossier(
                founded=f.get("founded"),
                hq=f.get("hq"),
                public=f.get("public", False),
                stage=f.get("stage"),
                total_raised_usd=f.get("total_raised_usd"),
                valuation_usd=f.get("valuation_usd"),
                last_round=last_round,
                headcount=f.get("headcount"),
                headcount_trend=f.get("headcount_trend"),
                layoffs=f.get("layoffs", []),
                financial_health=f.get("financial_health"),
                confidence=f.get("confidence", 0.0),
                sources=[SourceRef(**s) for s in f.get("sources", [])],
            )

        # Parse sentiment
        sentiment = None
        s = data.get("sentiment")
        if s:
            sentiment = SentimentDossier(
                overall_rating_estimate=s.get("overall_rating_estimate"),
                rating_scale=s.get("rating_scale", "out of 5"),
                ceo_approval_pct=s.get("ceo_approval_pct"),
                recommend_pct=s.get("recommend_pct"),
                positives=s.get("positives", []),
                negatives=s.get("negatives", []),
                staleness_warning=s.get("staleness_warning"),
                confidence=s.get("confidence", 0.0),
                sources=[SourceRef(**src) for src in s.get("sources", [])],
            )

        # Parse fit
        fit = None
        ft = data.get("fit")
        if ft:
            fit = FitDossier(
                remote_policy=ft.get("remote_policy"),
                remote_walkback=ft.get("remote_walkback"),
                size_bucket=ft.get("size_bucket"),
                ic_vs_mgmt_culture=ft.get("ic_vs_mgmt_culture"),
                comp_band=ft.get("comp_band"),
                clearance_required=ft.get("clearance_required", False),
                confidence=ft.get("confidence", 0.0),
                sources=[SourceRef(**src) for src in ft.get("sources", [])],
            )

        # Parse verdict flags
        vf = data.get("verdict_flags", {})
        verdict_flags = VerdictFlags(
            green=vf.get("green", []),
            red=vf.get("red", []),
            watch=vf.get("watch", []),
        )

        return CompanyResearchResult(
            company_name=data.get("company", company),
            researched_at=data.get("researched_at", now),
            overall_confidence=data.get("overall_confidence", 0.0),
            summary=data.get("summary", ""),
            verdict_flags=verdict_flags,
            funding=funding,
            sentiment=sentiment,
            fit=fit,
            gaps=data.get("gaps", []),
            sources_used=["llm_dossier"],
        )
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def research_company(
    company: str,
    company_homepage: str | None = None,
    enable_llm: bool = True,
) -> CompanyResearchResult:
    """Research a company by aggregating data from multiple sources.

    Args:
        company: Company name to research.
        company_homepage: Optional company homepage URL (used as company_domain).
        enable_llm: Whether to attempt LLM dossier generation.

    Returns:
        CompanyResearchResult with whatever data could be gathered.
    """
    now = datetime.now(timezone.utc).isoformat()
    result = CompanyResearchResult(
        company_name=company,
        company_homepage=company_homepage,
        researched_at=now,
    )

    # 1. Wikipedia (company description — context for LLM and display)
    wiki = fetch_wikipedia_info(company)
    if wiki:
        result.wikipedia = wiki
        result.sources_used.append("wikipedia")

    # 2. Wikidata (structured data: founded year, headcount — context + fallback)
    wikidata_founded: int | None = None
    wikidata_headcount: int | None = None
    wikidata = fetch_wikidata_info(
        company,
        wikipedia_title=wiki.title if wiki else None,
    )
    if wikidata:
        wikidata_founded = wikidata.founded
        wikidata_headcount = wikidata.headcount
        result.sources_used.append("wikidata")

    # 3. LLM dossier generation (comprehensive: funding + sentiment + fit)
    if enable_llm:
        dossier = fetch_llm_dossier(
            company=company,
            company_domain=company_homepage,
            wikipedia_extract=wiki.extract if wiki else "",
            wikidata_founded=wikidata_founded,
            wikidata_headcount=wikidata_headcount,
        )
        if dossier:
            # Preserve Wikipedia info and merge sources
            dossier.wikipedia = wiki
            if "wikipedia" not in dossier.sources_used:
                dossier.sources_used.insert(0, "wikipedia")
            if "wikidata" not in dossier.sources_used and wikidata:
                dossier.sources_used.insert(1, "wikidata")
            # Merge Wikidata fallback into funding if LLM didn't populate it
            if wikidata and dossier.funding:
                if dossier.funding.founded is None and wikidata_founded:
                    dossier.funding.founded = wikidata_founded
                if dossier.funding.headcount is None and wikidata_headcount:
                    dossier.funding.headcount = wikidata_headcount
            elif wikidata and not dossier.funding:
                dossier.funding = wikidata
            result = dossier
        elif wikidata:
            # LLM unavailable — use Wikidata as fallback funding data
            result.funding = wikidata

    return result
