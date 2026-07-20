"""Deterministic (no LLM, no embeddings) bullet relevance ranking and
near-duplicate collapse for Phase 1 recent-tier bullet selection.

This is the "deterministic layer decides what goes in" half of the Phase 1
pipeline: pure lexical scoring against the JD text, followed by a
near-duplicate collapse and a hard cap. The LLM never sees dropped
candidates and never chooses what to drop — see resume/generator.py for how
the selected set is injected into the generation prompt.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

from seeker_os.resume.master_parser import BulletUnit, CategoryBlock, ProjectBlock

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+.#/-]*")

# General-purpose English stopwords (function words) — distinct from the
# configurable title_stopwords, which filter seniority/generic *title* terms
# from earning the title-match boost, not from tokenization in general.
_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "for",
    "with", "at", "by", "from", "as", "is", "are", "was", "were", "be",
    "been", "being", "this", "that", "these", "those", "it", "its",
    "into", "across", "over", "under", "than", "then", "so", "such",
    "not", "no", "do", "does", "did", "have", "has", "had", "will",
    "would", "can", "could", "should", "may", "might", "must", "about",
    "which", "who", "whom", "their", "our", "your", "his", "her", "they",
    "we", "you", "i", "he", "she", "them", "us", "including", "via",
    "all", "any", "each", "other", "more", "most", "some",
})

# Default generic-business-vocabulary stopwords. These are non-discriminating
# terms that appear in almost every JD and resume but carry no technical
# signal. Configurable via channel_rules.yml (business_stopwords); this is
# the fallback default set.
_DEFAULT_BUSINESS_STOPWORDS = frozenset({
    "client", "team", "years", "measurable", "location", "building",
    "through", "ensure", "across", "support", "strong", "proven",
    "opportunity", "experience", "role", "position", "candidates",
    "benefits", "working", "work", "ability", "looking", "join",
    "help", "helping", "driving", "drive",
})

# JD section headers that mark responsibility/qualification content.
# Matched case-insensitively at the start of a line.
_JD_SECTION_HEADERS = re.compile(
    r"^(?:#{1,6}\s*)?(?:"
    r"responsibilities|qualifications|requirements|"
    r"what you'?ll do|what you will do|"
    r"key responsibilities|core responsibilities|"
    r"job responsibilities|job requirements|"
    r"preferred qualifications|preferred skills|"
    r"nice.to.have|nice to haves|"
    r"technical requirements|technical qualifications|"
    r"skills and qualifications|skills and experience|"
    r"about the role|about the position|"
    r"what you'?ll be doing|what you will be doing"
    r")\s*:?\s*$",
    re.IGNORECASE,
)

# Boilerplate patterns — lines to exclude when no section headers are found.
# All patterns are word-bounded to prevent substring hazards (e.g. "pto"
# matching inside "crypto", "eeo" inside "theoretical", "remote" inside
# "remotely-sensed"). Multi-word phrases use \b at both ends; single tokens
# use \b at both ends. Hyphenated patterns like "on-site" use \b and the
# optional hyphen.
_BOILERPLATE_RE = re.compile(
    r"(?:"
    r"\bequal opportunity\b|\beeo\b|\bdiversity\b|\binclusion\b|"
    r"\bbenefits\b|\bhealth insurance\b|\b401k\b|\bpto\b|\bpaid time off\b|"
    r"\bcompensation\b|\bsalary range\b|\bpay range\b|\bbase salary\b|"
    r"\bwe offer\b|\bour benefits\b|"
    r"\breasonable accommodation\b|\bdisability\b|"
    r"\bbackground check\b|\bdrug screen\b|"
    r"\bvisa sponsorship\b|\bsponsorship\b|"
    r"\bremote\b|\bhybrid\b|\bon[.-]site\b|\bwork from home\b"
    r")",
    re.IGNORECASE,
)


def tokenize(text: str, business_stopwords: frozenset[str] | None = None) -> list[str]:
    """Lowercase, extract word-like tokens, drop generic and business stopwords."""
    raw = _TOKEN_RE.findall(text.lower())
    stops = _STOPWORDS | (business_stopwords or _DEFAULT_BUSINESS_STOPWORDS)
    return [t for t in raw if t not in stops and len(t) > 1]


def strip_html_to_text(html: str) -> str:
    """Strip HTML tags/entities to plain text, preserving block structure.

    Converts block-element boundaries (<br>, </p>, </div>, headings, list
    items, table rows) to newlines so the JD's structure survives for
    line-by-line scope_jd_text processing.  Whitespace is normalized per
    line; blank lines are dropped.
    """
    import html as html_mod
    if not html:
        return ""
    if "<" not in html:
        return html_mod.unescape(html)  # plain text, but still decode entities
    # Remove script and style blocks entirely
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    # <br> and block-closing tags become line breaks
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(
        r"</(p|div|h[1-6]|tr|ul|ol|section|article|header|footer|blockquote|pre|dd|dt)\s*>",
        "\n", text, flags=re.IGNORECASE,
    )
    # List items start on a new line with a bullet
    text = re.sub(r"<li[^>]*>", "\n- ", text, flags=re.IGNORECASE)
    # Remove all remaining tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Decode HTML entities
    text = html_mod.unescape(text)
    # Normalize spaces/tabs within each line, drop blank lines
    lines = [re.sub(r"[ \t\r\f\v]+", " ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def scope_jd_text(jd_text: str) -> tuple[str, str]:
    """Extract scoring-relevant text from a JD, avoiding boilerplate.

    If recognizable section headers (Responsibilities, Qualifications, etc.)
    are present, only the text under those sections is used. Otherwise, falls
    back to full text with boilerplate lines (EEO, benefits, compensation)
    filtered out.

    Returns (scoped_text, mode) where mode is "section_headers" or
    "full_text_filtered" or "full_text" (no boilerplate found to filter).
    """
    lines = jd_text.splitlines()
    header_indices = [
        i for i, line in enumerate(lines)
        if _JD_SECTION_HEADERS.match(line.strip())
    ]

    if header_indices:
        # Collect text from each header to the next header or section break.
        scoped_lines: list[str] = []
        for idx_pos, start in enumerate(header_indices):
            # The header line itself may contain content after the colon on
            # the same line — include it.
            scoped_lines.append(lines[start])
            end = header_indices[idx_pos + 1] if idx_pos + 1 < len(header_indices) else len(lines)
            for j in range(start + 1, end):
                line_stripped = lines[j].strip()
                # Stop at a new markdown heading or horizontal rule that isn't
                # a recognized section header.
                if line_stripped.startswith("#") and not _JD_SECTION_HEADERS.match(line_stripped):
                    break
                if line_stripped == "---":
                    break
                # Stop at unrecognized header-like lines to prevent section
                # bleeding. Two patterns:
                # 1. Short line ending with a colon (e.g. "Benefits:")
                # 2. Bare title-case header without a colon (e.g. "Benefits")
                #    — short, not a bullet, not empty, starts with uppercase,
                #    and not a recognized section header.
                if (
                    len(line_stripped) < 50
                    and line_stripped.endswith(":")
                    and not _JD_SECTION_HEADERS.match(line_stripped)
                    and not line_stripped.startswith("-")
                ):
                    break
                if (
                    len(line_stripped) < 50
                    and not line_stripped.endswith(":")
                    and not line_stripped.startswith("-")
                    and line_stripped
                    and line_stripped[0].isupper()
                    and not line_stripped.isupper()
                    and not _JD_SECTION_HEADERS.match(line_stripped)
                    and not any(c.isdigit() for c in line_stripped)
                    and len(line_stripped.split()) <= 3
                ):
                    break
                scoped_lines.append(lines[j])
        return "\n".join(scoped_lines), "section_headers"

    # No headers found — filter boilerplate lines from full text.
    filtered = [
        line for line in lines
        if not _BOILERPLATE_RE.search(line)
    ]
    if len(filtered) < len(lines):
        result = "\n".join(filtered)
        # Blind-selection guard: if filtering collapsed the JD to near-empty,
        # fall back to the raw text.  The boilerplate filter is a nicety, not
        # a correctness gate — an over-aggressive regex must never starve the
        # scorer of all JD terms.
        if len(result.strip()) < 100:
            return jd_text, "scope_collapsed"
        return result, "full_text_filtered"
    return jd_text, "full_text"


@dataclass
class ScoredBullet:
    bullet: BulletUnit
    score: float
    matched_terms: list[str] = field(default_factory=list)


def score_bullets(
    bullets: list[BulletUnit],
    jd_text: str,
    job_title: str,
    title_boost: float = 1.5,
    title_stopwords: frozenset[str] | set[str] = frozenset(),
    business_stopwords: frozenset[str] | set[str] | None = None,
) -> list[ScoredBullet]:
    """Score bullets by lexical overlap with the JD.

    Score = (sum of JD term-frequency weights for matched terms, with a
    title_boost multiplier on terms that also appear in the job title) /
    sqrt(bullet token count). Sqrt normalization (not linear) is used
    deliberately: linear normalization (divide by raw token count) unfairly
    penalizes longer bullets that legitimately match more JD terms, favoring
    terse single-match bullets over substantive multi-match ones.

    Title terms in `title_stopwords` (seniority/generic words like
    "principal", "senior") never earn the boost — they're not discriminating
    relevance signal for a bullet.

    `business_stopwords` are non-discriminating terms (client, team, years,
    etc.) that are excluded from both the JD term map and bullet token
    matching — they must never appear in matched_terms or contribute to
    scores.
    """
    biz_stops = frozenset(business_stopwords) if business_stopwords else _DEFAULT_BUSINESS_STOPWORDS
    jd_terms = Counter(tokenize(jd_text, business_stopwords=biz_stops))
    lowered_stopwords = {t.lower() for t in title_stopwords}
    title_terms = set(tokenize(job_title, business_stopwords=biz_stops)) - lowered_stopwords

    scored: list[ScoredBullet] = []
    for bullet in bullets:
        tokens = tokenize(bullet.text, business_stopwords=biz_stops)
        if not tokens:
            scored.append(ScoredBullet(bullet=bullet, score=0.0))
            continue
        matched: list[str] = []
        raw_score = 0.0
        for term in set(tokens):
            weight = jd_terms.get(term, 0)
            if weight == 0:
                continue
            if term in title_terms:
                weight *= title_boost
            raw_score += weight
            matched.append(term)
        normalized = raw_score / math.sqrt(len(tokens))
        scored.append(ScoredBullet(bullet=bullet, score=normalized, matched_terms=sorted(matched)))
    return scored


def _ngrams(tokens: list[str], n: int = 3) -> set[tuple[str, ...]]:
    if len(tokens) < n:
        return {tuple(tokens)} if tokens else set()
    return {tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1)}


def _jaccard(a: set, b: set) -> float:
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def collapse_near_duplicates(
    scored: list[ScoredBullet],
    threshold: float,
    ngram_size: int = 3,
    business_stopwords: frozenset[str] | set[str] | None = None,
) -> tuple[list[ScoredBullet], list[dict]]:
    """Greedily collapse near-duplicate bullets (same competency claim,
    different objects — e.g. four "built X pipelines" variants) within a
    role's candidate pool. Highest-scored bullet in each similarity cluster
    is kept; the rest are dropped with a reason referencing which bullet
    they were collapsed into.

    Pinned bullets are never dedupe-dropped. If an unpinned bullet clusters
    with a pinned one, the unpinned bullet is dropped.

    Returns (kept, dropped) — kept is sorted by score descending (pinned
    bullets retain their position in the ordering by score).
    """
    biz_stops = frozenset(business_stopwords) if business_stopwords else _DEFAULT_BUSINESS_STOPWORDS
    # Pinned bullets first (so they're kept before any unpinned duplicates),
    # then by score descending.
    ordered = sorted(scored, key=lambda s: (not s.bullet.pinned, -s.score))
    kept: list[ScoredBullet] = []
    kept_ngrams: list[tuple[ScoredBullet, set]] = []
    dropped: list[dict] = []

    for candidate in ordered:
        candidate_ngrams = _ngrams(tokenize(candidate.bullet.text, business_stopwords=biz_stops), ngram_size)
        collapsed_into = None
        for kept_bullet, kept_ng in kept_ngrams:
            if _jaccard(candidate_ngrams, kept_ng) >= threshold:
                # If the candidate is pinned, never drop it — even if it
                # clusters with an already-kept bullet. Keep both.
                if candidate.bullet.pinned:
                    continue
                collapsed_into = kept_bullet
                break
        if collapsed_into is not None:
            dropped.append({
                "index": candidate.bullet.bullet_index,
                "reason": "deduped",
                "collapsed_into_index": collapsed_into.bullet.bullet_index,
                "score": round(candidate.score, 4),
            })
        else:
            kept.append(candidate)
            kept_ngrams.append((candidate, candidate_ngrams))

    return kept, dropped


@dataclass
class SelectionResult:
    role_id: str
    candidate_count: int
    post_dedupe_count: int
    selected: list[dict] = field(default_factory=list)
    dropped: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    jd_scope_mode: str = ""


def select_bullets_for_role(
    bullets: list[BulletUnit],
    jd_text: str,
    job_title: str,
    cap: int,
    near_duplicate_threshold: float,
    title_boost: float = 1.5,
    title_stopwords: frozenset[str] | set[str] = frozenset(),
    business_stopwords: frozenset[str] | set[str] | None = None,
) -> SelectionResult:
    """Full Phase 1 selection pipeline for one role: rank, dedupe, cap.

    Pinned bullets (bullet.pinned=True) bypass ranking entirely and consume
    cap slots first, in master order. Ranking fills remaining slots from
    unpinned bullets. If pinned count exceeds the cap, all pinned bullets are
    kept anyway and a "pinned_exceeds_cap" warning is recorded — pins are
    authorial intent and win over caps.

    Pinned bullets are exempt from near-duplicate collapse (never dedupe-drop
    a pinned bullet; if an unpinned bullet clusters with a pinned one, the
    unpinned bullet is dropped).

    Returns a SelectionResult carrying enough detail (per-bullet scores and
    per-dropped-bullet reasons) to be recorded verbatim in the evaluation
    ledger for audit/inspection — every decision here must be inspectable
    after the fact when a generation looks wrong.
    """
    if not bullets:
        return SelectionResult(role_id="", candidate_count=0, post_dedupe_count=0)

    biz_stops = frozenset(business_stopwords) if business_stopwords else _DEFAULT_BUSINESS_STOPWORDS
    role_id = bullets[0].role_id

    # JD section scoping — extract scoring terms from relevant sections only.
    scoped_jd, jd_scope_mode = scope_jd_text(jd_text)

    pinned_bullets = [b for b in bullets if b.pinned]
    unpinned_bullets = [b for b in bullets if not b.pinned]

    # Score all bullets (pinned get scored too, for audit records, but their
    # score doesn't affect selection — they're always kept).
    scored = score_bullets(
        bullets, scoped_jd, job_title, title_boost, title_stopwords, biz_stops,
    )
    scored_map = {s.bullet.bullet_index: s for s in scored}

    # Collapse near-duplicates among ALL bullets, but pinned bullets are
    # never dropped by dedupe.
    kept, deduped_dropped = collapse_near_duplicates(
        scored, near_duplicate_threshold, business_stopwords=biz_stops,
    )

    # Separate kept into pinned and ranked.
    kept_pinned = [sb for sb in kept if sb.bullet.pinned]
    kept_ranked = [sb for sb in kept if not sb.bullet.pinned]

    warnings: list[str] = []
    if len(pinned_bullets) > cap:
        warnings.append("pinned_exceeds_cap")

    # Pinned bullets fill cap slots first (in master order, not score order).
    # Remaining slots go to ranked bullets by score.
    remaining_cap = max(0, cap - len(kept_pinned))
    selected_ranked = kept_ranked[:remaining_cap]
    capped_dropped = kept_ranked[remaining_cap:]

    # Build selected list: pinned first (in master order), then ranked.
    pinned_indices = {sb.bullet.bullet_index for sb in kept_pinned}
    selected_pinned = [
        sb for sb in kept_pinned
        if sb.bullet.bullet_index in pinned_indices
    ]
    # Pinned bullets in master order (original bullet_index order).
    selected_pinned.sort(key=lambda sb: sb.bullet.bullet_index)

    result = SelectionResult(
        role_id=role_id,
        candidate_count=len(bullets),
        post_dedupe_count=len(kept),
        warnings=warnings,
        jd_scope_mode=jd_scope_mode,
    )

    for sb in selected_pinned:
        result.selected.append({
            "index": sb.bullet.bullet_index,
            "score": round(sb.score, 4),
            "matched_terms": sb.matched_terms,
            "reason": "pinned",
        })
    for sb in selected_ranked:
        result.selected.append({
            "index": sb.bullet.bullet_index,
            "score": round(sb.score, 4),
            "matched_terms": sb.matched_terms,
            "reason": "ranked",
        })
    for sb in capped_dropped:
        result.dropped.append({
            "index": sb.bullet.bullet_index,
            "reason": "capped",
            "score": round(sb.score, 4),
        })
    result.dropped.extend(deduped_dropped)
    return result


@dataclass
class ProjectSelectionResult:
    """Result of portfolio project selection — same audit schema as
    SelectionResult, extended with project-level decisions."""
    selected_project_ids: list[str] = field(default_factory=list)
    dropped_project_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    per_project: dict[str, SelectionResult] = field(default_factory=dict)
    jd_scope_mode: str = ""


def _match_always_include(project_title: str, always_include: list[str]) -> bool:
    """Case-insensitive match of config string against project heading text
    after '### ' up to the first '—' (or full heading if no dash)."""
    # Extract the match key: text before first em-dash, stripped
    key = project_title.split("—")[0].strip().lower()
    for entry in always_include:
        if entry.strip().lower() == key:
            return True
    return False


def select_projects(
    projects: list[ProjectBlock],
    jd_text: str,
    job_title: str,
    max_projects: int,
    max_bullets_per_project: int,
    always_include: list[str],
    near_duplicate_threshold: float,
    title_boost: float = 1.5,
    title_stopwords: frozenset[str] | set[str] = frozenset(),
    business_stopwords: frozenset[str] | set[str] | None = None,
) -> ProjectSelectionResult:
    """Phase 1d: deterministically select portfolio projects and their bullets.

    Always-include projects consume project slots first (matched by heading
    text). Remaining projects are ranked by mean of their top-K bullet scores
    (K = max_bullets_per_project), not sum — sum rewards bullet count over
    relevance. Within each selected project, bullets are ranked/capped by
    max_bullets_per_project with pin markers working identically to role
    bullets.

    Zero-bullet projects are pass-through: never counted against max_projects,
    never dropped, rendered verbatim.

    If an always_include entry matches zero parsed projects, an audit warning
    is recorded (label="always_include_unmatched").

    Returns ProjectSelectionResult with per-project SelectionResult audit
    records.
    """
    result = ProjectSelectionResult()
    if not projects:
        return result

    biz_stops = frozenset(business_stopwords) if business_stopwords else _DEFAULT_BUSINESS_STOPWORDS
    scoped_jd, jd_scope_mode = scope_jd_text(jd_text)
    result.jd_scope_mode = jd_scope_mode

    # Separate zero-bullet projects (pass-through) from candidates
    zero_bullet_projects = [p for p in projects if not p.has_bullets]
    candidate_projects = [p for p in projects if p.has_bullets]

    # Always-include matching
    always_include_ids: list[str] = []
    matched_entries: set[str] = set()
    for entry in always_include:
        entry_lower = entry.strip().lower()
        found = False
        for p in candidate_projects:
            key = p.title.split("—")[0].strip().lower()
            if key == entry_lower:
                always_include_ids.append(p.project_id)
                matched_entries.add(entry_lower)
                found = True
                break
        if not found:
            result.warnings.append(f"always_include_unmatched:{entry}")

    # Rank remaining (non-always-include) projects by mean of top-K bullet scores
    remaining = [p for p in candidate_projects if p.project_id not in always_include_ids]
    project_scores: list[tuple[float, ProjectBlock]] = []
    for p in remaining:
        scored = score_bullets(
            p.bullets, scoped_jd, job_title, title_boost, title_stopwords, biz_stops,
        )
        # Mean of top-K scores (K = max_bullets_per_project)
        top_k = sorted(scored, key=lambda s: -s.score)[:max_bullets_per_project]
        if top_k:
            mean_score = sum(s.score for s in top_k) / len(top_k)
        else:
            mean_score = 0.0
        project_scores.append((mean_score, p))

    # Sort by score descending, master order tie-break
    project_scores.sort(key=lambda x: (-x[0], x[1].heading_line))

    # Fill project slots: always-include first, then ranked
    remaining_slots = max(0, max_projects - len(always_include_ids))
    ranked_selected = [p for _, p in project_scores[:remaining_slots]]
    ranked_dropped = [p for _, p in project_scores[remaining_slots:]]

    selected_ids = always_include_ids + [p.project_id for p in ranked_selected]
    dropped_ids = [p.project_id for p in ranked_dropped]

    result.selected_project_ids = selected_ids
    result.dropped_project_ids = dropped_ids

    # Per-project bullet selection for selected projects
    for p in candidate_projects:
        if p.project_id not in selected_ids:
            continue
        bullet_result = select_bullets_for_role(
            bullets=p.bullets,
            jd_text=jd_text,
            job_title=job_title,
            cap=max_bullets_per_project,
            near_duplicate_threshold=near_duplicate_threshold,
            title_boost=title_boost,
            title_stopwords=title_stopwords,
            business_stopwords=biz_stops,
        )
        # Override role_id with project_id in the result for consistency
        bullet_result.role_id = p.project_id
        result.per_project[p.project_id] = bullet_result

    return result


# --- Phase 3: Competency category selection ---

# Markdown table cell separators and bold markers — stripped before scoring.
_MD_TABLE_RE = re.compile(r"\|")
_BOLD_RE = re.compile(r"\*\*")
# Parenthetical delimiters — used to extract parenthetical content for
# qualifier-phrase stripping (not blanket removal).
_PAREN_RE = re.compile(r"\(([^)]*)\)")

# Default qualifier phrases — honesty text that must not influence scoring.
# Overridden by channel_rules.yml competency_qualifier_stopwords.
_DEFAULT_QUALIFIER_STOPWORDS = frozenset({
    "broad familiarity", "ai-assisted", "ai-assistance", "ai-accelerated",
    "growing", "re-ramping", "dated", "production depth", "familiar",
    "minimal", "with significant ai assistance",
})


@dataclass
class CompetencySelectionResult:
    """Result of competency category selection — same audit schema family
    as SelectionResult and ProjectSelectionResult."""
    selected_labels: list[str] = field(default_factory=list)
    dropped_labels: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    jd_scope_mode: str = ""
    dropped_line_nos: set[int] = field(default_factory=set)
    # Per-category item capping: maps category label -> list of kept item
    # strings (verbatim from skills_text). Categories not present in this
    # dict render their items unchanged.
    kept_items: dict[str, list[str]] = field(default_factory=dict)
    # Per-category dropped items for audit: maps label -> list of dropped item strings.
    dropped_items: dict[str, list[str]] = field(default_factory=dict)


def _split_skill_items(skills_text: str) -> list[str]:
    """Split competency skills text into individual skill items on the
    ' · ' separator, respecting parenthetical depth so that ' · ' inside
    parentheses is not treated as an item boundary.

    Returns a list of item strings with surrounding whitespace stripped.
    """
    items: list[str] = []
    paren_depth = 0
    current: list[str] = []
    i = 0
    text = skills_text
    while i < len(text):
        ch = text[i]
        if ch == "(":
            paren_depth += 1
            current.append(ch)
        elif ch == ")":
            paren_depth = max(0, paren_depth - 1)
            current.append(ch)
        elif paren_depth == 0 and text[i:i + 3] == " · ":
            item = "".join(current).strip()
            if item:
                items.append(item)
            current = []
            i += 3
            continue
        else:
            current.append(ch)
        i += 1
    tail = "".join(current).strip()
    if tail:
        items.append(tail)
    return items


def _strip_qualifier_phrases(text: str, qualifier_stopwords: frozenset[str]) -> str:
    """Strip markdown table syntax, bold markers, and known qualifier
    phrases from competency skills text before tokenizing for scoring.

    Unlike blanket parenthetical removal, this only strips known honesty
    phrases (e.g. 'broad familiarity', 'AI-assisted') from within
    parentheticals. Real skill terms inside parentheticals (e.g.
    'EC2, S3, IAM, VPC') are preserved for scoring.

    Qualifiers still render verbatim — this function only affects the
    text used for scoring, never the rendered output.
    """
    text = _MD_TABLE_RE.sub(" ", text)
    text = _BOLD_RE.sub("", text)

    # Strip known qualifier phrases from within parentheticals
    def _strip_paren(m: re.Match) -> str:
        inner = m.group(1).strip().lower()
        for phrase in qualifier_stopwords:
            inner = inner.replace(phrase, "")
        # Re-wrap non-qualifier content in parens so it's still
        # tokenized as part of the skills text
        cleaned = inner.strip()
        if cleaned:
            return f"({cleaned})"
        return ""

    text = _PAREN_RE.sub(_strip_paren, text)
    return text


def select_competencies(
    categories: list[CategoryBlock],
    jd_text: str,
    job_title: str,
    max_categories: int,
    always_include: list[str],
    title_boost: float = 1.5,
    title_stopwords: frozenset[str] | set[str] = frozenset(),
    business_stopwords: frozenset[str] | set[str] | None = None,
    label_boost: float = 1.5,
    qualifier_stopwords: frozenset[str] | set[str] | None = None,
    max_items_per_category: int = 0,
) -> CompetencySelectionResult:
    """Phase 3: deterministically select competency categories by JD relevance.

    Always-include categories consume slots first (matched case-insensitively
    against the category label). Remaining categories are scored by keyword
    overlap between their skills text (with only known qualifier phrases
    stripped) and the JD. The category label is also scored, with a
    label_boost multiplier applied to label tokens that match JD terms
    (sharing title_stopwords so generic label words like 'engineering'
    don't dominate).

    If max_items_per_category > 0, individual skill items within each
    selected category are ranked by JD relevance and only the top N render.
    Items are dropped whole, never truncated. Honesty qualifiers travel
    verbatim with surviving items. Categories with <= N items are unchanged.

    If an always_include entry matches zero parsed categories, an audit
    warning is recorded (label="competency_always_include_unmatched").

    Returns CompetencySelectionResult with selected/dropped labels, scores,
    line numbers for render filtering, and per-category kept/dropped items.
    """
    result = CompetencySelectionResult()
    if not categories:
        return result

    biz_stops = frozenset(business_stopwords) if business_stopwords else _DEFAULT_BUSINESS_STOPWORDS
    qual_stops = frozenset(qualifier_stopwords) if qualifier_stopwords else _DEFAULT_QUALIFIER_STOPWORDS
    scoped_jd, jd_scope_mode = scope_jd_text(jd_text)
    result.jd_scope_mode = jd_scope_mode

    # Always-include matching (case-insensitive against label)
    always_include_labels: list[str] = []
    for entry in always_include:
        entry_lower = entry.strip().lower()
        found = False
        for cat in categories:
            if cat.label.lower() == entry_lower:
                always_include_labels.append(cat.label)
                found = True
                break
        if not found:
            result.warnings.append(f"competency_always_include_unmatched:{entry}")

    # Score remaining (non-always-include) categories
    remaining = [c for c in categories if c.label not in always_include_labels]
    jd_terms = Counter(tokenize(scoped_jd, business_stopwords=biz_stops))
    lowered_stopwords = {t.lower() for t in title_stopwords}
    title_terms = set(tokenize(job_title, business_stopwords=biz_stops)) - lowered_stopwords

    scored_categories: list[tuple[float, CategoryBlock]] = []
    for cat in remaining:
        # Strip only known qualifier phrases (not all parentheticals)
        clean_skills = _strip_qualifier_phrases(cat.skills_text, qual_stops)
        skills_tokens = tokenize(clean_skills, business_stopwords=biz_stops)

        # Label tokens — scored separately with label_boost
        label_tokens = tokenize(cat.label, business_stopwords=biz_stops)
        label_tokens_filtered = [t for t in label_tokens if t not in lowered_stopwords]

        all_tokens = skills_tokens + label_tokens_filtered
        if not all_tokens:
            scored_categories.append((0.0, cat))
            continue

        label_token_set = set(label_tokens_filtered)
        raw_score = 0.0
        for term in set(all_tokens):
            weight = jd_terms.get(term, 0)
            if weight == 0:
                continue
            if term in title_terms:
                weight *= title_boost
            if term in label_token_set:
                weight *= label_boost
            raw_score += weight
        normalized = raw_score / math.sqrt(len(all_tokens))
        scored_categories.append((normalized, cat))

    # Sort by score descending, master order tie-break
    scored_categories.sort(key=lambda x: (-x[0], x[1].line_no))

    # Fill slots: always-include first, then ranked
    remaining_slots = max(0, max_categories - len(always_include_labels))
    ranked_selected = [cat for _, cat in scored_categories[:remaining_slots]]
    ranked_dropped = [cat for _, cat in scored_categories[remaining_slots:]]

    selected_labels = always_include_labels + [c.label for c in ranked_selected]

    result.selected_labels = selected_labels
    for cat in ranked_dropped:
        score = next((s for s, c in scored_categories if c.label == cat.label), 0.0)
        result.dropped_labels.append({
            "label": cat.label,
            "score": round(score, 4),
            "reason": "ranked_below_cutoff",
            "line_no": cat.line_no,
        })
    result.dropped_line_nos = {c.line_no for c in ranked_dropped}

    # --- Per-category item capping (Lever 2) ---
    if max_items_per_category > 0:
        # Build a lookup from label -> CategoryBlock for selected categories
        selected_cats = {c.label: c for c in categories if c.label in selected_labels}
        for label, cat in selected_cats.items():
            items = _split_skill_items(cat.skills_text)
            if len(items) <= max_items_per_category:
                continue  # Category has few enough items — unchanged

            # Score each item by JD keyword overlap (using same scoring
            # infrastructure as category scoring, but per-item)
            scored_items: list[tuple[float, int, str]] = []
            for idx, item in enumerate(items):
                clean = _strip_qualifier_phrases(item, qual_stops)
                item_tokens = tokenize(clean, business_stopwords=biz_stops)
                if not item_tokens:
                    scored_items.append((0.0, idx, item))
                    continue
                raw = 0.0
                for term in set(item_tokens):
                    weight = jd_terms.get(term, 0)
                    if weight == 0:
                        continue
                    if term in title_terms:
                        weight *= title_boost
                    raw += weight
                normalized = raw / math.sqrt(len(item_tokens))
                scored_items.append((normalized, idx, item))

            # Sort by score descending, original order tie-break
            scored_items.sort(key=lambda x: (-x[0], x[1]))

            kept = [item for _, _, item in scored_items[:max_items_per_category]]
            dropped = [item for _, _, item in scored_items[max_items_per_category:]]
            result.kept_items[label] = kept
            result.dropped_items[label] = dropped

    return result
