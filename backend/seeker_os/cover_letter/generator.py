"""Cover letter generator — tailors a cover letter for a specific job.

Uses the same master resume as the source of truth, the same accuracy
validator (artifact_type='cover_letter'), and the same traceability checker.
Enforces per-application ai_policy from the jobs table.
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
SYSTEM_PROMPT = (_PROMPTS_DIR / "cover_letter_generation_system.txt").read_text(encoding="utf-8")
_USER_PROMPT_TEMPLATE = (_PROMPTS_DIR / "cover_letter_generation_user_template.txt").read_text(encoding="utf-8")


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
    """Load the experience anchor from identity_rules.yml for the prompt."""
    identity = settings.identity
    if not identity or not identity.experience_anchor.phrase:
        return ""
    anchor = identity.experience_anchor
    parts = [f'Use "{anchor.phrase}" for the experience anchor']
    if anchor.applies_to:
        parts.append(f"attached to {anchor.applies_to}")
    return ", ".join(parts) + "."


def _get_ai_policy(job_row) -> str | None:
    """Get per-application AI policy from job row, falling back to channel default."""
    ai_policy = job_row["ai_policy"] if "ai_policy" in job_row.keys() else None
    return ai_policy


def generate_cover_letter(
    settings: Settings,
    job_id: int,
    task: str = "cover_letter_generation",
    temperature: float = 0.7,
    max_tokens: int | None = None,
) -> dict:
    """Generate a tailored cover letter for a specific job.

    Enforces per-application ai_policy:
    - 'forbidden': returns a refusal dict, does not generate.
    - 'draft_only': generates but labels output as draft.
    - 'allowed' or null: generates normally.

    Args:
        settings: App settings
        job_id: Database job ID
        task: LLM task name (determines model routing)
        temperature: LLM temperature
        max_tokens: Max output tokens (None = resolve from config/defaults)

    Returns:
        Dict with cover letter metadata and validation results.
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

    # 2. Check ai_policy
    ai_policy = _get_ai_policy(job)
    if ai_policy == "forbidden":
        db.close()
        return {
            "job_id": job_id,
            "refused": True,
            "refusal_reason": "ai_policy is 'forbidden' for this job — AI authoring is not permitted.",
            "cover_letter_text": "",
            "validation_passed": False,
        }

    # 3. Load master resume
    if not settings.profile or not settings.profile.resume:
        db.close()
        raise ValueError("No resume config in profile.yml")

    master_path = Path(settings.profile.resume.master_path).expanduser()
    if not master_path.exists():
        db.close()
        raise FileNotFoundError(f"Master resume not found at {master_path}")

    master_resume = master_path.read_text()

    # 4. Build prompts
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

    # 5. Call LLM (inject channel rules into system prompt)
    system_prompt = SYSTEM_PROMPT
    channel_rules = settings.channel_rules
    if channel_rules and channel_rules.cover_letter:
        cl_channel = channel_rules.cover_letter
        channel_lines: list[str] = []
        if cl_channel.require_visible_urls:
            channel_lines.append(
                "Always include the full literal https:// URLs from the master resume as visible text."
            )
        if cl_channel.format_hints:
            channel_lines.append(f"Format: {cl_channel.format_hints}")
        if channel_lines:
            system_prompt += f"\n\n--- CHANNEL RULES (cover_letter) ---\n" + "\n".join(channel_lines) + "\n--- END CHANNEL RULES ---\n"
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

    cover_letter_text = response.text

    # draft_only: mark as draft but keep content clean — the notice is NOT
    # concatenated into cover_letter_text. The is_draft flag and draft_notice
    # string are returned separately so the frontend can render a banner above
    # the copyable content.
    is_draft = ai_policy == "draft_only"
    draft_notice = (
        "This content was AI-generated for your reference. "
        "Please rewrite in your own words before submitting."
        if is_draft else ""
    )

    # 6. Validate accuracy (on clean content, not the draft notice)
    validator = AccuracyValidator(settings)
    validation = validator.validate(
        cover_letter_text, artifact_type="cover_letter", master_resume=master_resume,
    )

    # 6b. Run traceability check
    traceability = TraceabilityChecker(settings)
    if traceability.enabled:
        trace_result = traceability.check(cover_letter_text, master_resume, artifact_type="cover_letter")
        trace_result.merge_into(validation)

    # 7. Save to DB
    now = datetime.now(timezone.utc).isoformat()
    output_dir = Path(settings.profile.resume.output_dir or "data/resumes").expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    safe_company = (job["company"] or "unknown").replace(" ", "_").replace("/", "_")
    safe_title = (job["title"] or "cover_letter").replace(" ", "_").replace("/", "_")[:50]
    md_filename = f"cover_{safe_company}_{safe_title}_{job_id}_{now[:10]}.md"
    md_path = output_dir / md_filename
    # Write clean content to the markdown file. If draft_only, add an
    # HTML comment header that is clearly out-of-band (not pasteable as
    # cover letter text into a form).
    if is_draft:
        file_content = f"<!-- DRAFT: {draft_notice} -->\n\n{cover_letter_text}"
    else:
        file_content = cover_letter_text
    md_path.write_text(file_content)

    cursor = db.execute(
        """
        INSERT INTO cover_letters
        (job_id, task, provider, model, cover_letter_text, master_resume_path,
         validation_passed, validation_violations, validation_checked_at,
         input_tokens, output_tokens, latency_ms, generated_at, updated_at,
         markdown_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_id, task, response.provider, response.model,
            cover_letter_text, str(master_path),
            validation.passed,
            json.dumps(validation.to_dict()["violations"]),
            validation.checked_at,
            response.input_tokens, response.output_tokens, response.latency_ms,
            now, now, str(md_path),
        ),
    )
    cover_letter_id = cursor.lastrowid
    db.commit()
    db.close()

    return {
        "cover_letter_id": cover_letter_id,
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
        "is_draft": is_draft,
        "draft_notice": draft_notice,
        "generated_at": now,
    }
