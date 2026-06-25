"""Tests for identity_rules and channel_rules config loading."""

import yaml
import pytest
from seeker_os.config import Settings, CONFIG_DIR


@pytest.fixture
def test_config_dir(tmp_path, monkeypatch):
    """Create a test config directory with minimal config files."""
    import shutil
    test_config = tmp_path / "config"
    test_config.mkdir()
    for f in CONFIG_DIR.iterdir():
        if f.is_file():
            shutil.copy(f, test_config / f.name)
    monkeypatch.setattr("seeker_os.config.CONFIG_DIR", test_config)
    return test_config


class TestIdentityRulesLoading:
    def test_identity_loaded_from_yaml(self, test_config_dir):
        """Identity rules are loaded from identity_rules.yml."""
        (test_config_dir / "identity_rules.yml").write_text(
            yaml.dump({"identity": {
                "positioning": "I build reliable systems",
                "experience_anchor": {
                    "phrase": "NN+ years in engineering",
                    "applies_to": "overall career",
                    "disallowed_variants": [r"(40|50)\+\s*years"],
                },
                "honest_qualifiers": [
                    {"skill": "Rust", "framing": "learning, not production"},
                ],
                "never_claim": ["Blockchain", "Web3"],
            }}, default_flow_style=False),
            encoding="utf-8",
        )
        settings = Settings()
        settings.config_dir = test_config_dir
        assert settings.identity is not None
        assert settings.identity.positioning == "I build reliable systems"
        assert settings.identity.experience_anchor.phrase == "NN+ years in engineering"
        assert settings.identity.experience_anchor.applies_to == "overall career"
        assert len(settings.identity.experience_anchor.disallowed_variants) == 1
        assert len(settings.identity.honest_qualifiers) == 1
        assert settings.identity.honest_qualifiers[0].skill == "Rust"
        assert settings.identity.never_claim == ["Blockchain", "Web3"]

    def test_identity_none_when_no_file(self, test_config_dir):
        """Identity is None when identity_rules.yml does not exist."""
        # Remove if it was copied from real config
        identity_file = test_config_dir / "identity_rules.yml"
        if identity_file.exists():
            identity_file.unlink()
        settings = Settings()
        settings.config_dir = test_config_dir
        assert settings.identity is None

    def test_identity_partial_config(self, test_config_dir):
        """Identity loads with only some fields configured."""
        (test_config_dir / "identity_rules.yml").write_text(
            yaml.dump({"identity": {
                "positioning": "Test positioning",
            }}, default_flow_style=False),
            encoding="utf-8",
        )
        settings = Settings()
        settings.config_dir = test_config_dir
        assert settings.identity is not None
        assert settings.identity.positioning == "Test positioning"
        assert settings.identity.experience_anchor.phrase == ""
        assert settings.identity.honest_qualifiers == []
        assert settings.identity.never_claim == []


class TestChannelRulesLoading:
    def test_channel_rules_loaded_from_yaml(self, test_config_dir):
        """Channel rules are loaded from channel_rules.yml."""
        (test_config_dir / "channel_rules.yml").write_text(
            yaml.dump({"channels": {
                "resume": {
                    "require_visible_urls": True,
                    "format_hints": "1-2 pages, markdown",
                    "ai_generation_default": "allowed",
                },
                "cover_letter": {
                    "require_visible_urls": False,
                    "format_hints": "Half page",
                    "ai_generation_default": "allowed",
                },
            }}, default_flow_style=False),
            encoding="utf-8",
        )
        settings = Settings()
        settings.config_dir = test_config_dir
        assert settings.channel_rules is not None
        assert settings.channel_rules.resume.require_visible_urls is True
        assert settings.channel_rules.resume.format_hints == "1-2 pages, markdown"
        assert settings.channel_rules.cover_letter.require_visible_urls is False

    def test_channel_rules_none_when_no_file(self, test_config_dir):
        """Channel rules is None when channel_rules.yml does not exist."""
        channel_file = test_config_dir / "channel_rules.yml"
        if channel_file.exists():
            channel_file.unlink()
        settings = Settings()
        settings.config_dir = test_config_dir
        assert settings.channel_rules is None
