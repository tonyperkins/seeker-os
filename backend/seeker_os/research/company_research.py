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
import logging
from datetime import UTC, datetime
from pathlib import Path

import httpx

from seeker_os.research.models import (
    CompanyResearchResult,
    FitDossier,
    FundingDossier,
    LastRound,
    SentimentDossier,
    SourceRef,
    VerdictFlags,
    VerificationState,
    WikipediaInfo,
)
from seeker_os.research.retrieval.models import RetrievalSnippet

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Wikipedia adapter (free, no auth)
# ---------------------------------------------------------------------------

WIKIPEDIA_SEARCH_URL = "https://en.wikipedia.org/w/api.php"
WIKIPEDIA_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"

# Wikipedia requires a User-Agent header per their robot policy.
# Default is generic (no personal handles). Overridden per-call from company_research.yml.
_DEFAULT_USER_AGENT = "SeekerOS/0.1 (product; contact: admin@example.com)"


def _build_headers(cr_config=None) -> dict:
    """Build a fresh headers dict for this call's HTTP requests.

    Uses the user_agent from company_research config if available,
    otherwise falls back to the generic default. Returns a new dict
    each call — never mutates shared state.
    """
    ua = _DEFAULT_USER_AGENT
    if cr_config and cr_config.user_agent:
        ua = cr_config.user_agent
    return {"User-Agent": ua}


def _search_wikipedia(company: str, timeout: int = 10, headers: dict | None = None) -> str | None:
    """Search Wikipedia for a company page title. Returns the best-matching title or None."""
    params = {
        "action": "query",
        "list": "search",
        "srsearch": f"{company} company",
        "srlimit": "5",
        "format": "json",
    }
    try:
        resp = httpx.get(WIKIPEDIA_SEARCH_URL, params=params, headers=headers or {}, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        search_results = data.get("query", {}).get("search", [])
        if not search_results:
            return None
        # Return the first result — Wikipedia search is usually good at ranking
        return search_results[0]["title"]
    except (httpx.HTTPStatusError, httpx.RequestError):
        return None
    except Exception as e:
        logger.warning("Unexpected error in _search_wikipedia('%s'): %s", company, e)
        return None


def fetch_wikipedia_info(company: str, timeout: int = 10, headers: dict | None = None) -> WikipediaInfo | None:
    """Fetch company information from Wikipedia.

    1. Search for the company page
    2. Fetch the page summary via REST API
    3. Return structured info
    """
    title = _search_wikipedia(company, timeout=timeout, headers=headers)
    if not title:
        return None

    url = WIKIPEDIA_SUMMARY_URL.format(title=title.replace(" ", "_"))
    try:
        resp = httpx.get(url, headers=headers or {}, timeout=timeout)
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
    except (httpx.HTTPStatusError, httpx.RequestError):
        return None
    except Exception as e:
        logger.warning("Unexpected error in fetch_wikipedia_info('%s'): %s", company, e)
        return None


# ---------------------------------------------------------------------------
# Wikidata adapter (free, no auth) — structured company data
# ---------------------------------------------------------------------------

WIKIDATA_ENTITY_URL = "https://www.wikidata.org/wiki/Special:EntityData/{item_id}.json"


def _get_wikidata_item_id(title: str, timeout: int = 10, headers: dict | None = None) -> str | None:
    """Get the Wikidata item ID for a Wikipedia page title."""
    params = {
        "action": "query",
        "prop": "pageprops",
        "ppprop": "wikibase_item",
        "titles": title,
        "format": "json",
    }
    try:
        resp = httpx.get(WIKIPEDIA_SEARCH_URL, params=params, headers=headers or {}, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        pages = data.get("query", {}).get("pages", {})
        for _pid, page in pages.items():
            wb_item = page.get("pageprops", {}).get("wikibase_item")
            if wb_item:
                return wb_item
    except (httpx.HTTPStatusError, httpx.RequestError):
        pass
    except Exception as e:
        logger.warning("Unexpected error in _get_wikidata_item_id('%s'): %s", title, e)
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
    headers: dict | None = None,
) -> tuple[FundingDossier | None, str | None]:
    """Fetch structured company data from Wikidata.

    Returns a (FundingDossier, official_website) tuple. The official_website
    comes from Wikidata property P856 and is used for entity disambiguation
    against the company's known homepage domain. Either element may be None.
    """
    if not wikipedia_title:
        wikipedia_title = _search_wikipedia(company, timeout=timeout, headers=headers)
    if not wikipedia_title:
        return None, None

    item_id = _get_wikidata_item_id(wikipedia_title, timeout=timeout, headers=headers)
    if not item_id:
        return None, None

    try:
        resp = httpx.get(
            WIKIDATA_ENTITY_URL.format(item_id=item_id),
            headers=headers or {},
            timeout=timeout,
        )
        if resp.status_code != 200:
            return None, None
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

        # P856 = official website (used for entity disambiguation)
        official_website = None
        if "P856" in claims:
            p856_val = _extract_wikidata_value(claims["P856"][0])
            if isinstance(p856_val, str):
                official_website = p856_val

        # Only return if we found something useful
        if founded_year or employees:
            wikidata_url = f"https://www.wikidata.org/wiki/{item_id}"
            now = datetime.now(UTC).isoformat()
            return FundingDossier(
                founded=founded_year,
                headcount=str(employees) if employees is not None else None,
                confidence=0.6,
                sources=[SourceRef(url=wikidata_url, retrieved=now)],
            ), official_website
        # Even without founded/employees, return the official_website for verification
        return None, official_website
    except (httpx.HTTPStatusError, httpx.RequestError):
        pass
    except Exception as e:
        logger.warning("Unexpected error in fetch_wikidata_info('%s'): %s", company, e)
    return None, None


# ---------------------------------------------------------------------------
# LLM dossier generation (uses configured LLM providers)
# ---------------------------------------------------------------------------

_PROMPTS_DIR = Path(__file__).parent / "prompts"
DOSSIER_SYSTEM_PROMPT = (_PROMPTS_DIR / "company_dossier_system.txt").read_text(encoding="utf-8")


def _strip_code_fences(text: str) -> str:
    """Strip markdown code fences from LLM response text."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    return text


def _loads_dossier_json(text: str) -> dict:
    """Parse dossier JSON, with a bounded repair for minor malformation.

    Models occasionally emit a stray prefix/suffix around the JSON object (a
    lead-in sentence, a trailing note). On a decode failure, retry once against
    the substring spanning the outermost braces before giving up. Raises
    json.JSONDecodeError if the text still can't be parsed.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start:end + 1])  # may re-raise JSONDecodeError
        raise


def fetch_llm_dossier(
    company: str,
    company_domain: str | None = None,
    careers_url: str | None = None,
    wikipedia_extract: str = "",
    wikidata_founded: int | None = None,
    wikidata_headcount: str | None = None,
    jd_text: str = "",
    retrieval_snippets: list[RetrievalSnippet] | None = None,
    fit_preferences_text: str = "",
    operation_id: str | None = None,
) -> CompanyResearchResult | None:
    """Generate a full company dossier using the configured LLM.

    This is a single comprehensive LLM call that produces the entire dossier:
    funding, sentiment, fit, verdict flags, and gaps. When no LLM providers
    are configured, returns None.

    Context from Wikipedia/Wikidata is passed to the LLM to improve accuracy.
    When retrieval_snippets are provided (Phase 3), they are injected as
    sourced context with URLs, and the prompt instructs the model to attach
    those URLs to claims.
    """
    try:
        from seeker_os.config import get_settings
        from seeker_os.llm.router import ModelRouter
    except ImportError:
        return None

    try:
        settings = get_settings()
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
    if jd_text:
        context_parts.append(f"## Job description (primary source — may name investors, stage, remote policy)\n---\n{jd_text}\n---")

    # Phase 3: inject retrieval snippets as sourced context
    retrieval_context = ""
    if retrieval_snippets:
        retrieval_lines = []
        for i, snip in enumerate(retrieval_snippets, 1):
            retrieval_lines.append(
                f"[{i}] URL: {snip.url}\n"
                f"    Source: {snip.source_domain}\n"
                f"    Title: {snip.title}\n"
                f"    Snippet: {snip.snippet}"
            )
        retrieval_context = (
            "## Retrieved web search results (sourced — cite these URLs in claims)\n"
            "---\n"
            + "\n".join(retrieval_lines)
            + "\n---\n"
            "IMPORTANT: When using information from these results, you MUST attach the "
            "corresponding URL to the claim in the sources array. Do not invent URLs. "
            "If a claim cannot be sourced from these results or the context above, set "
            "it to null and lower confidence."
        )
        context_parts.append(retrieval_context)

    context = "\n".join(context_parts) if context_parts else "No additional context available."

    fit_prefs_section = ""
    if fit_preferences_text:
        fit_prefs_section = f"\n\n## FIT_PREFERENCES (candidate's company preferences)\n{fit_preferences_text}"

    user_prompt = f"""## Input
- company_name: {company}
- company_domain: {company_domain or "N/A"}
- careers_url: {careers_url or "N/A"}

## Additional context gathered from free sources
{context}{fit_prefs_section}

Produce the dossier now. Return ONLY valid JSON matching the output schema."""

    try:
        response = router.generate(
            task="company_dossier_generation",
            system_prompt=DOSSIER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.3,
            operation_id=operation_id,
        )
    except Exception:
        logger.exception("LLM dossier generation call failed for company='%s'", company)
        return None

    # Parse the response separately so a malformed model reply (recoverable, and
    # distinct from a programming error) is diagnosable — and salvageable via a
    # bounded repair — rather than being swallowed by one broad except.
    text = _strip_code_fences(response.text)
    try:
        data = _loads_dossier_json(text)
    except json.JSONDecodeError as e:
        logger.error(
            "LLM dossier JSON parse failed for company='%s': %s. "
            "Wasted 2 paid research calls. Raw response (first 500 chars): %r",
            company, e, text[:500],
        )
        return None

    try:
        # Build the result from LLM output
        now = datetime.now(UTC).isoformat()

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
            researched_at=now,
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
        logger.exception(
            "Failed to assemble dossier for company='%s' from parsed JSON", company
        )
        return None


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def _build_fit_preferences_text(cr_config) -> str:
    """Build a human-readable fit preferences block from company_research config.

    Returns empty string if no fit preferences are configured, so the prompt
    section is omitted entirely and the LLM reports raw signals without judgment.
    """
    if not cr_config or not cr_config.fit_preferences:
        return ""

    fp = cr_config.fit_preferences
    lines: list[str] = []
    if fp.preferred_size_bucket:
        lines.append(f"- Preferred company size: {fp.preferred_size_bucket}")
    if fp.preferred_stage:
        lines.append(f"- Preferred funding stage: {fp.preferred_stage}")
    if fp.remote_policy:
        lines.append(f"- Remote policy preference: {fp.remote_policy}")
    if fp.ic_vs_mgmt:
        lines.append(f"- IC vs management culture: {fp.ic_vs_mgmt}")
    if not fp.clearance_ok:
        lines.append("- Clearance/citizenship requirements: NOT acceptable")
    if fp.notes:
        lines.append(f"- Additional notes: {fp.notes}")

    return "\n".join(lines) if lines else ""

def _run_retrieval_queries(
    adapter,
    company: str,
    funding_query_template: str = "{company} funding round investors valuation",
    sentiment_query_template: str = "{company} employee reviews sentiment glassdoor culture",
    cache_ttl_days: int = 7,
    force_refresh: bool = False,
    company_domain: str | None = None,
) -> list[RetrievalSnippet]:
    """Run retrieval queries for funding signals and employee sentiment.

    Returns a flat list of snippets from both query types. Each snippet
    carries a URL so the LLM can attach it to claims.

    Query templates come from config (company_research.yml → retrieval.*)
    and use a {company} placeholder. If a template omits the placeholder,
    it is used as-is without crashing.

    When company_domain is provided, the registrable domain is appended to
    the funding query string to disambiguate the right entity. The sentiment
    query is NOT modified — review sites (Glassdoor, Reddit) organize by
    company name, not domain, so appending the domain would suppress real
    reviews without improving disambiguation.

    Results are cached on disk (keyed by query string) to avoid redundant
    paid Tavily API calls. Set force_refresh=True to bypass the cache.
    """
    if not adapter:
        return []

    from seeker_os.discovery.cache import DiskCache

    cache = DiskCache(
        cache_dir=Path("data/retrieval_cache"),
        ttl_hours=cache_ttl_days * 24,
    )

    all_snippets: list[RetrievalSnippet] = []

    # Safe format: if {company} is not in the template, use it as-is
    try:
        funding_query = funding_query_template.format(company=company)
    except (KeyError, IndexError):
        funding_query = funding_query_template
    try:
        sentiment_query = sentiment_query_template.format(company=company)
    except (KeyError, IndexError):
        sentiment_query = sentiment_query_template

    # Disambiguate funding query by appending the registrable domain.
    # The domain appears in press coverage and funding announcements,
    # so this biases Tavily's ranking toward the right entity without
    # filtering out third-party sources (Crunchbase, TechCrunch, etc.).
    domain_token = _extract_host(company_domain) if company_domain else None
    if domain_token:
        funding_query = f"{funding_query} {domain_token}"

    queries = [funding_query, sentiment_query]

    for q in queries:
        # Check disk cache first (unless force_refresh)
        if not force_refresh:
            cached = cache.get(q)
            if cached is not None:
                try:
                    raw = json.loads(cached)
                    snippets = [RetrievalSnippet(**item) for item in raw]
                    all_snippets.extend(snippets)
                    logger.debug("Retrieval cache hit for query '%s'", q)
                    continue
                except Exception:
                    logger.debug("Retrieval cache parse failed for '%s' — re-fetching", q)

        # Budget guard — check caps before making a paid call
        adapter_type = getattr(adapter, "type", "tavily")
        try:
            from seeker_os.config import get_settings
            obs = get_settings().observability
            daily_cap = obs.budget_caps.tavily_daily_cap if adapter_type == "tavily" else 0
            monthly_cap = obs.budget_caps.tavily_monthly_cap if adapter_type == "tavily" else 0
        except Exception:
            daily_cap = 0
            monthly_cap = 0

        from seeker_os.observability.budget_guard import check_budget, record_call

        if not check_budget(adapter_type, daily_cap, monthly_cap):
            logger.warning(
                "budget_cap_exceeded: skipping retrieval query '%s' — "
                "%s daily/monthly cap reached", q, adapter_type,
            )
            continue

        # Cache miss or force_refresh — call the adapter
        try:
            snippets = adapter.search(q)
            all_snippets.extend(snippets)
            record_call(adapter_type, q, "succeeded")
            # Cache the results as JSON
            try:
                cache.set(q, json.dumps([s.model_dump() for s in snippets]))
            except Exception:
                logger.debug("Failed to cache retrieval results for '%s'", q)
        except Exception as e:
            record_call(adapter_type, q, "failed", str(e))
            logger.warning("Retrieval query '%s' failed: %s", q, e)

    return all_snippets


def _apply_staleness_flags(
    result: CompanyResearchResult,
    staleness_months: int,
) -> None:
    """Flag sentiment themes older than staleness_months as stale.

    Mutates result in place: sets staleness_warning on the sentiment dossier
    if any theme's age_months exceeds the threshold.
    """
    if not result.sentiment:
        return

    stale_themes: list[str] = []
    for theme in result.sentiment.positives + result.sentiment.negatives:
        if theme.age_months is not None and theme.age_months > staleness_months:
            stale_themes.append(theme.theme)

    if stale_themes:
        existing = result.sentiment.staleness_warning or ""
        warning = (
            f"Sentiment signals older than {staleness_months} months: "
            + ", ".join(stale_themes)
        )
        result.sentiment.staleness_warning = (
            f"{existing}; {warning}" if existing else warning
        )


def _apply_confidence_floor(
    result: CompanyResearchResult,
    confidence_floor: float,
) -> None:
    """Mark the dossier as a stub if overall_confidence is below the floor."""
    if result.overall_confidence < confidence_floor:
        result.is_stub = True


def _apply_verification_degradation(
    result: CompanyResearchResult,
    verification_state: VerificationState,
    mismatch_confidence: float,
) -> None:
    """Degrade section confidence for entity-verification failures.

    Only MISMATCH (wrong entity confirmed by P856 mismatch) triggers hard
    degradation. Section confidence is clamped via min() to mismatch_confidence,
    applied AFTER the *0.5 zero-source halving in _verify_dossier_sources so
    the clamp is authoritative — the final value cannot exceed mismatch_confidence.

    VERIFIED and UNVERIFIED states are NOT degraded. UNVERIFIED covers P856
    missing and domain-absent (manual-add) cases — common for small companies
    where uniform degradation would over-suppress the small-company funnel.

    After clamping sections, overall_confidence is recomputed as the mean of
    section confidences (downward only) so is_stub reflects the degradation.
    """
    if verification_state != VerificationState.MISMATCH:
        return

    for section in (result.funding, result.sentiment, result.fit):
        if section is None:
            continue
        section.confidence = min(section.confidence, mismatch_confidence)

    # Recompute overall_confidence: cap to mean of section confidences
    # (downward only) so _apply_confidence_floor sees the degraded state.
    section_confs = [
        s.confidence for s in [result.funding, result.sentiment, result.fit]
        if s is not None
    ]
    if section_confs:
        mean_section = sum(section_confs) / len(section_confs)
        if mean_section < result.overall_confidence:
            result.overall_confidence = mean_section


def _domain_matches_trust_entry(url: str, trust_entry: str) -> bool:
    """Check if a URL's domain matches a source_trust_order entry.

    Match is case-insensitive and subdomain-tolerant: a URL on
    "news.crunchbase.com" matches a trust entry "crunchbase.com".
    """
    try:
        from urllib.parse import urlparse
        host = urlparse(url).netloc.lower()
        if not host:
            return False
        entry = trust_entry.lower().strip()
        if not entry:
            return False
        # Exact match or subdomain match (host ends with ".entry")
        return host == entry or host.endswith("." + entry)
    except Exception:
        return False


def _extract_host(url: str) -> str | None:
    """Extract the lowercase hostname from a URL, stripping www. prefix."""
    try:
        from urllib.parse import urlparse
        host = urlparse(url).netloc.lower()
        if not host:
            return None
        return host.removeprefix("www.")
    except Exception:
        return None


def _domains_match(url_a: str | None, url_b: str | None) -> bool:
    """Check if two URLs refer to the same registrable domain.

    Bidirectional subdomain-tolerant match: a.acme.com matches acme.com,
    acme.com matches www.acme.com, but acme.com does NOT match acme.io.
    """
    if not url_a or not url_b:
        return False
    host_a = _extract_host(url_a)
    host_b = _extract_host(url_b)
    if not host_a or not host_b:
        return False
    return (
        host_a == host_b
        or host_a.endswith("." + host_b)
        or host_b.endswith("." + host_a)
    )


# Shared-host platforms where a subdomain is not a company-owned domain.
# Appending these to a funding query would inject a misleading token.
_GENERIC_HOST_SUFFIXES = (
    "notion.site",
    "webflow.io",
    "github.io",
    "githubusercontent.com",
    "medium.com",
    "wordpress.com",
    "substack.com",
    "wixsite.com",
    "squarespace.com",
    "shopify.com",
    "myshopify.com",
    "carrd.co",
    "linktr.ee",
)


def _is_generic_host(host: str | None) -> bool:
    """Check if a host is on a shared-host platform (not company-owned)."""
    if not host:
        return True
    return any(host == suffix or host.endswith("." + suffix) for suffix in _GENERIC_HOST_SUFFIXES)


def _rank_sources_by_trust(
    sources: list[SourceRef],
    trust_order: list[str],
) -> list[SourceRef]:
    """Stable-sort sources by source_trust_order rank.

    Sources whose domain matches an earlier entry in trust_order sort first.
    Domains not in the list sort last, preserving their original relative
    order (stable sort). Nothing is added or removed.
    """
    if not trust_order or not sources:
        return sources

    def trust_rank(src: SourceRef) -> int:
        for i, entry in enumerate(trust_order):
            if _domain_matches_trust_entry(src.url, entry):
                return i
        return len(trust_order)  # unlisted → after all known entries

    return sorted(sources, key=trust_rank)


# ---------------------------------------------------------------------------
# URL verification — strip model-invented URLs not present in retrieval results
# ---------------------------------------------------------------------------

_TRACKING_PARAM_PREFIXES = ("utm_",)
_TRACKING_PARAM_EXACT = frozenset({
    "ref", "source", "fbclid", "gclid", "msclkid", "yclid",
    "_hsenc", "_hsmi", "mc_cid", "mc_eid", "igshid",
})


def _strip_tracking_params(query: str) -> str:
    """Remove known tracking parameters from a query string, keep meaningful ones."""
    from urllib.parse import parse_qsl, urlencode

    if not query:
        return ""
    pairs = parse_qsl(query, keep_blank_values=True)
    kept = [
        (k, v) for k, v in pairs
        if not any(k.startswith(p) for p in _TRACKING_PARAM_PREFIXES)
        and k.lower() not in _TRACKING_PARAM_EXACT
    ]
    return urlencode(kept)


def _normalize_url(url: str) -> str:
    """Normalize a URL for comparison: lowercase host, strip trailing slash, strip fragment, strip tracking params."""
    from urllib.parse import urlsplit, urlunsplit

    if not url:
        return ""
    parts = urlsplit(url.strip())
    host = (parts.netloc or "").lower()
    path = parts.path.rstrip("/") or ""
    query = _strip_tracking_params(parts.query)
    return urlunsplit((parts.scheme.lower(), host, path, query, ""))


def _verify_section_sources(
    sources: list[SourceRef],
    retrieved_urls: set[str],
) -> tuple[list[SourceRef], int]:
    """Filter source URLs against the retrieved set.

    Returns (kept_sources, stripped_count).
    URLs not in the retrieved set are model-invented and removed.
    """
    kept: list[SourceRef] = []
    stripped = 0
    for src in sources:
        if _normalize_url(src.url) in retrieved_urls:
            kept.append(src)
        else:
            stripped += 1
    return kept, stripped


def _verify_dossier_sources(
    result: CompanyResearchResult,
    retrieval_snippets: list[RetrievalSnippet],
    extra_verified_urls: set[str] | None = None,
) -> None:
    """Enforce URL constraint: strip LLM-attached URLs not in the retrieved set.

    Called after the LLM dossier is built and before persistence.
    When retrieval did not run (no snippets), this is a no-op.
    For each section (funding, sentiment, fit), filters sources to only
    those URLs that were actually returned by the retrieval adapter or
    from other legitimate sources (Wikipedia, Wikidata).
    Sections left with zero sources have confidence halved and a note added.
    """
    if not retrieval_snippets:
        return

    retrieved_urls = {_normalize_url(s.url) for s in retrieval_snippets if s.url}
    if extra_verified_urls:
        retrieved_urls |= {_normalize_url(u) for u in extra_verified_urls if u}
    if not retrieved_urls:
        return

    for section_name, section in [
        ("funding", result.funding),
        ("sentiment", result.sentiment),
        ("fit", result.fit),
    ]:
        if section is None:
            continue
        kept, stripped = _verify_section_sources(section.sources, retrieved_urls)
        section.sources = kept
        section.stripped_count = stripped
        if stripped > 0 and len(kept) == 0:
            section.confidence = section.confidence * 0.5
            if section_name == "funding" and not section.financial_health:
                section.financial_health = "Sources unverified — LLM-attached URLs were not found in retrieval results."
            elif section_name == "sentiment":
                if not section.staleness_warning:
                    section.staleness_warning = "Sources unverified — LLM-attached URLs were not found in retrieval results."
                else:
                    section.staleness_warning += " | Sources unverified — URLs stripped."
            result.gaps.append(f"{section_name}: all sources stripped (model-invented URLs)")

    # Also verify retrieval_sources on the top-level result
    if result.retrieval_sources:
        kept_rs, stripped_rs = _verify_section_sources(result.retrieval_sources, retrieved_urls)
        result.retrieval_sources = kept_rs
        # retrieval_sources stripped count is implicit — they should all match

    # Recompute overall_confidence: cap to the mean of section confidences
    # so that a halved section pulls down the overall, and the confidence_floor
    # / is_stub check reflects the lost grounding.
    section_confs = [
        s.confidence for s in [result.funding, result.sentiment, result.fit]
        if s is not None
    ]
    if section_confs:
        mean_section = sum(section_confs) / len(section_confs)
        if mean_section < result.overall_confidence:
            result.overall_confidence = mean_section


def research_company(
    company: str,
    company_homepage: str | None = None,
    enable_llm: bool = True,
    jd_text: str = "",
    force_refresh: bool = False,
) -> CompanyResearchResult:
    """Research a company by aggregating data from multiple sources.

    Args:
        company: Company name to research.
        company_homepage: Optional company homepage URL (used as company_domain).
        enable_llm: Whether to attempt LLM dossier generation.
        jd_text: Optional job description text — fed to the LLM as a primary
            source. The JD frequently names funding stage, investors, and remote
            policy that the model otherwise cannot source.
        force_refresh: If True, bypass the on-disk retrieval cache for paid
            Tavily queries and re-fetch from the API.

    Returns:
        CompanyResearchResult with whatever data could be gathered.
    """
    now = datetime.now(UTC).isoformat()
    result = CompanyResearchResult(
        company_name=company,
        company_homepage=company_homepage,
        researched_at=now,
    )

    # Load company_research config for thresholds and retrieval
    cr_config = None
    retrieval_adapter = None
    try:
        from seeker_os.config import get_settings
        settings = get_settings()
        cr_config = settings.company_research
    except Exception as e:
        logger.error(
            "Failed to load Settings for company research — degrading to defaults: %s", e
        )

    # Build per-call headers from config (no shared mutable state)
    headers = _build_headers(cr_config)

    # Build retrieval adapter if configured
    if cr_config and cr_config.retrieval and cr_config.retrieval.type:
        try:
            from seeker_os.research.retrieval.registry import build_retrieval_adapter
            retrieval_adapter = build_retrieval_adapter(
                cr_config.retrieval.model_dump()
            )
        except Exception as e:
            logger.warning("Failed to build retrieval adapter: %s", e)

    # 1. Wikipedia (company description — context for LLM and display)
    wiki = fetch_wikipedia_info(company, headers=headers)
    if wiki:
        result.wikipedia = wiki
        result.sources_used.append("wikipedia")

    # 2. Wikidata (structured data: founded year, headcount — context + fallback)
    wikidata_founded: int | None = None
    wikidata_headcount: str | None = None
    wikidata, wikidata_official_website = fetch_wikidata_info(
        company,
        wikipedia_title=wiki.title if wiki else None,
        headers=headers,
    )
    if wikidata:
        wikidata_founded = wikidata.founded
        wikidata_headcount = wikidata.headcount
        result.sources_used.append("wikidata")

    # 2a. Entity disambiguation — verify Wikipedia/Wikidata against company_domain
    # Three states:
    #   VERIFIED: P856 matches company_domain (or Tavily domain-scoped, see below)
    #   UNVERIFIED: P856 missing, or company_domain absent (manual-add) — no hard degrade
    #   MISMATCH: P856 present but doesn't match — wrong entity, discard + hard degrade
    verification_state = VerificationState.UNVERIFIED
    company_host = _extract_host(company_homepage) if company_homepage else None
    # Skip verification for generic/shared-host domains (enrichment noise)
    if company_host and _is_generic_host(company_host):
        company_host = None

    if company_host:
        if wikidata_official_website:
            if _domains_match(wikidata_official_website, company_homepage):
                verification_state = VerificationState.VERIFIED
            else:
                # Domain mismatch — wrong entity. Discard all free-source data.
                logger.info(
                    "Entity disambiguation: discarding Wikipedia/Wikidata for '%s' — "
                    "P856 '%s' does not match company_homepage '%s'",
                    company, wikidata_official_website, company_homepage,
                )
                wiki = None
                result.wikipedia = None
                wikidata = None
                wikidata_founded = None
                wikidata_headcount = None
                if "wikipedia" in result.sources_used:
                    result.sources_used.remove("wikipedia")
                if "wikidata" in result.sources_used:
                    result.sources_used.remove("wikidata")
                result.gaps.append("Wikipedia/Wikidata entity discarded — domain mismatch")
                verification_state = VerificationState.MISMATCH
        else:
            # No P856 on the Wikidata entity — can't verify. Keep data, stay UNVERIFIED.
            pass
    # else: no company_domain (or generic host) — name-only retrieval, UNVERIFIED

    # 2b. Live retrieval (Phase 3) — funding + sentiment snippets with URLs
    retrieval_snippets: list[RetrievalSnippet] = []
    if retrieval_adapter:
        # retrieval_adapter is only built when cr_config and cr_config.retrieval are set,
        # so cr_config is guaranteed non-None inside this block.
        funding_template = cr_config.retrieval.funding_query_template
        sentiment_template = cr_config.retrieval.sentiment_query_template
        cache_ttl_days = cr_config.retrieval.retrieval_cache_ttl_days
        # Pass company_domain only if it's a real company host (not generic/shared)
        retrieval_domain = company_homepage if company_host else None
        retrieval_snippets = _run_retrieval_queries(
            retrieval_adapter, company,
            funding_query_template=funding_template,
            sentiment_query_template=sentiment_template,
            cache_ttl_days=cache_ttl_days,
            force_refresh=force_refresh,
            company_domain=retrieval_domain,
        )
        if retrieval_snippets:
            result.retrieval_used = True
            result.sources_used.append("retrieval")
            result.retrieval_sources = [
                SourceRef(url=snip.url, retrieved=now)
                for snip in retrieval_snippets
            ]
            result.retrieval_snippets = [
                {
                    "url": s.url,
                    "title": s.title,
                    "snippet": s.snippet,
                    "source_domain": s.source_domain,
                    "score": s.score,
                }
                for s in retrieval_snippets
            ]

    # 2c. Tavily domain verification — if Wikidata was absent but Tavily
    # returned snippets from the company's own domain, the entity is verified.
    # A company with no Wikipedia page but a clean domain-scoped Tavily result
    # is NOT a disambiguation failure and shouldn't be penalized.
    if (verification_state == VerificationState.UNVERIFIED
            and company_host and retrieval_snippets):
        for snip in retrieval_snippets:
            if _domains_match(snip.url, company_homepage):
                verification_state = VerificationState.VERIFIED
                logger.debug(
                    "Entity verified via Tavily domain match for '%s' "
                    "(snippet URL %s matches company_host %s)",
                    company, snip.url, company_host,
                )
                break

    # 3. LLM dossier generation (comprehensive: funding + sentiment + fit)
    dossier_operation_id: str | None = None
    if enable_llm:
        import uuid as _uuid
        dossier_operation_id = str(_uuid.uuid4())
        fit_prefs_text = _build_fit_preferences_text(cr_config)
        dossier = fetch_llm_dossier(
            company=company,
            company_domain=company_homepage,
            wikipedia_extract=wiki.extract if wiki else "",
            wikidata_founded=wikidata_founded,
            wikidata_headcount=wikidata_headcount,
            jd_text=jd_text,
            retrieval_snippets=retrieval_snippets or None,
            fit_preferences_text=fit_prefs_text,
            operation_id=dossier_operation_id,
        )
        if dossier:
            # Preserve Wikipedia info and merge sources (only if not discarded)
            if wiki:
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
                    dossier.funding.headcount = str(wikidata_headcount)
            elif wikidata and not dossier.funding:
                dossier.funding = wikidata
            # Preserve retrieval metadata from the pre-dossier result
            dossier.retrieval_used = result.retrieval_used
            dossier.retrieval_sources = result.retrieval_sources
            dossier.retrieval_snippets = result.retrieval_snippets
            if "retrieval" in result.sources_used and "retrieval" not in dossier.sources_used:
                dossier.sources_used.append("retrieval")
            result = dossier
        elif wikidata:
            # LLM unavailable — use Wikidata as fallback funding data
            result.funding = wikidata

    # 3b. Enforce URL constraint — strip model-invented URLs not in retrieval
    # Build the verified URL set from all legitimate sources: Tavily snippets +
    # Wikipedia/Wikidata URLs used in this run.
    extra_verified: set[str] = set()
    if wiki and wiki.url:
        extra_verified.add(wiki.url)
    # Wikidata doesn't carry a source URL, but if the LLM used Wikidata fallback
    # funding (Wikidata is a FundingDossier), its sources may have URLs
    if wikidata:
        for src in wikidata.sources:
            if src.url:
                extra_verified.add(src.url)
    _verify_dossier_sources(result, retrieval_snippets, extra_verified_urls=extra_verified)

    # 4. Apply Phase 3 thresholds
    # Use CompanyResearchConfig() to get canonical model defaults when cr_config
    # failed to load — avoids duplicating magic numbers in two places.
    from seeker_os.config import CompanyResearchConfig as _CRCfg
    _cr = cr_config or _CRCfg()
    staleness_months = _cr.staleness_months
    confidence_floor = _cr.confidence_floor
    mismatch_confidence = _cr.mismatch_confidence
    source_trust_order = _cr.source_trust_order
    _apply_staleness_flags(result, staleness_months)
    # Verification degradation runs AFTER _verify_dossier_sources (*0.5 halving)
    # and BEFORE _apply_confidence_floor (is_stub). The min() clamp ensures
    # mismatch_confidence is the authoritative ceiling for wrong-entity sections.
    _apply_verification_degradation(result, verification_state, mismatch_confidence)
    _apply_confidence_floor(result, confidence_floor)

    # 5. Rank sources by trust order (ordering only — no filtering, no inflation)
    if source_trust_order:
        result.retrieval_sources = _rank_sources_by_trust(
            result.retrieval_sources, source_trust_order,
        )
        if result.funding:
            result.funding.sources = _rank_sources_by_trust(
                result.funding.sources, source_trust_order,
            )
        if result.sentiment:
            result.sentiment.sources = _rank_sources_by_trust(
                result.sentiment.sources, source_trust_order,
            )
        if result.fit:
            result.fit.sources = _rank_sources_by_trust(
                result.fit.sources, source_trust_order,
            )

    result.verification_state = verification_state
    result._dossier_operation_id = dossier_operation_id  # type: ignore[attr-defined]
    return result
