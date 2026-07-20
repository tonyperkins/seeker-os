"""Resume generator — tailors a master resume to a specific job description.

Reads the master resume from the path in profile.yml, constructs a prompt
that includes the JD and accuracy rules, calls the LLM via the model router,
and stores the result.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from seeker_os.config import Settings
from seeker_os.database import get_connection, json_decode
from seeker_os.events import Actor, EventType, JobStatus, record_event, transition_status
from seeker_os.llm.router import ModelRouter
from seeker_os.observability.llm_ledger import attach_artifact, digest, fingerprint, record_evaluation
from seeker_os.resume.bullet_ranker import CompetencySelectionResult, select_bullets_for_role, select_competencies, select_projects
from seeker_os.resume.master_parser import parse_master_resume, render_filtered_master
from seeker_os.resume.role_recency import years_since_end
from seeker_os.validation import AccuracyValidator, Violation
from seeker_os.validation.ats_parse import ATSParseValidator
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


def _build_tiering_instructions(
    settings: Settings,
    selections_active: bool = False,
    mid_old_active: bool = False,
    portfolio_active: bool = False,
    competency_active: bool = False,
) -> str:
    """Build recency/relevance tiering instructions from channel_rules config.

    Returns empty string if no content_tiering is configured — the prompt
    says nothing about tiering in that case. No hardcoded values.

    `selections_active` indicates whether deterministic Phase 1 bullet
    selection actually ran for recent-tier roles. When True, the recent-roles
    line is rewritten to avoid contradicting the DETERMINISTIC BULLET SELECTION
    block.

    `mid_old_active` indicates mid/old tier deterministic selection also ran.
    When True, the mid/old lines are rewritten similarly.

    `portfolio_active` indicates portfolio project selection ran.

    `competency_active` indicates competency category selection ran.
    """
    if not settings.channel_rules or not settings.channel_rules.resume:
        return ""
    tiering = settings.channel_rules.resume.content_tiering
    if not tiering:
        return ""

    if selections_active:
        recent_line = (
            f"- Recent roles (within the last {tiering.recent_years} years): bullets have "
            f"already been deterministically pre-selected by relevance to this JD (see the "
            f"DETERMINISTIC BULLET SELECTION section below) — render exactly the bullets "
            f"provided for those roles; do not add or invent additional ones."
        )
    else:
        recent_line = (
            f"- Recent roles (within the last {tiering.recent_years} years): keep ALL strong "
            f"bullets — full detail."
        )

    if mid_old_active:
        mid_line = (
            f"- Mid-age roles ({tiering.recent_years}-{tiering.mid_years} years old): bullets have "
            f"already been deterministically pre-selected and capped at {tiering.mid_max_bullets} — "
            f"render exactly the bullets provided; do not add or invent additional ones."
        )
        old_line = (
            f"- Old roles ({tiering.mid_years}+ years old): bullets have already been "
            f"deterministically pre-selected and capped at {tiering.old_max_bullets} — "
            f"render exactly the bullets provided; do not add or invent additional ones."
        )
    else:
        mid_line = (
            f"- Mid-age roles ({tiering.recent_years}-{tiering.mid_years} years old): compress to at most {tiering.mid_max_bullets} highest-impact bullets. Prefer bullets with quantified outcomes or keywords matching the target JD; drop generic ones."
        )
        old_line = (
            f"- Old roles ({tiering.mid_years}+ years old): compress to at most {tiering.old_max_bullets} bullet or a single summary line."
        )

    lines = [
        f"Target length: {tiering.target_pages} pages. Apply recency-based bullet tiering to every role:",
        recent_line,
        mid_line,
        old_line,
        "- NEVER drop a role entirely or alter dates/titles. This is about bullet COUNT per role, not removing history.",
        "- JD-relevance can PROMOTE an older role's bullet: if a bullet from an older role directly matches the target JD's stack or requirements, keep it even when compressing. Recency is the default axis; JD-relevance can override downward compression.",
        "- All honesty/traceability rules still apply. Compressing means SELECTING which true bullets to show — never invent or merge into new claims.",
    ]

    if portfolio_active:
        lines.append(
            f"- Portfolio Projects: projects and their bullets have already been deterministically "
            f"selected by relevance to this JD (see the DETERMINISTIC BULLET SELECTION section below) — "
            f"render exactly the projects and bullets provided; do not add or invent additional ones."
        )

    if competency_active:
        comp_line = (
            f"- Core Competencies: categories have already been deterministically selected by relevance "
            f"to this JD — render exactly the competency categories provided in the master resume text; "
            f"do not add categories that aren't shown, and do not alter category labels or qualifier text."
        )
        if tiering.max_items_per_category > 0:
            comp_line += (
                f" Individual skill items within each category have also been pre-selected — "
                f"render exactly the items provided; do not add or reword items."
            )
        lines.append(comp_line)

    return "\n".join(lines)


def _build_selection_instructions(
    role_titles: dict[str, str],
    project_titles: dict[str, str] | None = None,
) -> str:
    """Build the render-only instruction for roles/projects with pre-selected bullets.

    Returns empty string if no roles or projects had deterministic selection applied.
    """
    project_titles = project_titles or {}
    if not role_titles and not project_titles:
        return ""

    parts: list[str] = []
    if role_titles:
        titles = ", ".join(sorted(role_titles.values()))
        parts.append(
            f"Roles with pre-selected bullets: {titles}"
        )
    if project_titles:
        p_titles = ", ".join(sorted(project_titles.values()))
        parts.append(
            f"Portfolio projects with pre-selected bullets: {p_titles}"
        )

    return (
        "For the following items, bullets have already been selected deterministically "
        "based on relevance to this JD — the master resume text you were given for these "
        "items contains ONLY the pre-selected bullets, in their original order.\n"
        "Render exactly those bullets (you may still reorder/reframe wording per the usual "
        "tailoring rules) — do NOT add a bullet for these items that isn't shown, and do NOT "
        "omit a bullet that IS shown. Selection is already done; your job here is rendering, "
        "not re-selecting.\n"
        + "\n".join(parts)
    )


def _run_deterministic_bullet_selection(
    settings: Settings,
    master_resume: str,
    jd_text: str,
    job_title: str,
    operation_id: str,
) -> tuple[str, dict[str, str], dict[str, str], bool, bool, bool, list[str], list[str]]:
    """Phase 1 + 1d + 3: deterministically select bullets and competency
    categories by JD relevance.

    Returns (master_resume_for_prompt, role_titles, project_titles,
    mid_old_active, portfolio_active, competency_active,
    selected_category_labels, pinned_bullet_texts).

    - role_titles maps role_id -> title for every role that had selection
      applied (empty dict if none).
    - project_titles maps project_id -> title for every portfolio project
      that had bullet selection applied (empty dict if none).
    - mid_old_active: True if mid/old tier deterministic selection ran.
    - portfolio_active: True if portfolio project selection ran.
    - competency_active: True if competency category selection ran.
    - selected_category_labels: list of selected category labels (empty if none).
    - pinned_bullet_texts: list of pinned bullet text strings that were
      selected (for ATS parse-survival verification).

    Falls back to the original master_resume text (selection inactive) on
    any parsing error — resume generation must never break because the
    master resume's formatting doesn't match the parser's expectations.
    """
    logger = logging.getLogger(__name__)
    if not settings.channel_rules or not settings.channel_rules.resume:
        return master_resume, {}, {}, False, False, False, [], []
    tiering = settings.channel_rules.resume.content_tiering
    if not tiering:
        return master_resume, {}, {}, False, False, False, [], []

    try:
        parsed = parse_master_resume(master_resume)
        title_stopwords = frozenset(tiering.title_stopwords)
        business_stopwords = frozenset(tiering.business_stopwords)
        selections: dict[str, list[int]] = {}
        role_titles: dict[str, str] = {}
        mid_old_active = False
        pinned_bullet_texts: list[str] = []

        # --- Recent tier (Phase 1) ---
        recent_roles = [
            role
            for role in parsed.roles_in_section("Professional Experience")
            if role.bullets
            and (
                (years := years_since_end(role.dates_raw)) is None
                or years <= tiering.recent_years
            )
        ]

        for role in recent_roles:
            cap = (
                tiering.recent_current_role_max_bullets
                if role.is_current
                else tiering.recent_other_max_bullets
            )
            if len(role.bullets) <= cap:
                continue

            result = select_bullets_for_role(
                bullets=role.bullets,
                jd_text=jd_text,
                job_title=job_title,
                cap=cap,
                near_duplicate_threshold=tiering.near_duplicate_similarity_threshold,
                title_stopwords=title_stopwords,
                business_stopwords=business_stopwords,
            )
            selections[role.role_id] = [item["index"] for item in result.selected]
            role_titles[role.role_id] = role.title

            try:
                record_evaluation(
                    operation_id=operation_id,
                    evaluator_name="bullet_selection",
                    evaluator_type="deterministic",
                    metric_name="bullet_selection",
                    passed=True,
                    label=role.role_id,
                    details={
                        "role_title": role.title,
                        "tier": "recent",
                        "candidate_count": result.candidate_count,
                        "post_dedupe_count": result.post_dedupe_count,
                        "cap": cap,
                        "selected": result.selected,
                        "dropped": result.dropped,
                        "warnings": result.warnings,
                        "jd_scope_mode": result.jd_scope_mode,
                    },
                )
            except Exception:
                logger.exception(
                    "bullet_selection_evaluation_write_failed",
                    extra={"operation_id": operation_id, "role_id": role.role_id},
                )

        # --- Mid/old tier deterministic enforcement (Phase 1d) ---
        all_exp_roles = parsed.roles_in_section("Professional Experience")
        for role in all_exp_roles:
            years = years_since_end(role.dates_raw)
            if years is None or years <= tiering.recent_years:
                continue  # already handled as recent

            if years <= tiering.mid_years:
                cap = tiering.mid_max_bullets
                tier_label = "mid"
            else:
                cap = tiering.old_max_bullets
                tier_label = "old"

            if not role.bullets or len(role.bullets) <= cap:
                continue

            result = select_bullets_for_role(
                bullets=role.bullets,
                jd_text=jd_text,
                job_title=job_title,
                cap=cap,
                near_duplicate_threshold=tiering.near_duplicate_similarity_threshold,
                title_stopwords=title_stopwords,
                business_stopwords=business_stopwords,
            )
            selections[role.role_id] = [item["index"] for item in result.selected]
            role_titles[role.role_id] = role.title
            mid_old_active = True

            try:
                record_evaluation(
                    operation_id=operation_id,
                    evaluator_name="bullet_selection",
                    evaluator_type="deterministic",
                    metric_name="bullet_selection",
                    passed=True,
                    label=role.role_id,
                    details={
                        "role_title": role.title,
                        "tier": tier_label,
                        "candidate_count": result.candidate_count,
                        "post_dedupe_count": result.post_dedupe_count,
                        "cap": cap,
                        "selected": result.selected,
                        "dropped": result.dropped,
                        "warnings": result.warnings,
                        "jd_scope_mode": result.jd_scope_mode,
                    },
                )
            except Exception:
                logger.exception(
                    "bullet_selection_evaluation_write_failed",
                    extra={"operation_id": operation_id, "role_id": role.role_id},
                )

        # --- Early Career roles: enforce old_max_bullets deterministically ---
        early_career_roles = parsed.roles_in_section("Early Career")
        for role in early_career_roles:
            cap = tiering.old_max_bullets
            if not role.bullets or len(role.bullets) <= cap:
                continue

            result = select_bullets_for_role(
                bullets=role.bullets,
                jd_text=jd_text,
                job_title=job_title,
                cap=cap,
                near_duplicate_threshold=tiering.near_duplicate_similarity_threshold,
                title_stopwords=title_stopwords,
                business_stopwords=business_stopwords,
            )
            selections[role.role_id] = [item["index"] for item in result.selected]
            role_titles[role.role_id] = role.title
            mid_old_active = True

            try:
                record_evaluation(
                    operation_id=operation_id,
                    evaluator_name="bullet_selection",
                    evaluator_type="deterministic",
                    metric_name="bullet_selection",
                    passed=True,
                    label=role.role_id,
                    details={
                        "role_title": role.title,
                        "tier": "early_career",
                        "candidate_count": result.candidate_count,
                        "post_dedupe_count": result.post_dedupe_count,
                        "cap": cap,
                        "selected": result.selected,
                        "dropped": result.dropped,
                        "warnings": result.warnings,
                        "jd_scope_mode": result.jd_scope_mode,
                    },
                )
            except Exception:
                logger.exception(
                    "bullet_selection_evaluation_write_failed",
                    extra={"operation_id": operation_id, "role_id": role.role_id},
                )

        # --- Portfolio project selection (Phase 1d) ---
        project_titles: dict[str, str] = {}
        dropped_project_ids: set[str] = set()
        portfolio_active = False

        if parsed.projects:
            proj_result = select_projects(
                projects=parsed.projects,
                jd_text=jd_text,
                job_title=job_title,
                max_projects=tiering.max_projects,
                max_bullets_per_project=tiering.max_bullets_per_project,
                always_include=tiering.always_include_projects,
                near_duplicate_threshold=tiering.near_duplicate_similarity_threshold,
                title_boost=tiering.title_boost,
                title_stopwords=title_stopwords,
                business_stopwords=business_stopwords,
            )
            portfolio_active = bool(proj_result.selected_project_ids or proj_result.dropped_project_ids)

            # Merge project bullet selections into the shared selections dict
            for pid, bullet_result in proj_result.per_project.items():
                selections[pid] = [item["index"] for item in bullet_result.selected]
                project = parsed.project_by_id(pid)
                if project:
                    project_titles[pid] = project.title

                try:
                    record_evaluation(
                        operation_id=operation_id,
                        evaluator_name="bullet_selection",
                        evaluator_type="deterministic",
                        metric_name="bullet_selection",
                        passed=True,
                        label=pid,
                        details={
                            "project_title": project.title if project else pid,
                            "tier": "portfolio",
                            "candidate_count": bullet_result.candidate_count,
                            "post_dedupe_count": bullet_result.post_dedupe_count,
                            "cap": tiering.max_bullets_per_project,
                            "selected": bullet_result.selected,
                            "dropped": bullet_result.dropped,
                            "warnings": bullet_result.warnings,
                            "jd_scope_mode": bullet_result.jd_scope_mode,
                        },
                    )
                except Exception:
                    logger.exception(
                        "bullet_selection_evaluation_write_failed",
                        extra={"operation_id": operation_id, "project_id": pid},
                    )

            # Record dropped projects
            dropped_project_ids = set(proj_result.dropped_project_ids)

            # Record zero-bullet project blocks suppressed from render output
            for project in parsed.projects:
                if not project.has_bullets:
                    try:
                        record_evaluation(
                            operation_id=operation_id,
                            evaluator_name="bullet_selection",
                            evaluator_type="deterministic",
                            metric_name="bullet_selection",
                            passed=True,
                            label=project.project_id,
                            details={
                                "project_title": project.title,
                                "tier": "portfolio",
                                "reason": "zero_bullet_suppressed",
                                "warning": f"zero_bullet_suppressed:{project.title}",
                            },
                        )
                    except Exception:
                        logger.exception(
                            "bullet_selection_evaluation_write_failed",
                            extra={"operation_id": operation_id, "project_id": project.project_id},
                        )

            # Record always_include_unmatched warnings
            for warning in proj_result.warnings:
                try:
                    record_evaluation(
                        operation_id=operation_id,
                        evaluator_name="bullet_selection",
                        evaluator_type="deterministic",
                        metric_name="bullet_selection",
                        passed=True,
                        label=warning,
                        details={"warning": warning},
                    )
                except Exception:
                    logger.exception(
                        "bullet_selection_evaluation_write_failed",
                        extra={"operation_id": operation_id, "warning": warning},
                    )

        # --- Competency category selection (Phase 3) ---
        dropped_category_line_nos: set[int] = set()
        competency_active = False
        selected_category_labels: list[str] = []
        cat_result = CompetencySelectionResult()

        if parsed.categories:
            cat_result = select_competencies(
                categories=parsed.categories,
                jd_text=jd_text,
                job_title=job_title,
                max_categories=tiering.max_competency_categories,
                always_include=tiering.always_include_competency_categories,
                title_boost=tiering.title_boost,
                title_stopwords=title_stopwords,
                business_stopwords=business_stopwords,
                label_boost=tiering.competency_label_boost,
                qualifier_stopwords=frozenset(tiering.competency_qualifier_stopwords),
                max_items_per_category=tiering.max_items_per_category,
            )
            competency_active = bool(cat_result.selected_labels)
            selected_category_labels = cat_result.selected_labels
            dropped_category_line_nos = cat_result.dropped_line_nos

            try:
                record_evaluation(
                    operation_id=operation_id,
                    evaluator_name="bullet_selection",
                    evaluator_type="deterministic",
                    metric_name="competency_selection",
                    passed=True,
                    label="competency_categories",
                    details={
                        "selected_labels": cat_result.selected_labels,
                        "dropped": cat_result.dropped_labels,
                        "warnings": cat_result.warnings,
                        "jd_scope_mode": cat_result.jd_scope_mode,
                        "max_categories": tiering.max_competency_categories,
                        "always_include": tiering.always_include_competency_categories,
                        "max_items_per_category": tiering.max_items_per_category,
                        "kept_items": cat_result.kept_items,
                        "dropped_items": cat_result.dropped_items,
                    },
                )
            except Exception:
                logger.exception(
                    "bullet_selection_evaluation_write_failed",
                    extra={"operation_id": operation_id, "label": "competency_categories"},
                )

            for warning in cat_result.warnings:
                try:
                    record_evaluation(
                        operation_id=operation_id,
                        evaluator_name="bullet_selection",
                        evaluator_type="deterministic",
                        metric_name="competency_selection",
                        passed=True,
                        label=warning,
                        details={"warning": warning},
                    )
                except Exception:
                    logger.exception(
                        "bullet_selection_evaluation_write_failed",
                        extra={"operation_id": operation_id, "warning": warning},
                    )

        if not selections and not dropped_project_ids and not dropped_category_line_nos and not cat_result.kept_items:
            return master_resume, {}, {}, False, False, False, [], []

        # Collect pinned bullet texts that were selected — the ATS gate
        # verifies these survived rendering.
        for role in parsed.roles:
            for idx in selections.get(role.role_id, []):
                if idx < len(role.bullets) and role.bullets[idx].pinned:
                    pinned_bullet_texts.append(role.bullets[idx].text)
        for proj in parsed.projects:
            for idx in selections.get(proj.project_id, []):
                if idx < len(proj.bullets) and proj.bullets[idx].pinned:
                    pinned_bullet_texts.append(proj.bullets[idx].text)

        master_resume_for_prompt = render_filtered_master(
            parsed, selections, dropped_project_ids, dropped_category_line_nos,
            kept_items=cat_result.kept_items if cat_result.kept_items else None,
        )
        return master_resume_for_prompt, role_titles, project_titles, mid_old_active, portfolio_active, competency_active, selected_category_labels, pinned_bullet_texts
    except Exception as exc:
        logger.exception(
            "bullet_selection_failed_falling_back", extra={"operation_id": operation_id}
        )
        try:
            record_evaluation(
                operation_id=operation_id,
                evaluator_name="bullet_selection",
                evaluator_type="deterministic",
                metric_name="bullet_selection",
                passed=False,
                label="parse_error",
                explanation_redacted=f"{type(exc).__name__}: {exc}"[:500],
                details={
                    "fallback": "unfiltered_master_resume",
                    "error_type": type(exc).__name__,
                },
            )
        except Exception:
            logger.exception(
                "bullet_selection_parse_error_eval_write_failed",
                extra={"operation_id": operation_id},
            )
        return master_resume, {}, {}, False, False, False, [], []


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
    operation_id = str(uuid.uuid4())

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

    # 3. Phase 1 + 1d + 3: deterministic bullet and competency selection
    # (pre-filter, not post-hoc trimming). Falls back to the unmodified
    # master resume on any parsing issue. Validation later still uses the
    # ORIGINAL unfiltered master_resume as ground truth — selection only
    # narrows what's offered to the LLM, it never changes what's true.
    master_resume_for_prompt, selected_role_titles, selected_project_titles, mid_old_active, portfolio_active, competency_active, selected_category_labels, pinned_bullet_texts = _run_deterministic_bullet_selection(
        settings=settings,
        master_resume=master_resume,
        jd_text=jd_text,
        job_title=job["title"] or "",
        operation_id=operation_id,
    )

    # 4. Build prompts
    accuracy_rules_text = _load_accuracy_rules_text(settings)
    anchor_text = _load_identity_anchor_text(settings)
    user_prompt = _build_user_prompt(
        master_resume=master_resume_for_prompt,
        job_title=job["title"] or "",
        company=job["company"] or "",
        jd_text=jd_text,
        accuracy_rules_text=accuracy_rules_text,
        anchor_text=anchor_text,
    )

    # 5. Call LLM (inject user instructions and channel rules into system prompt)
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
            system_prompt += "\n\n--- CHANNEL RULES (resume) ---\n" + "\n".join(channel_lines) + "\n--- END CHANNEL RULES ---\n"

    # Inject content tiering instructions from channel_rules config
    tiering_text = _build_tiering_instructions(
        settings,
        selections_active=bool(selected_role_titles),
        mid_old_active=mid_old_active,
        portfolio_active=portfolio_active,
        competency_active=competency_active,
    )
    if tiering_text:
        system_prompt += f"\n\n--- CONTENT TIERING (resume) ---\n{tiering_text}\n--- END CONTENT TIERING ---\n"

    # Inject the render-only rule for roles/projects with deterministically pre-selected bullets
    selection_text = _build_selection_instructions(selected_role_titles, selected_project_titles)
    if selection_text:
        system_prompt += f"\n\n--- DETERMINISTIC BULLET SELECTION ---\n{selection_text}\n--- END DETERMINISTIC BULLET SELECTION ---\n"
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
        operation_id=operation_id,
        prompt_name="resume_generation",
        prompt_version="1",
        prompt_template=_USER_PROMPT_TEMPLATE,
    )
    _emit("llm_generation", "Generating resume with LLM", "completed", f"{response.output_tokens} tokens in {response.latency_ms}ms")

    # 6. Validate accuracy (deterministic deny-list + LLM-judged traceability)
    _emit("validation", "Running accuracy validation", "started")
    validator = AccuracyValidator(settings)
    validation = validator.validate(response.text, artifact_type="resume", master_resume=master_resume)
    logger = logging.getLogger(__name__)
    logger.info("resume_gen job_id=%s: accuracy validation done, passed=%s, violations=%d", job_id, validation.passed, len(validation.violations))

    # 6b. Run traceability check (LLM-judged claim verification)
    traceability = TraceabilityChecker(settings)
    if traceability.enabled:
        _emit("traceability", "Verifying claim traceability", "started")
        trace_result = traceability.check(
            response.text, master_resume, artifact_type="resume",
            operation_id=operation_id, parent_call_id=response.call_id,
        )
        trace_result.merge_into(validation)
        _emit("traceability", "Verifying claim traceability", "completed", f"{len(trace_result.violations)} violations")
        logger.info("resume_gen job_id=%s: traceability done, claims=%d, violations=%d", job_id, len(trace_result.claims), len(trace_result.violations))

    # 6c. Page-count gate (PDF page count via weasyprint render)
    _emit("page_count", "Checking PDF page count", "started")
    from seeker_os.validation import PageCountValidator
    page_validator = PageCountValidator(settings)
    page_result = page_validator.validate(response.text)
    if page_result.violations:
        validation.violations.extend(page_result.violations)
        validation.passed = not any(v.severity == "high" for v in validation.violations)
    if page_result.diagnostics:
        validation.diagnostics = page_result.diagnostics
    if page_result.page_count is not None:
        validation.page_count = page_result.page_count
    page_count_str = f"{page_result.page_count} pages" if page_result.page_count is not None else "unknown"
    _emit("page_count", "Checking PDF page count", "completed", page_count_str)
    logger.info("resume_gen job_id=%s: page count check done, pages=%s, violations=%d", job_id, page_count_str, len(page_result.violations))

    # 6d. ATS parse-survival gate (deterministic text extraction checks)
    _emit("ats_parse", "Checking ATS parse survival", "started")
    ats_validator = ATSParseValidator(settings)
    ats_result = ats_validator.validate(
        resume_text=response.text,
        master_resume=master_resume,
        selected_role_titles=selected_role_titles,
        selected_project_titles=selected_project_titles,
        selected_category_labels=selected_category_labels,
        pinned_bullet_texts=pinned_bullet_texts,
    )
    if ats_result.violations:
        validation.violations.extend(
            Violation(**v) if isinstance(v, dict) else v
            for v in ats_result.violations
        )
    if ats_result.diagnostics:
        validation.diagnostics.update(ats_result.diagnostics)
    ats_str = f"{'passed' if ats_result.passed else f'{len(ats_result.violations)} failures'}"
    _emit("ats_parse", "Checking ATS parse survival", "completed", ats_str)
    logger.info("resume_gen job_id=%s: ATS parse check done, passed=%s, failures=%d", job_id, ats_result.passed, len(ats_result.violations))

    try:
        record_evaluation(
            operation_id=operation_id,
            call_id=response.call_id or None,
            evaluator_name="ats_parse_validator",
            evaluator_type="deterministic",
            metric_name="ats_parse_survival",
            passed=ats_result.passed,
            label="passed" if ats_result.passed else "failed",
            details=ats_result.diagnostics,
        )
    except Exception:
        logger.exception(
            "ats_parse_evaluation_write_failed",
            extra={"operation_id": operation_id},
        )

    _emit("validation", "Running accuracy validation", "completed", f"{'passed' if validation.passed else 'violations found'}")

    t0 = time.monotonic()
    try:
        record_evaluation(
            operation_id=operation_id,
            call_id=response.call_id or None,
            evaluator_name="accuracy_validator",
            evaluator_type="deterministic",
            metric_name="accuracy_validation",
            passed=validation.passed,
            label="passed" if validation.passed else "failed",
            details={"violation_count": len(validation.violations)},
            rubric_digest=digest(accuracy_rules_text),
        )
        logger.info("resume_gen job_id=%s: recording accuracy evaluation", job_id)
        if traceability.enabled:
            logger.info("resume_gen job_id=%s: recording %d claim evaluations", job_id, len(trace_result.claims))
            for claim in trace_result.claims:
                record_evaluation(
                    operation_id=operation_id,
                    call_id=response.call_id or None,
                    judge_call_id=trace_result.judge_call_id or None,
                    evaluator_name="claim_traceability",
                    evaluator_type="model",
                    metric_name="claim_traceability",
                    passed=claim.verdict == "supported",
                    label=claim.verdict,
                    details={
                        "claim_fingerprint": fingerprint(claim.claim),
                        "offending_text_fingerprint": fingerprint(claim.offending_text) if claim.offending_text else None,
                        "explanation_fingerprint": fingerprint(claim.explanation) if claim.explanation else None,
                        "master_resume_digest": digest(master_resume),
                    },
                    rubric_digest=digest(_USER_PROMPT_TEMPLATE),
                )
    except Exception:
        logging.getLogger(__name__).exception(
            "llm_evaluation_write_failed", extra={"operation_id": operation_id}
        )
    logger.info("resume_gen job_id=%s: evaluations recorded in %.1fs", job_id, time.monotonic() - t0)

    # 7. Save to DB
    _emit("saving", "Saving resume", "started")
    t1 = time.monotonic()
    now = datetime.now(UTC).isoformat()
    output_dir = Path(settings.profile.resume.output_dir or "data/resumes").expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save markdown file
    safe_company = (job["company"] or "unknown").replace(" ", "_").replace("/", "_")
    safe_title = (job["title"] or "resume").replace(" ", "_").replace("/", "_")[:50]
    md_filename = f"{safe_company}_{safe_title}_{job_id}_{now[:10]}.md"
    md_path = output_dir / md_filename
    md_path.write_text(response.text)
    logger.info("resume_gen job_id=%s: markdown written to %s", job_id, md_path)

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
    if resume_id is None:
        raise RuntimeError("Resume insert did not return an artifact ID")

    # Promote job status to 'interested' (resume generated = moving forward),
    # but only from non-decision states (ready, reviewing, etc.).  Never
    # override a user decision status (skipped, applied, engaged, etc.).
    if job["status"] not in JobStatus._DECISION_STATUSES:
        transition_status(
            db, job_id, "interested", EventType.RESUME_GENERATED, Actor.SYSTEM,
            metadata={"resume_id": resume_id},
        )
    else:
        record_event(
            db, job_id, EventType.RESUME_GENERATED, Actor.SYSTEM,
            metadata={"resume_id": resume_id, "status_preserved": job["status"]},
        )
    db.commit()
    db.close()
    logger.info("resume_gen job_id=%s: DB insert + status transition done in %.1fs, resume_id=%s", job_id, time.monotonic() - t1, resume_id)
    try:
        attach_artifact(operation_id, "resume", int(resume_id))
    except Exception:
        logging.getLogger(__name__).exception(
            "llm_artifact_link_failed", extra={"operation_id": operation_id}
        )
    logger.info("resume_gen job_id=%s: attach_artifact done, total post-LLM time %.1fs", job_id, time.monotonic() - t0)
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
        "validation_diagnostics": validation.diagnostics,
        "page_count": validation.page_count,
        "markdown_path": str(md_path),
        "generated_at": now,
        "operation_id": operation_id,
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

    now = datetime.now(UTC).isoformat()
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

    if job["status"] not in JobStatus._DECISION_STATUSES:
        transition_status(
            db, job_id, "interested", EventType.RESUME_GENERATED, Actor.SYSTEM,
            metadata={"resume_id": resume_id, "source": "manual"},
        )
    else:
        record_event(
            db, job_id, EventType.RESUME_GENERATED, Actor.SYSTEM,
            metadata={"resume_id": resume_id, "source": "manual",
                      "status_preserved": job["status"]},
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


def list_resumes(
    job_id: int | None = None,
    limit: int = 50,
    search: str | None = None,
    sort_by: str | None = None,
    order: str = "desc",
) -> list[dict]:
    """List generated resumes with optional search and sorting."""
    from seeker_os.api.resumes import RESUME_SORT_EXPRESSIONS

    db = get_connection()
    query = """SELECT r.*, j.company as job_company
               FROM resumes r
               LEFT JOIN jobs j ON r.job_id = j.id
               WHERE 1=1"""
    params: list = []

    if job_id:
        query += " AND r.job_id = ?"
        params.append(job_id)

    if search:
        query += " AND (j.company LIKE ? OR r.provider LIKE ? OR r.model LIKE ? OR r.task LIKE ?)"
        pat = f"%{search}%"
        params.extend([pat, pat, pat, pat])

    effective_sort = sort_by if sort_by and sort_by in RESUME_SORT_EXPRESSIONS else "generated_at"
    sort_expr = RESUME_SORT_EXPRESSIONS[effective_sort]
    direction = "ASC" if order == "asc" else "DESC"
    query += f" ORDER BY {sort_expr} {direction}, r.id DESC LIMIT ?"
    params.append(limit)

    rows = db.execute(query, params).fetchall()
    db.close()

    results = []
    for r in rows:
        results.append({
            "id": r["id"],
            "job_id": r["job_id"],
            "job_company": r["job_company"] or "",
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
