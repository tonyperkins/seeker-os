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


def _load_golden_dataset() -> list[dict]:
    """Load active cases from the golden dataset."""
    if not _GOLDEN_DATASET.exists():
        return []
    with open(_GOLDEN_DATASET) as f:
        data = yaml.safe_load(f) or {}
    return [c for c in data.get("cases", []) if c.get("status", "active") == "active"]


def _verdict_assert(expected_verdict: str) -> dict:
    """Build a verdict exact-match assertion."""
    return {
        "type": "python",
        "value": f"""
import json

def assert_verdict(output, context):
    text = output.strip()
    if text.startswith("```"):
        text = text.split("\\n", 1)[1] if "\\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return {{"pass": False, "score": 0, "reason": f"Invalid JSON: {{e}}"}}
    verdict = data.get("verdict", "")
    if verdict == "{expected_verdict}":
        return {{"pass": True, "score": 1, "reason": f"Verdict match: {{verdict}}"}}
    return {{"pass": False, "score": 0, "reason": f"Expected {expected_verdict}, got {{verdict}}"}}
""",
    }


def _json_schema_assert() -> dict:
    """Build a valid-JSON + required-fields assertion."""
    return {
        "type": "python",
        "value": """
import json

_REQUIRED_FIELDS = {"verdict", "weighted_score", "named_gaps", "confidence"}

def assert_json_schema(output, context):
    text = output.strip()
    if text.startswith("```"):
        text = text.split("\\n", 1)[1] if "\\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return {"pass": False, "score": 0, "reason": f"Invalid JSON: {e}"}
    missing = _REQUIRED_FIELDS - set(data.keys())
    if missing:
        return {"pass": False, "score": 0, "reason": f"Missing required fields: {missing}"}
    return {"pass": True, "score": 1, "reason": "Valid JSON with all required fields"}
""",
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
    """
    return {
        "type": "llm-rubric",
        "value": (
            "Judge the generated resume for traceability. Use the following "
            "system prompt as the rubric:\n\n"
            + _JUDGE_SYSTEM_PROMPT
            + "\n\nThe master resume to check against is provided in the user prompt. "
            "If ANY claim in the generated resume is 'unsupported' or 'overstated' "
            "per the judge's verdict, the test FAILS. Only 'supported' claims pass. "
            "Respond with PASS or FAIL and a brief reason."
        ),
        "provider": {
            "id": "anthropic:messages:claude-haiku-4-5",
            "config": {
                "apiBaseUrl": "https://api.anthropic.com",
                "apiKey": "{{ env.ANTHROPIC_API_KEY }}",
                "temperature": 0.0,
                "max_tokens": 4096,
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
