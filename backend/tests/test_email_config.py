from pathlib import Path

from seeker_os.config import Settings


def test_email_config_loads_and_expands_token_path(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "email.yml").write_text(
        """
enabled: true
account_key: work_inbound
dedicated_account_address: inbound@example.com
primary_account_address: primary@example.com
oauth:
  client_id: ${GMAIL_OAUTH_CLIENT_ID}
  client_secret: ${GMAIL_OAUTH_CLIENT_SECRET}
  token_path: data/.gmail_oauth.json
""".strip()
    )
    monkeypatch.setenv("GMAIL_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("GMAIL_OAUTH_CLIENT_SECRET", "client-secret")

    settings = Settings(config_dir=config_dir)

    assert settings.email is not None
    assert settings.email.enabled is True
    assert settings.email.account_key == "work_inbound"
    assert settings.email.oauth.client_id == "client-id"
    assert settings.email.oauth.client_secret == "client-secret"
    assert Path(settings.email.oauth.token_path).is_absolute()


def test_email_config_is_optional(tmp_path):
    settings = Settings(config_dir=tmp_path)
    assert settings.email is None
