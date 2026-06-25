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
import re
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from seeker_os.config import Settings
from seeker_os.validation import Violation, ValidationResult

logger = logging.getLogger(__name__)


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


JUDGE_SYSTEM_PROMPT = """You are a strict accuracy auditor. You judge whether factual claims
in a generated artifact are substantiated by the candidate's master resume.

## Your job
1. Extract every factual claim from the generated artifact. A factual claim is any
   statement about skills, technologies, years of experience, quantified achievements,
   job titles, responsibilities, or project outcomes.
2. For each claim, judge it against the master resume:
   - **supported**: The master resume directly substantiates this claim.
   - **unsupported**: The master resume does NOT contain any evidence for this claim.
   - **overstated**: The master resume contains partial evidence, but the artifact
     inflates it (e.g., "expert" when the resume says "familiar", or "led a team of 20"
     when the resume says "contributed to a team").

## Rules — STRICT, not charitable
- A claim is UNSUPPORTED unless the master resume substantiates it. Absence of evidence
  is evidence of absence.
- Rounding up a qualifier counts as OVERSTATED. "Familiar, growing" → "expert" is overstated.
  "Contributed to" → "led" is overstated.
- Do not give the benefit of the doubt. If the resume doesn't clearly support it, flag it.
- Formatting/reorganization is not a claim. "Put skills section first" is not a factual claim.
- The artifact type may be resume, cover_letter, or application_answer. The same standard applies.

## Output format
Return ONLY valid JSON (no markdown, no code fences):
{
  "claims": [
    {
      "claim": "The factual claim as stated in the artifact",
      "verdict": "supported | unsupported | overstated",
      "explanation": "Why — cite the master resume or note its absence",
      "offending_text": "The exact text from the artifact that is problematic (empty if supported)"
    }
  ]
}
"""


def _build_judge_user_prompt(artifact_text: str, master_resume: str, artifact_type: str) -> str:
    return f"""## ARTIFACT TYPE
{artifact_type}

## MASTER RESUME (source of truth)
---
{master_resume}
---

## GENERATED ARTIFACT (to be audited)
---
{artifact_text}
---

Extract every factual claim from the generated artifact and judge each one against the
master resume. Return ONLY valid JSON matching the output schema."""


def _strip_code_fences(text: str) -> str:
    """Strip markdown code fences if present."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json or ```)
        lines = lines[1:]
        # Remove trailing ``` if present
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines)
    return text


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
            return TraceabilityResult(checked_at=datetime.now(timezone.utc).isoformat())

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
                checked_at=datetime.now(timezone.utc).isoformat(),
            )

        from seeker_os.llm.router import ModelRouter

        router = ModelRouter(self.settings)
        user_prompt = _build_judge_user_prompt(artifact_text, master_resume, artifact_type)

        response = router.generate(
            task=self._task,
            system_prompt=JUDGE_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.0,
            max_tokens=4000,
        )

        text = _strip_code_fences(response.text)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.error("Traceability judge returned invalid JSON: %s", text[:200])
            # Treat parse failure as a single high-severity violation
            return TraceabilityResult(
                violations=[Violation(
                    rule_id="traceability_parse_error",
                    description="Traceability judge returned unparseable response",
                    violation="Could not parse LLM traceability response — manual review required",
                    severity="high",
                )],
                checked_at=datetime.now(timezone.utc).isoformat(),
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
            checked_at=datetime.now(timezone.utc).isoformat(),
        )
