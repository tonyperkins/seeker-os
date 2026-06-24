"""Anthropic provider — native Messages API."""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import anthropic

from seeker_os.llm.models import LLMRequest, LLMResponse, ModelInfo, ProviderHealth

# OAuth client_id used by Claude CLI / Hermes (shared PKCE flow)
_OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
_OAUTH_TOKEN_ENDPOINTS = [
    "https://platform.claude.com/v1/oauth/token",
    "https://console.anthropic.com/v1/oauth/token",
]


def _resolve_token_path(token_path: str) -> Path:
    """Resolve an OAuth token path — expanduser and resolve relative to project root."""
    from seeker_os.config import PROJECT_ROOT
    p = Path(token_path).expanduser()
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return p


def _load_oauth_data(token_path: str) -> dict:
    """Load the full OAuth data from a JSON file."""
    path = _resolve_token_path(token_path)
    if not path.exists():
        raise FileNotFoundError(f"OAuth token file not found: {path}")
    return json.loads(path.read_text())


def _load_oauth_token(token_path: str) -> str:
    """Load an OAuth access token from a JSON file.

    Supports the Hermes-style format: {"accessToken": "...", "refreshToken": "...", "expiresAt": "..."}
    Also supports a simple {"access_token": "..."} format.
    """
    data = _load_oauth_data(token_path)
    if "accessToken" in data:
        return data["accessToken"]
    if "access_token" in data:
        return data["access_token"]
    raise ValueError("OAuth token file has no accessToken/access_token field")


def _is_token_expired(token_path: str, skew_seconds: int = 60) -> bool:
    """Check if the OAuth token is expired (with a safety skew)."""
    try:
        data = _load_oauth_data(token_path)
        expires_at = data.get("expiresAt", 0)
        if isinstance(expires_at, str):
            expires_at = int(expires_at)
        # expiresAt is in milliseconds
        now_ms = int(time.time() * 1000)
        return now_ms + (skew_seconds * 1000) >= expires_at
    except Exception:
        return False  # Can't check — let the API call fail naturally


def _refresh_oauth_token(token_path: str) -> str:
    """Refresh an expired OAuth token using the refresh token.

    Updates the token file in-place with the new access/refresh tokens.
    Returns the new access token.
    """
    data = _load_oauth_data(token_path)
    refresh_token = data.get("refreshToken") or data.get("refresh_token")
    if not refresh_token:
        raise ValueError("No refresh token in OAuth file — cannot refresh")

    post_data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": _OAUTH_CLIENT_ID,
    }).encode()

    last_error = None
    for endpoint in _OAUTH_TOKEN_ENDPOINTS:
        try:
            req = urllib.request.Request(
                endpoint,
                data=post_data,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": "seeker-os/0.1.0 (external, cli)",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read())

            new_data = {
                "accessToken": result["access_token"],
                "refreshToken": result.get("refresh_token", refresh_token),
                "expiresAt": int(time.time() * 1000) + result.get("expires_in", 3600) * 1000,
            }
            # Preserve any other fields from the original file
            for k, v in data.items():
                if k not in new_data:
                    new_data[k] = v

            _resolve_token_path(token_path).write_text(json.dumps(new_data, indent=2))
            return result["access_token"]
        except Exception as e:
            last_error = e
            continue

    raise RuntimeError(f"Failed to refresh OAuth token from all endpoints: {last_error}")


class AnthropicProvider:
    """Direct Anthropic API provider using native Messages API.

    Supports two auth methods:
    - api_key: Standard API key (sk-ant-...)
    - oauth: OAuth token from a file (e.g. from `anthropic` CLI login or Hermes).
             Automatically refreshes expired tokens using the stored refresh token.

    Docs: https://docs.anthropic.com/en/api/messages
    Models: https://docs.anthropic.com/en/api/models
    """

    def __init__(
        self,
        provider_id: str,
        api_key: str = "",
        base_url: str | None = None,
        label: str = "",
        auth_method: str = "api_key",
        oauth_token_path: str | None = None,
    ):
        self._id = provider_id
        self._type = "anthropic"
        self._label = label or provider_id
        self._auth_method = auth_method
        self._oauth_token_path = oauth_token_path

        if auth_method == "oauth" and oauth_token_path:
            self._refresh_if_needed()
            token = _load_oauth_token(oauth_token_path)
            self._client = anthropic.Anthropic(
                auth_token=token,
                base_url=base_url,
            )
        else:
            self._client = anthropic.Anthropic(
                api_key=api_key or None,
                base_url=base_url,
            )

    def _refresh_if_needed(self) -> None:
        """Check if the OAuth token is expired and refresh it if so."""
        if self._auth_method != "oauth" or not self._oauth_token_path:
            return
        if _is_token_expired(self._oauth_token_path):
            try:
                _refresh_oauth_token(self._oauth_token_path)
            except Exception:
                pass  # Let the API call fail with a clear error if refresh fails

    def _rebuild_client(self) -> None:
        """Rebuild the Anthropic client with a fresh token (after refresh)."""
        if self._auth_method == "oauth" and self._oauth_token_path:
            token = _load_oauth_token(self._oauth_token_path)
            self._client = anthropic.Anthropic(
                auth_token=token,
                base_url=self._client.base_url,
            )

    @property
    def id(self) -> str:
        return self._id

    @property
    def type(self) -> str:
        return self._type

    def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate a completion using Anthropic's Messages API."""
        self._refresh_if_needed()
        self._rebuild_client()
        start = time.monotonic()

        kwargs: dict = {
            "model": request.model,
            "max_tokens": request.max_tokens or 4096,
            "system": request.system_prompt,
            "messages": [{"role": "user", "content": request.user_prompt}],
        }

        # Only include temperature if explicitly set (some models reject it)
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature

        try:
            response = self._client.messages.create(**kwargs)
        except Exception as e:
            # If temperature is rejected, retry without it
            if "temperature" in str(e).lower() and "deprecated" in str(e).lower():
                kwargs.pop("temperature", None)
                response = self._client.messages.create(**kwargs)
            else:
                raise
        latency = int((time.monotonic() - start) * 1000)

        text = ""
        if response.content:
            text = "".join(block.text for block in response.content if hasattr(block, "text"))

        return LLMResponse(
            text=text,
            model=response.model,
            provider=self._id,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            latency_ms=latency,
            task=request.task,
        )

    def list_models(self) -> list[ModelInfo]:
        """Fetch available models from Anthropic's API."""
        self._refresh_if_needed()
        self._rebuild_client()
        now = datetime.now(timezone.utc).isoformat()
        response = self._client.models.list()
        models: list[ModelInfo] = []
        for m in response.data:
            models.append(ModelInfo(
                id=m.id,
                label=m.display_name or m.id,
                provider_id=self._id,
                context_window=getattr(m, "context_window", None),
                max_output=None,
                tags=[],
                source="auto",
                available=True,
                fetched_at=now,
            ))
        return models

    def test_connection(self) -> ProviderHealth:
        """Test connectivity by listing models."""
        self._refresh_if_needed()
        self._rebuild_client()
        start = time.monotonic()
        try:
            self._client.models.list(limit=1)
            latency = int((time.monotonic() - start) * 1000)
            return ProviderHealth(
                provider_id=self._id,
                healthy=True,
                message="Connection OK",
                latency_ms=latency,
                checked_at=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as e:
            return ProviderHealth(
                provider_id=self._id,
                healthy=False,
                message=str(e),
                latency_ms=int((time.monotonic() - start) * 1000),
                checked_at=datetime.now(timezone.utc).isoformat(),
            )
