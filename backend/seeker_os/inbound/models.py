"""Internal models for the inbound email pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ParsedMessage:
    gmail_message_id: str
    gmail_thread_id: str | None
    rfc822_message_id: str | None
    sender_address: str
    sender_domain: str
    subject: str
    received_at: str
    body_text: str = field(repr=False)


@dataclass(frozen=True)
class MatchResult:
    suggested_job_id: int | None
    score: float
    features: dict
    candidates: list[dict]
    state: str
    matcher_version: str


@dataclass(frozen=True)
class PollResult:
    account_key: str
    messages_seen: int
    messages_inserted: int
    cursor: str
    resynced: bool = False
