"""Artifact-agnostic accuracy validator.

Checks generated artifacts (resumes, cover letters, application answers)
against deterministic deny-list rules from accuracy_rules.yml and identity_rules.yml.

Rule types (all deterministic, all fast):
- disallowed_phrases: phrases that must not appear (case-insensitive)
- forbidden_technologies: technologies that must never appear (word-boundary match)
- required_phrases: phrases that must appear
- experience_anchor: flags non-standard year counts via regex
- education_omission: flags education mentions via regex

The LLM-judged traceability pass lives in traceability.py and is invoked
separately by the caller when configured.
"""

from __future__ import annotations

import logging
import re
import yaml
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from seeker_os.config import Settings

logger = logging.getLogger(__name__)

KNOWN_RULE_TYPES = frozenset({
    "disallowed_phrases",
    "forbidden_technologies",
    "required_phrases",
    "experience_anchor",
    "education_omission",
})

ARTIFACT_TYPES = frozenset({"resume", "cover_letter", "application_answer"})


class Violation(BaseModel):
    """A single accuracy rule violation."""
    rule_id: str
    description: str
    violation: str
    severity: str  # 'high' or 'medium'
    matched_text: str = ""


class ValidationResult(BaseModel):
    """Result of validating a generated artifact."""
    passed: bool
    violations: list[Violation] = Field(default_factory=list)
    checked_at: str = ""

    @property
    def has_high_severity(self) -> bool:
        return any(v.severity == "high" for v in self.violations)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "checked_at": self.checked_at,
            "violations": [v.model_dump() for v in self.violations],
        }


class AccuracyValidator:
    """Validates generated artifacts against accuracy rules from YAML.

    Artifact-agnostic: the same deny-list checks apply to resumes, cover
    letters, and application answers. The LLM-judged traceability pass
    is handled separately by TraceabilityChecker.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._rules: list[dict] = []
        self._load_rules()

    def _load_identity_anchor(self) -> tuple[str, list[str]]:
        """Load experience anchor phrase and disallowed_variants from identity_rules.yml.

        Returns (phrase, disallowed_variants). If no identity or anchor is
        configured, returns ("", []) — the check does not run.
        """
        identity = self.settings.identity
        if not identity or not identity.experience_anchor.phrase:
            return "", []
        anchor = identity.experience_anchor
        return anchor.phrase, anchor.disallowed_variants

    def _load_rules(self):
        """Load rules from accuracy_rules.yml."""
        if not self.settings.profile or not self.settings.profile.resume:
            return

        rules_path = self.settings.config_dir / "accuracy_rules.yml"
        if not rules_path.exists():
            return

        with open(rules_path) as f:
            data = yaml.safe_load(f)
        self._rules = data.get("rules", [])

        # Guard: warn on unknown rule types so they fail loudly instead of
        # being silently ignored during validation.
        for rule in self._rules:
            rule_type = rule.get("type", "")
            if rule_type not in KNOWN_RULE_TYPES:
                rule_id = rule.get("id", "unknown")
                logger.warning(
                    "Unknown accuracy rule type '%s' for rule '%s' — "
                    "this rule will be ignored. Known types: %s",
                    rule_type,
                    rule_id,
                    ", ".join(sorted(KNOWN_RULE_TYPES)),
                )

    def validate(
        self,
        artifact_text: str,
        artifact_type: str = "resume",
        master_resume: str = "",
    ) -> ValidationResult:
        """Validate generated artifact text against all deterministic rules.

        Args:
            artifact_text: The generated artifact text (resume, cover letter, etc.)
            artifact_type: One of 'resume', 'cover_letter', 'application_answer'.
            master_resume: The master resume (used by traceability pass, not here).

        Returns:
            ValidationResult with any violations found
        """
        violations: list[Violation] = []
        text_lower = artifact_text.lower()

        for rule in self._rules:
            rule_id = rule.get("id", "unknown")
            description = rule.get("description", "")
            severity = rule.get("severity", "high")
            rule_type = rule.get("type", "")

            if rule_type == "disallowed_phrases":
                for phrase in rule.get("phrases", []):
                    pattern = r'\b' + re.escape(phrase) + r'\b'
                    if re.search(pattern, artifact_text, re.IGNORECASE):
                        violations.append(Violation(
                            rule_id=rule_id,
                            description=description,
                            violation=f"Contains disallowed phrase: '{phrase}'",
                            severity=severity,
                            matched_text=phrase,
                        ))

            elif rule_type == "forbidden_technologies":
                for tech in rule.get("technologies", []):
                    # Use word boundary matching for technologies
                    pattern = r'\b' + re.escape(tech) + r'\b'
                    if re.search(pattern, artifact_text, re.IGNORECASE):
                        violations.append(Violation(
                            rule_id=rule_id,
                            description=description,
                            violation=f"Claims {tech} — forbidden technology",
                            severity=severity,
                            matched_text=tech,
                        ))

            elif rule_type == "required_phrases":
                for phrase in rule.get("phrases", []):
                    if phrase.lower() not in text_lower:
                        violations.append(Violation(
                            rule_id=rule_id,
                            description=description,
                            violation=f"Missing required phrase: '{phrase}'",
                            severity=severity,
                            matched_text=phrase,
                        ))

            elif rule_type == "experience_anchor":
                # Check for disallowed experience anchor variants.
                # Patterns come from the rule's "patterns" list (accuracy_rules.yml)
                # and from identity_rules.yml disallowed_variants.
                anchor_phrase, identity_variants = self._load_identity_anchor()
                patterns = rule.get("patterns", []) + identity_variants
                for pattern in patterns:
                    if re.search(pattern, artifact_text, re.IGNORECASE):
                        violation_msg = "Uses a non-standard experience anchor"
                        if anchor_phrase:
                            violation_msg += f" (must be {anchor_phrase})"
                        violations.append(Violation(
                            rule_id=rule_id,
                            description=description,
                            violation=violation_msg,
                            severity=severity,
                        ))

            elif rule_type == "education_omission":
                for pattern in rule.get("patterns", []):
                    if re.search(pattern, artifact_text, re.IGNORECASE):
                        violations.append(Violation(
                            rule_id=rule_id,
                            description=description,
                            violation="Mentions education — should be omitted",
                            severity=severity,
                        ))

        # An artifact passes if there are no high-severity violations
        # Medium-severity violations are warnings (flagged but not blocking)
        passed = not any(v.severity == "high" for v in violations)

        return ValidationResult(
            passed=passed,
            violations=violations,
            checked_at=datetime.now(timezone.utc).isoformat(),
        )

    def revalidate(self, resume_id: int) -> ValidationResult:
        """Re-validate a stored resume from the database."""
        from seeker_os.database import get_connection

        db = get_connection()
        row = db.execute("SELECT * FROM resumes WHERE id = ?", (resume_id,)).fetchone()
        if not row:
            db.close()
            raise ValueError(f"Resume {resume_id} not found")

        text = row["resume_text"] or ""
        master_path = Path(row["master_resume_path"] or "").expanduser()
        master_resume = master_path.read_text() if master_path.exists() else ""

        result = self.validate(text, artifact_type="resume", master_resume=master_resume)

        # Update DB
        import json
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "UPDATE resumes SET validation_passed=?, validation_violations=?, validation_checked_at=?, updated_at=? WHERE id=?",
            (result.passed, json.dumps(result.to_dict()["violations"]), result.checked_at, now, resume_id),
        )
        db.commit()
        db.close()

        return result
