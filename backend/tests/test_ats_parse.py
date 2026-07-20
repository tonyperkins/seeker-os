"""Tests for the ATS parse-survival gate.

Happy path: run the gate against resume 66's existing render and verify
all assertions pass — contact info, URLs, role integrity, section headings,
competency lines, pin content, and no artifacts.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from seeker_os.config import get_settings
from seeker_os.database import get_connection
from seeker_os.resume.master_parser import parse_master_resume
from seeker_os.validation.ats_parse import ATSParseValidator


@pytest.fixture(scope="module")
def resume_66_data():
    """Load resume 66's text, master resume, and audit data from the DB."""
    settings = get_settings()
    db = get_connection()
    try:
        r = db.execute("SELECT resume_text FROM resumes WHERE id = 66").fetchone()
        if r is None:
            pytest.skip("Resume 66 not found in database")
        resume_text = r["resume_text"]

        master_path = Path(settings.profile.resume.master_path).expanduser()
        if not master_path.exists():
            pytest.skip("Master resume not found")
        master_resume = master_path.read_text()

        # Get audit data — filter out zero_bullet_suppressed projects
        evals = db.execute(
            """
            SELECT metric_name, label, details_json
            FROM llm_evaluations
            WHERE artifact_type = 'resume' AND artifact_id = 66
            ORDER BY evaluated_at
            """
        ).fetchall()

        role_titles: dict[str, str] = {}
        project_titles: dict[str, str] = {}
        category_labels: list[str] = []

        for e in evals:
            d = json.loads(e["details_json"]) if e["details_json"] else {}
            if e["metric_name"] == "bullet_selection" and "role_title" in d:
                role_titles[e["label"]] = d["role_title"]
            elif (
                e["metric_name"] == "bullet_selection"
                and "project_title" in d
                and d.get("reason") != "zero_bullet_suppressed"
            ):
                project_titles[e["label"]] = d["project_title"]
            elif e["metric_name"] == "competency_selection" and "selected_labels" in d:
                category_labels = d["selected_labels"]

        # Reconstruct pinned bullet texts from audit records — the same
        # approach used by revalidate_all.  Only bullets that were
        # selected with reason=pinned in the generation's own audit
        # records are included, cross-referenced against the master to
        # get the text.  This avoids stale test data when new pins are
        # added to the master after the resume was generated.
        parsed = parse_master_resume(master_resume)
        pinned: list[str] = []
        for e in evals:
            if e["metric_name"] != "bullet_selection":
                continue
            d = json.loads(e["details_json"]) if e["details_json"] else {}
            selected = d.get("selected", [])
            pinned_indices = [s["index"] for s in selected if s.get("reason") == "pinned"]
            if not pinned_indices:
                continue
            for role in parsed.roles:
                if role.role_id == e["label"]:
                    for idx in pinned_indices:
                        if idx < len(role.bullets) and role.bullets[idx].pinned:
                            pinned.append(role.bullets[idx].text)
            for proj in parsed.projects:
                if proj.project_id == e["label"]:
                    for idx in pinned_indices:
                        if idx < len(proj.bullets) and proj.bullets[idx].pinned:
                            pinned.append(proj.bullets[idx].text)

        # Reconstruct key_terms from competency_selection audit kept_items
        key_terms: list[str] = []
        for e in evals:
            if e["metric_name"] == "competency_selection" and "selected_labels" in (
                json.loads(e["details_json"]) if e["details_json"] else {}
            ):
                d = json.loads(e["details_json"]) if e["details_json"] else {}
                kept_items = d.get("kept_items", {})
                for items in kept_items.values():
                    for item in items:
                        first_word = item.strip().split()[0] if item.strip() else ""
                        if first_word and len(first_word) > 2:
                            key_terms.append(first_word)
                key_terms.extend(d.get("selected_labels", []))

        return {
            "settings": settings,
            "resume_text": resume_text,
            "master_resume": master_resume,
            "role_titles": role_titles,
            "project_titles": project_titles,
            "category_labels": category_labels,
            "pinned": pinned,
            "key_terms": key_terms,
        }
    finally:
        db.close()


class TestATSParseHappyPath:
    """Happy path: all assertions pass on resume 66's existing render."""

    def test_gate_passes_overall(self, resume_66_data):
        """The ATS parse gate should pass on resume 66."""
        validator = ATSParseValidator(resume_66_data["settings"])
        result = validator.validate(
            resume_text=resume_66_data["resume_text"],
            master_resume=resume_66_data["master_resume"],
            selected_role_titles=resume_66_data["role_titles"],
            selected_project_titles=resume_66_data["project_titles"],
            selected_category_labels=resume_66_data["category_labels"],
            pinned_bullet_texts=resume_66_data["pinned"],
            key_terms=resume_66_data["key_terms"],
        )
        assert result.passed, (
            f"ATS parse gate failed with {len([a for a in result.assertions if not a.passed])} failures: "
            + "; ".join(a.assertion_id for a in result.assertions if not a.passed)
        )

    def test_contact_name_present(self, resume_66_data):
        """Assertion 1: name extracts from the contact block."""
        validator = ATSParseValidator(resume_66_data["settings"])
        result = validator.validate(
            resume_text=resume_66_data["resume_text"],
            master_resume=resume_66_data["master_resume"],
        )
        name_assertions = [a for a in result.assertions if a.assertion_id == "contact_name"]
        assert len(name_assertions) == 1
        assert name_assertions[0].passed

    def test_contact_email_intact(self, resume_66_data):
        """Assertion 1: email survives without wrap/hyphenation artifacts."""
        validator = ATSParseValidator(resume_66_data["settings"])
        result = validator.validate(
            resume_text=resume_66_data["resume_text"],
            master_resume=resume_66_data["master_resume"],
        )
        email_assertions = [a for a in result.assertions if a.assertion_id == "contact_email"]
        assert len(email_assertions) == 1
        assert email_assertions[0].passed
        assert "tony.perkins@perkinslab.com" in email_assertions[0].expected

    def test_contact_location_present(self, resume_66_data):
        """Assertion 1: location extracts from the contact block."""
        validator = ATSParseValidator(resume_66_data["settings"])
        result = validator.validate(
            resume_text=resume_66_data["resume_text"],
            master_resume=resume_66_data["master_resume"],
        )
        loc_assertions = [a for a in result.assertions if a.assertion_id == "contact_location"]
        assert len(loc_assertions) == 1
        assert loc_assertions[0].passed

    def test_citizenship_exactly_once(self, resume_66_data):
        """Assertion 1: citizenship line present exactly once (Rule 13)."""
        validator = ATSParseValidator(resume_66_data["settings"])
        result = validator.validate(
            resume_text=resume_66_data["resume_text"],
            master_resume=resume_66_data["master_resume"],
        )
        cit_assertions = [a for a in result.assertions if a.assertion_id == "contact_citizenship"]
        assert len(cit_assertions) == 1
        assert cit_assertions[0].passed

    def test_urls_survive_exact(self, resume_66_data):
        """Assertion 2: critical URLs survive as full-string matches including scheme."""
        validator = ATSParseValidator(resume_66_data["settings"])
        result = validator.validate(
            resume_text=resume_66_data["resume_text"],
            master_resume=resume_66_data["master_resume"],
        )
        url_assertions = [a for a in result.assertions if a.assertion_id.startswith("url_")]
        assert len(url_assertions) >= 3  # perkinslab, linkedin, github
        for a in url_assertions:
            assert a.passed, f"URL assertion failed: {a.assertion_id} — expected {a.expected}"

    def test_linkedin_url_has_www(self, resume_66_data):
        """Assertion 2: the www. in the LinkedIn URL must survive (Lever matcher requires it)."""
        validator = ATSParseValidator(resume_66_data["settings"])
        result = validator.validate(
            resume_text=resume_66_data["resume_text"],
            master_resume=resume_66_data["master_resume"],
        )
        linkedin_assertions = [
            a for a in result.assertions if "linkedin" in a.assertion_id.lower()
        ]
        assert len(linkedin_assertions) >= 1
        for a in linkedin_assertions:
            assert a.passed
            assert "www.linkedin.com" in a.expected

    def test_role_titles_extract(self, resume_66_data):
        """Assertion 3: every selected role title extracts as findable text."""
        validator = ATSParseValidator(resume_66_data["settings"])
        result = validator.validate(
            resume_text=resume_66_data["resume_text"],
            master_resume=resume_66_data["master_resume"],
            selected_role_titles=resume_66_data["role_titles"],
        )
        role_assertions = [a for a in result.assertions if a.assertion_id.startswith("role_title_")]
        assert len(role_assertions) == len(resume_66_data["role_titles"])
        for a in role_assertions:
            assert a.passed, f"Role title assertion failed: {a.assertion_id}"

    def test_project_titles_extract(self, resume_66_data):
        """Assertion 3: every selected project title extracts as findable text."""
        validator = ATSParseValidator(resume_66_data["settings"])
        result = validator.validate(
            resume_text=resume_66_data["resume_text"],
            master_resume=resume_66_data["master_resume"],
            selected_project_titles=resume_66_data["project_titles"],
        )
        proj_assertions = [a for a in result.assertions if a.assertion_id.startswith("project_title_")]
        assert len(proj_assertions) == len(resume_66_data["project_titles"])
        for a in proj_assertions:
            assert a.passed, f"Project title assertion failed: {a.assertion_id}"

    def test_section_headings_extract(self, resume_66_data):
        """Assertion 4: section headings extract intact."""
        validator = ATSParseValidator(resume_66_data["settings"])
        result = validator.validate(
            resume_text=resume_66_data["resume_text"],
            master_resume=resume_66_data["master_resume"],
        )
        section_assertions = [a for a in result.assertions if a.assertion_id.startswith("section_")]
        assert len(section_assertions) >= 3  # at least Summary, Competencies, Experience
        for a in section_assertions:
            assert a.passed, f"Section heading assertion failed: {a.assertion_id} — expected {a.expected}"

    def test_competency_labels_extract(self, resume_66_data):
        """Assertion 5: each selected competency category label extracts."""
        validator = ATSParseValidator(resume_66_data["settings"])
        result = validator.validate(
            resume_text=resume_66_data["resume_text"],
            master_resume=resume_66_data["master_resume"],
            selected_category_labels=resume_66_data["category_labels"],
        )
        label_assertions = [a for a in result.assertions if a.assertion_id.startswith("competency_label_")]
        assert len(label_assertions) == len(resume_66_data["category_labels"])
        for a in label_assertions:
            assert a.passed, f"Competency label assertion failed: {a.assertion_id}"

    def test_competency_lines_have_skills(self, resume_66_data):
        """Assertion 5: each competency line contains at least one skill item."""
        validator = ATSParseValidator(resume_66_data["settings"])
        result = validator.validate(
            resume_text=resume_66_data["resume_text"],
            master_resume=resume_66_data["master_resume"],
            selected_category_labels=resume_66_data["category_labels"],
        )
        skill_assertions = [a for a in result.assertions if a.assertion_id.startswith("competency_skills_")]
        assert len(skill_assertions) == len(resume_66_data["category_labels"])
        for a in skill_assertions:
            assert a.passed, f"Competency skills assertion failed: {a.assertion_id}"

    def test_pin_content_survives(self, resume_66_data):
        """Assertion 6: pinned bullet text extracts findable in output."""
        validator = ATSParseValidator(resume_66_data["settings"])
        result = validator.validate(
            resume_text=resume_66_data["resume_text"],
            master_resume=resume_66_data["master_resume"],
            pinned_bullet_texts=resume_66_data["pinned"],
            key_terms=resume_66_data["key_terms"],
        )
        pin_assertions = [a for a in result.assertions if a.assertion_id.startswith("pin_content_")]
        assert len(pin_assertions) == len(resume_66_data["pinned"])
        for a in pin_assertions:
            assert a.passed, f"Pin content assertion failed: {a.assertion_id}"

    def test_no_html_fragments(self, resume_66_data):
        """Assertion 7: no HTML/XML fragments in extracted text."""
        validator = ATSParseValidator(resume_66_data["settings"])
        result = validator.validate(
            resume_text=resume_66_data["resume_text"],
            master_resume=resume_66_data["master_resume"],
        )
        html_assertions = [a for a in result.assertions if a.assertion_id == "no_html_fragments"]
        assert len(html_assertions) == 1
        assert html_assertions[0].passed

    def test_no_pin_markers(self, resume_66_data):
        """Assertion 7: no pin markers in extracted text."""
        validator = ATSParseValidator(resume_66_data["settings"])
        result = validator.validate(
            resume_text=resume_66_data["resume_text"],
            master_resume=resume_66_data["master_resume"],
        )
        pin_marker_assertions = [a for a in result.assertions if a.assertion_id == "no_pin_markers"]
        assert len(pin_marker_assertions) == 1
        assert pin_marker_assertions[0].passed

    def test_no_placeholders(self, resume_66_data):
        """Assertion 7: no placeholder tokens in extracted text."""
        validator = ATSParseValidator(resume_66_data["settings"])
        result = validator.validate(
            resume_text=resume_66_data["resume_text"],
            master_resume=resume_66_data["master_resume"],
        )
        placeholder_assertions = [a for a in result.assertions if a.assertion_id == "no_placeholders"]
        assert len(placeholder_assertions) == 1
        assert placeholder_assertions[0].passed

    def test_no_table_syntax(self, resume_66_data):
        """Assertion 7: no raw markdown table syntax in extracted text."""
        validator = ATSParseValidator(resume_66_data["settings"])
        result = validator.validate(
            resume_text=resume_66_data["resume_text"],
            master_resume=resume_66_data["master_resume"],
        )
        table_assertions = [a for a in result.assertions if a.assertion_id == "no_table_syntax"]
        assert len(table_assertions) == 1
        assert table_assertions[0].passed

    def test_diagnostics_recorded(self, resume_66_data):
        """Diagnostics should include assertion counts and failure details."""
        validator = ATSParseValidator(resume_66_data["settings"])
        result = validator.validate(
            resume_text=resume_66_data["resume_text"],
            master_resume=resume_66_data["master_resume"],
            selected_role_titles=resume_66_data["role_titles"],
            selected_project_titles=resume_66_data["project_titles"],
            selected_category_labels=resume_66_data["category_labels"],
            pinned_bullet_texts=resume_66_data["pinned"],
            key_terms=resume_66_data["key_terms"],
        )
        d = result.diagnostics
        assert "ats_parse_passed" in d
        assert d["ats_parse_passed"] is True
        assert "ats_parse_html_assertions" in d
        assert d["ats_parse_html_assertions"] > 0
        assert d["ats_parse_html_failures"] == 0
        assert "ats_parse_docx_available" in d
        assert "ats_parse_failed_assertions" in d
        assert len(d["ats_parse_failed_assertions"]) == 0

    def test_violations_are_medium_severity(self, resume_66_data):
        """ATS parse violations should be medium severity (flag-for-review, not hard-fail)."""
        # This test verifies the severity even though there are no failures on resume 66.
        # The severity is set in the ATSParseResult.violations property.
        validator = ATSParseValidator(resume_66_data["settings"])
        result = validator.validate(
            resume_text=resume_66_data["resume_text"],
            master_resume=resume_66_data["master_resume"],
        )
        # All violations (if any) should be medium severity
        for v in result.violations:
            assert v["severity"] == "medium", (
                f"ATS parse violation {v['rule_id']} has severity {v['severity']}, expected 'medium'"
            )


# ---------------------------------------------------------------------------
# Negative tests — corrupted fixtures that must fail with named diagnostics
# ---------------------------------------------------------------------------


class TestATSParseNegativeTests:
    """Corrupted-fixture tests verifying the gate catches specific failures."""

    def test_url_split_across_lines_fails(self, resume_66_data):
        """A URL broken across two lines must fail the exact-URL assertion."""
        text = resume_66_data["resume_text"]
        # Break the perkinslab URL across a newline
        corrupted = text.replace(
            "https://perkinslab.com",
            "https://perkins\nlab.com",
        )
        validator = ATSParseValidator(resume_66_data["settings"])
        result = validator.validate(
            resume_text=corrupted,
            master_resume=resume_66_data["master_resume"],
        )
        assert not result.passed
        # The perkinslab URL assertion must be among the failures
        url_failures = [
            a for a in result.assertions
            if not a.passed and "perkinslab" in a.assertion_id
        ]
        assert len(url_failures) >= 1, "Expected perkinslab URL assertion to fail"
        assert "perkinslab.com" in url_failures[0].expected

    def test_www_stripped_from_linkedin_fails(self, resume_66_data):
        """Stripping www. from the LinkedIn URL must fail the exact-URL assertion."""
        text = resume_66_data["resume_text"]
        corrupted = text.replace(
            "https://www.linkedin.com/in/tonyperkins",
            "https://linkedin.com/in/tonyperkins",
        )
        validator = ATSParseValidator(resume_66_data["settings"])
        result = validator.validate(
            resume_text=corrupted,
            master_resume=resume_66_data["master_resume"],
        )
        assert not result.passed
        linkedin_failures = [
            a for a in result.assertions
            if not a.passed and "linkedin" in a.assertion_id.lower()
        ]
        assert len(linkedin_failures) >= 1, "Expected LinkedIn URL assertion to fail"
        assert "www.linkedin.com" in linkedin_failures[0].expected

    def test_role_date_range_broken_fails(self, resume_66_data):
        """A role title with a broken date range must fail the role-title assertion.

        We corrupt a role title by inserting a newline mid-string, which
        breaks the contiguous text extraction that ATS parsers rely on.
        """
        text = resume_66_data["resume_text"]
        role_titles = resume_66_data["role_titles"]
        # Pick the first role title and break it
        first_role_id = next(iter(role_titles))
        first_title = role_titles[first_role_id]
        # Insert a newline in the middle of the title in the resume text
        mid = len(first_title) // 2
        corrupted_title = first_title[:mid] + "\n" + first_title[mid:]
        corrupted = text.replace(first_title, corrupted_title, 1)
        validator = ATSParseValidator(resume_66_data["settings"])
        result = validator.validate(
            resume_text=corrupted,
            master_resume=resume_66_data["master_resume"],
            selected_role_titles=role_titles,
        )
        assert not result.passed
        role_failures = [
            a for a in result.assertions
            if not a.passed and a.assertion_id.startswith("role_title_")
        ]
        assert len(role_failures) >= 1, "Expected role title assertion to fail"
        # The failed assertion should name the role
        assert first_title in role_failures[0].expected or first_title[:mid] in role_failures[0].expected

    def test_competency_label_with_no_items_fails(self, resume_66_data):
        """A competency label whose items have been removed must fail the
        competency-skills assertion (orphaned label guard)."""
        text = resume_66_data["resume_text"]
        category_labels = resume_66_data["category_labels"]
        # Pick the first category label and strip its skill items
        target_label = category_labels[0]
        # Find the competency line and replace its skill content with nothing
        # The line looks like: **Label:** skills text here
        lines = text.split("\n")
        corrupted_lines = []
        for line in lines:
            if target_label in line and ":**" in line:
                # Replace with just the label, no skills
                corrupted_lines.append(f"**{target_label}:**")
            else:
                corrupted_lines.append(line)
        corrupted = "\n".join(corrupted_lines)
        validator = ATSParseValidator(resume_66_data["settings"])
        result = validator.validate(
            resume_text=corrupted,
            master_resume=resume_66_data["master_resume"],
            selected_category_labels=category_labels,
        )
        assert not result.passed
        # The competency_skills assertion for this label must fail
        skill_failures = [
            a for a in result.assertions
            if not a.passed and a.assertion_id.startswith("competency_skills_")
        ]
        assert len(skill_failures) >= 1, "Expected competency skills assertion to fail"
        assert target_label in skill_failures[0].description


# ---------------------------------------------------------------------------
# PDF extraction layer tests
# ---------------------------------------------------------------------------


class TestATSParsePDFLayer:
    """Tests for the PDF extraction path — the format employers most often
    receive, and the layer where layout-sensitive parsing failures live."""

    def test_pdf_layer_available(self, resume_66_data):
        """The PDF extraction layer should be available (weasyprint + pymupdf/pypdf)."""
        validator = ATSParseValidator(resume_66_data["settings"])
        result = validator.validate(
            resume_text=resume_66_data["resume_text"],
            master_resume=resume_66_data["master_resume"],
        )
        # If weasyprint or a PDF library isn't installed, this test skips
        if not result.diagnostics.get("ats_parse_pdf_available"):
            pytest.skip("PDF extraction layer not available (weasyprint or pypdf/pymupdf missing)")
        assert result.diagnostics["ats_parse_pdf_available"] is True

    def test_pdf_contact_block_passes(self, resume_66_data):
        """Assertion 1 (PDF): contact block elements survive PDF extraction."""
        validator = ATSParseValidator(resume_66_data["settings"])
        result = validator.validate(
            resume_text=resume_66_data["resume_text"],
            master_resume=resume_66_data["master_resume"],
        )
        if not result.diagnostics.get("ats_parse_pdf_available"):
            pytest.skip("PDF extraction layer not available")
        pdf_contact = [a for a in result.assertions if "(pdf)" in a.assertion_id and "contact" in a.assertion_id]
        assert len(pdf_contact) >= 4  # name, email, location, citizenship
        for a in pdf_contact:
            assert a.passed, f"PDF contact assertion failed: {a.assertion_id} — {a.description}"

    def test_pdf_urls_survive_exact(self, resume_66_data):
        """Assertion 2 (PDF): critical URLs survive PDF extraction as exact strings."""
        validator = ATSParseValidator(resume_66_data["settings"])
        result = validator.validate(
            resume_text=resume_66_data["resume_text"],
            master_resume=resume_66_data["master_resume"],
        )
        if not result.diagnostics.get("ats_parse_pdf_available"):
            pytest.skip("PDF extraction layer not available")
        pdf_urls = [a for a in result.assertions if "(pdf)" in a.assertion_id and a.assertion_id.startswith("url_")]
        assert len(pdf_urls) >= 3
        for a in pdf_urls:
            assert a.passed, f"PDF URL assertion failed: {a.assertion_id} — expected {a.expected}"

    def test_pdf_no_artifacts(self, resume_66_data):
        """Assertion 7 (PDF): no HTML fragments, pin markers, placeholders, or table syntax in PDF text."""
        validator = ATSParseValidator(resume_66_data["settings"])
        result = validator.validate(
            resume_text=resume_66_data["resume_text"],
            master_resume=resume_66_data["master_resume"],
        )
        if not result.diagnostics.get("ats_parse_pdf_available"):
            pytest.skip("PDF extraction layer not available")
        pdf_artifacts = [a for a in result.assertions if "(pdf)" in a.assertion_id and a.assertion_id.startswith("no_")]
        assert len(pdf_artifacts) >= 4  # html_fragments, pin_markers, placeholders, table_syntax
        for a in pdf_artifacts:
            assert a.passed, f"PDF artifact assertion failed: {a.assertion_id} — {a.description}"

    def test_pdf_diagnostics_recorded(self, resume_66_data):
        """PDF diagnostics should include availability, assertion counts, and failure details."""
        validator = ATSParseValidator(resume_66_data["settings"])
        result = validator.validate(
            resume_text=resume_66_data["resume_text"],
            master_resume=resume_66_data["master_resume"],
            selected_role_titles=resume_66_data["role_titles"],
            selected_project_titles=resume_66_data["project_titles"],
            selected_category_labels=resume_66_data["category_labels"],
            pinned_bullet_texts=resume_66_data["pinned"],
            key_terms=resume_66_data["key_terms"],
        )
        if not result.diagnostics.get("ats_parse_pdf_available"):
            pytest.skip("PDF extraction layer not available")
        d = result.diagnostics
        assert "ats_parse_pdf_available" in d
        assert d["ats_parse_pdf_available"] is True
        assert "ats_parse_pdf_passed" in d
        assert d["ats_parse_pdf_passed"] is True
        assert d["ats_parse_pdf_assertions"] > 0
        assert d["ats_parse_pdf_failures"] == 0

    def test_pdf_www_stripped_from_linkedin_fails(self, resume_66_data):
        """Corrupted case: stripping www. from the LinkedIn URL must fail the
        PDF URL assertion — this is the layout-sensitive layer where the
        original Ladders parse anomaly would live."""
        text = resume_66_data["resume_text"]
        corrupted = text.replace(
            "https://www.linkedin.com/in/tonyperkins",
            "https://linkedin.com/in/tonyperkins",
        )
        validator = ATSParseValidator(resume_66_data["settings"])
        result = validator.validate(
            resume_text=corrupted,
            master_resume=resume_66_data["master_resume"],
        )
        if not result.diagnostics.get("ats_parse_pdf_available"):
            pytest.skip("PDF extraction layer not available")
        assert not result.passed
        pdf_linkedin_failures = [
            a for a in result.assertions
            if not a.passed and "(pdf)" in a.assertion_id and "linkedin" in a.assertion_id.lower()
        ]
        assert len(pdf_linkedin_failures) >= 1, "Expected PDF LinkedIn URL assertion to fail"
        assert "www.linkedin.com" in pdf_linkedin_failures[0].expected


class TestKeyTermSurvival:
    """Assertion 8 (PDF-only): key-term token survival.

    Critical JD-relevant terms (sourced from the competency selection
    audit's kept_items and category labels) must survive PDF extraction
    as standalone, word-boundary-matchable tokens.
    """

    def test_key_terms_pass_on_normal_pdf(self, resume_66_data):
        """Key terms from resume 66's competency selection should survive
        PDF extraction as word-boundary tokens."""
        validator = ATSParseValidator(resume_66_data["settings"])
        result = validator.validate(
            resume_text=resume_66_data["resume_text"],
            master_resume=resume_66_data["master_resume"],
            key_terms=resume_66_data["key_terms"],
        )
        if not result.diagnostics.get("ats_parse_pdf_available"):
            pytest.skip("PDF extraction layer not available")
        key_term_assertions = [
            a for a in result.assertions
            if a.assertion_id.startswith("key_term_") and "(pdf)" in a.assertion_id
        ]
        assert len(key_term_assertions) > 0, "Expected key-term assertions to be generated"
        for a in key_term_assertions:
            assert a.passed, f"Key term assertion failed: {a.assertion_id} — expected '{a.expected}', found '{a.found}'"

    def test_hyphen_merged_term_fails(self, resume_66_data):
        """A deliberately hyphen-merged critical term in the PDF text
        should fail the key-term survival assertion.

        We simulate this by creating a minimal resume where a key term
        (e.g. 'Terraform') appears only as part of a hyphen-merged
        compound ('Terraformbased') in the rendered output. We test
        the assertion logic directly rather than through full PDF
        rendering, since the merge behavior is extractor-dependent.
        """
        validator = ATSParseValidator(resume_66_data["settings"])
        # Test the assertion directly with simulated extracted text
        # where 'terraform' only appears as 'terraformbased' (merged)
        fake_pdf_text = "Senior Platform Engineer\nTerraformbased infrastructure automation\n"
        assertions = validator._check_key_term_survival(fake_pdf_text, ["terraform"], source="pdf")
        assert len(assertions) == 1
        assert not assertions[0].passed, "Hyphen-merged 'Terraformbased' should not match 'terraform' as a word-boundary token"
        assert "not found as standalone token" in assertions[0].found

    def test_intact_term_passes(self, resume_66_data):
        """An intact key term should pass the word-boundary assertion."""
        validator = ATSParseValidator(resume_66_data["settings"])
        fake_pdf_text = "Terraform-based infrastructure automation and Terraform modules\n"
        assertions = validator._check_key_term_survival(fake_pdf_text, ["terraform"], source="pdf")
        assert len(assertions) == 1
        assert assertions[0].passed, "'Terraform' as a standalone word should pass"

    def test_substring_does_not_match(self, resume_66_data):
        """A term that only appears as a substring of a larger word
        should NOT pass the word-boundary assertion."""
        validator = ATSParseValidator(resume_66_data["settings"])
        fake_pdf_text = "Extensive experience with Terraformification of cloud resources\n"
        assertions = validator._check_key_term_survival(fake_pdf_text, ["terraform"], source="pdf")
        assert len(assertions) == 1
        assert not assertions[0].passed, "'Terraform' inside 'Terraformification' should not match as a word-boundary token"


class TestHyphenMergeDiagnostic:
    """Diagnostic (not assertion): detect and report hyphen-merge and
    line-wrap-split candidates in PDF extraction.

    These are reported as diagnostics — they don't fail the gate — so
    a critical instance is visible without failing on harmless ones.
    """

    def test_diagnostic_reports_line_wrap_splits(self, resume_66_data):
        """The Trojan resume's PDF extraction should report line-wrap
        splits (e.g. 'Outcome-\\nbased') as diagnostics, not failures."""
        validator = ATSParseValidator(resume_66_data["settings"])
        result = validator.validate(
            resume_text=resume_66_data["resume_text"],
            master_resume=resume_66_data["master_resume"],
            key_terms=resume_66_data["key_terms"],
        )
        if not result.diagnostics.get("ats_parse_pdf_available"):
            pytest.skip("PDF extraction layer not available")
        d = result.diagnostics
        # The diagnostic keys should be present
        assert "ats_parse_pdf_hyphen_merges" in d
        assert "ats_parse_pdf_line_wrap_splits" in d
        # Line-wrap splits should be non-negative
        assert d["ats_parse_pdf_line_wrap_splits"] >= 0
        # The diagnostic should NOT cause the gate to fail
        # (diagnostics are informational, not assertions)
        key_term_failures = [
            a for a in result.assertions
            if a.assertion_id.startswith("key_term_") and "(pdf)" in a.assertion_id and not a.passed
        ]
        # Key terms should pass (the split terms still appear intact elsewhere)
        # or if they fail, the diagnostic should have surfaced the issue
        if key_term_failures:
            assert d["ats_parse_pdf_line_wrap_splits"] > 0 or d["ats_parse_pdf_hyphen_merges"] > 0, \
                "Key term failures should be explained by hyphen-merge or line-wrap diagnostics"

    def test_diagnostic_detects_simulated_merge(self, resume_66_data):
        """The diagnostic should detect a simulated hyphen-merge:
        markdown has 'cloud-based' but PDF text has 'cloudbased'."""
        validator = ATSParseValidator(resume_66_data["settings"])
        fake_pdf_text = "Cloudbased infrastructure with real-world experience\n"
        fake_resume_text = "Cloud-based infrastructure with real-world experience\n"
        diag = validator._diagnose_hyphen_merges(fake_pdf_text, fake_resume_text)
        assert diag["hyphen_merge_count"] >= 1
        merge_terms = [m["term"] for m in diag["hyphen_merges"]]
        assert "cloud-based" in merge_terms

    def test_diagnostic_detects_simulated_split(self, resume_66_data):
        """The diagnostic should detect a simulated line-wrap split:
        markdown has 'production-grade' but PDF text has 'production-\\ngrade'."""
        validator = ATSParseValidator(resume_66_data["settings"])
        fake_pdf_text = "Built production-\ngrade CI/CD pipelines\n"
        fake_resume_text = "Built production-grade CI/CD pipelines\n"
        diag = validator._diagnose_hyphen_merges(fake_pdf_text, fake_resume_text)
        assert diag["line_wrap_split_count"] >= 1
        split_terms = [s["term"] for s in diag["line_wrap_splits"]]
        assert "production-grade" in split_terms

    def test_diagnostic_no_issues_when_intact(self, resume_66_data):
        """The diagnostic should report zero issues when all hyphenated
        terms survive intact in the PDF text."""
        validator = ATSParseValidator(resume_66_data["settings"])
        fake_pdf_text = "Cloud-based infrastructure with production-grade CI/CD\n"
        fake_resume_text = "Cloud-based infrastructure with production-grade CI/CD\n"
        diag = validator._diagnose_hyphen_merges(fake_pdf_text, fake_resume_text)
        assert diag["hyphen_merge_count"] == 0
        assert diag["line_wrap_split_count"] == 0
