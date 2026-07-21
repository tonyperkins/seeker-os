"""Minimal Google OAuth client with a private, local token store."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.parse import urlsplit

import httpx

from seeker_os.config import EmailConfig

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
PROFILE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/profile"


class OAuthError(RuntimeError):
    pass


class TokenStore:
    def __init__(self, path: str):
        self.path = Path(path)
        self.state_path = self.path.with_name(f"{self.path.stem}_state.json")

    @staticmethod
    def _atomic_private_write(path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(f"{path.suffix}.tmp")
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp, 0o600)
            os.replace(temp, path)
            os.chmod(path, 0o600)
        finally:
            if temp.exists():
                temp.unlink()

    def load(self) -> dict:
        if not self.path.exists():
            raise OAuthError("Gmail is not authorized; connect the dedicated account first")
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise OAuthError("Stored Gmail authorization is unreadable; reauthorize") from exc

    def save(self, token: dict) -> None:
        self._atomic_private_write(self.path, token)

    def save_state(self, state: str, redirect_uri: str) -> None:
        self._atomic_private_write(
            self.state_path,
            {
                "state_sha256": hashlib.sha256(state.encode()).hexdigest(),
                "redirect_uri": redirect_uri,
                "expires_at": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
            },
        )

    def consume_state(self, state: str) -> str:
        try:
            saved = json.loads(self.state_path.read_text(encoding="utf-8"))
            expires = datetime.fromisoformat(saved["expires_at"])
            expected = saved["state_sha256"]
            redirect_uri = saved["redirect_uri"]
        except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
            raise OAuthError("OAuth state is missing or invalid; start authorization again") from exc
        finally:
            if self.state_path.exists():
                self.state_path.unlink()
        actual = hashlib.sha256(state.encode()).hexdigest()
        if expires < datetime.now(UTC) or not secrets.compare_digest(actual, expected):
            raise OAuthError("OAuth state expired or did not match; start authorization again")
        return redirect_uri


class OAuthManager:
    def __init__(self, config: EmailConfig):
        self.config = config
        self.store = TokenStore(config.oauth.token_path)

    def authorization_url(self, origin: str) -> str:
        redirect_uri = f"{origin.rstrip('/')}/api/inbound/oauth/callback"
        if redirect_uri not in self.config.oauth.redirect_uris:
            raise OAuthError("This browser origin is not an approved Gmail OAuth callback")
        state = secrets.token_urlsafe(32)
        self.store.save_state(state, redirect_uri)
        params = {
            "client_id": self.config.oauth.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": self.config.oauth.scope,
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "false",
            "state": state,
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    def exchange_callback(self, code: str, state: str) -> dict:
        redirect_uri = self.store.consume_state(state)
        try:
            response = httpx.post(
                TOKEN_URL,
                data={
                    "code": code,
                    "client_id": self.config.oauth.client_id,
                    "client_secret": self.config.oauth.client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
                timeout=self.config.request_timeout_seconds,
            )
            response.raise_for_status()
            token = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OAuthError("Google rejected the Gmail authorization exchange") from exc

        access_token = token.get("access_token")
        refresh_token = token.get("refresh_token")
        if not access_token or not refresh_token:
            raise OAuthError("Google did not return a durable refresh token; reauthorize with consent")
        profile = self._profile(access_token)
        connected_email = (profile.get("emailAddress") or "").lower()
        expected = self.config.dedicated_account_address.lower()
        if connected_email != expected:
            raise OAuthError(
                f"Authorized Gmail account is {connected_email or 'unknown'}, expected dedicated account {expected}"
            )

        stored = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": token.get("token_type", "Bearer"),
            "scope": token.get("scope", self.config.oauth.scope),
            "expires_at": (
                datetime.now(UTC) + timedelta(seconds=int(token.get("expires_in", 3600)))
            ).isoformat(),
            "account_email": connected_email,
        }
        self.store.save(stored)
        return {"account_email": connected_email, "scope": stored["scope"], "redirect_uri": redirect_uri}

    def access_token(self) -> str:
        token = self.store.load()
        if token.get("account_email", "").lower() != self.config.dedicated_account_address.lower():
            raise OAuthError("Stored Gmail authorization is not for the configured dedicated account")
        try:
            expires = datetime.fromisoformat(token["expires_at"])
        except (KeyError, TypeError, ValueError) as exc:
            raise OAuthError("Stored Gmail authorization has no valid expiry; reauthorize") from exc
        if expires > datetime.now(UTC) + timedelta(minutes=2):
            return token["access_token"]
        return self._refresh(token)

    def status(self) -> dict:
        try:
            token = self.store.load()
        except OAuthError:
            return {"connected": False, "account_email": None}
        return {
            "connected": bool(token.get("refresh_token")),
            "account_email": token.get("account_email"),
            "token_file_mode": oct(self.store.path.stat().st_mode & 0o777),
        }

    def _refresh(self, token: dict) -> str:
        try:
            response = httpx.post(
                TOKEN_URL,
                data={
                    "client_id": self.config.oauth.client_id,
                    "client_secret": self.config.oauth.client_secret,
                    "refresh_token": token["refresh_token"],
                    "grant_type": "refresh_token",
                },
                timeout=self.config.request_timeout_seconds,
            )
            response.raise_for_status()
            refreshed = response.json()
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise OAuthError("Gmail authorization refresh failed; reauthorize the dedicated account") from exc
        if not refreshed.get("access_token"):
            raise OAuthError("Gmail authorization refresh returned no access token")
        token.update({
            "access_token": refreshed["access_token"],
            "expires_at": (
                datetime.now(UTC) + timedelta(seconds=int(refreshed.get("expires_in", 3600)))
            ).isoformat(),
        })
        self.store.save(token)
        return token["access_token"]

    def _profile(self, access_token: str) -> dict:
        try:
            response = httpx.get(
                PROFILE_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=self.config.request_timeout_seconds,
            )
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OAuthError("Unable to verify the authorized Gmail account") from exc
