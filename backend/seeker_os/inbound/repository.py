"""SQLite persistence and lease operations for inbound Gmail sync."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from seeker_os.inbound.models import MatchResult, ParsedMessage


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_sync_row(db, account_key: str) -> None:
    now = utc_now().isoformat()
    db.execute(
        """
        INSERT INTO inbound_sync_state(account_key, updated_at)
        VALUES (?, ?)
        ON CONFLICT(account_key) DO NOTHING
        """,
        (account_key, now),
    )


def acquire_lease(db, account_key: str, owner: str, lease_seconds: int = 300) -> bool:
    """Atomically claim the account cursor across API and CLI processes."""
    now = utc_now()
    expires = now + timedelta(seconds=lease_seconds)
    db.execute("BEGIN IMMEDIATE")
    try:
        ensure_sync_row(db, account_key)
        cursor = db.execute(
            """
            UPDATE inbound_sync_state
            SET lease_owner = ?, lease_expires_at = ?, updated_at = ?
            WHERE account_key = ?
              AND (
                  lease_owner IS NULL OR lease_expires_at IS NULL
                  OR lease_expires_at <= ? OR lease_owner = ?
              )
            """,
            (owner, expires.isoformat(), now.isoformat(), account_key, now.isoformat(), owner),
        )
        db.commit()
        return cursor.rowcount == 1
    except Exception:
        db.rollback()
        raise


def release_lease(db, account_key: str, owner: str) -> None:
    db.execute(
        """
        UPDATE inbound_sync_state
        SET lease_owner = NULL, lease_expires_at = NULL, updated_at = ?
        WHERE account_key = ? AND lease_owner = ?
        """,
        (utc_now().isoformat(), account_key, owner),
    )
    db.commit()


def get_sync_state(db, account_key: str):
    return db.execute(
        "SELECT * FROM inbound_sync_state WHERE account_key = ?", (account_key,)
    ).fetchone()


def finish_poll(db, account_key: str, owner: str, history_id: str) -> None:
    now = utc_now().isoformat()
    db.execute(
        """
        UPDATE inbound_sync_state
        SET history_id = ?, last_success_at = ?, last_error = NULL,
            lease_owner = NULL, lease_expires_at = NULL, updated_at = ?
        WHERE account_key = ? AND lease_owner = ?
        """,
        (history_id, now, now, account_key, owner),
    )
    db.commit()


def fail_poll(db, account_key: str, owner: str, error: str) -> None:
    now = utc_now().isoformat()
    db.execute(
        """
        UPDATE inbound_sync_state
        SET last_error = ?, lease_owner = NULL, lease_expires_at = NULL, updated_at = ?
        WHERE account_key = ? AND lease_owner = ?
        """,
        (error[:1000], now, account_key, owner),
    )
    db.commit()


def insert_message(db, account_key: str, message: ParsedMessage, match: MatchResult) -> bool:
    """Insert one metadata-only review row; duplicate Gmail IDs are idempotent."""
    now = utc_now().isoformat()
    cursor = db.execute(
        """
        INSERT OR IGNORE INTO inbound_messages (
            account_key, gmail_message_id, gmail_thread_id, rfc822_message_id,
            sender_address, sender_domain, subject, received_at,
            suggested_job_id, match_score, match_features, match_candidates,
            matcher_version, state, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            account_key, message.gmail_message_id, message.gmail_thread_id,
            message.rfc822_message_id, message.sender_address, message.sender_domain,
            message.subject, message.received_at, match.suggested_job_id,
            match.score, json.dumps(match.features), json.dumps(match.candidates),
            match.matcher_version, match.state, now, now,
        ),
    )
    db.commit()
    return cursor.rowcount == 1
