"""LLM-based structured metadata extraction from JD text.

Uses the light tier to extract compensation, workplace type, seniority,
role type, commitment, and countries from job description text when the
ATS API doesn't provide structured fields.

Returns a Pydantic model with optional fields — callers merge with
ATS-provided and user-provided values (user > ATS > LLM).
"""

from __future__ import annotations

import json
import logging

from pydantic import BaseModel, field_validator

from seeker_os.config import Settings, get_settings

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = """\
You are a job posting parser. Extract structured metadata from the job description text.
Return ONLY valid JSON — no markdown, no code fences, no commentary.

Extract these fields (all optional — use null if not found or ambiguous):
{
  "jd_text": <string or null>,        // the cleaned job description text — ONLY the actual job posting
                                      // content (duties, requirements, company info, benefits).
                                      // EXCLUDE all site navigation, sign-in prompts, similar jobs,
                                      // people also viewed, recommended jobs, job alerts, footer,
                                      // cookie notices, and any other page chrome. If the input
                                      // is already a clean JD, return it as-is.
  "title": <string or null>,          // job title, e.g. "Staff AI Infrastructure Engineer"
  "company": <string or null>,        // company name, e.g. "Chainguard", "Google"
  "location": <string or null>,       // primary work location, e.g. "Austin, TX" or "Reston, VA"
  "comp_min": <integer or null>,      // minimum salary/baseline, in annual USD equivalent
  "comp_max": <integer or null>,      // maximum salary/top of range, in annual USD equivalent
  "comp_currency": <string or null>,  // e.g. "USD", "EUR", "GBP", "CAD"
  "workplace_type": <string or null>, // "Remote", "Hybrid", or "On-Site"
  "seniority_level": <string or null>, // "Senior", "Staff", "Principal", "Mid", "Junior", etc.
  "role_type": <string or null>,      // "Individual Contributor", "Manager", "Director", etc.
  "commitment": <string or null>,     // "Full Time", "Part Time", "Contract"
  "countries": [<string>, ...]        // list of country names mentioned as work locations
}

Rules:
- For jd_text, return ONLY the job posting content. The input may be a raw web page that includes navigation, similar jobs listings, sign-in forms, and other non-JD content. Strip all of that and return only the actual job description. If the input is already a clean JD (no page chrome), return it verbatim.
- For title, extract the job title from the JD header or first line (e.g. "Staff AI Infrastructure Engineer", "Senior SRE"). Use the full title as written.
- For company, look for the company name in the JD text (e.g. "Chainguard is the trusted source...", "About Us: Acme Corp"). Use the proper capitalized name.
- For location, extract the primary work location from the JD (e.g. "Austin, TX", "Reston, VA", "Remote, US"). If multiple locations are listed, use the first or primary one.
- For compensation, look for salary ranges, base salary, or pay bands. Convert to annual integers (strip commas/currency symbols). If only an hourly/monthly rate is given, annualize it (hourly * 2080, monthly * 12).
- For workplace_type, infer from phrases like "remote-first", "work from anywhere", "hybrid", "in-office", "on-site".
- For seniority_level, infer from the job title and experience requirements (e.g. "5-7 years" → "Senior", "10+ years" → "Staff/Principal").
- For role_type, infer from the job title and responsibilities (IC vs management).
- For countries, extract from location strings and JD text (e.g. "Canada - Remote; United States - Remote" → ["Canada", "United States"]).
- If a field cannot be determined, use null. Do not guess.
"""


class ExtractedMetadata(BaseModel):
    """Structured metadata extracted from JD text by the LLM."""
    jd_text: str | None = None
    title: str | None = None
    company: str | None = None
    location: str | None = None
    comp_min: int | None = None
    comp_max: int | None = None
    comp_currency: str | None = None
    workplace_type: str | None = None
    seniority_level: str | None = None
    role_type: str | None = None
    commitment: str | None = None
    countries: list[str] | None = None

    @field_validator("comp_min", "comp_max", mode="before")
    @classmethod
    def _round_comp(cls, v):
        if v is None:
            return None
        return int(round(float(v)))


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines)
    return text


def extract_metadata_from_jd(
    jd_text: str,
    title: str = "",
    location: str = "",
    settings: Settings | None = None,
    operation_id: str | None = None,
) -> ExtractedMetadata:
    """Use an LLM to extract structured metadata from JD text.

    Args:
        jd_text: The full job description text (HTML-stripped).
        title: Job title (helps the LLM infer seniority/role type).
        location: Location string from ATS (helps with workplace/countries).
        settings: Settings instance. If None, will create one.

    Returns:
        ExtractedMetadata with any fields the LLM could determine.
        Returns empty ExtractedMetadata (all None) on failure.
    """
    if not jd_text or len(jd_text) < 100:
        return ExtractedMetadata()

    if settings is None:
        settings = get_settings()

    if not settings.providers:
        logger.info("No LLM providers configured — skipping metadata extraction")
        return ExtractedMetadata()

    from seeker_os.llm.router import ModelRouter

    router = ModelRouter(settings)

    max_chars = settings.scoring.metadata_max_jd_chars if settings.scoring else 8000
    # When the input looks like a raw web page (not a clean JD), send more
    # text so the LLM can extract the JD content from amidst page chrome.
    if len(jd_text) > max_chars:
        max_chars = min(len(jd_text), 32000)
    user_prompt = (
        f"Job Title: {title or 'Unknown'}\n"
        f"Location: {location or 'Unknown'}\n"
        f"\nJob Description:\n{jd_text[:max_chars]}\n\n"
        f"Extract the structured metadata as JSON."
    )

    try:
        response = router.generate(
            task="metadata_extraction",
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.0,
            operation_id=operation_id,
        )
    except Exception as e:
        from seeker_os.llm.models import TruncationError as _TE
        if isinstance(e, _TE):
            logger.warning("LLM metadata extraction was truncated (max_tokens=%s, produced %d): %s",
                           e.requested_max_tokens, e.output_tokens, e)
        else:
            logger.warning("LLM metadata extraction failed: %s", e)
        return ExtractedMetadata()

    text = _strip_code_fences(response.text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("LLM metadata extraction returned invalid JSON: %s", text[:200])
        return ExtractedMetadata()

    try:
        return ExtractedMetadata(
            jd_text=data.get("jd_text"),
            title=data.get("title"),
            company=data.get("company"),
            location=data.get("location"),
            comp_min=data.get("comp_min"),
            comp_max=data.get("comp_max"),
            comp_currency=data.get("comp_currency"),
            workplace_type=data.get("workplace_type"),
            seniority_level=data.get("seniority_level"),
            role_type=data.get("role_type"),
            commitment=data.get("commitment"),
            countries=data.get("countries"),
        )
    except Exception as e:
        logger.warning("LLM metadata extraction parse error: %s", e)
        return ExtractedMetadata()
