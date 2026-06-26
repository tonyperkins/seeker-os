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
from pydantic import BaseModel

from seeker_os.config import Settings

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = """\
You are a job posting parser. Extract structured metadata from the job description text.
Return ONLY valid JSON — no markdown, no code fences, no commentary.

Extract these fields (all optional — use null if not found or ambiguous):
{
  "company": <string or null>,        // company name, e.g. "Chainguard", "Google"
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
- For company, look for the company name in the JD text (e.g. "Chainguard is the trusted source...", "About Us: Acme Corp"). Use the proper capitalized name.
- For compensation, look for salary ranges, base salary, or pay bands. Convert to annual integers (strip commas/currency symbols). If only an hourly/monthly rate is given, annualize it (hourly * 2080, monthly * 12).
- For workplace_type, infer from phrases like "remote-first", "work from anywhere", "hybrid", "in-office", "on-site".
- For seniority_level, infer from the job title and experience requirements (e.g. "5-7 years" → "Senior", "10+ years" → "Staff/Principal").
- For role_type, infer from the job title and responsibilities (IC vs management).
- For countries, extract from location strings and JD text (e.g. "Canada - Remote; United States - Remote" → ["Canada", "United States"]).
- If a field cannot be determined, use null. Do not guess.
"""


class ExtractedMetadata(BaseModel):
    """Structured metadata extracted from JD text by the LLM."""
    company: str | None = None
    comp_min: int | None = None
    comp_max: int | None = None
    comp_currency: str | None = None
    workplace_type: str | None = None
    seniority_level: str | None = None
    role_type: str | None = None
    commitment: str | None = None
    countries: list[str] | None = None


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
        settings = Settings()

    if not settings.providers:
        logger.info("No LLM providers configured — skipping metadata extraction")
        return ExtractedMetadata()

    from seeker_os.llm.router import ModelRouter

    router = ModelRouter(settings)

    user_prompt = (
        f"Job Title: {title or 'Unknown'}\n"
        f"Location: {location or 'Unknown'}\n"
        f"\nJob Description:\n{jd_text[:8000]}\n\n"
        f"Extract the structured metadata as JSON."
    )

    try:
        response = router.generate(
            task="metadata_extraction",
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.0,
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
            company=data.get("company"),
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
