"""Accuracy validator — checks generated resumes against accuracy rules.

Reads rules from config/accuracy_rules.yml and validates:
- disallowed_phrases: phrases that must not appear (case-insensitive)
- forbidden_technologies: technologies that must never appear
- required_phrases: phrases that must appear
- experience_anchor: checks for non-standard year counts
- education_omission: checks for education mentions

Violations are flagged with severity (high/medium) and the resume is
held for manual review if any high-severity violations exist.
"""

from __future__ import annotations

import re
import yaml
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from seeker_os.config import Settings


@dataclass
class Violation:
    """A single accuracy rule violation."""
    rule_id: str
    description: str
    violation: str
    severity: str  # 'high' or 'medium'
    matched_text: str = ""


@dataclass
class ValidationResult:
    """Result of validating a generated resume."""
    passed: bool
    violations: list[Violation] = field(default_factory=list)
    checked_at: str = ""

    @property
    def has_high_severity(self) -> bool:
        return any(v.severity == "high" for v in self.violations)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "checked_at": self.checked_at,
            "violations": [
                {
                    "rule_id": v.rule_id,
                    "description": v.description,
                    "violation": v.violation,
                    "severity": v.severity,
                    "matched_text": v.matched_text,
                }
                for v in self.violations
            ],
        }


class AccuracyValidator:
    """Validates generated resumes against accuracy rules from YAML."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._rules: list[dict] = []
        self._load_rules()

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

    def validate(self, generated_text: str, master_resume: str = "") -> ValidationResult:
        """Validate generated resume text against all rules.

        Args:
            generated_text: The generated resume text
            master_resume: The master resume (for future traceability checks)

        Returns:
            ValidationResult with any violations found
        """
        violations: list[Violation] = []
        text_lower = generated_text.lower()

        for rule in self._rules:
            rule_id = rule.get("id", "unknown")
            description = rule.get("description", "")
            severity = rule.get("severity", "high")
            rule_type = rule.get("type", "")

            if rule_type == "disallowed_phrases":
                for phrase in rule.get("phrases", []):
                    if phrase.lower() in text_lower:
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
                    if re.search(pattern, generated_text, re.IGNORECASE):
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
                # Check for non-standard year counts
                for pattern in rule.get("patterns", [r'(20|30)\+\s*years']):
                    if re.search(pattern, generated_text, re.IGNORECASE):
                        violations.append(Violation(
                            rule_id=rule_id,
                            description=description,
                            violation="Uses non-standard experience anchor (must be 25+)",
                            severity=severity,
                        ))

            elif rule_type == "education_omission":
                for pattern in rule.get("patterns", []):
                    if re.search(pattern, generated_text, re.IGNORECASE):
                        violations.append(Violation(
                            rule_id=rule_id,
                            description=description,
                            violation="Mentions education — should be omitted",
                            severity=severity,
                        ))

        # A resume passes if there are no high-severity violations
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

        result = self.validate(text, master_resume)

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
