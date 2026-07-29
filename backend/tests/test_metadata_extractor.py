"""Tests for metadata_extractor workplace_type post-processing.

The LLM sometimes classifies a job as "Hybrid" when the JD text actually
says remote is an option (e.g. "Hybrid Seattle preferred / Remote OK too").
The _post_process_workplace_type safety-net catches these cases.
"""

from __future__ import annotations

from seeker_os.analysis.metadata_extractor import _post_process_workplace_type


class TestPostProcessWorkplaceType:
    """Verify _post_process_workplace_type overrides Hybrid→Remote correctly."""

    def test_remote_ok_too(self):
        """'Remote OK too' should override Hybrid→Remote."""
        jd = "Hybrid Seattle preferred / Remote OK too\nFull-Time"
        assert _post_process_workplace_type("Hybrid", jd) == "Remote"

    def test_remote_ok(self):
        """'Remote OK' should override Hybrid→Remote."""
        jd = "Hybrid preferred. Remote OK. Full benefits."
        assert _post_process_workplace_type("Hybrid", jd) == "Remote"

    def test_open_to_fully_remote(self):
        """'open to fully remote for the right person' should override."""
        jd = "We are a remote-first team. Open to fully remote for the right person."
        assert _post_process_workplace_type("Hybrid", jd) == "Remote"

    def test_remote_first(self):
        """'remote-first' should override Hybrid→Remote."""
        jd = "We are a remote-first team with a small in-person office."
        assert _post_process_workplace_type("Hybrid", jd) == "Remote"

    def test_work_from_anywhere(self):
        """'work from anywhere' should override Hybrid→Remote."""
        jd = "Hybrid in NYC. Work from anywhere also accepted."
        assert _post_process_workplace_type("Hybrid", jd) == "Remote"

    def test_remote_is_an_option(self):
        """'remote is an option' should override Hybrid→Remote."""
        jd = "Hybrid in Seattle. Remote is an option for the right candidate."
        assert _post_process_workplace_type("Hybrid", jd) == "Remote"

    def test_remote_friendly(self):
        """'remote friendly' should override Hybrid→Remote."""
        jd = "Hybrid in Austin. We are remote friendly."
        assert _post_process_workplace_type("Hybrid", jd) == "Remote"

    def test_pure_hybrid_stays_hybrid(self):
        """Genuine hybrid (no remote option mentioned) should stay Hybrid."""
        jd = "Hybrid: 3 days in office, 2 days remote. Seattle, WA."
        assert _post_process_workplace_type("Hybrid", jd) == "Hybrid"

    def test_remote_not_overridden_for_on_site(self):
        """On-Site should not be overridden even if 'remote' appears in text."""
        jd = "On-Site in Seattle. No remote option."
        assert _post_process_workplace_type("On-Site", jd) == "On-Site"

    def test_empty_workplace_type(self):
        """Empty/None workplace_type should pass through as empty string."""
        assert _post_process_workplace_type("", "some jd text") == ""
        assert _post_process_workplace_type(None, "some jd text") == ""  # type: ignore[arg-type]

    def test_remote_classification_unchanged(self):
        """Remote should stay Remote even if 'hybrid' appears in text."""
        jd = "Remote. We used to be hybrid but now we're fully remote."
        assert _post_process_workplace_type("Remote", jd) == "Remote"

    def test_boundless_job_posting(self):
        """Reproduces the exact Boundless Principal Architect posting that was
        misclassified as Hybrid."""
        jd = """\
Principal Architect

Hybrid Seattle preferred  / Remote OK too
Full-Time

We're hiring a Principal Architect to reinvent how legal work gets done in the age of AI.

We are a remote-first team with a small in-person office in Seattle. Our ideal
applicant is based in Seattle and will be in the office two-days per week,
although we are open to fully remote for the right person.
"""
        assert _post_process_workplace_type("Hybrid", jd) == "Remote"
