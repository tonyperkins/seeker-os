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
from seeker_os.resume.validator import AccuracyValidator, ValidationResult


SYSTEM_PROMPT = """You are an expert resume writer who tailors resumes for specific job descriptions.

CRITICAL RULES — VIOLATIONS WILL CAUSE THE RESUME TO BE REJECTED:
1. NEVER invent skills, technologies, or experience not present in the master resume.
2. NEVER inflate years of experience or claim depth beyond what the master resume states.
3. NEVER use technologies listed as "forbidden" in the accuracy rules.
4. NEVER mention education unless explicitly required by the JD (and even then, only state it factually).
5. Every claim must be traceable to the master resume. You may reorganize, emphasize, or de-emphasize, but never fabricate.
6. Always include the full literal https:// URLs from the master resume as visible text (not just hyperlinks).
7. Use "25+ years" for experience anchor, attached to overall engineering career, NOT to cloud/DevOps specifically.
8. If the JD requires a technology not in the master resume, simply omit it — do not claim it. The gap is noted elsewhere.

OUTPUT FORMAT:
- Markdown format
- Start with a professional summary (2-3 lines)
- Skills/core competencies section
- Professional experience (reverse chronological)
- Keep it concise — 1-2 pages max
- Use action verbs and quantified achievements where available in the master resume
"""


def _build_user_prompt(
    master_resume: str,
    job_title: str,
    company: str,
    jd_text: str,
    accuracy_rules_text: str,
) -> str:
    """Build the user prompt with the master resume, JD, and accuracy rules."""
    return f"""## MASTER RESUME
Do not deviate from the facts in this resume. You may reorganize and emphasize, but never invent.

---
{master_resume}
---

## TARGET JOB
Title: {job_title}
Company: {company}

## JOB DESCRIPTION
---
{jd_text}
---

## ACCURACY RULES (MUST FOLLOW)
These rules are validated programmatically after generation. Violations will flag the resume for manual review.
---
{accuracy_rules_text}
---

## INSTRUCTIONS
Tailor the master resume for this specific job. Emphasize relevant experience and skills. De-emphasize irrelevant parts. Do NOT add anything not in the master resume. Follow ALL accuracy rules above.

Generate the tailored resume in Markdown format:"""


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
    user_prompt = _build_user_prompt(
        master_resume=master_resume,
        job_title=job["title"] or "",
        company=job["company"] or "",
        jd_text=jd_text,
        accuracy_rules_text=accuracy_rules_text,
    )

    # 4. Call LLM (inject user instructions into system prompt if present)
    system_prompt = SYSTEM_PROMPT
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

    # 5. Validate accuracy
    validator = AccuracyValidator(settings)
    validation = validator.validate(response.text, master_resume)

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
