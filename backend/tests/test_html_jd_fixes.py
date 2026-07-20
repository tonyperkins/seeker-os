"""Tests for HTML JD preprocessing, boilerplate word-bounding, and
blind-selection guard.

These three fixes address the root cause found in production resume 66
(job 1727, Trojan Trading): the JD was stored as raw HTML on a single
line, the boilerplate regex matched 'pto' inside 'crypto', and
scope_jd_text collapsed to 0 chars — every bullet and competency scored
0.0, selection ran blind in master order.
"""

from __future__ import annotations

from seeker_os.resume.bullet_ranker import (
    _BOILERPLATE_RE,
    scope_jd_text,
    strip_html_to_text,
    tokenize,
)


# ---------------------------------------------------------------------------
# Fix #2: HTML preprocessing
# ---------------------------------------------------------------------------


class TestStripHtmlToText:
    def test_plain_text_passes_through(self):
        assert strip_html_to_text("No HTML here") == "No HTML here"

    def test_empty_string(self):
        assert strip_html_to_text("") == ""

    def test_simple_tags_stripped(self):
        result = strip_html_to_text("<p>Hello <b>world</b></p>")
        assert "Hello" in result
        assert "world" in result
        assert "<" not in result

    def test_block_elements_become_newlines(self):
        html = "<p>First paragraph</p><p>Second paragraph</p>"
        result = strip_html_to_text(html)
        lines = result.splitlines()
        assert len(lines) == 2
        assert "First paragraph" in lines[0]
        assert "Second paragraph" in lines[1]

    def test_br_becomes_newline(self):
        result = strip_html_to_text("Line 1<br>Line 2<br/>Line 3")
        lines = result.splitlines()
        assert len(lines) == 3

    def test_list_items_get_bullets(self):
        result = strip_html_to_text("<ul><li>Item 1</li><li>Item 2</li></ul>")
        lines = result.splitlines()
        assert any("Item 1" in l for l in lines)
        assert any("Item 2" in l for l in lines)

    def test_html_entities_decoded(self):
        result = strip_html_to_text("Cost &amp; schedule &mdash; aligned")
        assert "&" in result
        assert "—" in result
        assert "&amp;" not in result

    def test_script_style_removed(self):
        result = strip_html_to_text(
            "<style>.foo { color: red; }</style><p>Visible text</p>"
            "<script>alert('x')</script><p>More text</p>"
        )
        assert "Visible text" in result
        assert "More text" in result
        assert "color" not in result
        assert "alert" not in result

    def test_prod_jd_1727_yields_real_terms(self):
        """The actual Trojan Trading JD (raw HTML) must yield a term map
        containing kubernetes, terraform, prometheus, grafana, observability
        after stripping + scoping + tokenizing."""
        html_jd = (
            '<div style="text-align: justify;"><strong>About Trojan</strong></div>'
            '<div>Trojan is at the forefront of crypto trading technology.</div>'
            '<div>Requirements:</div>'
            '<ul>'
            '<li>Experience with Kubernetes and Terraform for infrastructure as code</li>'
            '<li>Observability &amp; Reliability: monitoring using Prometheus, Grafana, or Datadog</li>'
            '<li>Work with remote teams</li>'
            '</ul>'
            '<div>We offer competitive salary, benefits, and PTO.</div>'
        )
        clean = strip_html_to_text(html_jd)
        scoped, mode = scope_jd_text(clean)
        tokens = tokenize(scoped)

        assert "kubernetes" in tokens, f"kubernetes not found in {tokens}"
        assert "terraform" in tokens, f"terraform not found in {tokens}"
        assert "prometheus" in tokens, f"prometheus not found in {tokens}"
        assert "grafana" in tokens, f"grafana not found in {tokens}"
        assert "observability" in tokens, f"observability not found in {tokens}"

    def test_crypto_not_stripped_by_boilerplate(self):
        """The word 'crypto' must not be stripped by the boilerplate regex
        (regression test for pto matching inside crypto)."""
        clean = strip_html_to_text(
            "<div>Trojan is at the forefront of crypto trading technology.</div>"
        )
        assert "crypto" in clean.lower()


# ---------------------------------------------------------------------------
# Fix #3: Boilerplate regex word-bounding
# ---------------------------------------------------------------------------


class TestBoilerplateWordBounding:
    def test_pto_does_not_match_crypto(self):
        assert not _BOILERPLATE_RE.search("crypto trading technology")

    def test_pto_matches_standalone(self):
        assert _BOILERPLATE_RE.search("We offer competitive PTO and benefits")

    def test_eeo_does_not_match_theoretical(self):
        assert not _BOILERPLATE_RE.search("theoretical computer science")

    def test_eeo_matches_standalone(self):
        assert _BOILERPLATE_RE.search("We are an EEO employer")

    def test_remote_does_not_match_remotely(self):
        """'remote' should not match inside 'remotely' — but 'remotely'
        contains 'remote' as a word boundary match. Actually \bremote\b
        WILL match 'remotely' because \b is between 'e' and 'l'... wait no,
        \b is a word boundary, and 'remotely' has no boundary between
        'remote' and 'ly'. Let me check."""
        # \bremote\b requires a non-word char after 'remote'. In 'remotely',
        # 'l' is a word char, so \bremote\b does NOT match. Good.
        assert not _BOILERPLATE_RE.search("remotely sensed data")

    def test_remote_matches_standalone(self):
        assert _BOILERPLATE_RE.search("This is a remote position")

    def test_sponsorship_matches_standalone(self):
        assert _BOILERPLATE_RE.search("visa sponsorship available")

    def test_benefits_matches_standalone(self):
        assert _BOILERPLATE_RE.search("great benefits package")

    def test_diversity_matches_standalone(self):
        assert _BOILERPLATE_RE.search("commitment to diversity")

    def test_on_site_with_hyphen(self):
        assert _BOILERPLATE_RE.search("on-site work required")

    def test_on_site_with_dot(self):
        assert _BOILERPLATE_RE.search("on.site work required")

    def test_401k_matches(self):
        assert _BOILERPLATE_RE.search("401k matching")

    def test_line_with_crypto_survives_filter(self):
        """A line containing 'crypto trading' must survive the boilerplate
        filter in scope_jd_text."""
        # Build a JD with no section headers so the boilerplate filter runs
        jd = "Trojan is at the forefront of crypto trading technology.\nWe offer great benefits and PTO."
        scoped, mode = scope_jd_text(jd)
        assert "crypto" in scoped.lower(), f"crypto was stripped! mode={mode}, scoped={scoped!r}"

    def test_actual_benefits_line_filtered(self):
        """A line that is actually about PTO and benefits should be filtered."""
        jd = (
            "Job requires Kubernetes and Terraform for infrastructure as code management.\n"
            "Experience with Prometheus and Grafana for observability monitoring.\n"
            "PTO and benefits included."
        )
        scoped, mode = scope_jd_text(jd)
        assert mode == "full_text_filtered"
        assert "kubernetes" in scoped.lower()
        assert "pto" not in scoped.lower()


# ---------------------------------------------------------------------------
# Fix #1: Blind-selection guard (scope_collapsed fallback)
# ---------------------------------------------------------------------------


class TestBlindSelectionGuard:
    def test_scope_collapsed_on_empty_filter(self):
        """If boilerplate filtering removes everything, scope_jd_text falls
        back to the raw text with mode='scope_collapsed'."""
        # A single-line JD where the entire line matches boilerplate
        jd = "We offer competitive compensation, benefits, PTO, and remote work."
        scoped, mode = scope_jd_text(jd)
        assert mode == "scope_collapsed"
        assert scoped == jd  # falls back to raw text

    def test_scope_collapsed_preserves_content(self):
        """Even when collapsing, the raw text is returned so the scorer
        can still extract terms."""
        jd = "crypto trading bot using Kubernetes and Prometheus, with benefits and PTO."
        scoped, mode = scope_jd_text(jd)
        # 'pto' is now word-bounded, so 'crypto' survives. But 'benefits'
        # and 'PTO' still match. Let's check if the line survives.
        # Actually with word-bounded regex, 'PTO' matches as a word,
        # 'benefits' matches, 'compensation' would match. So the line
        # is filtered. But 'crypto' no longer matches. So the filtered
        # result should still have content... unless ALL content is boilerplate.
        # In this case, 'Kubernetes' and 'Prometheus' are not boilerplate,
        # so the line should survive.
        # Wait — the filter is line-based. If the JD is one line and any
        # boilerplate term matches, the WHOLE line is dropped.
        # With the old regex, 'pto' in 'crypto' would match. With the new
        # word-bounded regex, 'PTO' as a standalone word matches.
        # So this line IS filtered (PTO and benefits are present).
        # The filtered result is empty → scope_collapsed → fallback to raw.
        assert mode == "scope_collapsed"
        assert "kubernetes" in scoped.lower()

    def test_normal_filter_not_collapsed(self):
        """Normal filtering (some lines removed, content remains) should
        not trigger scope_collapsed."""
        jd = (
            "Job requires Kubernetes and Terraform for infrastructure as code management.\n"
            "Experience with Prometheus and Grafana for observability monitoring.\n"
            "We offer competitive benefits and PTO.\n"
            "Remote work available with flexible hybrid schedule."
        )
        scoped, mode = scope_jd_text(jd)
        assert mode == "full_text_filtered"
        assert "kubernetes" in scoped.lower()
        assert "terraform" in scoped.lower()

    def test_no_boilerplate_returns_full_text(self):
        """JD with no boilerplate at all returns full_text mode."""
        jd = "Job requires Kubernetes and Terraform experience.\nMust know Prometheus and Grafana."
        scoped, mode = scope_jd_text(jd)
        assert mode == "full_text"
        assert "kubernetes" in scoped.lower()
