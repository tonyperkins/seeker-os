"""Anthropic OAuth PKCE flow — initiate, exchange, and store tokens.

This implements the same OAuth flow used by the Claude CLI and Hermes:
1. Generate PKCE code_verifier + code_challenge
2. Build authorization URL for claude.ai/oauth/authorize
3. User authorizes in browser, gets a code on the callback page
4. User pastes the code back
5. Exchange code + verifier for access/refresh tokens
6. Save tokens to a local file

The token file format matches Hermes: {"accessToken", "refreshToken", "expiresAt"}
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import urllib.parse
import urllib.request
from pathlib import Path

from seeker_os.config import DATA_DIR

# Same client_id used by Claude CLI / Hermes (shared PKCE flow)
OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
OAUTH_AUTHORIZE_URL = "https://claude.ai/oauth/authorize"
OAUTH_TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"
OAUTH_REDIRECT_URI = "https://console.anthropic.com/oauth/code/callback"
OAUTH_SCOPES = "org:create_api_key user:profile user:inference"

# Local token storage
TOKEN_FILE = DATA_DIR / ".anthropic_oauth.json"

# In-memory store for PKCE state (per-process, short-lived)
# Maps state -> {code_verifier, created_at}
_pkce_states: dict[str, dict] = {}


def generate_pkce() -> tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge (S256)."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def initiate_oauth() -> dict:
    """Start the OAuth flow — generate PKCE and return the authorization URL.

    Returns:
        {"auth_url": str, "state": str}
    """
    verifier, challenge = generate_pkce()
    state = secrets.token_urlsafe(32)

    _pkce_states[state] = {
        "code_verifier": verifier,
        "created_at": time.time(),
    }

    # Clean up old states (older than 10 minutes)
    cutoff = time.time() - 600
    for s in list(_pkce_states.keys()):
        if _pkce_states[s]["created_at"] < cutoff:
            del _pkce_states[s]

    params = {
        "code": "true",
        "client_id": OAUTH_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": OAUTH_REDIRECT_URI,
        "scope": OAUTH_SCOPES,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    auth_url = f"{OAUTH_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"

    return {"auth_url": auth_url, "state": state}


def exchange_code(code: str, state: str) -> dict:
    """Exchange the authorization code for access/refresh tokens.

    Args:
        code: The authorization code from the callback (may include #state suffix)
        state: The state parameter returned with the code

    Returns:
        {"access_token": str, "refresh_token": str, "expires_at_ms": int}

    Raises:
        ValueError: If state doesn't match or exchange fails
    """
    # Parse the code — user may paste "code#state" or just "code"
    splits = code.split("#")
    actual_code = splits[0]
    received_state = splits[1] if len(splits) > 1 else state

    # Validate state to prevent CSRF
    if received_state not in _pkce_states:
        raise ValueError("Invalid or expired state. Please restart the authorization flow.")

    pkce_data = _pkce_states.pop(received_state)
    code_verifier = pkce_data["code_verifier"]

    exchange_data = json.dumps({
        "grant_type": "authorization_code",
        "client_id": OAUTH_CLIENT_ID,
        "code": actual_code,
        "state": received_state,
        "redirect_uri": OAUTH_REDIRECT_URI,
        "code_verifier": code_verifier,
    }).encode()

    req = urllib.request.Request(
        OAUTH_TOKEN_URL,
        data=exchange_data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "seeker-os/0.1.0 (external, cli)",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=15) as resp:
        result = json.loads(resp.read().decode())

    access_token = result.get("access_token", "")
    refresh_token = result.get("refresh_token", "")
    expires_in = result.get("expires_in", 3600)

    if not access_token:
        raise ValueError("No access token in response from Anthropic")

    expires_at_ms = int(time.time() * 1000) + (expires_in * 1000)

    # Save token to file
    token_data = {
        "accessToken": access_token,
        "refreshToken": refresh_token,
        "expiresAt": expires_at_ms,
    }
    save_token(token_data)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at_ms": expires_at_ms,
    }


def save_token(token_data: dict) -> None:
    """Save OAuth token data to the local token file."""
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(token_data, indent=2), encoding="utf-8")


def get_token_status() -> dict:
    """Check if we have a valid OAuth token.

    Returns:
        {"exists": bool, "expired": bool, "expires_at": int | None, "path": str}
    """
    if not TOKEN_FILE.exists():
        return {"exists": False, "expired": True, "expires_at": None, "path": str(TOKEN_FILE)}

    try:
        data = json.loads(TOKEN_FILE.read_text())
        expires_at = data.get("expiresAt", 0)
        if isinstance(expires_at, str):
            expires_at = int(expires_at)
        now_ms = int(time.time() * 1000)
        return {
            "exists": True,
            "expired": now_ms + 60000 >= expires_at,
            "expires_at": expires_at,
            "path": str(TOKEN_FILE),
        }
    except Exception:
        return {"exists": False, "expired": True, "expires_at": None, "path": str(TOKEN_FILE)}


def get_token_path() -> str:
    """Return the path to the local OAuth token file."""
    return str(TOKEN_FILE)
