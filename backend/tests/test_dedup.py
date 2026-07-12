"""Tests for dedup normalization and layers."""

from seeker_os.dedup.normalize import normalize_title, normalize_company
from seeker_os.dedup.layers import url_hash, composite_key, content_hash


class TestNormalizeTitle:
    def test_sr_expands_to_senior(self):
        assert "senior" in normalize_title("Sr SRE")

    def test_sre_expands(self):
        result = normalize_title("SRE")
        assert "site reliability engineer" in result

    def test_removes_punctuation(self):
        result = normalize_title("Senior SRE / DevOps")
        assert "/" not in result

    def test_removes_noise_words(self):
        result = normalize_title("Engineer of Platform")
        assert "of" not in result.split()

    def test_devops_not_doubled(self):
        """devops should not become 'devopsdevops' (bidirectional bug check)."""
        result = normalize_title("DevOps Engineer")
        assert "devopsdevops" not in result

    def test_case_insensitive(self):
        assert normalize_title("SENIOR SRE") == normalize_title("senior sre")


class TestNormalizeCompany:
    def test_strips_inc(self):
        assert normalize_company("TREX Solutions Inc") == "trex solutions"

    def test_strips_llc(self):
        assert normalize_company("Acme LLC") == "acme"

    def test_strips_technologies(self):
        assert normalize_company("Cloud Technologies") == "cloud"

    def test_only_strips_one_suffix(self):
        """Should only strip one suffix, not chain.
        "Acme Inc LLC" ends with " llc", so that's what gets stripped."""
        result = normalize_company("Acme Inc LLC")
        # Strips " llc" (the matching suffix), leaving "acme inc"
        assert "inc" in result
        assert "llc" not in result

    def test_rstrip_bug_check(self):
        """rstrip strips a character SET, not a suffix string.
        's' in 'systems' would strip all trailing s chars. Verify we use slicing."""
        # "Systems" should become "systems" -> stripped to "" (correct)
        # But "Boss" should NOT lose the "s" — rstrip would strip it
        result = normalize_company("Boss")
        assert result == "boss"  # not "bo"

    def test_case_insensitive(self):
        assert normalize_company("ACME INC") == normalize_company("acme inc")


class TestUrlHash:
    def test_consistent(self):
        assert url_hash("https://example.com/job/123") == url_hash("https://example.com/job/123")

    def test_strips_trailing_slash(self):
        assert url_hash("https://example.com/job/123") == url_hash("https://example.com/job/123/")

    def test_case_insensitive(self):
        assert url_hash("https://Example.COM/Job/123") == url_hash("https://example.com/job/123")

    def test_different_urls_different_hashes(self):
        assert url_hash("https://a.com") != url_hash("https://b.com")


class TestCompositeKey:
    def test_basic_decomposition(self):
        source_map = {"grnhse": "greenhouse"}
        key = composite_key("grnhse___trexsolutions___8534403002", source_map)
        assert key == "greenhouse:trexsolutions:8534403002"

    def test_url_encoded(self):
        source_map = {}
        key = composite_key("careflow%2FEA.00A___board___123", source_map)
        assert key is not None
        assert "/" in key  # URL-decoded

    def test_malformed_returns_none(self):
        source_map = {}
        assert composite_key("malformed_id", source_map) is None
        assert composite_key("a___b", source_map) is None

    def test_unknown_source_passes_through(self):
        source_map = {}
        key = composite_key("unknown___board___123", source_map)
        assert key == "unknown:board:123"


class TestContentHash:
    def test_consistent(self):
        assert content_hash("Hello World JD text here") == content_hash("Hello World JD text here")

    def test_strips_html(self):
        assert content_hash("<p>Hello</p>") == content_hash("Hello")

    def test_case_insensitive(self):
        assert content_hash("HELLO") == content_hash("hello")

    def test_normalizes_whitespace(self):
        assert content_hash("hello   world") == content_hash("hello world")

    def test_full_text_not_truncated(self):
        # Content hash uses the full JD text, not just the first 500 chars.
        # This prevents false positives when different roles share boilerplate intros.
        assert content_hash("a" * 600) != content_hash("a" * 500)
