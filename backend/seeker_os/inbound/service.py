"""Use-case layer for polling, review decisions, and confirmation."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from seeker_os.config import EmailConfig
from seeker_os.database import get_connection, json_decode
from seeker_os.events import Actor, EventType, record_event
from seeker_os.inbound.gmail import GmailClient, GmailMessageNotFound, HistoryCursorExpired
from seeker_os.inbound.links import gmail_link_inputs, primary_gmail_link
from seeker_os.inbound.matcher import match_message
from seeker_os.inbound.models import PollResult
from seeker_os.inbound.oauth import OAuthManager
from seeker_os.inbound.repository import (
    acquire_lease,
    ensure_sync_row,
    fail_poll,
    finish_poll,
    get_sync_state,
    insert_message,
    release_lease,
)

logger = logging.getLogger(__name__)


class InboundError(RuntimeError):
    pass


class InboundDisabled(InboundError):
    pass


class SyncLocked(InboundError):
    pass


class InboundNotFound(InboundError):
    pass


class InvalidDecision(InboundError):
    pass


def _row_to_item(row, config: EmailConfig) -> dict:
    keys = set(row.keys())
    return {
        "id": row["id"],
        "account_key": row["account_key"],
        "gmail_message_id": row["gmail_message_id"],
        "gmail_thread_id": row["gmail_thread_id"],
        "rfc822_message_id": row["rfc822_message_id"],
        "sender_address": row["sender_address"],
        "sender_domain": row["sender_domain"],
        "subject": row["subject"],
        "received_at": row["received_at"],
        "suggested_job_id": row["suggested_job_id"],
        "suggested_job_title": row["suggested_job_title"] if "suggested_job_title" in keys else None,
        "suggested_job_company": row["suggested_job_company"] if "suggested_job_company" in keys else None,
        "final_job_id": row["final_job_id"],
        "match_score": row["match_score"],
        "match_features": json_decode(row["match_features"]) or {},
        "match_candidates": json_decode(row["match_candidates"]) or [],
        "matcher_version": row["matcher_version"],
        "state": row["state"],
        "decision": row["decision"],
        "decided_at": row["decided_at"],
        "confirmed_event_id": row["confirmed_event_id"],
        "primary_gmail_link": primary_gmail_link(config, row["rfc822_message_id"]),
    }


class InboundService:
    def __init__(
        self,
        config: EmailConfig,
        *,
        gmail: GmailClient | None = None,
        connection_factory=get_connection,
    ):
        self.config = config
        self.oauth = OAuthManager(config)
        self.gmail = gmail or GmailClient(config, self.oauth)
        self.connection_factory = connection_factory

    def _require_enabled(self) -> None:
        if not self.config.enabled:
            raise InboundDisabled("Inbound email is disabled in config/email.yml")

    def oauth_status(self) -> dict:
        return self.oauth.status()

    def authorization_url(self, origin: str) -> str:
        self._require_enabled()
        return self.oauth.authorization_url(origin)

    def oauth_callback(self, code: str, state: str) -> dict:
        self._require_enabled()
        result = self.oauth.exchange_callback(code, state)
        db = self.connection_factory()
        try:
            ensure_sync_row(db, self.config.account_key)
            db.commit()
        finally:
            db.close()
        return result

    def poll(self) -> PollResult:
        self._require_enabled()
        owner = str(uuid.uuid4())
        db = self.connection_factory()
        if not acquire_lease(db, self.config.account_key, owner):
            db.close()
            raise SyncLocked("Another inbound sync is already running")

        inserted = 0
        seen = 0
        resynced = False
        try:
            state = get_sync_state(db, self.config.account_key)
            history_id = state["history_id"] if state else None
            if not history_id:
                profile = self.gmail.profile()
                cursor = str(profile["historyId"])
                message_ids = []
                if self.config.initial_backfill_days:
                    message_ids = self.gmail.list_message_ids(
                        f"newer_than:{self.config.initial_backfill_days}d"
                    )
            else:
                try:
                    message_ids, cursor = self.gmail.history_message_ids(history_id)
                except HistoryCursorExpired:
                    # Bounded recovery only. The old cursor remains durable until
                    # all discovered messages below are processed successfully.
                    resynced = True
                    profile = self.gmail.profile()
                    cursor = str(profile["historyId"])
                    message_ids = self.gmail.list_message_ids(
                        f"newer_than:{self.config.history_resync_lookback_days}d"
                    )

            for message_id in dict.fromkeys(message_ids):
                try:
                    message = self.gmail.message(message_id)
                except GmailMessageNotFound:
                    logger.info("inbound_message_unavailable account=%s", self.config.account_key)
                    continue
                match = match_message(db, message, self.config.matcher)
                seen += 1
                inserted += int(insert_message(db, self.config.account_key, message, match))

            finish_poll(db, self.config.account_key, owner, cursor)
            return PollResult(
                account_key=self.config.account_key,
                messages_seen=seen,
                messages_inserted=inserted,
                cursor=cursor,
                resynced=resynced,
            )
        except Exception as exc:
            logger.warning("inbound_poll_failed account=%s type=%s", self.config.account_key, type(exc).__name__)
            fail_poll(db, self.config.account_key, owner, str(exc))
            raise
        finally:
            # Harmless if finish_poll/fail_poll already released it. This also
            # covers a failure before the error state could be persisted.
            try:
                release_lease(db, self.config.account_key, owner)
            finally:
                db.close()

    def status(self) -> dict:
        db = self.connection_factory()
        try:
            ensure_sync_row(db, self.config.account_key)
            db.commit()
            state = get_sync_state(db, self.config.account_key)
            pending = db.execute(
                "SELECT COUNT(*) FROM inbound_messages WHERE state IN ('matched', 'unmatched')"
            ).fetchone()[0]
            return {
                "enabled": self.config.enabled,
                "account_key": self.config.account_key,
                "dedicated_account_address": self.config.dedicated_account_address,
                "primary_account_address": self.config.primary_account_address,
                "message_id_equality_verified": self.config.message_id_equality_verified,
                "oauth": self.oauth.status(),
                "history_id": state["history_id"],
                "last_success_at": state["last_success_at"],
                "last_error": state["last_error"],
                "sync_locked": bool(state["lease_owner"]),
                "pending_count": pending,
            }
        finally:
            db.close()

    def list_messages(self, state: str | None = None, job_id: int | None = None) -> list[dict]:
        where: list[str] = []
        params: list = []
        if state:
            states = [part.strip() for part in state.split(",") if part.strip()]
            where.append(f"i.state IN ({','.join('?' * len(states))})")
            params.extend(states)
        if job_id is not None:
            where.append(
                """(
                    i.suggested_job_id = ? OR i.final_job_id = ? OR EXISTS (
                        SELECT 1 FROM json_each(i.match_candidates) candidate
                        WHERE json_extract(candidate.value, '$.job_id') = ?
                    )
                )"""
            )
            params.extend([job_id, job_id, job_id])
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        db = self.connection_factory()
        try:
            rows = db.execute(
                f"""
                SELECT i.*, j.title AS suggested_job_title,
                       j.company AS suggested_job_company
                FROM inbound_messages i
                LEFT JOIN jobs j ON j.id = i.suggested_job_id
                {clause}
                ORDER BY i.received_at DESC, i.id DESC
                """,
                params,
            ).fetchall()
            return [_row_to_item(row, self.config) for row in rows]
        finally:
            db.close()

    def dismiss(self, inbound_id: int) -> dict:
        db = self.connection_factory()
        try:
            now = datetime.now(UTC).isoformat()
            cursor = db.execute(
                """
                UPDATE inbound_messages
                SET state = 'dismissed', decision = 'dismissed', decided_at = ?, updated_at = ?
                WHERE id = ? AND state IN ('matched', 'unmatched')
                """,
                (now, now, inbound_id),
            )
            if cursor.rowcount != 1:
                row = db.execute("SELECT state FROM inbound_messages WHERE id = ?", (inbound_id,)).fetchone()
                if not row:
                    raise InboundNotFound(f"Inbound message {inbound_id} not found")
                raise InvalidDecision(f"Inbound message is already {row['state']}")
            db.commit()
            row = db.execute("SELECT * FROM inbound_messages WHERE id = ?", (inbound_id,)).fetchone()
            return _row_to_item(row, self.config)
        finally:
            db.close()

    def confirm(self, inbound_id: int, job_id: int) -> dict:
        """Atomically create an immutable company-authored email event."""
        db = self.connection_factory()
        try:
            db.execute("BEGIN IMMEDIATE")
            inbound = db.execute(
                "SELECT * FROM inbound_messages WHERE id = ?", (inbound_id,)
            ).fetchone()
            if not inbound:
                raise InboundNotFound(f"Inbound message {inbound_id} not found")
            if inbound["state"] not in ("matched", "unmatched"):
                raise InvalidDecision(f"Inbound message is already {inbound['state']}")
            job = db.execute("SELECT id FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not job:
                raise InboundNotFound(f"Job {job_id} not found")

            metadata = {
                "source": "gmail_inbound",
                "inbound_message_id": inbound_id,
                "account_key": inbound["account_key"],
                "sender": inbound["sender_address"],
                "subject": inbound["subject"],
                "rfc822_message_id": inbound["rfc822_message_id"],
                "gmail_message_id": inbound["gmail_message_id"],
                "gmail_thread_id": inbound["gmail_thread_id"],
                "gmail_link_inputs": gmail_link_inputs(
                    self.config, inbound["rfc822_message_id"]
                ),
            }
            event_id = record_event(
                db,
                job_id,
                EventType.EMAIL_RECEIVED,
                Actor.COMPANY,
                metadata=metadata,
                occurred_at=inbound["received_at"],
                note=inbound["subject"] or None,
                allow_before_discovery=True,
            )
            now = datetime.now(UTC).isoformat()
            db.execute(
                """
                UPDATE inbound_messages
                SET state = 'confirmed', decision = 'confirmed', final_job_id = ?,
                    confirmed_event_id = ?, decided_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (job_id, event_id, now, now, inbound_id),
            )
            db.commit()
            row = db.execute("SELECT * FROM inbound_messages WHERE id = ?", (inbound_id,)).fetchone()
            return _row_to_item(row, self.config)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
