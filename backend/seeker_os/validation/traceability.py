"""LLM-judged claim traceability checker.

Extracts factual claims from a generated artifact and judges each one
against the master resume. Uses the light/validation tier per LLM_ROUTING.md.

Output per claim: supported | unsupported | overstated.
Any unsupported or overstated claim is a HIGH-severity violation.

Configurable via accuracy_rules.yml:
  traceability:
    enabled: true          # default ON for single generations
    task: "accuracy_validation"  # LLM task name (routes to light tier)

Can be disabled for cost in bulk runs by setting enabled: false.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from seeker_os.config import Settings
from seeker_os.validation import ValidationResult, Violation

logger = logging.getLogger(__name__)


_PROMPTS_DIR = Path(__file__).parent / "prompts"


class ClaimJudgment(BaseModel):
    """A single claim extracted from the artifact and its judgment."""
    claim: str
    verdict: str  # 'supported' | 'unsupported' | 'overstated'
    explanation: str = ""
    offending_text: str = ""


class TraceabilityResult(BaseModel):
    """Result of the traceability pass."""
    claims: list[ClaimJudgment] = Field(default_factory=list)
    violations: list[Violation] = Field(default_factory=list)
    checked_at: str = ""

    def merge_into(self, result: ValidationResult) -> None:
        """Merge traceability violations into a ValidationResult."""
        result.violations.extend(self.violations)
        if any(v.severity == "high" for v in self.violations):
            result.passed = False


JUDGE_SYSTEM_PROMPT = (_PROMPTS_DIR / "traceability_judge_system.txt").read_text(encoding="utf-8")
_JUDGE_USER_TEMPLATE = (_PROMPTS_DIR / "traceability_judge_user_template.txt").read_text(encoding="utf-8")


def _build_judge_user_prompt(artifact_text: str, master_resume: str, artifact_type: str) -> str:
    return _JUDGE_USER_TEMPLATE.format(
        artifact_type=artifact_type,
        master_resume=master_resume,
        artifact_text=artifact_text,
    )


def _extract_json(text: str) -> str:
    """Extract the JSON object from an LLM response.

    Handles:
    - Markdown code fences (```json ... ``` or ``` ... ```)
    - Prose preamble before the JSON object
    - Trailing text after the JSON object
    - Plain JSON with surrounding whitespace
    """
    text = text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json or ```)
        lines = lines[1:]
        # Remove trailing ``` if present
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    # If it starts with {, still use brace matching to find the end
    # (there may be trailing text after the JSON object)
    if text.startswith("{"):
        start = 0
    else:
        # Extract the first JSON object using brace matching
        # This handles prose preamble like "Here is the analysis:\n{...}"
        start = text.find("{")
        if start == -1:
            return text  # No JSON object found — let json.loads raise

    # Find the matching closing brace
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]

    # Truncated JSON — return what we have
    return text[start:]


class TraceabilityChecker:
    """LLM-judged claim traceability pass.

    Uses the light/validation tier to check that every factual claim in a
    generated artifact is substantiated by the master resume.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._enabled = True
        self._task = "accuracy_validation"
        self._load_config()

    def _load_config(self):
        """Load traceability config from accuracy_rules.yml."""
        if not self.settings.profile or not self.settings.profile.resume:
            return

        rules_path = self.settings.config_dir / "accuracy_rules.yml"
        if not rules_path.exists():
            return

        import yaml
        with open(rules_path) as f:
            data = yaml.safe_load(f)

        config = data.get("traceability", {})
        if isinstance(config, dict):
            self._enabled = config.get("enabled", True)
            self._task = config.get("task", "accuracy_validation")

    @property
    def enabled(self) -> bool:
        return self._enabled

    def check(
        self,
        artifact_text: str,
        master_resume: str,
        artifact_type: str = "resume",
    ) -> TraceabilityResult:
        """Run the traceability check on the generated artifact.

        Args:
            artifact_text: The generated artifact text.
            master_resume: The master resume text (source of truth).
            artifact_type: One of 'resume', 'cover_letter', 'application_answer'.

        Returns:
            TraceabilityResult with claims and any violations.
        """
        if not self._enabled:
            return TraceabilityResult(checked_at=datetime.now(UTC).isoformat())

        if not master_resume.strip():
            logger.warning("Traceability check failed-closed — master resume is empty")
            return TraceabilityResult(
                violations=[Violation(
                    rule_id="traceability_no_master",
                    description="Cannot verify claims — master resume missing or empty",
                    violation="Traceability check could not run: master resume is empty. "
                              "Artifact flagged for manual review.",
                    severity="high",
                )],
                checked_at=datetime.now(UTC).isoformat(),
            )

        from seeker_os.llm.models import TruncationError
        from seeker_os.llm.router import ModelRouter

        router = ModelRouter(self.settings)
        user_prompt = _build_judge_user_prompt(artifact_text, master_resume, artifact_type)

        try:
            response = router.generate(
                task=self._task,
                system_prompt=JUDGE_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.0,
            )
        except TruncationError as e:
            logger.error("Traceability judge was truncated: %s", e)
            return TraceabilityResult(
                violations=[Violation(
                    rule_id="traceability_truncated",
                    description="Traceability judge response was truncated (hit max_tokens ceiling)",
                    violation=str(e),
                    severity="high",
                )],
                checked_at=datetime.now(UTC).isoformat(),
            )

        text = _extract_json(response.text)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.error(
                "Traceability judge returned invalid JSON (response length=%d, "
                "output_tokens=%d, extracted length=%d): %s",
                len(response.text), response.output_tokens,
                len(text), text[:500],
            )
            # Treat parse failure as a single high-severity violation
            return TraceabilityResult(
                violations=[Violation(
                    rule_id="traceability_parse_error",
                    description="Traceability judge returned unparseable response",
                    violation="Could not parse LLM traceability response — manual review required",
                    severity="high",
                )],
                checked_at=datetime.now(UTC).isoformat(),
            )

        claims: list[ClaimJudgment] = []
        violations: list[Violation] = []

        for claim_data in data.get("claims", []):
            claim = ClaimJudgment(
                claim=claim_data.get("claim", ""),
                verdict=claim_data.get("verdict", "supported"),
                explanation=claim_data.get("explanation", ""),
                offending_text=claim_data.get("offending_text", ""),
            )
            claims.append(claim)

            if claim.verdict == "unsupported":
                violations.append(Violation(
                    rule_id="traceability_unsupported",
                    description=f"Unsupported claim: \"{claim.claim}\"",
                    violation=f"Claim not found in master resume: {claim.offending_text or claim.claim}",
                    severity="high",
                    matched_text=claim.offending_text or claim.claim,
                ))
            elif claim.verdict == "overstated":
                violations.append(Violation(
                    rule_id="traceability_overstated",
                    description=f"Overstated claim: \"{claim.claim}\"",
                    violation=f"Claim inflated beyond master resume: {claim.offending_text or claim.claim}",
                    severity="high",
                    matched_text=claim.offending_text or claim.claim,
                ))

        return TraceabilityResult(
            claims=claims,
            violations=violations,
            checked_at=datetime.now(UTC).isoformat(),
        )
