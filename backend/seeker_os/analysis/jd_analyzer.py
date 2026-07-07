"""JD Analysis agent — evaluates a single job posting against the candidate's profile.

Produces a fit verdict (APPLY / CONDITIONAL / MONITOR / SKIP) with a full breakdown:
named gaps, hard blockers, rubric scoring, comp assessment, positioning check,
company fit, and tailoring guidance.

The system prompt and output schema are defined here. All personal data (master
resume, preferences, accuracy rules, scoring rubric) is injected from YAML config
files — nothing is hardcoded.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

from seeker_os.config import Settings
from seeker_os.database import get_connection, json_decode, json_encode


_PROMPTS_DIR = Path(__file__).parent / "prompts"
SYSTEM_PROMPT = (_PROMPTS_DIR / "jd_analysis_system.txt").read_text(encoding="utf-8")
_USER_PROMPT_TEMPLATE = (_PROMPTS_DIR / "jd_analysis_user_template.txt").read_text(encoding="utf-8")


def _strip_code_fences(text: str) -> str:
    """Strip markdown code fences from LLM response text."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    return text


def _load_master_resume(settings: Settings) -> str:
    """Load the master resume text from the path in profile.yml."""
    if not settings.profile or not settings.profile.resume:
        return "(no master resume configured)"
    master_path = Path(settings.profile.resume.master_path).expanduser()
    if not master_path.exists():
        return f"(master resume not found at {master_path})"
    return master_path.read_text()


def _load_prefs_text(settings: Settings) -> str:
    """Load candidate preferences as a text block for the prompt."""
    if not settings.profile:
        return "(no profile configured)"
    p = settings.profile
    lines = [
        f"Comp floor: ${p.comp.floor:,}",
        f"Comp target: ${p.comp.target:,}",
        f"Comp stretch: ${p.comp.stretch:,}",
        f"Remote only: {p.location.remote_only}",
        f"Accepted cities: {', '.join(p.location.accepted_cities) or '(none)'}",
        f"Accepted states: {', '.join(p.location.accepted_states) or '(none)'}",
        f"Rejected cities: {', '.join(p.location.rejected_cities) or '(none)'}",
        f"Experience: {p.experience.years} years ({p.experience.anchor_phrase})",
        f"Role type: {p.employment.role_type}",
        f"Commitment: {p.employment.commitment}",
        f"Reject commitments: {', '.join(p.employment.reject_commitments) or '(none)'}",
        f"Reject role types: {', '.join(p.employment.reject_role_types) or '(none)'}",
        f"Blacklist: {', '.join(p.blacklist) or '(none)'}",
    ]
    if p.instructions:
        lines.append(f"Instructions: {p.instructions}")
    return "\n".join(lines)


def _load_accuracy_rules_text(settings: Settings) -> str:
    """Load analysis-relevant accuracy rules as a text block for the JD analysis prompt.

    Only emits rule types that are meaningful during analysis (not generation):
    - forbidden_technologies: never-claim items the model must not score as matches
    - disallowed_phrases: phrasing that must not appear in any generated output

    Generation-only rule types (required_phrases, experience_anchor,
    education_omission) are omitted — they constrain artifact text, not the
    analysis verdict, and add noise to the analysis prompt.
    """
    if not settings.profile or not settings.profile.resume:
        return "(no accuracy rules configured)"
    rules_path = settings.config_dir / "accuracy_rules.yml"
    if not rules_path.exists():
        return "(accuracy_rules.yml not found)"
    with open(rules_path) as f:
        data = yaml.safe_load(f)
    _ANALYSIS_RELEVANT = {"forbidden_technologies", "disallowed_phrases"}
    lines: list[str] = []
    for rule in data.get("rules", []):
        rule_type = rule.get("type", "")
        if rule_type not in _ANALYSIS_RELEVANT:
            continue
        lines.append(f"- [{rule.get('severity', 'high').upper()}] {rule['description']}")
        if rule_type == "disallowed_phrases" and rule.get("phrases"):
            lines.append(f"  Disallowed phrases: {', '.join(rule['phrases'])}")
        if rule_type == "forbidden_technologies" and rule.get("technologies"):
            lines.append(f"  FORBIDDEN TECHNOLOGIES (never-claim): {', '.join(rule['technologies'])}")
    return "\n".join(lines) if lines else "(no analysis-relevant rules defined)"


def _load_rubric_text(settings: Settings) -> str:
    """Load scoring rubric as a text block for the prompt."""
    if not settings.scoring:
        return "(no scoring rubric configured)"
    s = settings.scoring
    lines = [
        f"Post threshold: {s.post_threshold}",
        f"Per-company cap: {s.per_company_cap}",
        f"Max score: {s.max_score}",
        "",
        "Base scores:",
    ]
    for rule in s.base_scores:
        label = rule.label
        score = rule.score
        pattern = f" (pattern: {rule.pattern})" if rule.pattern else ""
        check = f" (check: {rule.check})" if rule.check else ""
        lines.append(f"  - {label}: {score}{pattern}{check}")
    lines.append("")
    lines.append("Positive modifiers:")
    for mod in s.positive_modifiers:
        pattern = f" (pattern: {mod.pattern})" if mod.pattern else ""
        lines.append(f"  - {mod.signal}: +{mod.points} (check: {mod.check}){pattern}")
    lines.append("")
    lines.append("Negative modifiers:")
    for mod in s.negative_modifiers:
        pattern = f" (pattern: {mod.pattern})" if mod.pattern else ""
        lines.append(f"  - {mod.signal}: {mod.points} (check: {mod.check}){pattern}")
    return "\n".join(lines)


def _load_identity_text(settings: Settings) -> str:
    """Load identity rules as a text block for the prompt."""
    identity = settings.identity
    if not identity:
        return "(no identity rules configured)"
    lines: list[str] = []
    if identity.positioning:
        lines.append(f"Positioning: {identity.positioning}")
    if identity.work_eligibility:
        lines.append(f"Work eligibility: {identity.work_eligibility}")
    if identity.experience_anchor.phrase:
        lines.append(f"Experience anchor: {identity.experience_anchor.phrase}")
        if identity.experience_anchor.applies_to:
            lines.append(f"  Applies to: {identity.experience_anchor.applies_to}")
    if identity.honest_qualifiers:
        lines.append("Honest qualifiers (verbatim — do not upgrade):")
        for hq in identity.honest_qualifiers:
            lines.append(f"  - {hq.skill}: {hq.framing}")
    if identity.never_claim:
        lines.append(f"Never claim: {', '.join(identity.never_claim)}")
    return "\n".join(lines) if lines else "(no identity rules configured)"


def _load_company_research_text(db, company: str) -> str:
    """Load the most recent cached company research dossier as a text block.

    Returns '(no company research available)' if no cached dossier exists.
    This is best-effort — analysis should still work without research.
    """
    if not company:
        return "(no company research available)"

    from seeker_os.dedup.normalize import normalize_company

    company_norm = normalize_company(company)
    if not company_norm:
        return "(no company research available)"

    row = db.execute(
        "SELECT * FROM company_research WHERE company_norm = ? ORDER BY researched_at DESC LIMIT 1",
        (company_norm,),
    ).fetchone()
    if not row:
        return "(no company research available)"

    lines: list[str] = []

    summary = row["summary"] if "summary" in row.keys() else ""
    if summary:
        lines.append(f"Summary: {summary}")

    overall_conf = row["overall_confidence"] if "overall_confidence" in row.keys() else 0.0
    lines.append(f"Overall confidence: {overall_conf:.2f}")

    # Funding section
    funding_data = json_decode(row["funding_data"]) if row["funding_data"] else None
    if funding_data:
        lines.append("")
        lines.append("Funding / company stage:")
        if funding_data.get("stage"):
            lines.append(f"  Stage: {funding_data['stage']}")
        if funding_data.get("founded"):
            lines.append(f"  Founded: {funding_data['founded']}")
        if funding_data.get("headcount"):
            lines.append(f"  Headcount: {funding_data['headcount']}")
        if funding_data.get("public"):
            lines.append(f"  Public company: yes")
        if funding_data.get("total_raised_usd"):
            lines.append(f"  Total raised: ${funding_data['total_raised_usd']:,}")
        if funding_data.get("financial_health"):
            lines.append(f"  Financial health: {funding_data['financial_health']}")
        if funding_data.get("headcount_trend"):
            lines.append(f"  Headcount trend: {funding_data['headcount_trend']}")
        layoffs = funding_data.get("layoffs", [])
        if layoffs:
            lines.append(f"  Layoffs: {len(layoffs)} event(s)")
            for lay in layoffs:
                lines.append(f"    - {lay.get('date', '?')}: {lay.get('detail', '')}")

    # Sentiment section
    sentiment_data = json_decode(row["sentiment_data"]) if row["sentiment_data"] else None
    if sentiment_data:
        lines.append("")
        lines.append("Employee sentiment:")
        if sentiment_data.get("overall_rating_estimate"):
            lines.append(f"  Overall rating: {sentiment_data['overall_rating_estimate']}")
        if sentiment_data.get("ceo_approval_pct") is not None:
            lines.append(f"  CEO approval: {sentiment_data['ceo_approval_pct']}%")
        positives = sentiment_data.get("positives", [])
        negatives = sentiment_data.get("negatives", [])
        if positives:
            pos_items = [
                p.get("theme", str(p)) if isinstance(p, dict) else str(p)
                for p in positives[:5]
            ]
            lines.append(f"  Positives: {', '.join(pos_items)}")
        if negatives:
            neg_items = [
                n.get("theme", str(n)) if isinstance(n, dict) else str(n)
                for n in negatives[:5]
            ]
            lines.append(f"  Negatives: {', '.join(neg_items)}")

    # Fit section
    fit_data = json_decode(row["fit_data"]) if "fit_data" in row.keys() and row["fit_data"] else None
    if fit_data:
        lines.append("")
        lines.append("Company fit:")
        if fit_data.get("remote_policy"):
            lines.append(f"  Remote policy: {fit_data['remote_policy']}")
        if fit_data.get("size_bucket"):
            lines.append(f"  Size: {fit_data['size_bucket']}")
        if fit_data.get("comp_band"):
            lines.append(f"  Comp band: {fit_data['comp_band']}")
        if fit_data.get("clearance_required"):
            lines.append(f"  Clearance required: yes")

    # Verdict flags
    verdict_data = json_decode(row["verdict_flags"]) if "verdict_flags" in row.keys() and row["verdict_flags"] else None
    if verdict_data:
        greens = verdict_data.get("green", [])
        reds = verdict_data.get("red", [])
        watches = verdict_data.get("watch", [])
        if greens:
            lines.append(f"  Green flags: {', '.join(greens)}")
        if reds:
            lines.append(f"  Red flags: {', '.join(reds)}")
        if watches:
            lines.append(f"  Watch items: {', '.join(watches)}")

    return "\n".join(lines) if lines else "(company research returned no structured data)"


def _build_user_prompt(
    master_resume: str,
    prefs_text: str,
    rules_text: str,
    rubric_text: str,
    identity_text: str,
    jd_text: str,
    company: str,
    title: str,
    location: str,
    comp_min: int | None,
    comp_max: int | None,
    url: str,
    company_research_text: str = "",
) -> str:
    """Build the user prompt with all injected context."""
    comp_str = "Not posted"
    if comp_min is not None and comp_max is not None:
        comp_str = f"${comp_min:,} – ${comp_max:,}"
    elif comp_min is not None:
        comp_str = f"${comp_min:,}+"
    elif comp_max is not None:
        comp_str = f"≤${comp_max:,}"

    return _USER_PROMPT_TEMPLATE.format(
        master_resume=master_resume,
        prefs_text=prefs_text,
        identity_text=identity_text,
        rules_text=rules_text,
        rubric_text=rubric_text,
        jd_text=jd_text,
        company=company,
        title=title,
        location=location,
        comp_str=comp_str,
        url=url,
        company_research_text=company_research_text,
    )


def analyze_job(
    settings: Settings,
    job_id: int,
    task: str = "jd_analysis",
    temperature: float = 0.3,
    max_tokens: int | None = None,
) -> dict:
    """Run JD analysis for a specific job.

    Args:
        settings: App settings (loads all YAML configs)
        job_id: Database job ID
        task: LLM task name (determines model routing)
        temperature: LLM temperature (low for analytical consistency)
        max_tokens: Max output tokens (None = resolve from config/defaults)

    Returns:
        Dict with the full analysis result and LLM metadata.
    """
    from seeker_os.llm.router import ModelRouter

    # 1. Load the job from DB
    db = get_connection()
    job = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not job:
        db.close()
        raise ValueError(f"Job {job_id} not found")

    jd_text = job["jd_full"] or ""
    if not jd_text:
        db.close()
        raise ValueError(f"Job {job_id} has no JD fetched — run Tier 3 first")

    # 2. Load all context from config
    master_resume = _load_master_resume(settings)
    prefs_text = _load_prefs_text(settings)
    rules_text = _load_accuracy_rules_text(settings)
    rubric_text = _load_rubric_text(settings)
    identity_text = _load_identity_text(settings)
    company_research_text = _load_company_research_text(db, job["company"] or "")

    # 3. Build prompt
    user_prompt = _build_user_prompt(
        master_resume=master_resume,
        prefs_text=prefs_text,
        rules_text=rules_text,
        rubric_text=rubric_text,
        identity_text=identity_text,
        jd_text=jd_text,
        company=job["company"] or "",
        title=job["title"] or "",
        location=job["location"] or "",
        comp_min=job["comp_min"],
        comp_max=job["comp_max"],
        url=job["apply_url"] or "",
        company_research_text=company_research_text,
    )

    # 4. Call LLM
    router = ModelRouter(settings)
    from seeker_os.llm.models import TruncationError
    try:
        response = router.generate(
            task=task,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except TruncationError as e:
        db.close()
        raise TruncationError(
            task=e.task,
            model=e.model,
            requested_max_tokens=e.requested_max_tokens,
            output_tokens=e.output_tokens,
            stop_reason=e.stop_reason,
        ) from e

    # 5. Parse JSON response
    text = _strip_code_fences(response.text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        db.close()
        raise ValueError(
            f"JD analysis LLM returned invalid JSON for job {job_id} "
            f"(model={response.model}, output_tokens={response.output_tokens}): "
            f"{text[:300]!r}"
        ) from exc

    # 6. Store in DB
    now = datetime.now(timezone.utc).isoformat()
    analysis_json = json.dumps(data)

    cursor = db.execute(
        """
        INSERT INTO job_analyses
        (job_id, provider, model, task, input_tokens, output_tokens, latency_ms,
         analysis_json, verdict, weighted_score, one_line, confidence,
         analyzed_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_id, response.provider, response.model, task,
            response.input_tokens, response.output_tokens, response.latency_ms,
            analysis_json,
            data.get("verdict", ""),
            data.get("weighted_score", 0.0),
            data.get("one_line", ""),
            data.get("confidence", 0.0),
            now,
            now,
        ),
    )
    analysis_id = cursor.lastrowid

    # Compute and store verdict + net_score on the jobs table
    verdict = data.get("verdict", "")
    verdict_caps = (
        settings.scoring.verdict_caps if settings.scoring else {}
    )
    # Fetch existing score + research_delta to compute net
    job_row = db.execute(
        "SELECT score, research_delta FROM jobs WHERE id = ?", (job_id,)
    ).fetchone()
    base_score = float(job_row["score"]) if job_row and job_row["score"] is not None else 0.0
    research_delta = float(job_row["research_delta"] or 0.0) if job_row else 0.0
    max_score = float(settings.scoring.max_score) if settings.scoring else 10.0
    min_score = float(settings.scoring.min_score) if settings.scoring else 0.0

    from seeker_os.scoring.net_score import compute_net_score
    net = compute_net_score(
        base_score=base_score,
        research_delta=research_delta,
        analysis_verdict=verdict or None,
        verdict_caps=verdict_caps,
        max_score=max_score,
        min_score=min_score,
        unknown_verdict_cap=settings.scoring.unknown_verdict_cap if settings.scoring else None,
    )
    db.execute(
        # TODO: analysis_delta is vestigial (always 0.0 — never computed). Remove or implement.
        "UPDATE jobs SET analysis_verdict = ?, analysis_delta = 0.0, net_score = ? WHERE id = ?",
        (verdict, net, job_id),
    )

    db.commit()
    db.close()

    # 7. Return result
    result = dict(data)
    result["id"] = analysis_id
    result["job_id"] = job_id
    result["analyzed_at"] = now
    result["provider"] = response.provider
    result["model"] = response.model
    result["input_tokens"] = response.input_tokens
    result["output_tokens"] = response.output_tokens
    result["latency_ms"] = response.latency_ms
    return result


def get_latest_analysis(job_id: int) -> dict | None:
    """Get the most recent analysis for a job from DB."""
    db = get_connection()
    try:
        row = db.execute(
            "SELECT * FROM job_analyses WHERE job_id = ? ORDER BY analyzed_at DESC LIMIT 1",
            (job_id,),
        ).fetchone()
        if not row:
            return None

        data = json.loads(row["analysis_json"])
        data["id"] = row["id"]
        data["job_id"] = row["job_id"]
        data["provider"] = row["provider"] or ""
        data["model"] = row["model"] or ""
        data["input_tokens"] = row["input_tokens"] or 0
        data["output_tokens"] = row["output_tokens"] or 0
        data["latency_ms"] = row["latency_ms"] or 0
        data["analyzed_at"] = row["analyzed_at"] or ""
        return data
    finally:
        db.close()
