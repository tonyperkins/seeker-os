"""Resume generator — tailors a master resume to a specific job description.

Reads the master resume from the path in profile.yml, constructs a prompt
that includes the JD and accuracy rules, calls the LLM via the model router,
and stores the result.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from seeker_os.config import Settings
from seeker_os.database import get_connection, json_decode
from seeker_os.events import transition_status, EventType, Actor
from seeker_os.llm.router import ModelRouter
from seeker_os.validation import AccuracyValidator
from seeker_os.validation.traceability import TraceabilityChecker


_PROMPTS_DIR = Path(__file__).parent / "prompts"
SYSTEM_PROMPT = (_PROMPTS_DIR / "resume_generation_system.txt").read_text(encoding="utf-8")
_USER_PROMPT_TEMPLATE = (_PROMPTS_DIR / "resume_generation_user_template.txt").read_text(encoding="utf-8")


def _build_user_prompt(
    master_resume: str,
    job_title: str,
    company: str,
    jd_text: str,
    accuracy_rules_text: str,
    anchor_text: str = "",
) -> str:
    """Build the user prompt with the master resume, JD, and accuracy rules."""
    anchor_section = ""
    if anchor_text:
        anchor_section = f"\n## EXPERIENCE ANCHOR\n{anchor_text}\n"

    return _USER_PROMPT_TEMPLATE.format(
        master_resume=master_resume,
        job_title=job_title,
        company=company,
        jd_text=jd_text,
        accuracy_rules_text=accuracy_rules_text,
        anchor_section=anchor_section,
    )


def _load_accuracy_rules_text(settings: Settings) -> str:
    """Load accuracy rules as a human-readable text block for the prompt."""
    if not settings.profile or not settings.profile.resume:
        return "(no accuracy rules configured)"

    rules_path = settings.config_dir / "accuracy_rules.yml"
    if not rules_path.exists():
        return "(accuracy_rules.yml not found)"

    import yaml
    with open(rules_path) as f:
        data = yaml.safe_load(f)

    lines: list[str] = []
    for rule in data.get("rules", []):
        rule_type = rule.get("type", "")
        lines.append(f"- [{rule.get('severity', 'high').upper()}] {rule['description']}")
        if rule_type == "disallowed_phrases" and rule.get("phrases"):
            lines.append(f"  Disallowed phrases (DO NOT use): {', '.join(rule['phrases'])}")
        if rule_type == "forbidden_technologies" and rule.get("technologies"):
            lines.append(f"  FORBIDDEN TECHNOLOGIES (must NEVER appear): {', '.join(rule['technologies'])}")
        if rule_type == "required_phrases" and rule.get("phrases"):
            lines.append(f"  Required phrases (MUST include): {', '.join(rule['phrases'])}")
        if rule_type in ("experience_anchor", "education_omission") and rule.get("patterns"):
            lines.append(f"  Patterns to avoid: {', '.join(rule['patterns'])}")

    return "\n".join(lines) if lines else "(no rules defined)"


def _load_identity_anchor_text(settings: Settings) -> str:
    """Load the experience anchor from identity_rules.yml for the prompt.

    Returns empty string if no identity or anchor is configured — the prompt
    says nothing about an anchor in that case. No hardcoded fallback.
    """
    identity = settings.identity
    if not identity or not identity.experience_anchor.phrase:
        return ""
    anchor = identity.experience_anchor
    parts = [f'Use "{anchor.phrase}" for the experience anchor']
    if anchor.applies_to:
        parts.append(f"attached to {anchor.applies_to}")
    return ", ".join(parts) + "."


def _load_never_claim_text(settings: Settings) -> str:
    """Load the never-claim list from identity_rules.yml for the prompt.

    Returns empty string if no identity or no never_claim entries — the prompt
    says nothing about never-claim in that case. No hardcoded fallback.
    """
    identity = settings.identity
    if not identity or not identity.never_claim:
        return ""
    items = ", ".join(identity.never_claim)
    return f"NEVER mention these technologies anywhere in the resume: {items}"


def _load_honest_qualifiers_text(settings: Settings) -> str:
    """Load the honest qualifiers from identity_rules.yml for the prompt.

    Returns empty string if no identity or no honest_qualifiers entries — the
    prompt says nothing about honest qualifiers in that case. No hardcoded
    fallback.
    """
    identity = settings.identity
    if not identity or not identity.honest_qualifiers:
        return ""
    lines: list[str] = []
    for hq in identity.honest_qualifiers:
        lines.append(f"- {hq.skill}: {hq.framing}")
    return "\n".join(lines)


def _load_work_eligibility_text(settings: Settings) -> str:
    """Load work eligibility from identity_rules.yml for the prompt.

    Returns empty string if no identity or no work_eligibility configured —
    the prompt says nothing about it in that case. No hardcoded fallback.
    """
    identity = settings.identity
    if not identity or not identity.work_eligibility:
        return ""
    return (
        f"If the job description asks about work authorization, citizenship, "
        f"or visa sponsorship, include this factual statement: "
        f"\"{identity.work_eligibility}\". Do not invent or embellish beyond this."
    )


def _build_tiering_instructions(settings: Settings) -> str:
    """Build recency/relevance tiering instructions from channel_rules config.

    Returns empty string if no content_tiering is configured — the prompt
    says nothing about tiering in that case. No hardcoded values.
    """
    if not settings.channel_rules or not settings.channel_rules.resume:
        return ""
    tiering = settings.channel_rules.resume.content_tiering
    if not tiering:
        return ""

    lines = [
        f"Target length: {tiering.target_pages} pages. Apply recency-based bullet tiering to every role:",
        f"- Recent roles (within the last {tiering.recent_years} years): keep ALL strong bullets — full detail.",
        f"- Mid-age roles ({tiering.recent_years}-{tiering.mid_years} years old): compress to at most {tiering.mid_max_bullets} highest-impact bullets. Prefer bullets with quantified outcomes or keywords matching the target JD; drop generic ones.",
        f"- Old roles ({tiering.mid_years}+ years old): compress to at most {tiering.old_max_bullets} bullet or a single summary line.",
        "- NEVER drop a role entirely or alter dates/titles. This is about bullet COUNT per role, not removing history.",
        "- JD-relevance can PROMOTE an older role's bullet: if a bullet from an older role directly matches the target JD's stack or requirements, keep it even when compressing. Recency is the default axis; JD-relevance can override downward compression.",
        "- All honesty/traceability rules still apply. Compressing means SELECTING which true bullets to show — never invent or merge into new claims.",
    ]
    return "\n".join(lines)


def generate_resume(
    settings: Settings,
    job_id: int,
    task: str = "resume_generation_standard",
    temperature: float = 0.7,
    max_tokens: int | None = None,
    progress_cb: Callable[[str, str, str, str], None] | None = None,
) -> dict:
    """Generate a tailored resume for a specific job.

    Args:
        settings: App settings
        job_id: Database job ID
        task: LLM task name (determines model routing)
        temperature: LLM temperature
        max_tokens: Max output tokens (None = resolve from config/defaults)
        progress_cb: Optional callback invoked as (step, step_label, status, detail)
                     at each pipeline step. Enables SSE progress streaming.

    Returns:
        Dict with resume metadata and validation results.
    """
    def _emit(step: str, label: str, status: str, detail: str = ""):
        if progress_cb:
            progress_cb(step, label, status, detail)

    # 1. Load the job from DB
    _emit("load_job", "Loading job", "started")
    db = get_connection()
    job = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not job:
        db.close()
        raise ValueError(f"Job {job_id} not found")

    jd_text = job["jd_full"] or ""
    if not jd_text:
        db.close()
        raise ValueError(f"Job {job_id} has no JD fetched — run Tier 3 first")

    _emit("load_job", "Loading job", "completed", f"{job['company'] or 'Unknown'} — {job['title'] or 'Unknown'}")

    # 2. Load master resume
    if not settings.profile or not settings.profile.resume:
        db.close()
        raise ValueError("No resume config in profile.yml")

    master_path = Path(settings.profile.resume.master_path).expanduser()
    if not master_path.exists():
        db.close()
        raise FileNotFoundError(f"Master resume not found at {master_path}")

    master_resume = master_path.read_text()

    # 3. Build prompts
    accuracy_rules_text = _load_accuracy_rules_text(settings)
    anchor_text = _load_identity_anchor_text(settings)
    user_prompt = _build_user_prompt(
        master_resume=master_resume,
        job_title=job["title"] or "",
        company=job["company"] or "",
        jd_text=jd_text,
        accuracy_rules_text=accuracy_rules_text,
        anchor_text=anchor_text,
    )

    # 4. Call LLM (inject user instructions and channel rules into system prompt)
    system_prompt = SYSTEM_PROMPT

    # Inject never-claim list from identity_rules.yml as a hard constraint
    never_claim_text = _load_never_claim_text(settings)
    if never_claim_text:
        system_prompt += f"\n\n--- NEVER CLAIM ---\n{never_claim_text}\n--- END NEVER CLAIM ---\n"

    # Inject honest qualifiers from identity_rules.yml — skill framings must
    # match the master's wording verbatim and must not be upgraded or paraphrased
    honest_qualifiers_text = _load_honest_qualifiers_text(settings)
    if honest_qualifiers_text:
        system_prompt += (
            f"\n\n--- HONEST QUALIFIERS (verbatim — do not upgrade) ---\n"
            f"Wherever the skill appears (competency lines, summary, bullets), "
            f"its qualifier must match the master's wording and must not be "
            f"upgraded or paraphrased into a stronger claim.\n"
            f"{honest_qualifiers_text}\n"
            f"--- END HONEST QUALIFIERS ---\n"
        )

    # Inject work eligibility from identity_rules.yml
    work_eligibility_text = _load_work_eligibility_text(settings)
    if work_eligibility_text:
        system_prompt += f"\n\n--- WORK ELIGIBILITY ---\n{work_eligibility_text}\n--- END WORK ELIGIBILITY ---\n"

    channel_rules = settings.channel_rules
    if channel_rules and channel_rules.resume:
        resume_channel = channel_rules.resume
        channel_lines: list[str] = []
        if resume_channel.require_visible_urls:
            channel_lines.append(
                "Always include the full literal https:// URLs from the master resume as visible text (not just hyperlinks)."
            )
        if resume_channel.format_hints:
            channel_lines.append(f"Format: {resume_channel.format_hints}")
        if channel_lines:
            system_prompt += f"\n\n--- CHANNEL RULES (resume) ---\n" + "\n".join(channel_lines) + "\n--- END CHANNEL RULES ---\n"

    # Inject content tiering instructions from channel_rules config
    tiering_text = _build_tiering_instructions(settings)
    if tiering_text:
        system_prompt += f"\n\n--- CONTENT TIERING (resume) ---\n{tiering_text}\n--- END CONTENT TIERING ---\n"
    if settings.profile and settings.profile.instructions:
        system_prompt += f"\n\n--- USER INSTRUCTIONS ---\n{settings.profile.instructions}\n--- END USER INSTRUCTIONS ---\n"
    router = ModelRouter(settings)
    _emit("llm_generation", "Generating resume with LLM", "started", f"Task: {task}")
    response = router.generate(
        task=task,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    _emit("llm_generation", "Generating resume with LLM", "completed", f"{response.output_tokens} tokens in {response.latency_ms}ms")

    # 5. Validate accuracy (deterministic deny-list + LLM-judged traceability)
    _emit("validation", "Running accuracy validation", "started")
    validator = AccuracyValidator(settings)
    validation = validator.validate(response.text, artifact_type="resume", master_resume=master_resume)

    # 5b. Run traceability check (LLM-judged claim verification)
    traceability = TraceabilityChecker(settings)
    if traceability.enabled:
        _emit("traceability", "Verifying claim traceability", "started")
        trace_result = traceability.check(response.text, master_resume, artifact_type="resume")
        trace_result.merge_into(validation)
        _emit("traceability", "Verifying claim traceability", "completed", f"{len(trace_result.violations)} violations")
    _emit("validation", "Running accuracy validation", "completed", f"{'passed' if validation.passed else 'violations found'}")

    # 6. Save to DB
    _emit("saving", "Saving resume", "started")
    now = datetime.now(timezone.utc).isoformat()
    output_dir = Path(settings.profile.resume.output_dir or "data/resumes").expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save markdown file
    safe_company = (job["company"] or "unknown").replace(" ", "_").replace("/", "_")
    safe_title = (job["title"] or "resume").replace(" ", "_").replace("/", "_")[:50]
    md_filename = f"{safe_company}_{safe_title}_{job_id}_{now[:10]}.md"
    md_path = output_dir / md_filename
    md_path.write_text(response.text)

    cursor = db.execute(
        """
        INSERT INTO resumes
        (job_id, task, provider, model, resume_text, master_resume_path,
         validation_passed, validation_violations, validation_checked_at,
         input_tokens, output_tokens, latency_ms, generated_at, updated_at,
         markdown_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_id, task, response.provider, response.model,
            response.text, str(master_path),
            validation.passed,
            json.dumps(validation.to_dict()["violations"]),
            validation.checked_at,
            response.input_tokens, response.output_tokens, response.latency_ms,
            now, now, str(md_path),
        ),
    )
    resume_id = cursor.lastrowid

    # Update job status to 'interested' (resume generated = moving forward)
    transition_status(
        db, job_id, "interested", EventType.RESUME_GENERATED, Actor.SYSTEM,
        metadata={"resume_id": resume_id},
    )
    db.commit()
    db.close()
    _emit("saving", "Saving resume", "completed", f"Resume #{resume_id}")

    return {
        "resume_id": resume_id,
        "job_id": job_id,
        "task": task,
        "provider": response.provider,
        "model": response.model,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "latency_ms": response.latency_ms,
        "validation_passed": validation.passed,
        "validation_violations": validation.violations,
        "markdown_path": str(md_path),
        "generated_at": now,
    }


def create_manual_resume(settings: Settings, job_id: int, resume_text: str) -> dict:
    """Save a hand-built (user-pasted) markdown resume for a job.

    Skips LLM generation and accuracy/traceability validation — the user
    authored this content directly, so there is no master-resume claim set
    to validate against. Stored and tracked identically to a generated
    resume otherwise (file on disk, DB row, job status transition).

    Args:
        settings: App settings
        job_id: Database job ID
        resume_text: Markdown resume text supplied by the user

    Returns:
        Dict with resume metadata (same shape as generate_resume's result,
        minus LLM-specific fields).
    """
    resume_text = resume_text.strip()
    if not resume_text:
        raise ValueError("resume_text is empty")

    db = get_connection()
    job = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not job:
        db.close()
        raise ValueError(f"Job {job_id} not found")

    now = datetime.now(timezone.utc).isoformat()
    output_dir = Path(
        settings.profile.resume.output_dir if settings.profile and settings.profile.resume else "data/resumes"
    ).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    safe_company = (job["company"] or "unknown").replace(" ", "_").replace("/", "_")
    safe_title = (job["title"] or "resume").replace(" ", "_").replace("/", "_")[:50]
    md_filename = f"{safe_company}_{safe_title}_{job_id}_{now[:10]}_manual.md"
    md_path = output_dir / md_filename
    md_path.write_text(resume_text)

    master_path = None
    if settings.profile and settings.profile.resume:
        candidate = Path(settings.profile.resume.master_path).expanduser()
        if candidate.exists():
            master_path = candidate

    cursor = db.execute(
        """
        INSERT INTO resumes
        (job_id, task, provider, model, resume_text, master_resume_path,
         validation_passed, validation_violations, validation_checked_at,
         input_tokens, output_tokens, latency_ms, generated_at, updated_at,
         markdown_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_id, "manual", "manual", "user_provided",
            resume_text, str(master_path) if master_path else None,
            True, json.dumps([]), None,
            0, 0, 0,
            now, now, str(md_path),
        ),
    )
    resume_id = cursor.lastrowid

    transition_status(
        db, job_id, "interested", EventType.RESUME_GENERATED, Actor.SYSTEM,
        metadata={"resume_id": resume_id, "source": "manual"},
    )
    db.commit()
    db.close()

    return {
        "resume_id": resume_id,
        "job_id": job_id,
        "task": "manual",
        "provider": "manual",
        "model": "user_provided",
        "input_tokens": 0,
        "output_tokens": 0,
        "latency_ms": 0,
        "validation_passed": True,
        "validation_violations": [],
        "markdown_path": str(md_path),
        "generated_at": now,
    }


def list_resumes(job_id: int | None = None, limit: int = 50) -> list[dict]:
    """List generated resumes."""
    db = get_connection()
    if job_id:
        rows = db.execute(
            "SELECT * FROM resumes WHERE job_id = ? ORDER BY generated_at DESC LIMIT ?",
            (job_id, limit),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM resumes ORDER BY generated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    db.close()

    results = []
    for r in rows:
        results.append({
            "id": r["id"],
            "job_id": r["job_id"],
            "task": r["task"] or "",
            "provider": r["provider"] or "",
            "model": r["model"] or "",
            "validation_passed": bool(r["validation_passed"]),
            "validation_violations": json_decode(r["validation_violations"]) or [],
            "input_tokens": r["input_tokens"] or 0,
            "output_tokens": r["output_tokens"] or 0,
            "latency_ms": r["latency_ms"] or 0,
            "generated_at": r["generated_at"] or "",
            "markdown_path": r["markdown_path"] or "",
            "pdf_path": r["pdf_path"],
            "docx_path": r["docx_path"],
        })
    return results


def get_resume(resume_id: int) -> dict | None:
    """Get a single resume by ID."""
    db = get_connection()
    row = db.execute("SELECT * FROM resumes WHERE id = ?", (resume_id,)).fetchone()
    db.close()
    if not row:
        return None

    # Also get the job info
    db = get_connection()
    job = db.execute("SELECT title, company FROM jobs WHERE id = ?", (row["job_id"],)).fetchone()
    db.close()

    return {
        "id": row["id"],
        "job_id": row["job_id"],
        "job_title": job["title"] if job else "",
        "job_company": job["company"] if job else "",
        "task": row["task"] or "",
        "provider": row["provider"] or "",
        "model": row["model"] or "",
        "resume_text": row["resume_text"] or "",
        "validation_passed": bool(row["validation_passed"]),
        "validation_violations": json_decode(row["validation_violations"]) or [],
        "validation_checked_at": row["validation_checked_at"],
        "input_tokens": row["input_tokens"] or 0,
        "output_tokens": row["output_tokens"] or 0,
        "latency_ms": row["latency_ms"] or 0,
        "generated_at": row["generated_at"] or "",
        "markdown_path": row["markdown_path"] or "",
        "pdf_path": row["pdf_path"],
        "docx_path": row["docx_path"],
    }
