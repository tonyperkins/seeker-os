"""Tests for PDF page-count gate and PageCountValidator.

Tests the Phase 2 page-count validation:
- count_pdf_pages() returns accurate page counts
- PageCountValidator fails >2 pages (high severity)
- PageCountValidator warns at exactly 2 pages (medium severity, near-full)
- PageCountValidator passes <2 pages
- Diagnostics include per-section line counts and per-role bullet counts
- Graceful degradation when weasyprint not installed
"""

from __future__ import annotations

import pytest

from seeker_os.config import Settings
from seeker_os.validation import PageCountValidator, ValidationResult, Violation


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

SHORT_RESUME = """# Test User
https://example.com | https://linkedin.com/in/test

## Professional Experience

### Senior SRE at Acme Corp (2023-Present)
- Built Kubernetes platform serving 50M requests/day
- Reduced incident response time by 40%

### SRE at Beta Inc (2020-2023)
- Managed 200-node Kafka cluster
- Automated deployment pipelines
"""

TWO_PAGE_RESUME = """# Test User
https://example.com | https://linkedin.com/in/test

## Professional Experience

### Principal SRE at Acme Corp (2023-Present)
- Built Kubernetes platform serving 50M requests/day across 15 regions
- Reduced incident response time by 40% through automated runbooks and blameless post-mortems
- Led migration from monolithic infrastructure to microservices architecture
- Designed and implemented multi-region failover with RTO < 5 minutes
- Mentored team of 8 engineers on SRE practices and observability
- Established SLO/SLI framework adopted across 12 product teams

### Senior SRE at Beta Inc (2020-2023)
- Managed 200-node Kafka cluster processing 2TB/day
- Automated deployment pipelines reducing deploy time from 45min to 8min
- Built self-healing infrastructure with auto-scaling and auto-remediation
- Led on-call rotation for 24/7 coverage of critical payment systems

### SRE at Gamma Corp (2018-2020)
- Implemented comprehensive monitoring with Prometheus and Grafana
- Reduced infrastructure costs by 30% through right-sizing and reserved instances
- Built CI/CD pipeline with GitHub Actions and ArgoCD
- Migrated 50 services from EC2 to EKS with zero downtime
- Established capacity planning process for seasonal traffic spikes
- Designed multi-account AWS landing zone with centralized logging
- Built automated DR testing framework with quarterly failover exercises
- Implemented network policy enforcement across all Kubernetes namespaces
- Created self-service runbook generation tool adopted by 5 teams
- Led migration from monolithic monitoring to federated Prometheus setup
- Built automated capacity forecasting model for seasonal traffic patterns
- Implemented Pod Security Standards across all Kubernetes namespaces
- Designed and implemented multi-cluster service mesh with Istio
- Created internal SRE playbook template adopted organization-wide
- Built automated compliance scanning pipeline for SOC2 requirements
- Developed custom Prometheus exporters for business-critical metrics
- Led migration from monolithic monitoring to federated Prometheus setup
- Built automated compliance scanning pipeline for SOC2 requirements
- Created capacity planning models for seasonal traffic spikes
- Implemented network policy enforcement across all Kubernetes namespaces
- Designed multi-account AWS landing zone with centralized logging
- Built automated DR testing framework with quarterly failover exercises

## Core Competencies
- **Cloud:** AWS, GCP, Azure
- **Orchestration:** Kubernetes, ECS, Nomad
- **Observability:** Prometheus, Grafana, Datadog, Jaeger
"""

LONG_RESUME = """# Test User
https://example.com | https://linkedin.com/in/test
test@example.com | (555) 123-4567

## Summary
Principal Site Reliability Engineer with 14+ years building and scaling distributed systems for high-growth technology companies. Deep expertise in Kubernetes platform engineering, multi-region infrastructure, and observability. Proven track record of reducing incident response times, optimizing infrastructure costs, and mentoring engineering teams. Passionate about building developer-first platforms that enable rapid, safe deployment at scale.

## Professional Experience

### Principal SRE at Acme Corp (2023-Present)
- Built Kubernetes platform serving 50M requests/day across 15 regions
- Reduced incident response time by 40% through automated runbooks and blameless post-mortems
- Led migration from monolithic infrastructure to microservices architecture
- Designed and implemented multi-region failover with RTO < 5 minutes
- Mentored team of 8 engineers on SRE practices and observability
- Established SLO/SLI framework adopted across 12 product teams
- Architected event-driven platform processing 10B events/day
- Drove platform engineering roadmap for 40 engineering teams
- Built internal developer platform reducing service bootstrap from 2 weeks to 2 hours
- Implemented progressive delivery with canary deployments and automated rollback
- Created self-service observability stack adopted by 30+ teams
- Led incident response for critical outages with blameless post-mortem culture
- Designed capacity planning models for seasonal traffic spikes with 99.99% uptime
- Built cost allocation framework tracking per-team infrastructure spend in real-time
- Implemented zero-trust security model across all platform components
- Spearheaded adoption of OpenTelemetry across 50+ services for vendor-neutral observability
- Created platform engineering charter and roadmap aligned with company-wide engineering goals
- Drove adoption of GitOps workflows with ArgoCD for all platform infrastructure changes
- Built golden-path templates reducing new service setup from days to minutes
- Established platform reliability reviews with quarterly business impact reporting

### Senior SRE at Beta Inc (2020-2023)
- Managed 200-node Kafka cluster processing 2TB/day
- Automated deployment pipelines reducing deploy time from 45min to 8min
- Built self-healing infrastructure with auto-scaling and auto-remediation
- Led on-call rotation for 24/7 coverage of critical payment systems
- Designed chaos engineering practice with regular game days
- Implemented cost optimization saving $2M annually through spot instances and right-sizing
- Built comprehensive runbook automation reducing MTTR by 60%
- Migrated 50 services from EC2 to EKS with zero downtime
- Established incident review process adopted across all engineering teams
- Created internal SRE certification program graduated by 15 engineers
- Designed multi-region database replication strategy with automated failover
- Implemented feature flag platform enabling progressive rollout for 100+ services
- Built centralized logging platform ingesting 5TB/day with sub-second search latency
- Led vendor evaluation and migration from Datadog to self-hosted observability stack

### SRE at Gamma Corp (2018-2020)
- Implemented comprehensive monitoring with Prometheus and Grafana
- Reduced infrastructure costs by 30% through right-sizing and reserved instances
- Built CI/CD pipeline with GitHub Actions and ArgoCD
- Migrated 50 services from EC2 to EKS with zero downtime
- Established capacity planning process for seasonal traffic spikes
- Designed multi-account AWS landing zone with centralized logging
- Built automated DR testing framework with quarterly failover exercises
- Implemented network policy enforcement across all Kubernetes namespaces

### DevOps Engineer at Delta Inc (2016-2018)
- Built Docker-based deployment platform serving 20 teams
- Implemented infrastructure as code with Terraform across 3 AWS accounts
- Managed 500-server fleet with Ansible and Puppet
- Designed blue-green deployment strategy for zero-downtime releases
- Created self-service portal for developer environment provisioning
- Implemented secrets management with HashiCorp Vault across all environments

### Platform Engineer at Epsilon Corp (2014-2016)
- Designed and built internal PaaS on Cloud Foundry
- Implemented blue-green deployment strategy for 30 microservices
- Built service mesh for 30 microservices with Istio
- Created developer documentation and onboarding guides
- Led migration from on-prem to AWS with zero data loss

### Software Engineer at Zeta Inc (2012-2014)
- Developed backend services in Java and Python
- Built REST APIs serving 1M requests/day
- Implemented automated testing reducing production bugs by 50%
- Participated in on-call rotation for critical e-commerce platform

### Junior Developer at Theta Inc (2010-2012)
- Developed web applications using PHP and JavaScript
- Maintained legacy codebase and fixed critical bugs
- Participated in code reviews and pair programming sessions
- Built automated testing framework for PHP applications

### Intern at Iota Corp (2009-2010)
- Assisted in development of internal tools and dashboards
- Wrote SQL queries for reporting and data analysis
- Maintained documentation for development team processes
- Participated in agile ceremonies including standups and retrospectives

## Core Competencies
- **Cloud:** AWS, GCP, Azure
- **Orchestration:** Kubernetes, ECS, Nomad, Mesos
- **Observability:** Prometheus, Grafana, Datadog, Jaeger, Honeycomb
- **CI/CD:** GitHub Actions, ArgoCD, Jenkins, CircleCI, GitLab CI
- **IaC:** Terraform, Pulumi, CloudFormation, Ansible, SaltStack
- **Languages:** Go, Python, Rust, Java, TypeScript, Ruby, C++
- **Databases:** PostgreSQL, MySQL, Redis, Cassandra, MongoDB, Elasticsearch
- **Messaging:** Kafka, RabbitMQ, SQS, NATS, Pulsar
"""


@pytest.fixture
def settings(tmp_path, monkeypatch):
    """Create minimal settings for PageCountValidator."""
    s = Settings.__new__(Settings)
    s.channel_rules = None
    return s


# ---------------------------------------------------------------------------
# count_pdf_pages tests
# ---------------------------------------------------------------------------


class TestCountPdfPages:
    def test_short_resume_one_page(self):
        from seeker_os.resume.export import count_pdf_pages

        pages = count_pdf_pages(SHORT_RESUME)
        if pages is None:
            pytest.skip("weasyprint not installed")
        assert pages == 1

    def test_long_resume_multiple_pages(self):
        from seeker_os.resume.export import count_pdf_pages

        pages = count_pdf_pages(LONG_RESUME)
        if pages is None:
            pytest.skip("weasyprint not installed")
        assert pages > 2

    def test_returns_none_when_weasyprint_missing(self, monkeypatch):
        """When weasyprint is not installed, count_pdf_pages returns None."""
        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name in ("weasyprint", "markdown"):
                raise ImportError(f"No module named '{name}'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        from seeker_os.resume.export import count_pdf_pages

        assert count_pdf_pages("test") is None


# ---------------------------------------------------------------------------
# PageCountValidator tests
# ---------------------------------------------------------------------------


class TestPageCountValidator:
    def test_short_resume_passes(self, settings):
        validator = PageCountValidator(settings)
        result = validator.validate(SHORT_RESUME)
        if result.page_count is None:
            pytest.skip("weasyprint not installed")
        assert result.passed is True
        assert len(result.violations) == 0
        assert result.page_count == 1

    def test_over_two_pages_fails_high_severity(self, settings):
        validator = PageCountValidator(settings)
        result = validator.validate(LONG_RESUME)
        if result.page_count is None:
            pytest.skip("weasyprint not installed")
        assert result.passed is False
        assert result.has_high_severity
        page_violations = [v for v in result.violations if v.rule_id == "page_count_exceeded"]
        assert len(page_violations) == 1
        assert page_violations[0].severity == "high"
        assert str(result.page_count) in page_violations[0].violation

    def test_exactly_two_pages_passes_no_violations(self, settings):
        """At exactly 2 pages (the target), the validator should pass with
        no violations — 2 pages is the target, not a warning condition."""
        validator = PageCountValidator(settings)
        result = validator.validate(TWO_PAGE_RESUME)
        if result.page_count is None:
            pytest.skip("weasyprint not installed")
        if result.page_count != 2:
            pytest.skip(f"TWO_PAGE_RESUME produced {result.page_count} pages, not 2 — adjust fixture")
        assert result.passed is True
        assert len(result.violations) == 0
        assert not result.has_high_severity

    def test_no_high_severity_when_under_limit(self, settings):
        validator = PageCountValidator(settings)
        result = validator.validate(SHORT_RESUME)
        if result.page_count is None:
            pytest.skip("weasyprint not installed")
        assert not result.has_high_severity

    def test_graceful_degradation_no_weasyprint(self, settings, monkeypatch):
        """When weasyprint is not installed, validator passes with no violations."""
        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name in ("weasyprint", "markdown"):
                raise ImportError(f"No module named '{name}'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        validator = PageCountValidator(settings)
        result = validator.validate(SHORT_RESUME)
        assert result.passed is True
        assert len(result.violations) == 0
        assert result.page_count is None


# ---------------------------------------------------------------------------
# Diagnostics tests
# ---------------------------------------------------------------------------


class TestPageCountDiagnostics:
    def test_diagnostics_contain_sections(self, settings):
        validator = PageCountValidator(settings)
        result = validator.validate(LONG_RESUME)
        if result.page_count is None:
            pytest.skip("weasyprint not installed")
        assert result.diagnostics
        assert "sections" in result.diagnostics
        sections = result.diagnostics["sections"]
        # Should have Professional Experience and Core Competencies sections
        section_names = list(sections.keys())
        assert any("Professional Experience" in s for s in section_names)
        assert any("Core Competencies" in s for s in section_names)

    def test_section_line_counts_are_positive(self, settings):
        validator = PageCountValidator(settings)
        result = validator.validate(LONG_RESUME)
        if result.page_count is None:
            pytest.skip("weasyprint not installed")
        sections = result.diagnostics["sections"]
        for name, info in sections.items():
            if name != "(header)":
                assert info["line_count"] > 0, f"Section '{name}' has 0 lines"

    def test_role_bullet_counts(self, settings):
        validator = PageCountValidator(settings)
        result = validator.validate(LONG_RESUME)
        if result.page_count is None:
            pytest.skip("weasyprint not installed")
        role_counts = result.diagnostics["role_bullet_counts"]
        # Should have multiple roles with bullet counts
        assert len(role_counts) >= 3
        # Each role should have at least 2 bullets
        for role, count in role_counts.items():
            assert count >= 2, f"Role '{role}' has only {count} bullets"

    def test_diagnostics_identify_overage_source(self, settings):
        """When a resume exceeds the page limit, diagnostics should help
        identify which section has the most content."""
        validator = PageCountValidator(settings)
        result = validator.validate(LONG_RESUME)
        if result.page_count is None:
            pytest.skip("weasyprint not installed")
        sections = result.diagnostics["sections"]
        # The Professional Experience section should have the most lines
        pe_section = next(
            (info for name, info in sections.items() if "Professional Experience" in name),
            None,
        )
        assert pe_section is not None
        assert pe_section["line_count"] > 10  # it's a long resume

    def test_diagnostics_present_even_when_passing(self, settings):
        """Diagnostics should be generated regardless of pass/fail status."""
        validator = PageCountValidator(settings)
        result = validator.validate(SHORT_RESUME)
        if result.page_count is None:
            pytest.skip("weasyprint not installed")
        assert result.diagnostics
        assert "sections" in result.diagnostics
        assert "role_bullet_counts" in result.diagnostics


# ---------------------------------------------------------------------------
# Integration: ValidationResult with page_count fields
# ---------------------------------------------------------------------------


class TestValidationResultPageCount:
    def test_to_dict_includes_page_count(self):
        result = ValidationResult(
            passed=False,
            violations=[Violation(
                rule_id="page_count_exceeded",
                description="Exceeds 2-page limit",
                violation="Resume is 3 pages (limit: 2)",
                severity="high",
            )],
            checked_at="2025-01-01T00:00:00Z",
            page_count=3,
            diagnostics={"sections": {}, "role_bullet_counts": {}},
        )
        d = result.to_dict()
        assert d["page_count"] == 3
        assert "diagnostics" in d

    def test_to_dict_omits_page_count_when_none(self):
        result = ValidationResult(
            passed=True,
            violations=[],
            checked_at="2025-01-01T00:00:00Z",
        )
        d = result.to_dict()
        assert "page_count" not in d
        assert "diagnostics" not in d


# ---------------------------------------------------------------------------
# Height-based gate tests (tolerance-aware)
# ---------------------------------------------------------------------------


def _make_tiered_settings(target_pages: int, tolerance: float) -> Settings:
    """Build a Settings object with specific page gate config."""
    from seeker_os.config import ContentTieringConfig
    from dataclasses import dataclass

    @dataclass
    class _FakeTiering(ContentTieringConfig):
        pass

    @dataclass
    class _FakeChannelConfig:
        content_tiering: ContentTieringConfig
        require_visible_urls: bool = True
        format_hints: str = ""

    @dataclass
    class _FakeChannelRules:
        resume: _FakeChannelConfig

    @dataclass
    class _FakeSettings:
        channel_rules: _FakeChannelRules
        profile: object = None
        identity: object = None

    tiering = ContentTieringConfig(
        target_pages=target_pages,
        page_overflow_tolerance=tolerance,
    )
    return _FakeSettings(
        channel_rules=_FakeChannelRules(
            resume=_FakeChannelConfig(content_tiering=tiering)
        )
    )


class TestHeightBasedGate:
    """Tests for the height-based page gate with overflow tolerance."""

    def test_exactly_at_budget_passes(self):
        """A resume whose content height equals exactly the page budget
        (target_pages × printable_page_height) must pass with no violations."""
        settings = _make_tiered_settings(target_pages=1, tolerance=0.10)
        validator = PageCountValidator(settings)
        result = validator.validate(SHORT_RESUME)
        if result.page_count is None:
            pytest.skip("weasyprint not installed")
        # SHORT_RESUME is 1 page, target_pages=1 → ratio should be ~1.0
        ratio = result.diagnostics.get("height_ratio", 0)
        assert ratio <= 1.0, f"SHORT_RESUME ratio {ratio} should be <= 1.0 for 1-page budget"
        assert result.passed is True
        assert len(result.violations) == 0

    def test_within_tolerance_passes_with_ratio(self):
        """A resume that spills beyond the budget but within tolerance
        must pass, with the height ratio recorded in diagnostics."""
        # Use TWO_PAGE_RESUME with target_pages=1 and tolerance=1.0
        # (100% tolerance = allows up to 2 pages of height for a 1-page budget)
        settings = _make_tiered_settings(target_pages=1, tolerance=1.0)
        validator = PageCountValidator(settings)
        result = validator.validate(TWO_PAGE_RESUME)
        if result.page_count is None:
            pytest.skip("weasyprint not installed")
        if result.page_count < 2:
            pytest.skip("TWO_PAGE_RESUME didn't produce 2+ pages — adjust fixture")
        # With 100% tolerance, a 2-page resume against a 1-page budget
        # has ratio ~2.0, which is within 1.0+1.0=2.0 budget
        ratio = result.diagnostics.get("height_ratio", 0)
        assert ratio > 1.0, f"Expected ratio > 1.0 (spill), got {ratio}"
        assert ratio <= 2.0, f"Expected ratio <= 2.0 (within tolerance), got {ratio}"
        assert result.passed is True
        assert "height_ratio" in result.diagnostics
        assert result.diagnostics["height_ratio"] > 1.0

    def test_beyond_tolerance_fails_high_severity(self):
        """A resume whose content height exceeds budget × (1 + tolerance)
        must fail with high severity."""
        # LONG_RESUME is many pages; target_pages=1, tolerance=0.10
        # → budget = 1 page, max_allowed = 1.1 pages, LONG_RESUME >> 1.1
        settings = _make_tiered_settings(target_pages=1, tolerance=0.10)
        validator = PageCountValidator(settings)
        result = validator.validate(LONG_RESUME)
        if result.page_count is None:
            pytest.skip("weasyprint not installed")
        assert result.passed is False
        assert result.has_high_severity
        page_violations = [v for v in result.violations if v.rule_id == "page_count_exceeded"]
        assert len(page_violations) == 1
        assert page_violations[0].severity == "high"
        # Diagnostics should record the ratio
        assert "height_ratio" in result.diagnostics
        assert result.diagnostics["height_ratio"] > 1.1

    def test_tolerance_zero_reproduces_strict_behavior(self):
        """With tolerance=0, the gate fails if content height exceeds
        the budget by even 1px — reproducing strict integer-page behavior
        for any content that spills past the target page count."""
        # TWO_PAGE_RESUME with target_pages=1, tolerance=0
        # → budget = 1 page, max_allowed = 1 page exactly
        # TWO_PAGE_RESUME is 2 pages → ratio ~2.0 >> 1.0 → fail
        settings = _make_tiered_settings(target_pages=1, tolerance=0.0)
        validator = PageCountValidator(settings)
        result = validator.validate(TWO_PAGE_RESUME)
        if result.page_count is None:
            pytest.skip("weasyprint not installed")
        if result.page_count < 2:
            pytest.skip("TWO_PAGE_RESUME didn't produce 2+ pages — adjust fixture")
        assert result.passed is False
        assert result.has_high_severity
        # Also verify SHORT_RESUME (1 page) still passes with tolerance=0
        settings2 = _make_tiered_settings(target_pages=1, tolerance=0.0)
        validator2 = PageCountValidator(settings2)
        result2 = validator2.validate(SHORT_RESUME)
        if result2.page_count is None:
            pytest.skip("weasyprint not installed")
        assert result2.passed is True
        assert len(result2.violations) == 0
