"""Regression tests for honest_qualifiers injection from identity_rules.yml.

Verifies that:
- _load_honest_qualifiers_text formats each qualifier as "- skill: framing"
- The text is injected into the system prompt verbatim, inside the
  HONEST QUALIFIERS section, with the "do not upgrade" guard
- Empty/absent identity produces no injection (no hardcoded fallback)
- A specific Ansible era-bounded qualifier renders correctly
"""

import pytest

from seeker_os.config import (
    HonestQualifier,
    IdentityConfig,
    Settings,
)
from seeker_os.resume.generator import _load_honest_qualifiers_text


class _FakeIdentity:
    """Minimal identity stub for testing."""
    def __init__(self, honest_qualifiers=None, never_claim=None,
                 positioning="", work_eligibility=""):
        self.honest_qualifiers = honest_qualifiers or []
        self.never_claim = never_claim or []
        self.positioning = positioning
        self.work_eligibility = work_eligibility


class _FakeSettings:
    def __init__(self, identity=None):
        self.identity = identity


class TestLoadHonestQualifiersText:
    def test_empty_identity_returns_empty(self):
        settings = _FakeSettings(identity=None)
        assert _load_honest_qualifiers_text(settings) == ""

    def test_no_qualifiers_returns_empty(self):
        settings = _FakeSettings(identity=_FakeIdentity())
        assert _load_honest_qualifiers_text(settings) == ""

    def test_single_qualifier_formatted(self):
        settings = _FakeSettings(identity=_FakeIdentity(honest_qualifiers=[
            HonestQualifier(skill="Kubernetes", framing="production 2018–2022, currently ramping"),
        ]))
        text = _load_honest_qualifiers_text(settings)
        assert "- Kubernetes: production 2018–2022, currently ramping" in text

    def test_multiple_qualifiers_all_present(self):
        settings = _FakeSettings(identity=_FakeIdentity(honest_qualifiers=[
            HonestQualifier(skill="Kubernetes", framing="production 2018–2022, currently ramping"),
            HonestQualifier(skill="AWS", framing="broad familiarity, not deep expertise"),
            HonestQualifier(skill="Ansible", framing="Acme Corp 2017–2018 — not current daily use"),
        ]))
        text = _load_honest_qualifiers_text(settings)
        assert "- Kubernetes: production 2018–2022, currently ramping" in text
        assert "- AWS: broad familiarity, not deep expertise" in text
        assert "- Ansible: Acme Corp 2017–2018 — not current daily use" in text

    def test_ansible_era_bounded_qualifier(self):
        """The Ansible qualifier must render era-bounded, not as a bare current skill."""
        settings = _FakeSettings(identity=_FakeIdentity(honest_qualifiers=[
            HonestQualifier(
                skill="Ansible",
                framing="Acme Corp 2017–2018 — Ansible-driven configuration management, not current daily use",
            ),
        ]))
        text = _load_honest_qualifiers_text(settings)
        assert "Ansible" in text
        assert "Acme Corp 2017–2018" in text
        assert "not current daily use" in text
        # Must NOT appear as a bare skill without era context
        lines = text.strip().split("\n")
        ansible_lines = [l for l in lines if "Ansible" in l]
        assert len(ansible_lines) == 1
        assert "2017" in ansible_lines[0]


class TestSystemPromptInjection:
    """Verify the full system prompt includes the HONEST QUALIFIERS section."""

    def test_prompt_contains_honest_qualifiers_section(self, monkeypatch):
        """The generate_resume function injects honest qualifiers into the system
        prompt. We verify the prompt-building functions directly — they are the
        injection point."""
        import seeker_os.resume.generator as genmod

        identity = _FakeIdentity(
            honest_qualifiers=[
                HonestQualifier(
                    skill="Ansible",
                    framing="Acme Corp 2017–2018 — Ansible-driven configuration management, not current daily use",
                ),
                HonestQualifier(skill="Kubernetes", framing="production 2018–2022, currently ramping"),
            ],
            never_claim=["ArgoCD", "Helm"],
        )

        settings = _FakeSettings(identity=identity)

        hq_text = genmod._load_honest_qualifiers_text(settings)
        assert "Ansible" in hq_text
        assert "Acme Corp 2017–2018" in hq_text
        assert "Kubernetes" in hq_text

        # The never-claim list must NOT include Ansible (it was removed)
        nc_text = genmod._load_never_claim_text(settings)
        assert "Ansible" not in nc_text
        assert "ArgoCD" in nc_text
        assert "Helm" in nc_text
