"""Application answer generator — drafts answers to application questions.

Uses the master resume as the source of truth, the same accuracy validator
(artifact_type='application_answer'), and the same traceability checker.
Enforces per-application ai_policy from the jobs table:
- 'forbidden': must NOT author content — returns a refusal, may only critique
  a user-supplied draft.
- 'draft_only': labels output as a draft for the user to rewrite.
- 'allowed' or null: generates normally.
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
SYSTEM_PROMPT = (_PROMPTS_DIR / "application_answer_generation_system.txt").read_text(encoding="utf-8")
CRITIQUE_SYSTEM_PROMPT = (_PROMPTS_DIR / "application_answer_critique_system.txt").read_text(encoding="utf-8")
_USER_PROMPT_TEMPLATE = (_PROMPTS_DIR / "application_answer_generation_user_template.txt").read_text(encoding="utf-8")
_CRITIQUE_USER_TEMPLATE = (_PROMPTS_DIR / "application_answer_critique_user_template.txt").read_text(encoding="utf-8")


def _build_user_prompt(
    master_resume: str,
    job_title: str,
    company: str,
    question: str,
    jd_text: str,
    accuracy_rules_text: str,
) -> str:
    """Build the user prompt for generating an application answer."""
    return _USER_PROMPT_TEMPLATE.format(
        master_resume=master_resume,
        job_title=job_title,
        company=company,
        question=question,
        jd_text=jd_text,
        accuracy_rules_text=accuracy_rules_text,
    )


def _build_critique_prompt(
    master_resume: str,
    question: str,
    user_draft: str,
    accuracy_rules_text: str = "",
) -> str:
    """Build the user prompt for critiquing a user-supplied draft."""
    return _CRITIQUE_USER_TEMPLATE.format(
        master_resume=master_resume,
        question=question,
        user_draft=user_draft,
        accuracy_rules_text=accuracy_rules_text,
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

    return "\n".join(lines) if lines else "(no rules defined)"


def _get_ai_policy(job_row) -> str | None:
    """Get per-application AI policy from job row."""
    return job_row["ai_policy"] if "ai_policy" in job_row.keys() else None


def generate_application_answer(
    settings: Settings,
    job_id: int,
    question: str,
    task: str = "application_answer_generation",
    temperature: float = 0.7,
    max_tokens: int | None = 2000,
) -> dict:
    """Generate a draft answer to an application question.

    Enforces per-application ai_policy:
    - 'forbidden': returns a refusal dict, does not author content.
    - 'draft_only': generates but labels output as draft.
    - 'allowed' or null: generates normally.

    Args:
        settings: App settings
        job_id: Database job ID
        question: The application question to answer
        task: LLM task name
        temperature: LLM temperature
        max_tokens: Max output tokens

    Returns:
        Dict with answer metadata and validation results.
    """
    # 1. Load the job from DB
    db = get_connection()
    job = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not job:
        db.close()
        raise ValueError(f"Job {job_id} not found")

    jd_text = job["jd_full"] or ""

    # 2. Check ai_policy
    ai_policy = _get_ai_policy(job)
    if ai_policy == "forbidden":
        db.close()
        return {
            "job_id": job_id,
            "question": question,
            "refused": True,
            "refusal_reason": "ai_policy is 'forbidden' for this job — AI authoring is not permitted. You may submit your own draft for critique.",
            "answer_text": "",
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
    user_prompt = _build_user_prompt(
        master_resume=master_resume,
        job_title=job["title"] or "",
        company=job["company"] or "",
        question=question,
        jd_text=jd_text,
        accuracy_rules_text=accuracy_rules_text,
    )

    # 5. Call LLM
    system_prompt = SYSTEM_PROMPT
    channel_rules = settings.channel_rules
    if channel_rules and channel_rules.application_answer:
        aa_channel = channel_rules.application_answer
        channel_lines: list[str] = []
        if aa_channel.format_hints:
            channel_lines.append(f"Format: {aa_channel.format_hints}")
        if channel_lines:
            system_prompt += f"\n\n--- CHANNEL RULES (application_answer) ---\n" + "\n".join(channel_lines) + "\n--- END CHANNEL RULES ---\n"

    router = ModelRouter(settings)
    response = router.generate(
        task=task,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    answer_text = response.text

    # draft_only: mark as draft but keep content clean — the notice is NOT
    # concatenated into answer_text. The is_draft flag and draft_notice string
    # are returned separately so the frontend can render a banner above the
    # copyable content.
    is_draft = ai_policy == "draft_only"
    draft_notice = (
        "This content was AI-generated for your reference. "
        "Please rewrite in your own words before submitting."
        if is_draft else ""
    )

    # 6. Validate accuracy (on clean content, not the draft notice)
    validator = AccuracyValidator(settings)
    validation = validator.validate(
        answer_text, artifact_type="application_answer", master_resume=master_resume,
    )

    # 6b. Run traceability check
    traceability = TraceabilityChecker(settings)
    if traceability.enabled:
        trace_result = traceability.check(answer_text, master_resume, artifact_type="application_answer")
        trace_result.merge_into(validation)

    # 7. Save to DB
    now = datetime.now(timezone.utc).isoformat()
    output_dir = Path(settings.profile.resume.output_dir or "data/resumes").expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    safe_company = (job["company"] or "unknown").replace(" ", "_").replace("/", "_")
    md_filename = f"answer_{safe_company}_{job_id}_{now[:10]}.md"
    md_path = output_dir / md_filename
    # Write clean content to the markdown file. If draft_only, add an
    # HTML comment header that is clearly out-of-band (not pasteable as
    # answer text into a form).
    if is_draft:
        file_content = f"<!-- DRAFT: {draft_notice} -->\n\n{answer_text}"
    else:
        file_content = answer_text
    md_path.write_text(file_content)

    cursor = db.execute(
        """
        INSERT INTO application_answers
        (job_id, question, task, provider, model, answer_text, master_resume_path,
         validation_passed, validation_violations, validation_checked_at,
         input_tokens, output_tokens, latency_ms, generated_at, updated_at,
         markdown_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_id, question, task, response.provider, response.model,
            answer_text, str(master_path),
            validation.passed,
            json.dumps(validation.to_dict()["violations"]),
            validation.checked_at,
            response.input_tokens, response.output_tokens, response.latency_ms,
            now, now, str(md_path),
        ),
    )
    answer_id = cursor.lastrowid
    db.commit()
    db.close()

    return {
        "answer_id": answer_id,
        "job_id": job_id,
        "question": question,
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


def critique_application_answer(
    settings: Settings,
    job_id: int,
    question: str,
    user_draft: str,
    task: str = "application_answer_critique",
    temperature: float = 0.3,
    max_tokens: int | None = 2000,
) -> dict:
    """Critique a user-supplied draft answer (allowed even when ai_policy='forbidden').

    This does NOT author content — it only reviews and suggests improvements.

    Args:
        settings: App settings
        job_id: Database job ID
        question: The application question
        user_draft: The user's own draft answer
        task: LLM task name
        temperature: LLM temperature
        max_tokens: Max output tokens

    Returns:
        Dict with critique feedback.
    """
    # 1. Load the job from DB
    db = get_connection()
    job = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not job:
        db.close()
        raise ValueError(f"Job {job_id} not found")

    # 2. Load master resume
    if not settings.profile or not settings.profile.resume:
        db.close()
        raise ValueError("No resume config in profile.yml")

    master_path = Path(settings.profile.resume.master_path).expanduser()
    if not master_path.exists():
        db.close()
        raise FileNotFoundError(f"Master resume not found at {master_path}")

    master_resume = master_path.read_text()

    # 3. Load accuracy rules for the critique prompt
    accuracy_rules_text = _load_accuracy_rules_text(settings)

    # 4. Build prompt
    user_prompt = _build_critique_prompt(
        master_resume=master_resume,
        question=question,
        user_draft=user_draft,
        accuracy_rules_text=accuracy_rules_text,
    )

    # 5. Call LLM
    router = ModelRouter(settings)
    response = router.generate(
        task=task,
        system_prompt=CRITIQUE_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    db.close()

    return {
        "job_id": job_id,
        "question": question,
        "critique": response.text,
        "provider": response.provider,
        "model": response.model,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "latency_ms": response.latency_ms,
    }
