"""Promptfoo helper — builds JD analysis prompt pair with injected config context.

Reads the production prompt files and injects master resume, preferences,
accuracy rules, scoring rubric, and identity rules from config/*.yml —
exactly as jd_analyzer.py does in production. No prompt text is duplicated.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure backend is on the path
_repo_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_repo_root / "backend"))

from seeker_os.analysis.jd_analyzer import (  # noqa: E402
    SYSTEM_PROMPT,
    _build_user_prompt,
    _load_accuracy_rules_text,
    _load_identity_text,
    _load_master_resume,
    _load_prefs_text,
    _load_rubric_text,
)
from seeker_os.config import get_settings  # noqa: E402


def _get_settings():
    """Load settings from the configured config directory."""
    config_dir = os.environ.get("SEEKER_OS_CONFIG_DIR", str(_repo_root / "config"))
    os.environ.setdefault("SEEKER_OS_CONFIG_DIR", config_dir)
    return get_settings()


def buildPrompts(test: dict, context: dict | None = None) -> list[dict]:
    """Build the system + user prompt pair for a JD analysis test case.

    Called by promptfoo for each test case. The test's `vars` must contain
    `jd_text` (the job description). All other context (master resume, prefs,
    rules, rubric, identity) is loaded from config files.
    """
    settings = _get_settings()

    vars = test.get("vars", {})
    jd_text = vars.get("jd_text", "")

    user_prompt = _build_user_prompt(
        master_resume=_load_master_resume(settings),
        prefs_text=_load_prefs_text(settings),
        rules_text=_load_accuracy_rules_text(settings),
        rubric_text=_load_rubric_text(settings),
        identity_text=_load_identity_text(settings),
        jd_text=jd_text,
        company="[COMPANY]",
        title=vars.get("title", "[TITLE]"),
        location=vars.get("location", ""),
        comp_min=vars.get("comp_min"),
        comp_max=vars.get("comp_max"),
        url="",
        company_research_text="(no company research available)",
    )

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
