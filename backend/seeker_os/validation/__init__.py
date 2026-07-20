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
from datetime import UTC, datetime
from pathlib import Path

import yaml
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
    # Optional diagnostics from PageCountValidator (per-section line counts,
    # per-role bullet counts). Not set by AccuracyValidator.
    diagnostics: dict = Field(default_factory=dict)
    page_count: int | None = None

    @property
    def has_high_severity(self) -> bool:
        return any(v.severity == "high" for v in self.violations)

    def to_dict(self) -> dict:
        d = {
            "passed": self.passed,
            "checked_at": self.checked_at,
            "violations": [v.model_dump() for v in self.violations],
        }
        if self.diagnostics:
            d["diagnostics"] = self.diagnostics
        if self.page_count is not None:
            d["page_count"] = self.page_count
        return d


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
            checked_at=datetime.now(UTC).isoformat(),
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
        now = datetime.now(UTC).isoformat()
        db.execute(
            "UPDATE resumes SET validation_passed=?, validation_violations=?, validation_checked_at=?, updated_at=? WHERE id=?",
            (result.passed, json.dumps(result.to_dict()["violations"]), result.checked_at, now, resume_id),
        )
        db.commit()
        db.close()

        return result


def revalidate_all(resume_id: int, settings: Settings | None = None) -> ValidationResult:
    """Re-run all deterministic validation gates against a stored resume.

    Mirrors the gate sequence in generator.py:generate_resume (lines 845-918):
    1. AccuracyValidator (deny-list rules)
    2. PageCountValidator (height-based page gate)
    3. ATSParseValidator (text extraction survival)

    Traceability (LLM-judged) is NOT re-run — it requires an LLM call and
    the original response.call_id. The previous traceability verdict is
    preserved in the audit trail.

    Records a 'revalidation' eval in llm_evaluations with the previous
    verdict in details_json, then updates the resume's validation_passed
    and validation_violations columns.
    """
    import json

    from seeker_os.config import get_settings
    from seeker_os.database import get_connection
    from seeker_os.observability.llm_ledger import record_evaluation
    from seeker_os.validation.ats_parse import ATSParseValidator

    if settings is None:
        settings = get_settings()

    db = get_connection()
    try:
        row = db.execute("SELECT * FROM resumes WHERE id = ?", (resume_id,)).fetchone()
        if not row:
            raise ValueError(f"Resume {resume_id} not found")

        text = row["resume_text"] or ""
        master_path = Path(row["master_resume_path"] or "").expanduser()
        master_resume = master_path.read_text() if master_path.exists() else ""

        # Preserve previous verdict
        previous_passed = row["validation_passed"]
        previous_violations = row["validation_violations"]

        # --- Gate 1: Accuracy (deny-list) ---
        validator = AccuracyValidator(settings)
        validation = validator.validate(text, artifact_type="resume", master_resume=master_resume)

        # --- Gate 2: Page count (height-based) ---
        page_validator = PageCountValidator(settings)
        page_result = page_validator.validate(text)
        if page_result.violations:
            validation.violations.extend(page_result.violations)
            validation.passed = not any(v.severity == "high" for v in validation.violations)
        if page_result.diagnostics:
            validation.diagnostics = page_result.diagnostics
        if page_result.page_count is not None:
            validation.page_count = page_result.page_count

        # --- Gate 3: ATS parse survival ---
        # Reconstruct audit data from llm_evaluations for this resume
        operation_id = None
        role_titles: dict[str, str] = {}
        project_titles: dict[str, str] = {}
        category_labels: list[str] = []
        pinned_bullet_texts: list[str] = []
        key_terms: list[str] = []

        # Find the operation_id from existing audit records
        op_row = db.execute(
            "SELECT DISTINCT operation_id FROM llm_evaluations WHERE artifact_type = 'resume' AND artifact_id = ? LIMIT 1",
            (resume_id,),
        ).fetchone()
        if op_row:
            operation_id = op_row["operation_id"]

        if operation_id:
            evals = db.execute(
                "SELECT metric_name, label, details_json FROM llm_evaluations WHERE operation_id = ? AND metric_name = 'bullet_selection'",
                (operation_id,),
            ).fetchall()
            for e in evals:
                d = json.loads(e["details_json"]) if e["details_json"] else {}
                if d.get("reason") == "zero_bullet_suppressed" or "warning" in d:
                    continue
                if "role_title" in d:
                    role_titles[e["label"]] = d["role_title"]
                elif "project_title" in d:
                    project_titles[e["label"]] = d["project_title"]

            comp_row = db.execute(
                "SELECT details_json FROM llm_evaluations WHERE operation_id = ? AND metric_name = 'competency_selection' AND label = 'competency_categories'",
                (operation_id,),
            ).fetchone()
            if comp_row:
                cd = json.loads(comp_row["details_json"]) if comp_row["details_json"] else {}
                category_labels = cd.get("selected_labels", [])

            # Reconstruct pinned bullet texts from master resume
            try:
                from seeker_os.resume.master_parser import parse_master_resume
                parsed = parse_master_resume(master_resume)
                # Get selected indices
                for e in evals:
                    d = json.loads(e["details_json"]) if e["details_json"] else {}
                    selected_indices = [s["index"] for s in d.get("selected", [])]
                    for role in parsed.roles:
                        if role.role_id == e["label"]:
                            for idx in selected_indices:
                                if idx < len(role.bullets) and role.bullets[idx].pinned:
                                    pinned_bullet_texts.append(role.bullets[idx].text)
                    for proj in parsed.projects:
                        if proj.project_id == e["label"]:
                            for idx in selected_indices:
                                if idx < len(proj.bullets) and proj.bullets[idx].pinned:
                                    pinned_bullet_texts.append(proj.bullets[idx].text)
            except Exception:
                logger.exception("revalidate_all: failed to reconstruct pinned bullets")

            # Reconstruct key_terms from competency_selection audit kept_items
            if comp_row:
                kept_items = cd.get("kept_items", {})
                for items in kept_items.values():
                    for item in items:
                        first_word = item.strip().split()[0] if item.strip() else ""
                        if first_word and len(first_word) > 2:
                            key_terms.append(first_word)
                key_terms.extend(category_labels)

        ats_validator = ATSParseValidator(settings)
        ats_result = ats_validator.validate(
            resume_text=text,
            master_resume=master_resume,
            selected_role_titles=role_titles,
            selected_project_titles=project_titles,
            selected_category_labels=category_labels,
            pinned_bullet_texts=pinned_bullet_texts,
            key_terms=key_terms,
        )
        if ats_result.violations:
            validation.violations.extend(
                Violation(**v) if isinstance(v, dict) else v
                for v in ats_result.violations
            )
            validation.passed = not any(v.severity == "high" for v in validation.violations)
        if ats_result.diagnostics:
            validation.diagnostics.update(ats_result.diagnostics)

        # --- Record revalidation eval with previous verdict ---
        # Direct insert because record_evaluation doesn't set artifact_type/artifact_id
        import uuid as _uuid
        try:
            from seeker_os.observability.llm_ledger import _now
            reval_id = str(_uuid.uuid4())
            db.execute(
                """INSERT INTO llm_evaluations (
                    evaluation_id, operation_id, artifact_type, artifact_id,
                    evaluator_name, evaluator_type, evaluator_version, metric_name, passed, label,
                    details_json, evaluated_at
                ) VALUES (?, ?, 'resume', ?, ?, 'deterministic', '1', 'revalidation', ?, ?, ?, ?)""",
                (
                    reval_id, operation_id, resume_id,
                    "revalidation", validation.passed,
                    "passed" if validation.passed else "failed",
                    json.dumps({
                        "previous_passed": previous_passed,
                        "previous_violations": json.loads(previous_violations) if previous_violations else [],
                        "new_violation_count": len(validation.violations),
                        "gates_run": ["accuracy", "page_count", "ats_parse"],
                        "traceability_rerun": False,
                    }, sort_keys=True),
                    _now(),
                ),
            )
            db.commit()
        except Exception:
            logger.exception("revalidate_all: failed to record revalidation eval")

        # --- Update DB ---
        now = datetime.now(UTC).isoformat()
        db.execute(
            "UPDATE resumes SET validation_passed=?, validation_violations=?, validation_checked_at=?, updated_at=? WHERE id=?",
            (validation.passed, json.dumps(validation.to_dict()["violations"]), validation.checked_at or now, now, resume_id),
        )
        db.commit()

        return validation
    finally:
        db.close()


class PageCountValidator:
    """Validates resume length by measuring rendered content height.

    Uses weasyprint's render() to measure the true content height and page
    count, then applies a height-based gate:
    - total_content_height > (target_pages × printable_page_height) × (1 + tolerance): high-severity violation (fail)
    - within tolerance: pass (even if page count exceeds target_pages by a small spill)

    The height-based gate distinguishes a 204px spill (within 10% tolerance,
    mostly empty final page) from a full extra page of content.

    Includes diagnostics that name the overage source: per-section line
    estimates and per-role bullet counts, plus the height ratio and page
    integer for transparency.

    Follows the AccuracyValidator pattern: returns ValidationResult with
    Violation objects, merges into the main validation result.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._target_pages = 2
        self._tolerance = 0.10
        if settings.channel_rules and settings.channel_rules.resume:
            tiering = settings.channel_rules.resume.content_tiering
            if tiering:
                self._target_pages = tiering.target_pages
                self._tolerance = tiering.page_overflow_tolerance

    def validate(self, resume_text: str) -> ValidationResult:
        """Validate resume page count and return diagnostics.

        Args:
            resume_text: The generated resume markdown text.

        Returns:
            ValidationResult with page-count violations and diagnostics.
        """
        from seeker_os.resume.export import measure_pdf_pages

        violations: list[Violation] = []
        diagnostics = self._generate_diagnostics(resume_text)
        measurement = measure_pdf_pages(resume_text)

        if measurement is None:
            # weasyprint not installed — can't check, return pass with no violations
            return ValidationResult(
                passed=True,
                violations=[],
                checked_at=datetime.now(UTC).isoformat(),
            )

        page_count = measurement["page_count"]
        total_height = measurement["total_content_height"]
        printable_height = measurement["printable_page_height"]
        target = self._target_pages
        tolerance = self._tolerance

        budget = target * printable_height
        max_allowed = budget * (1 + tolerance)
        height_ratio = total_height / budget if budget > 0 else 0.0

        # Record height metrics in diagnostics
        diagnostics["page_count"] = page_count
        diagnostics["total_content_height"] = round(total_height, 1)
        diagnostics["printable_page_height"] = round(printable_height, 1)
        diagnostics["page_budget"] = round(budget, 1)
        diagnostics["max_allowed_height"] = round(max_allowed, 1)
        diagnostics["height_ratio"] = round(height_ratio, 4)
        diagnostics["target_pages"] = target
        diagnostics["page_overflow_tolerance"] = tolerance

        if total_height > max_allowed:
            violation = Violation(
                rule_id="page_count_exceeded",
                description=f"Resume exceeds {target}-page limit (height ratio {height_ratio:.2f}, tolerance {tolerance:.0%})",
                violation=(
                    f"Resume is {page_count} pages, content height {total_height:.0f}px "
                    f"exceeds budget {budget:.0f}px × (1 + {tolerance:.0%}) = {max_allowed:.0f}px "
                    f"(ratio {height_ratio:.2f})"
                ),
                severity="high",
                matched_text=f"{page_count} pages, ratio {height_ratio:.2f}",
            )
            violations.append(violation)

        passed = not any(v.severity == "high" for v in violations)

        result = ValidationResult(
            passed=passed,
            violations=violations,
            checked_at=datetime.now(UTC).isoformat(),
            diagnostics=diagnostics,
            page_count=page_count,
        )
        return result

    def _generate_diagnostics(self, resume_text: str) -> dict:
        """Generate per-section line estimates and per-role bullet counts.

        Parses the generated resume markdown to identify sections (## headers)
        and roles (### headers under Professional Experience), counting lines
        and bullets in each. This helps identify which section is causing
        page overflow.
        """
        lines = resume_text.split("\n")
        sections: dict[str, dict] = {}
        current_section = "(header)"
        current_role: str | None = None
        section_line_count = 0
        section_bullet_count = 0
        role_bullet_counts: dict[str, int] = {}

        for line in lines:
            stripped = line.strip()

            # Section header (## )
            if stripped.startswith("## "):
                # Close previous section
                if current_section not in sections:
                    sections[current_section] = {
                        "line_count": section_line_count,
                        "bullet_count": section_bullet_count,
                    }
                else:
                    sections[current_section]["line_count"] += section_line_count
                    sections[current_section]["bullet_count"] += section_bullet_count

                current_section = stripped[3:].strip()
                current_role = None
                section_line_count = 0
                section_bullet_count = 0
                continue

            # Role header (### ) under Professional Experience
            if stripped.startswith("### "):
                current_role = stripped[4:].strip()
                role_bullet_counts[current_role] = 0
                section_line_count += 1
                continue

            # Bullet line
            if stripped.startswith("- ") or stripped.startswith("* "):
                section_bullet_count += 1
                if current_role:
                    role_bullet_counts[current_role] = (
                        role_bullet_counts.get(current_role, 0) + 1
                    )

            # Count non-empty lines
            if stripped:
                section_line_count += 1

        # Close final section
        if current_section not in sections:
            sections[current_section] = {
                "line_count": section_line_count,
                "bullet_count": section_bullet_count,
            }
        else:
            sections[current_section]["line_count"] += section_line_count
            sections[current_section]["bullet_count"] += section_bullet_count

        return {
            "sections": sections,
            "role_bullet_counts": role_bullet_counts,
        }
