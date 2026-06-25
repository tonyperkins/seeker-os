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
from seeker_os.database import get_connection, json_encode


SYSTEM_PROMPT = """You evaluate a single job posting against the candidate's profile and produce a
fit verdict for a job-search dashboard. Output is ingested into a database AND
rendered as an analysis card, so return valid JSON matching the schema below and
nothing else. No prose outside the JSON.

## How to think (this is the conversational analysis, formalized)
1. STATE GAPS FIRST. Before any recommendation, name where the candidate does not
   meet the JD as written. Be blunt. A principal-level honest gap ("K8s is primary
   here; candidate is re-ramping, prod at one employer 2016–2020") is the product,
   not a thing to hide.
2. Score each rubric dimension, apply bonuses/penalties/blockers from RUBRIC, and
   compute the weighted total. Show the per-dimension breakdown.
3. Check HARD BLOCKERS explicitly. Any present => verdict cannot exceed SKIP
   regardless of score. Blockers include: onsite/hybrid outside commute tolerance,
   clearance/citizenship requirements, and any never-claim tech as a PRIMARY stack
   requirement.
4. Check COMP against the floor in PREFS. Unposted comp is a flag, not a blocker.
5. Check POSITIONING. The candidate's identity is deploying/operating AI systems
   reliably in production — the infra/reliability layer. Roles that are actually
   AI/ML model- or feature-BUILDING are a positioning mismatch even if the stack
   overlaps. Call this out.
6. Produce tailoring guidance — but tailoring is REORDER and REFRAME ONLY.

## Accuracy guardrails (NON-NEGOTIABLE — override helpfulness)
- NEVER invent or upgrade a competency to match the JD. Do not mirror JD language
  back as a claimed skill.
- NEVER suggest claiming any item on the never-claim list as production depth.
- Honest skill qualifiers from MASTER_RESUME are verbatim. Do not round up
  ("familiar, growing" stays that; it does not become "experienced").
- Tailoring guidance may only reorder the competency table and reframe the summary
  for emphasis. Every bullet stays verbatim from the master. If a suggestion would
  require a new claim, do not make it — flag the gap instead.
- If the JD demands something the candidate genuinely lacks, the correct output is a
  lower score and a named gap, never a fabricated qualification.

## Output schema
{
  "company": "string",
  "title": "string",
  "url": "string",
  "verdict": "APPLY | CONDITIONAL | MONITOR | SKIP",
  "weighted_score": 0.0,
  "one_line": "blunt one-sentence verdict",
  "named_gaps": [
    { "area": "", "jd_requires": "", "candidate_actual": "", "severity": "low|med|high|blocker" }
  ],
  "hard_blockers": [ { "type": "", "detail": "" } ],
  "rubric_breakdown": [
    { "dimension": "", "weight": 0.0, "raw": 0.0, "weighted": 0.0, "note": "" }
  ],
  "bonuses_applied": [ "" ],
  "penalties_applied": [ "" ],
  "comp": { "posted": null, "meets_floor": null, "note": "" },
  "positioning": { "aligned": true, "note": "AI-in-prod infra vs model/feature-building" },
  "company_fit": { "size_bucket": null, "stage": null, "remote_policy": null, "note": "" },
  "tailoring": {
    "lead_with": [ "competencies to surface first — must already exist in master" ],
    "reframe_summary": "emphasis-only reframe, no new claims",
    "do_not_claim": [ "JD terms that would be embellishment if mirrored back" ]
  },
  "red_flags": [ "" ],
  "confidence": 0.0
}

## Verdict rules
- SKIP: any hard blocker present, OR positioning is a clear mismatch, OR
  weighted_score below the RUBRIC skip threshold.
- MONITOR: borderline score, or interesting company with a current disqualifier
  (e.g., comp unposted + size unknown) worth re-checking later.
- CONDITIONAL: good fit with one named, surmountable gap or an open question
  (e.g., comp not posted, remote policy ambiguous).
- APPLY: clears blockers, meets comp floor or close, positioning aligned, score
  above the apply threshold.
Always populate named_gaps even on APPLY. There is always at least one gap to name."""


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
    """Load accuracy rules as a text block for the prompt."""
    if not settings.profile or not settings.profile.resume:
        return "(no accuracy rules configured)"
    rules_path = settings.config_dir / "accuracy_rules.yml"
    if not rules_path.exists():
        return "(accuracy_rules.yml not found)"
    with open(rules_path) as f:
        data = yaml.safe_load(f)
    lines: list[str] = []
    for rule in data.get("rules", []):
        rule_type = rule.get("type", "")
        lines.append(f"- [{rule.get('severity', 'high').upper()}] {rule['description']}")
        if rule_type == "disallowed_phrases" and rule.get("phrases"):
            lines.append(f"  Disallowed phrases: {', '.join(rule['phrases'])}")
        if rule_type == "forbidden_technologies" and rule.get("technologies"):
            lines.append(f"  FORBIDDEN TECHNOLOGIES (never-claim): {', '.join(rule['technologies'])}")
        if rule_type == "required_phrases" and rule.get("phrases"):
            lines.append(f"  Required phrases: {', '.join(rule['phrases'])}")
        if rule_type in ("experience_anchor", "education_omission") and rule.get("patterns"):
            lines.append(f"  Patterns to avoid: {', '.join(rule['patterns'])}")
    return "\n".join(lines) if lines else "(no rules defined)"


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


def _build_user_prompt(
    master_resume: str,
    prefs_text: str,
    rules_text: str,
    rubric_text: str,
    jd_text: str,
    company: str,
    title: str,
    location: str,
    comp_min: int | None,
    comp_max: int | None,
    url: str,
) -> str:
    """Build the user prompt with all injected context."""
    comp_str = "Not posted"
    if comp_min is not None and comp_max is not None:
        comp_str = f"${comp_min:,} – ${comp_max:,}"
    elif comp_min is not None:
        comp_str = f"${comp_min:,}+"
    elif comp_max is not None:
        comp_str = f"≤${comp_max:,}"

    return f"""## Injected context (authoritative — do not contradict)

### MASTER_RESUME
---
{master_resume}
---

### PREFERENCES
---
{prefs_text}
---

### RULES (accuracy + never-claim guardrails)
---
{rules_text}
---

### RUBRIC (weighted scoring dimensions, bonuses, penalties, blockers)
---
{rubric_text}
---

### JOB_POSTING
---
{jd_text}
---

### JOB_META
- Company: {company}
- Title: {title}
- Location: {location}
- Comp (if posted): {comp_str}
- URL: {url}

Produce the analysis now. Return ONLY valid JSON matching the output schema."""


def analyze_job(
    settings: Settings,
    job_id: int,
    task: str = "jd_analysis",
    temperature: float = 0.3,
    max_tokens: int | None = 4096,
) -> dict:
    """Run JD analysis for a specific job.

    Args:
        settings: App settings (loads all YAML configs)
        job_id: Database job ID
        task: LLM task name (determines model routing)
        temperature: LLM temperature (low for analytical consistency)
        max_tokens: Max output tokens

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

    # 3. Build prompt
    user_prompt = _build_user_prompt(
        master_resume=master_resume,
        prefs_text=prefs_text,
        rules_text=rules_text,
        rubric_text=rubric_text,
        jd_text=jd_text,
        company=job["company"] or "",
        title=job["title"] or "",
        location=job["location"] or "",
        comp_min=job["comp_min"],
        comp_max=job["comp_max"],
        url=job["apply_url"] or "",
    )

    # 4. Call LLM
    router = ModelRouter(settings)
    response = router.generate(
        task=task,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    # 5. Parse JSON response
    text = _strip_code_fences(response.text)
    data = json.loads(text)

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
        return data
    finally:
        db.close()
