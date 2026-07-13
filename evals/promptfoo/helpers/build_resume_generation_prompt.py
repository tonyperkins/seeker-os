"""Promptfoo helper — builds resume generation prompt pair with injected config context.

Reads the production prompt files and injects master resume and accuracy rules
from config/*.yml — exactly as the resume generator does in production.
No prompt text is duplicated.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure backend is on the path
_repo_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_repo_root / "backend"))

from seeker_os.config import get_settings  # noqa: E402

# Load the production prompt files
_PROMPTS_DIR = _repo_root / "backend" / "seeker_os" / "resume" / "prompts"
_SYSTEM_PROMPT = (_PROMPTS_DIR / "resume_generation_system.txt").read_text(encoding="utf-8")
_USER_TEMPLATE = (_PROMPTS_DIR / "resume_generation_user_template.txt").read_text(encoding="utf-8")


def _get_settings():
    """Load settings from the configured config directory."""
    config_dir = os.environ.get("SEEKER_OS_CONFIG_DIR", str(_repo_root / "config"))
    os.environ.setdefault("SEEKER_OS_CONFIG_DIR", config_dir)
    return get_settings()


def _load_accuracy_rules_text(settings) -> str:
    """Load accuracy rules as a text block for the resume generation prompt."""
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
        lines.append(f"- [{rule.get('severity', 'high').upper()}] {rule['description']}")
        if rule.get('phrases'):
            lines.append(f"  Phrases: {', '.join(rule['phrases'])}")
        if rule.get('technologies'):
            lines.append(f"  FORBIDDEN: {', '.join(rule['technologies'])}")
    return "\n".join(lines) if lines else "(no rules defined)"


def _load_master_resume(settings) -> str:
    """Load the master resume text from the path in profile.yml."""
    if not settings.profile or not settings.profile.resume:
        return "(no master resume configured)"
    master_path = Path(settings.profile.resume.master_path).expanduser()
    if not master_path.exists():
        return f"(master resume not found at {master_path})"
    return master_path.read_text()


def buildPrompts(test: dict, context: dict | None = None) -> list[dict]:
    """Build the system + user prompt pair for a resume generation test case.

    Called by promptfoo for each test case. The test's `vars` must contain
    `jd_text` (the job description). The master resume and accuracy rules
    are loaded from config files.
    """
    settings = _get_settings()

    vars = test.get("vars", {})
    jd_text = vars.get("jd_text", "")

    user_prompt = _USER_TEMPLATE.format(
        master_resume=_load_master_resume(settings),
        job_title=vars.get("title", "[TITLE]"),
        company="[COMPANY]",
        jd_text=jd_text,
        accuracy_rules_text=_load_accuracy_rules_text(settings),
        anchor_section="",
    )

    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
