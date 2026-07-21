"""Gmail REST client and MIME-safe metadata extraction."""

from __future__ import annotations

import base64
import html
import re
from datetime import UTC, datetime
from email.utils import parseaddr
from html.parser import HTMLParser

import httpx

from seeker_os.config import EmailConfig
from seeker_os.inbound.models import ParsedMessage
from seeker_os.inbound.oauth import OAuthManager

GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


class GmailError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class HistoryCursorExpired(GmailError):
    pass


class GmailMessageNotFound(GmailError):
    """A History entry referred to a message that is no longer readable."""


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style"}:
            self.hidden += 1
        elif tag in {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1
        elif tag in {"p", "div", "li", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)

    def text(self) -> str:
        value = html.unescape("".join(self.parts))
        value = re.sub(r"[\t ]+", " ", value)
        value = re.sub(r"\n\s*\n+", "\n", value)
        return value.strip()


def _decode_data(data: str, max_bytes: int) -> str:
    try:
        padded = data + "=" * (-len(data) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))[:max_bytes]
        return raw.decode("utf-8", errors="replace")
    except (ValueError, UnicodeEncodeError):
        return ""


def _walk_text_parts(payload: dict, max_bytes: int) -> tuple[list[str], list[str]]:
    plain: list[str] = []
    rich: list[str] = []
    remaining = max_bytes

    def walk(part: dict) -> None:
        nonlocal remaining
        if remaining <= 0:
            return
        filename = part.get("filename") or ""
        body = part.get("body") or {}
        # attachmentId and filenames are never fetched, even for text MIME types.
        if not filename and not body.get("attachmentId") and body.get("data"):
            decoded = _decode_data(body["data"], remaining)
            remaining -= len(decoded.encode("utf-8", errors="replace"))
            mime = (part.get("mimeType") or "").lower()
            if mime == "text/plain":
                plain.append(decoded)
            elif mime == "text/html":
                parser = _TextExtractor()
                parser.feed(decoded)
                rich.append(parser.text())
        for child in part.get("parts") or []:
            walk(child)

    walk(payload)
    return plain, rich


def parse_gmail_message(raw: dict, max_body_bytes: int) -> ParsedMessage:
    payload = raw.get("payload") or {}
    headers = {
        str(item.get("name", "")).lower(): str(item.get("value", ""))
        for item in payload.get("headers") or []
    }
    sender_address = parseaddr(headers.get("from", ""))[1].lower()
    sender_domain = sender_address.rpartition("@")[2]
    plain, rich = _walk_text_parts(payload, max_body_bytes)
    body = "\n".join(part for part in (plain or rich) if part).strip()
    internal_ms = int(raw.get("internalDate") or 0)
    received = datetime.fromtimestamp(internal_ms / 1000, tz=UTC).isoformat()
    return ParsedMessage(
        gmail_message_id=str(raw["id"]),
        gmail_thread_id=raw.get("threadId"),
        rfc822_message_id=headers.get("message-id") or None,
        sender_address=sender_address,
        sender_domain=sender_domain,
        subject=headers.get("subject", ""),
        received_at=received,
        body_text=body,
    )


class GmailClient:
    def __init__(self, config: EmailConfig, oauth: OAuthManager | None = None):
        self.config = config
        self.oauth = oauth or OAuthManager(config)

    def _get(self, path: str, params: dict | None = None) -> dict:
        try:
            response = httpx.get(
                f"{GMAIL_BASE}{path}",
                params=params,
                headers={"Authorization": f"Bearer {self.oauth.access_token()}"},
                timeout=self.config.request_timeout_seconds,
            )
            response.raise_for_status()
            return response.json()
        except HistoryCursorExpired:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            raise GmailError("Gmail API request failed", status) from exc

    def profile(self) -> dict:
        return self._get("/profile")

    def message(self, message_id: str) -> ParsedMessage | None:
        try:
            raw = self._get(f"/messages/{message_id}", {"format": "full"})
        except GmailError as exc:
            if exc.status_code == 404:
                raise GmailMessageNotFound("Gmail message is no longer available", 404) from exc
            raise
        # History retains messageAdded records after a user moves a message to
        # Trash. Do not turn deleted or spam mail into a review item.
        if {"TRASH", "SPAM"}.intersection(raw.get("labelIds") or []):
            return None
        return parse_gmail_message(raw, self.config.max_body_bytes)

    def list_message_ids(self, query: str) -> list[str]:
        ids: list[str] = []
        page_token: str | None = None
        while True:
            params = {"q": query, "maxResults": 500}
            if page_token:
                params["pageToken"] = page_token
            data = self._get("/messages", params)
            ids.extend(str(item["id"]) for item in data.get("messages") or [])
            page_token = data.get("nextPageToken")
            if not page_token:
                return ids

    def history_message_ids(self, start_history_id: str) -> tuple[list[str], str]:
        ids: set[str] = set()
        newest_history_id = start_history_id
        page_token: str | None = None
        while True:
            params = {
                "startHistoryId": start_history_id,
                "historyTypes": "messageAdded",
                "maxResults": 500,
            }
            if page_token:
                params["pageToken"] = page_token
            try:
                data = self._get("/history", params)
            except GmailError as exc:
                if exc.status_code == 404:
                    raise HistoryCursorExpired("Gmail History cursor expired", 404) from exc
                raise
            newest_history_id = str(data.get("historyId") or newest_history_id)
            for history in data.get("history") or []:
                for addition in history.get("messagesAdded") or []:
                    message = addition.get("message") or {}
                    if message.get("id"):
                        ids.add(str(message["id"]))
            page_token = data.get("nextPageToken")
            if not page_token:
                return sorted(ids), newest_history_id
