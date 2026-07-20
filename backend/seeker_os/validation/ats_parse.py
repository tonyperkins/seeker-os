"""ATS parse-survival gate.

Verifies that critical content survives text extraction from the final
rendered artifact. Targets the parsing-failure bug class (w:noWrap was
one instance; the inline-separator collapse and per-JD competency
variation added new seams since this was first drafted).

NOT a keyword scorer — extraction survival only. Deterministic, offline,
no third-party APIs.

Same behavior as the page gate: flag-for-review (medium severity), not
hard-fail. The caller saves ats_parse_check_passed plus a diagnostic
naming each failed assertion and what was found instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from seeker_os.config import Settings


@dataclass
class ATSParseAssertionResult:
    """Result of a single ATS parse assertion."""
    assertion_id: str
    description: str
    passed: bool
    found: str = ""
    expected: str = ""


@dataclass
class ATSParseResult:
    """Result of the ATS parse-survival gate."""
    passed: bool
    assertions: list[ATSParseAssertionResult] = field(default_factory=list)
    diagnostics: dict = field(default_factory=dict)

    @property
    def violations(self) -> list[dict]:
        """Return failed assertions as violation dicts for the validation pipeline."""
        return [
            {
                "rule_id": f"ats_parse_{a.assertion_id}",
                "description": a.description,
                "violation": f"Expected: {a.expected}, Found: {a.found or '(missing)'}",
                "severity": "medium",
                "matched_text": a.found,
            }
            for a in self.assertions if not a.passed
        ]


def _extract_text_from_html(html: str) -> str:
    """Extract plain text from an HTML string, simulating ATS extraction.

    Strips all HTML tags, decodes common entities, and collapses whitespace
    to single spaces while preserving line breaks from block-level elements.
    """
    # Convert block-level closing tags to newlines
    text = re.sub(
        r'</(p|div|h[1-6]|li|tr|td|th|br|ul|ol|table)\s*>',
        '\n',
        html,
        flags=re.IGNORECASE,
    )
    # Convert <br> and <br/> to newlines
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    # Strip all remaining tags
    text = re.sub(r'<[^>]+>', '', text)
    # Decode common HTML entities
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    text = text.replace('&nbsp;', ' ').replace('&quot;', '"').replace('&#39;', "'")
    text = text.replace('&mdash;', '—').replace('&ndash;', '–')
    text = text.replace('&middot;', '·')
    # Collapse multiple spaces but preserve newlines
    text = re.sub(r'[ \t]+', ' ', text)
    # Remove spaces around newlines
    text = re.sub(r' *\n *', '\n', text)
    # Collapse multiple newlines
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _render_markdown_to_html(markdown_text: str) -> str:
    """Convert markdown to HTML using the same pipeline as export_pdf."""
    from seeker_os.resume.export import _convert_competencies_table, _collapse_inline_breaks

    try:
        import markdown
    except ImportError:
        return markdown_text

    md_text = _convert_competencies_table(markdown_text)
    md_text = _collapse_inline_breaks(md_text)
    html_body = markdown.markdown(md_text, extensions=["extra", "tables", "nl2br"])
    html_body = re.sub(
        r'(?<!["\'>])(https?://[^\s<]+)',
        r'<span class="url">\1</span>',
        html_body,
    )
    return html_body


def _extract_docx_text_from_markdown(markdown_text: str) -> str | None:
    """Generate a DOCX from markdown text and extract text from it.

    This simulates the full DOCX export → ATS extraction path.
    Returns None if python-docx is not installed.
    """
    import tempfile
    from pathlib import Path

    try:
        from seeker_os.resume.export import export_docx
        from seeker_os.resume.extract import extract_docx_text
    except ImportError:
        return None

    with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
        f.write(markdown_text)
        md_path = Path(f.name)

    try:
        docx_path = md_path.with_suffix(".docx")
        result = export_docx(md_path, docx_path)
        if result is None:
            return None
        return extract_docx_text(result)
    except Exception:
        return None
    finally:
        md_path.unlink(missing_ok=True)
        if docx_path.exists():
            docx_path.unlink(missing_ok=True)


def _extract_pdf_text_from_markdown(markdown_text: str) -> str | None:
    """Generate a real PDF from markdown text and extract text from it.

    This validates the actual PDF export path — the format employers most
    often receive, and the layer where layout-sensitive parsing failures
    (e.g. the original Ladders noWrap anomaly) would live.

    Returns None if weasyprint or a PDF text extraction library is not installed.
    """
    import tempfile
    from pathlib import Path

    try:
        from seeker_os.resume.export import export_pdf
        from seeker_os.resume.extract import extract_pdf_text
    except ImportError:
        return None

    with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
        f.write(markdown_text)
        md_path = Path(f.name)

    try:
        pdf_path = md_path.with_suffix(".pdf")
        result = export_pdf(md_path, pdf_path)
        if result is None:
            return None
        return extract_pdf_text(result)
    except Exception:
        return None
    finally:
        md_path.unlink(missing_ok=True)
        if pdf_path.exists():
            pdf_path.unlink(missing_ok=True)


class ATSParseValidator:
    """Validates that critical content survives text extraction.

    Extracts plain text from the rendered HTML (the same path the PDF
    renders from) and optionally from a DOCX export, then runs assertions
    to verify contact info, URLs, role integrity, section headings,
    competency lines, pin content, and absence of artifacts.

    Expected values are sourced from the master resume and the generation's
    own selection audit — no hardcoded duplicates.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    def validate(
        self,
        resume_text: str,
        master_resume: str,
        selected_role_titles: dict[str, str] | None = None,
        selected_project_titles: dict[str, str] | None = None,
        selected_category_labels: list[str] | None = None,
        pinned_bullet_texts: list[str] | None = None,
    ) -> ATSParseResult:
        """Run ATS parse-survival assertions on the rendered resume.

        Args:
            resume_text: The generated resume markdown text.
            master_resume: The original master resume text (source of expected
                contact/URL values).
            selected_role_titles: Dict of role_id → title from the selection audit.
            selected_project_titles: Dict of project_id → title from the selection audit.
            selected_category_labels: List of selected competency category labels.
            pinned_bullet_texts: List of pinned bullet text strings that should
                survive rendering.

        Returns:
            ATSParseResult with per-assertion results and diagnostics.
        """
        selected_role_titles = selected_role_titles or {}
        selected_project_titles = selected_project_titles or {}
        selected_category_labels = selected_category_labels or []
        pinned_bullet_texts = pinned_bullet_texts or []

        # Extract expected values from the master resume
        expected = self._extract_expected_values(master_resume)

        # Render the resume markdown to HTML and extract text
        html = _render_markdown_to_html(resume_text)
        extracted = _extract_text_from_html(html)

        # Also try DOCX extraction
        docx_text = _extract_docx_text_from_markdown(resume_text)

        assertions: list[ATSParseAssertionResult] = []

        # 1. Contact block
        assertions.extend(self._check_contact_block(extracted, expected))

        # 2. URLs
        assertions.extend(self._check_urls(extracted, expected))

        # 3. Role integrity
        assertions.extend(self._check_role_integrity(extracted, selected_role_titles, selected_project_titles))

        # 4. Section headings
        assertions.extend(self._check_section_headings(extracted, resume_text))

        # 5. Competency lines
        assertions.extend(self._check_competency_lines(extracted, selected_category_labels))

        # 6. Pin content
        assertions.extend(self._check_pin_content(extracted, pinned_bullet_texts))

        # 7. No artifacts
        assertions.extend(self._check_no_artifacts(extracted, resume_text))

        # Run DOCX assertions if available
        docx_assertions: list[ATSParseAssertionResult] = []
        if docx_text is not None:
            docx_assertions.extend(self._check_contact_block(docx_text, expected, source="docx"))
            docx_assertions.extend(self._check_urls(docx_text, expected, source="docx"))
            docx_assertions.extend(self._check_no_artifacts(docx_text, resume_text, source="docx"))

        # Run PDF assertions if available (layout-sensitive subset: 1, 2, 7)
        pdf_text = _extract_pdf_text_from_markdown(resume_text)
        pdf_assertions: list[ATSParseAssertionResult] = []
        if pdf_text is not None:
            pdf_assertions.extend(self._check_contact_block(pdf_text, expected, source="pdf"))
            pdf_assertions.extend(self._check_urls(pdf_text, expected, source="pdf"))
            pdf_assertions.extend(self._check_no_artifacts(pdf_text, resume_text, source="pdf"))

        all_passed = all(a.passed for a in assertions)
        docx_passed = all(a.passed for a in docx_assertions) if docx_assertions else True
        pdf_passed = all(a.passed for a in pdf_assertions) if pdf_assertions else True

        diagnostics = {
            "ats_parse_passed": all_passed,
            "ats_parse_html_assertions": len(assertions),
            "ats_parse_html_failures": sum(1 for a in assertions if not a.passed),
            "ats_parse_docx_available": docx_text is not None,
            "ats_parse_docx_passed": docx_passed if docx_text is not None else None,
            "ats_parse_docx_assertions": len(docx_assertions),
            "ats_parse_docx_failures": sum(1 for a in docx_assertions if not a.passed),
            "ats_parse_pdf_available": pdf_text is not None,
            "ats_parse_pdf_passed": pdf_passed if pdf_text is not None else None,
            "ats_parse_pdf_assertions": len(pdf_assertions),
            "ats_parse_pdf_failures": sum(1 for a in pdf_assertions if not a.passed),
            "ats_parse_failed_assertions": [
                {
                    "assertion_id": a.assertion_id,
                    "description": a.description,
                    "expected": a.expected,
                    "found": a.found,
                }
                for a in assertions + docx_assertions + pdf_assertions if not a.passed
            ],
        }

        return ATSParseResult(
            passed=all_passed and docx_passed and pdf_passed,
            assertions=assertions + docx_assertions + pdf_assertions,
            diagnostics=diagnostics,
        )

    def _extract_expected_values(self, master_resume: str) -> dict:
        """Extract expected contact/URL values from the master resume.

        Sources name, email, location, citizenship, and URLs from the
        master resume's contact block (first few lines after the h1).
        """
        lines = master_resume.split("\n")
        expected: dict = {
            "name": "",
            "email": "",
            "location": "",
            "citizenship": "",
            "urls": [],
        }

        # Name from h1
        for line in lines:
            if line.startswith("# "):
                expected["name"] = line[2:].strip()
                break

        # Contact block: scan first 10 lines for known patterns
        for line in lines[:10]:
            stripped = line.strip()
            # Email
            if "@" in stripped and not expected["email"]:
                email_match = re.search(r'[\w.+-]+@[\w.-]+\.\w+', stripped)
                if email_match:
                    expected["email"] = email_match.group()
            # Location (city, state pattern)
            if not expected["location"]:
                loc_match = re.search(r'([A-Z][a-z]+(?:\s[A-Z][a-z]+)*,\s[A-Z]{2})', stripped)
                if loc_match:
                    expected["location"] = loc_match.group(1)
            # Citizenship / sponsorship
            if "citizen" in stripped.lower() or "sponsorship" in stripped.lower() or "authorization" in stripped.lower():
                if not expected["citizenship"]:
                    expected["citizenship"] = stripped
            # URLs
            for url_match in re.finditer(r'https?://[^\s·|]+', stripped):
                url = url_match.group().rstrip(",.;)")
                if url not in expected["urls"]:
                    expected["urls"].append(url)

        return expected

    def _check_contact_block(self, text: str, expected: dict, source: str = "html") -> list[ATSParseAssertionResult]:
        """Assertion 1: contact block elements present and intact."""
        results: list[ATSParseAssertionResult] = []
        suffix = f" ({source})" if source != "html" else ""

        # Name
        name_present = expected["name"] and expected["name"] in text
        results.append(ATSParseAssertionResult(
            assertion_id=f"contact_name{suffix}",
            description=f"Name '{expected['name']}' present in extracted text",
            passed=name_present,
            found=expected["name"] if name_present else "(not found)",
            expected=expected["name"],
        ))

        # Email intact (no wrap/hyphenation)
        email_intact = expected["email"] and expected["email"] in text
        results.append(ATSParseAssertionResult(
            assertion_id=f"contact_email{suffix}",
            description=f"Email '{expected['email']}' intact (no wrap/hyphenation artifacts)",
            passed=email_intact,
            found=expected["email"] if email_intact else "(not found or corrupted)",
            expected=expected["email"],
        ))

        # Location
        loc_present = expected["location"] and expected["location"] in text
        results.append(ATSParseAssertionResult(
            assertion_id=f"contact_location{suffix}",
            description=f"Location '{expected['location']}' present",
            passed=loc_present,
            found=expected["location"] if loc_present else "(not found)",
            expected=expected["location"],
        ))

        # Citizenship exactly once
        if expected["citizenship"]:
            citizenship_count = text.count(expected["citizenship"])
            results.append(ATSParseAssertionResult(
                assertion_id=f"contact_citizenship{suffix}",
                description=f"Citizenship line '{expected['citizenship']}' present exactly once",
                passed=citizenship_count == 1,
                found=f"{citizenship_count} occurrences",
                expected="exactly 1 occurrence",
            ))

        return results

    def _check_urls(self, text: str, expected: dict, source: str = "html") -> list[ATSParseAssertionResult]:
        """Assertion 2: critical URLs survive as full-string matches."""
        results: list[ATSParseAssertionResult] = []
        suffix = f" ({source})" if source != "html" else ""

        for url in expected["urls"]:
            # Exact full-string match including scheme
            url_present = url in text
            results.append(ATSParseAssertionResult(
                assertion_id=f"url_{re.sub(r'[^a-zA-Z0-9]', '_', url)}{suffix}",
                description=f"URL '{url}' present as exact full-string match",
                passed=url_present,
                found=url if url_present else "(not found or fragmented)",
                expected=url,
            ))

        return results

    def _check_role_integrity(
        self,
        text: str,
        role_titles: dict[str, str],
        project_titles: dict[str, str],
    ) -> list[ATSParseAssertionResult]:
        """Assertion 3: role/project title, company, and date range extract as findable text."""
        results: list[ATSParseAssertionResult] = []

        for role_id, title in role_titles.items():
            # Strip markdown formatting from title for text search
            clean_title = re.sub(r'[*`]', '', title).strip()
            title_found = clean_title in text
            results.append(ATSParseAssertionResult(
                assertion_id=f"role_title_{role_id}",
                description=f"Role title '{clean_title}' extracts as findable text",
                passed=title_found,
                found=clean_title if title_found else "(not found)",
                expected=clean_title,
            ))

        for proj_id, title in project_titles.items():
            # Project titles may have markdown — strip it
            clean_title = re.sub(r'[*`]', '', title).strip()
            # Project titles in the resume may have parenthetical suffixes;
            # check if the core title (before any parenthetical) is present
            core_title = clean_title.split("(")[0].strip().rstrip("—").strip()
            title_found = core_title in text if core_title else clean_title in text
            results.append(ATSParseAssertionResult(
                assertion_id=f"project_title_{proj_id}",
                description=f"Project title '{core_title}' extracts as findable text",
                passed=title_found,
                found=core_title if title_found else "(not found)",
                expected=core_title,
            ))

        return results

    def _check_section_headings(self, text: str, resume_text: str) -> list[ATSParseAssertionResult]:
        """Assertion 4: section headings present in extracted text."""
        results: list[ATSParseAssertionResult] = []

        # Extract section headings from the generated resume markdown
        sections = re.findall(r'^##\s+(.+)$', resume_text, re.MULTILINE)

        for section in sections:
            section = section.strip()
            # The heading text should appear in the extracted text
            # (without markdown ## prefix)
            section_found = section in text
            results.append(ATSParseAssertionResult(
                assertion_id=f"section_{re.sub(r'[^a-zA-Z0-9]', '_', section).lower()}",
                description=f"Section heading '{section}' extracts intact",
                passed=section_found,
                found=section if section_found else "(not found)",
                expected=section,
            ))

        return results

    def _check_competency_lines(
        self,
        text: str,
        selected_category_labels: list[str],
    ) -> list[ATSParseAssertionResult]:
        """Assertion 5: each selected competency category label extracts, and
        each rendered line contains at least one skill item."""
        results: list[ATSParseAssertionResult] = []

        for label in selected_category_labels:
            # The label should appear in the extracted text
            label_found = label in text
            results.append(ATSParseAssertionResult(
                assertion_id=f"competency_label_{re.sub(r'[^a-zA-Z0-9]', '_', label).lower()}",
                description=f"Competency label '{label}' extracts in text",
                passed=label_found,
                found=label if label_found else "(not found)",
                expected=label,
            ))

            if not label_found:
                # If the label isn't found, the skill item check is moot
                continue

            # Check that the competency line has at least one skill item
            # Find the competency line: the label should be at the START
            # of the line (possibly after stripped markdown bold markers),
            # not just anywhere in the line — otherwise a label like
            # "AI Infrastructure" would match the subtitle line too.
            for line in text.split("\n"):
                stripped_line = line.strip()
                # Competency lines look like "Label: skills" or "Label: skills"
                # after HTML extraction strips the ** markers
                if stripped_line.startswith(label):
                    # The line should have content after the label
                    # (at least one skill item)
                    after_label = stripped_line[len(label):].strip()
                    # Strip leading colons/spacing
                    after_label = after_label.lstrip(":").strip()
                    has_skills = len(after_label) > 3  # at least a few chars of skill text
                    results.append(ATSParseAssertionResult(
                        assertion_id=f"competency_skills_{re.sub(r'[^a-zA-Z0-9]', '_', label).lower()}",
                        description=f"Competency line for '{label}' contains at least one skill item",
                        passed=has_skills,
                        found=after_label[:80] if after_label else "(empty)",
                        expected="at least one skill item",
                    ))
                    break

        return results

    def _check_pin_content(
        self,
        text: str,
        pinned_bullet_texts: list[str],
    ) -> list[ATSParseAssertionResult]:
        """Assertion 6: pinned bullet text extracts findable in output."""
        results: list[ATSParseAssertionResult] = []

        for i, bullet_text in enumerate(pinned_bullet_texts):
            # Strip markdown formatting for text search
            clean_bullet = re.sub(r'[*`]', '', bullet_text).strip()
            # Use a substring of the first ~40 chars for matching — the LLM
            # may rephrase slightly, but the core claim should survive
            search_text = clean_bullet[:60].strip()
            if not search_text:
                continue
            # Check if a meaningful portion of the bullet text is present
            # Use first 30 chars as the search key — enough to be unique
            search_key = clean_bullet[:30].strip()
            bullet_found = search_key in text
            results.append(ATSParseAssertionResult(
                assertion_id=f"pin_content_{i}",
                description=f"Pinned bullet text '{search_key}...' extracts findable in output",
                passed=bullet_found,
                found=search_key if bullet_found else "(not found)",
                expected=search_key,
            ))

        return results

    def _check_no_artifacts(self, text: str, resume_text: str, source: str = "html") -> list[ATSParseAssertionResult]:
        """Assertion 7: no HTML/XML fragments, pin markers, placeholders, or raw markdown table syntax."""
        results: list[ATSParseAssertionResult] = []
        suffix = f" ({source})" if source != "html" else ""

        # HTML/XML fragments
        html_fragments = re.findall(r'<[a-zA-Z/][^>]*>', text)
        results.append(ATSParseAssertionResult(
            assertion_id=f"no_html_fragments{suffix}",
            description="No HTML/XML fragments in extracted text",
            passed=len(html_fragments) == 0,
            found=f"{len(html_fragments)} fragments: {html_fragments[:3]}" if html_fragments else "(clean)",
            expected="0 HTML/XML fragments",
        ))

        # Pin markers
        pin_patterns = ["<!-- pin -->", "<!--pin-->", "<!-- PIN -->", "<!--PIN-->"]
        pin_found = [p for p in pin_patterns if p.lower() in text.lower()]
        results.append(ATSParseAssertionResult(
            assertion_id=f"no_pin_markers{suffix}",
            description="No pin markers in extracted text",
            passed=len(pin_found) == 0,
            found=f"found: {pin_found}" if pin_found else "(clean)",
            expected="0 pin markers",
        ))

        # Placeholder tokens (common patterns)
        placeholder_patterns = [
            r'\{\{[^}]+\}\}',  # {{placeholder}}
            r'\$\{[^}]+\}',   # ${placeholder}
            r'\[PLACEHOLDER\]',
            r'\[TODO\]',
            r'\[INSERT[^]]*\]',
        ]
        placeholders_found = []
        for pattern in placeholder_patterns:
            matches = re.findall(pattern, text)
            placeholders_found.extend(matches)
        results.append(ATSParseAssertionResult(
            assertion_id=f"no_placeholders{suffix}",
            description="No placeholder tokens in extracted text",
            passed=len(placeholders_found) == 0,
            found=f"{len(placeholders_found)} found: {placeholders_found[:3]}" if placeholders_found else "(clean)",
            expected="0 placeholder tokens",
        ))

        # Raw markdown table syntax (pipe characters with dashes = table separator)
        # Only check if the resume text itself doesn't contain legitimate pipe tables
        # that were converted — the _convert_competencies_table should have handled them
        table_syntax = re.findall(r'\|[\s\-:|]+\|', text)
        results.append(ATSParseAssertionResult(
            assertion_id=f"no_table_syntax{suffix}",
            description="No raw markdown table syntax in extracted text",
            passed=len(table_syntax) == 0,
            found=f"{len(table_syntax)} found" if table_syntax else "(clean)",
            expected="0 table separator patterns",
        ))

        return results
