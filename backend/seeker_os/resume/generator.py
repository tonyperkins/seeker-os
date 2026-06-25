"""Resume generator — tailors a master resume to a specific job description.

Reads the master resume from the path in profile.yml, constructs a prompt
that includes the JD and accuracy rules, calls the LLM via the model router,
and stores the result.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from seeker_os.config import Settings
from seeker_os.database import get_connection, json_decode
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


def generate_resume(
    settings: Settings,
    job_id: int,
    task: str = "resume_generation_standard",
    temperature: float = 0.7,
    max_tokens: int | None = 16000,
) -> dict:
    """Generate a tailored resume for a specific job.

    Args:
        settings: App settings
        job_id: Database job ID
        task: LLM task name (determines model routing)
        temperature: LLM temperature
        max_tokens: Max output tokens

    Returns:
        Dict with resume metadata and validation results.
    """
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
    if settings.profile and settings.profile.instructions:
        system_prompt += f"\n\n--- USER INSTRUCTIONS ---\n{settings.profile.instructions}\n--- END USER INSTRUCTIONS ---\n"
    router = ModelRouter(settings)
    response = router.generate(
        task=task,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    # 5. Validate accuracy (deterministic deny-list + LLM-judged traceability)
    validator = AccuracyValidator(settings)
    validation = validator.validate(response.text, artifact_type="resume", master_resume=master_resume)

    # 5b. Run traceability check (LLM-judged claim verification)
    traceability = TraceabilityChecker(settings)
    if traceability.enabled:
        trace_result = traceability.check(response.text, master_resume, artifact_type="resume")
        trace_result.merge_into(validation)

    # 6. Save to DB
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
    db.execute(
        "UPDATE jobs SET status='interested', updated_at=? WHERE id=?",
        (now, job_id),
    )
    db.commit()
    db.close()

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
