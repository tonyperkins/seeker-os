"""Promptfoo helper — generates test cases from the golden dataset.

Loads evals/golden_dataset.yml and produces promptfoo test specs:
  - jdAnalysisTests: verdict exact-match + valid JSON assertion
  - resumeGenerationTests: LLM-as-judge faithfulness using traceability judge
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import yaml

_repo_root = Path(__file__).resolve().parents[3]
_GOLDEN_DATASET = _repo_root / "evals" / "golden_dataset.yml"

# Traceability judge system prompt — reused, not duplicated
_JUDGE_SYSTEM_PROMPT = (
    _repo_root / "backend" / "seeker_os" / "validation" / "prompts"
    / "traceability_judge_system.txt"
).read_text(encoding="utf-8")

_JUDGE_USER_TEMPLATE = (
    _repo_root / "backend" / "seeker_os" / "validation" / "prompts"
    / "traceability_judge_user_template.txt"
).read_text(encoding="utf-8")


def _load_master_resume_for_judge() -> str:
    """Load master resume text for inclusion in the judge rubric.

    The llm-rubric judge only sees the model output, not the original prompt.
    We need to include the master resume in the rubric so the judge can
    verify traceability.
    """
    sys.path.insert(0, str(_repo_root / "backend"))
    from seeker_os.config import get_settings
    config_dir = os.environ.get("SEEKER_OS_CONFIG_DIR", str(_repo_root / "config"))
    os.environ.setdefault("SEEKER_OS_CONFIG_DIR", config_dir)
    settings = get_settings()
    if not settings.profile or not settings.profile.resume:
        return "(no master resume configured)"
    master_path = Path(settings.profile.resume.master_path).expanduser()
    if not master_path.exists():
        return f"(master resume not found at {master_path})"
    return master_path.read_text()


def _load_golden_dataset() -> list[dict]:
    """Load active cases from the golden dataset.

    If EVAL_TEST_LIMIT env var is set, return only that many cases
    (spread across verdict categories for representative coverage).
    """
    if not _GOLDEN_DATASET.exists():
        return []
    with open(_GOLDEN_DATASET) as f:
        data = yaml.safe_load(f) or {}
    cases = [c for c in data.get("cases", []) if c.get("status", "active") == "active"]

    limit = os.environ.get("EVAL_TEST_LIMIT")
    if limit:
        limit = int(limit)
        if limit > 0 and limit < len(cases):
            # Spread across verdicts: take proportional samples from each category
            from collections import defaultdict
            by_verdict = defaultdict(list)
            for c in cases:
                by_verdict[c["expected_verdict"]].append(c)
            result = []
            per_verdict = max(1, limit // len(by_verdict))
            for verdict, group in by_verdict.items():
                result.extend(group[:per_verdict])
            return result[:limit]
    return cases


def _extract_json(text: str) -> str:
    """Extract JSON from model output, handling markdown fences and reasoning prefixes.

    Some models (Qwen, DeepSeek) prepend 'Thinking: ...' reasoning before the JSON.
    Some wrap in ```json ... ``` fences.
    """
    text = text.strip()
    # Strip markdown code fences
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    # If it starts with { or [, assume it's already JSON
    if text and text[0] in "{[":
        return text
    # Try to find JSON object/array in the text (handles reasoning prefixes)
    for marker in ["{", "["]:
        idx = text.find(marker)
        if idx >= 0:
            # Find the matching closing bracket
            return text[idx:]
    return text


def _json_extract_code() -> str:
    """Python code snippet to extract JSON from model output.

    Handles markdown fences and reasoning/thinking prefixes (Qwen, DeepSeek).
    This is injected into assertion 'value' fields.
    """
    return '''
import json

text = output.strip()
if text.startswith("```"):
    text = text.split("\\n", 1)[1] if "\\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
# Handle reasoning/thinking prefixes (Qwen, DeepSeek, etc.)
# Find the last valid JSON object in the text
if text and text[0] not in "{[":
    # Try last fenced block first
    fence_idx = text.rfind("```")
    if fence_idx > 0:
        before = text[:fence_idx]
        open_fence = before.rfind("```")
        if open_fence >= 0:
            inner = text[open_fence+3:fence_idx].strip()
            if inner and inner[0] in "{[":
                text = inner
    # Fall back: scan backwards for a brace that starts valid JSON
    if text[0] not in "{[":
        search_pos = len(text)
        found = False
        while search_pos > 0 and not found:
            idx = text.rfind("{", 0, search_pos)
            if idx < 0:
                break
            candidate = text[idx:].rstrip("` \\n\\r")
            if candidate.endswith("```"):
                candidate = candidate[:-3].strip()
            try:
                json.loads(candidate)
                text = candidate
                found = True
            except json.JSONDecodeError:
                search_pos = idx
        if not found:
            idx = text.find("{")
            if idx >= 0:
                text = text[idx:]
'''


def _verdict_assert(expected_verdict: str) -> dict:
    """Build a verdict exact-match assertion."""
    return {
        "type": "python",
        "value": _json_extract_code() + f'''try:
    data = json.loads(text)
except json.JSONDecodeError as e:
    return {{"pass": False, "score": 0, "reason": f"Invalid JSON: {{e}}"}}
verdict = data.get("verdict", "")
if verdict == "{expected_verdict}":
    return {{"pass": True, "score": 1, "reason": f"Verdict match: {{verdict}}"}}
return {{"pass": False, "score": 0, "reason": f"Expected {expected_verdict}, got {{verdict}}"}}
''',
    }


def _json_schema_assert() -> dict:
    """Build a valid-JSON + required-fields assertion."""
    return {
        "type": "python",
        "value": _json_extract_code() + '''
_REQUIRED_FIELDS = {"verdict", "weighted_score", "named_gaps", "confidence"}
try:
    data = json.loads(text)
except json.JSONDecodeError as e:
    return {"pass": False, "score": 0, "reason": f"Invalid JSON: {e}"}
missing = _REQUIRED_FIELDS - set(data.keys())
if missing:
    return {"pass": False, "score": 0, "reason": f"Missing required fields: {missing}"}
return {"pass": True, "score": 1, "reason": "Valid JSON with all required fields"}
''',
    }


def jdAnalysisTests() -> list[dict]:
    """Generate promptfoo test cases for JD analysis verdict accuracy."""
    cases = _load_golden_dataset()
    tests = []
    for case in cases:
        tests.append({
            "vars": {
                "jd_text": case["jd_text"],
                "title": case.get("title", ""),
            },
            "assert": [
                _json_schema_assert(),
                _verdict_assert(case["expected_verdict"]),
            ],
            "metadata": {
                "case_id": case["id"],
                "expected_verdict": case["expected_verdict"],
                "expected_gaps": case.get("expected_gaps", []),
            },
        })
    return tests


def _faithfulness_judge_assert() -> dict:
    """Build an LLM-as-judge faithfulness assertion using the traceability judge.

    The judge prompt is reused from validation/prompts/traceability_judge_system.txt.
    Any unsupported or overstated claim = failure (matches TraceabilityChecker
    severity in traceability.py:254-269).

    The judge provider is configurable via env vars:
      JUDGE_PROVIDER_ID — full promptfoo provider id (default: anthropic:messages:claude-haiku-4-5)
      JUDGE_API_BASE_URL — API base URL (default: https://api.anthropic.com)
      JUDGE_API_KEY — API key env var name in nunjucks syntax (default: {{ env.ANTHROPIC_API_KEY }})
    """
    judge_provider_id = os.environ.get(
        "JUDGE_PROVIDER_ID", "anthropic:messages:claude-haiku-4-5"
    )
    judge_api_base = os.environ.get(
        "JUDGE_API_BASE_URL", "https://api.anthropic.com"
    )
    judge_api_key = os.environ.get(
        "JUDGE_API_KEY", "{{ env.ANTHROPIC_API_KEY }}"
    )

    return {
        "type": "llm-rubric",
        "value": (
            "Judge the generated resume for traceability. Use the following "
            "system prompt as the rubric:\n\n"
            + _JUDGE_SYSTEM_PROMPT
            + "\n\n=== MASTER RESUME (source of truth) ===\n"
            + _load_master_resume_for_judge()
            + "\n\n=== END MASTER RESUME ===\n\n"
            "The generated resume is the model output below. "
            "If ANY claim in the generated resume is 'unsupported' or 'overstated' "
            "per the judge's verdict (comparing against the master resume above), "
            "the test FAILS. Only 'supported' claims pass. "
            "Respond with PASS or FAIL and a brief reason."
        ),
        "provider": {
            "id": judge_provider_id,
            "config": {
                "apiBaseUrl": judge_api_base,
                "apiKey": judge_api_key,
                "temperature": 0.0,
                "max_tokens": 16000,
            },
        },
    }


def resumeGenerationTests() -> list[dict]:
    """Generate promptfoo test cases for resume generation faithfulness.

    Only includes cases with APPLY or CONDITIONAL verdicts — these are the
    cases where resume generation would actually run in production.
    """
    cases = _load_golden_dataset()
    tests = []
    for case in cases:
        if case["expected_verdict"] not in ("APPLY", "CONDITIONAL"):
            continue
        tests.append({
            "vars": {
                "jd_text": case["jd_text"],
                "title": case.get("title", ""),
            },
            "assert": [
                _faithfulness_judge_assert(),
            ],
            "metadata": {
                "case_id": case["id"],
                "expected_verdict": case["expected_verdict"],
            },
        })
    return tests
