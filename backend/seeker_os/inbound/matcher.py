"""Deterministic, evidence-preserving inbound-message matcher."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from seeker_os.config import EmailMatcherConfig
from seeker_os.dedup.normalize import normalize_company
from seeker_os.inbound.models import MatchResult, ParsedMessage

MATCHER_VERSION = "inbound-v1"
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+#.-]*", re.IGNORECASE)
_TITLE_STOPWORDS = {
    "and", "the", "for", "with", "engineer", "engineering", "developer",
    "senior", "staff", "principal", "lead", "manager", "director", "remote",
}


def _hostname(value: str | None) -> str:
    if not value:
        return ""
    candidate = value if "://" in value else f"https://{value}"
    host = (urlparse(candidate).hostname or "").lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def _domain_matches(sender_domain: str, candidate_domain: str) -> bool:
    return bool(
        sender_domain
        and candidate_domain
        and (
            sender_domain == candidate_domain
            or sender_domain.endswith(f".{candidate_domain}")
            or candidate_domain.endswith(f".{sender_domain}")
        )
    )


def _phrase_present(phrase: str, text: str) -> bool:
    words = _TOKEN_RE.findall(phrase.lower())
    if not words:
        return False
    pattern = r"\b" + r"[\s._&+-]+".join(re.escape(word) for word in words) + r"\b"
    return re.search(pattern, text, re.IGNORECASE) is not None


def _title_terms(title: str) -> set[str]:
    return {
        token.lower() for token in _TOKEN_RE.findall(title)
        if len(token) >= 3 and token.lower() not in _TITLE_STOPWORDS
    }


def _active_jobs(db) -> list:
    return db.execute(
        """
        SELECT id, title, company, company_homepage, apply_url, ats_source
        FROM jobs
        WHERE status IN ('applied', 'engaged')
        ORDER BY id
        """
    ).fetchall()


def match_message(db, message: ParsedMessage, config: EmailMatcherConfig) -> MatchResult:
    """Rank every candidate with positive evidence; never persist message body."""
    searchable = f"{message.subject}\n{message.body_text}".lower()
    common_names = {normalize_company(name) for name in config.common_company_names}
    mapped_ats = {
        _hostname(domain): {normalize_company(name) for name in companies}
        for domain, companies in config.ats_domain_companies.items()
    }
    has_application_context = any(
        _phrase_present(term, searchable) for term in config.application_context_terms
    )

    candidates: list[dict] = []
    for job in _active_jobs(db):
        features: list[dict] = []
        score = 0.0
        company_norm = normalize_company(job["company"] or "")

        job_domains = {
            domain for domain in (
                _hostname(job["company_homepage"]),
                _hostname(job["apply_url"]),
            ) if domain
        }
        matched_domains = sorted(
            domain for domain in job_domains
            if _domain_matches(message.sender_domain, domain)
        )
        if matched_domains:
            score += config.domain_weight
            features.append({
                "signal": "sender_domain",
                "weight": config.domain_weight,
                "evidence": matched_domains,
            })

        allowed_companies = mapped_ats.get(message.sender_domain, set())
        if company_norm and company_norm in allowed_companies:
            score += config.ats_company_weight
            features.append({
                "signal": "configured_ats_company",
                "weight": config.ats_company_weight,
                "evidence": message.sender_domain,
            })

        if (
            company_norm
            and company_norm not in common_names
            and _phrase_present(job["company"] or "", searchable)
        ):
            score += config.company_name_weight
            features.append({
                "signal": "company_name",
                "weight": config.company_name_weight,
                "evidence": job["company"],
            })

        title_terms = _title_terms(job["title"] or "")
        matched_title_terms = sorted(term for term in title_terms if _phrase_present(term, searchable))
        if matched_title_terms and title_terms:
            title_score = config.title_term_weight * len(matched_title_terms) / len(title_terms)
            score += title_score
            features.append({
                "signal": "title_terms",
                "weight": round(title_score, 6),
                "evidence": matched_title_terms,
            })

        if has_application_context and features:
            score += config.application_context_weight
            features.append({
                "signal": "application_context",
                "weight": config.application_context_weight,
                "evidence": True,
            })

        if features:
            candidates.append({
                "job_id": job["id"],
                "score": round(min(score, 1.0), 6),
                "features": features,
            })

    candidates.sort(key=lambda item: (-item["score"], item["job_id"]))
    if not candidates:
        return MatchResult(None, 0.0, {}, [], "unmatched", MATCHER_VERSION)

    winner = candidates[0]
    matched = winner["score"] >= config.match_threshold
    ambiguous = (
        matched
        and len(candidates) > 1
        and winner["score"] - candidates[1]["score"] <= config.ambiguity_margin
    )
    return MatchResult(
        suggested_job_id=winner["job_id"] if matched and not ambiguous else None,
        score=winner["score"],
        features={
            "winner": winner["features"],
            "ambiguous": ambiguous,
            "threshold": config.match_threshold,
            "ambiguity_margin": config.ambiguity_margin,
        },
        candidates=candidates,
        state="matched" if matched else "unmatched",
        matcher_version=MATCHER_VERSION,
    )
