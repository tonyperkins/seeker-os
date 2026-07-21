import base64
import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from seeker_os.api import inbound as inbound_api
from seeker_os.config import EmailConfig
from seeker_os.database import get_connection, run_migrations
from seeker_os.inbound.gmail import GmailClient, parse_gmail_message
from seeker_os.inbound.matcher import match_message
from seeker_os.inbound.models import ParsedMessage
from seeker_os.inbound.repository import acquire_lease, release_lease
from seeker_os.inbound.service import InboundService


def _config(tmp_path, **overrides):
    values = {
        "enabled": True,
        "dedicated_account_address": "inbound@example.com",
        "primary_account_address": "primary@example.com",
        "oauth": {
            "client_id": "client-id",
            "client_secret": "client-secret",
            "token_path": str(tmp_path / ".gmail_oauth.json"),
        },
    }
    values.update(overrides)
    return EmailConfig(**values)


def _factory(dbfile):
    return lambda: get_connection(dbfile)


def _job(db, *, company, title="Site Reliability Engineer", status="applied", homepage=None):
    now = datetime.now(UTC).isoformat()
    cursor = db.execute(
        """
        INSERT INTO jobs(title, company, company_homepage, url_hash, status, discovered_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (title, company, homepage, f"hash-{company}-{title}", status, now),
    )
    db.commit()
    return cursor.lastrowid


def _message(message_id="gmail-1", *, subject="Application at Acme", body="Acme SRE application"):
    return ParsedMessage(
        gmail_message_id=message_id,
        gmail_thread_id="thread-1",
        rfc822_message_id="<same-id@example.com>",
        sender_address="recruiting@acme.com",
        sender_domain="acme.com",
        subject=subject,
        received_at=(datetime.now(UTC) - timedelta(days=2)).isoformat(),
        body_text=body,
    )


def test_matcher_persists_all_ranked_candidates_and_applies_ambiguity_rule(tmp_path):
    dbfile = tmp_path / "matcher.db"
    run_migrations(dbfile)
    db = get_connection(dbfile)
    try:
        first = _job(db, company="Acme", homepage="https://acme.com")
        second = _job(db, company="Acme Labs", homepage="https://acme.com")
        result = match_message(
            db,
            _message(body="Acme and Acme Labs SRE application"),
            _config(tmp_path).matcher,
        )
    finally:
        db.close()

    assert result.state == "matched"
    assert result.suggested_job_id is None
    assert result.features["ambiguous"] is True
    assert [candidate["job_id"] for candidate in result.candidates] == [first, second]
    assert all(candidate["features"] for candidate in result.candidates)


def test_common_company_name_does_not_match_without_stronger_evidence(tmp_path):
    dbfile = tmp_path / "common.db"
    run_migrations(dbfile)
    db = get_connection(dbfile)
    try:
        _job(db, company="Target", homepage=None)
        config = _config(tmp_path)
        config.matcher.common_company_names = ["target"]
        result = match_message(
            db,
            _message(subject="Your target role", body="Your application is under review"),
            config.matcher,
        )
    finally:
        db.close()

    assert result.state == "unmatched"
    assert result.suggested_job_id is None


def test_mime_parser_prefers_plain_text_and_never_reads_attachments():
    def encode(value):
        return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")

    raw = {
        "id": "m1",
        "threadId": "t1",
        "internalDate": "1760000000000",
        "payload": {
            "headers": [
                {"name": "From", "value": "Recruiter <jobs@example.com>"},
                {"name": "Subject", "value": "Application update"},
                {"name": "Message-ID", "value": "<rfc@example.com>"},
            ],
            "parts": [
                {"mimeType": "text/plain", "filename": "", "body": {"data": encode("plain body")}},
                {"mimeType": "text/html", "filename": "", "body": {"data": encode("<b>html body</b>")}},
                {
                    "mimeType": "text/plain",
                    "filename": "secret.txt",
                    "body": {"attachmentId": "attachment-1", "data": encode("secret")},
                },
            ],
        },
    }

    parsed = parse_gmail_message(raw, 1024)

    assert parsed.body_text == "plain body"
    assert "secret" not in parsed.body_text
    assert parsed.sender_address == "jobs@example.com"
    assert parsed.rfc822_message_id == "<rfc@example.com>"


def test_gmail_client_excludes_messages_currently_in_trash(tmp_path, monkeypatch):
    client = GmailClient(_config(tmp_path))
    monkeypatch.setattr(client, "_get", lambda *_args, **_kwargs: {"labelIds": ["INBOX", "TRASH"]})

    assert client.message("deleted-message") is None


def test_cross_process_lease_blocks_second_owner(tmp_path):
    dbfile = tmp_path / "lease.db"
    run_migrations(dbfile)
    first = get_connection(dbfile)
    second = get_connection(dbfile)
    try:
        assert acquire_lease(first, "account", "owner-1") is True
        assert acquire_lease(second, "account", "owner-2") is False
        release_lease(first, "account", "owner-1")
        assert acquire_lease(second, "account", "owner-2") is True
    finally:
        release_lease(second, "account", "owner-2")
        first.close()
        second.close()


def test_oauth_callback_redirects_to_the_origin_that_started_authorization(monkeypatch):
    class Service:
        def oauth_callback(self, code, state):
            assert (code, state) == ("code", "state")
            return {"redirect_uri": "https://seekeros.perkinslab.com/api/inbound/oauth/callback"}

    monkeypatch.setattr(inbound_api, "_service", Service)

    response = inbound_api.oauth_callback("code", "state")

    assert response.status_code == 303
    assert response.headers["location"] == "https://seekeros.perkinslab.com/inbound?oauth=connected"


class _FakeGmail:
    def __init__(self, messages, fail_on=None):
        self.messages = messages
        self.fail_on = fail_on

    def profile(self):
        return {"historyId": "20"}

    def history_message_ids(self, history_id):
        assert history_id == "10"
        return list(self.messages), "20"

    def list_message_ids(self, query):
        return list(self.messages)

    def message(self, message_id):
        if message_id == self.fail_on:
            raise RuntimeError("transient failure")
        return _message(message_id=message_id)


def test_poll_does_not_advance_cursor_until_all_messages_are_durable(tmp_path):
    dbfile = tmp_path / "poll.db"
    run_migrations(dbfile)
    db = get_connection(dbfile)
    try:
        _job(db, company="Acme", homepage="https://acme.com")
        now = datetime.now(UTC).isoformat()
        db.execute(
            "INSERT INTO inbound_sync_state(account_key, history_id, updated_at) VALUES ('dedicated_gmail', '10', ?)",
            (now,),
        )
        db.commit()
    finally:
        db.close()

    config = _config(tmp_path)
    failing = InboundService(
        config,
        gmail=_FakeGmail(["m1", "m2"], fail_on="m2"),
        connection_factory=_factory(dbfile),
    )
    with pytest.raises(RuntimeError, match="transient"):
        failing.poll()

    db = get_connection(dbfile)
    try:
        assert db.execute("SELECT history_id FROM inbound_sync_state").fetchone()[0] == "10"
        assert db.execute("SELECT COUNT(*) FROM inbound_messages").fetchone()[0] == 1
    finally:
        db.close()

    retry = InboundService(
        config,
        gmail=_FakeGmail(["m1", "m2"]),
        connection_factory=_factory(dbfile),
    )
    result = retry.poll()
    assert result.messages_inserted == 1
    db = get_connection(dbfile)
    try:
        assert db.execute("SELECT history_id FROM inbound_sync_state").fetchone()[0] == "20"
        assert db.execute("SELECT COUNT(*) FROM inbound_messages").fetchone()[0] == 2
    finally:
        db.close()


def test_confirm_snapshots_audit_and_makes_event_relationally_immutable(tmp_path, monkeypatch):
    from seeker_os.api import events_routes
    from seeker_os.api.schemas import EventUpdate
    from seeker_os.events import Actor, EventType, record_event

    dbfile = tmp_path / "confirm.db"
    run_migrations(dbfile)
    config = _config(tmp_path, message_id_equality_verified=True)
    db = get_connection(dbfile)
    try:
        suggested_job_id = _job(db, company="Acme", homepage="https://acme.com")
        message = _message()
        match = match_message(db, message, config.matcher)
        from seeker_os.inbound.repository import insert_message
        assert insert_message(db, config.account_key, message, match)
        inbound_id = db.execute("SELECT id FROM inbound_messages").fetchone()[0]
        reassigned_job_id = _job(db, company="OtherCo", title="Platform Engineer")

        manual_event_id = record_event(
            db, suggested_job_id, EventType.EMAIL_RECEIVED, Actor.CANDIDATE,
            note="Manually logged email", allow_before_discovery=True,
        )
        db.commit()
    finally:
        db.close()

    service = InboundService(config, gmail=_FakeGmail([]), connection_factory=_factory(dbfile))
    confirmed = service.confirm(inbound_id, reassigned_job_id)
    assert confirmed["primary_gmail_link"] is not None
    assert confirmed["suggested_job_id"] == suggested_job_id
    assert confirmed["final_job_id"] == reassigned_job_id

    db = get_connection(dbfile)
    try:
        event = db.execute(
            "SELECT * FROM application_events WHERE id = ?", (confirmed["confirmed_event_id"],)
        ).fetchone()
        metadata = json.loads(event["metadata"])
        assert event["actor"] == "company"
        assert event["event_type"] == "email_received"
        assert event["occurred_at"] == message.received_at
        assert metadata["inbound_message_id"] == inbound_id
        assert metadata["source"] == "gmail_inbound"
        assert metadata["account_key"] == "dedicated_gmail"
        assert metadata["sender"] == "recruiting@acme.com"
        assert metadata["subject"] == "Application at Acme"
        assert metadata["rfc822_message_id"] == "<same-id@example.com>"
        assert metadata["gmail_link_inputs"]["account_address"] == "primary@example.com"
        with pytest.raises(HTTPException) as exc:
            events_routes._get_mutable_event(db, event["id"])
        assert exc.value.status_code == 403
    finally:
        db.close()

    # The read API is the authority the UI receives: same event type, but only
    # the Gmail-confirmed row is immutable by relational provenance.
    monkeypatch.setattr(events_routes, "get_connection", _factory(dbfile))
    events = events_routes.list_events(
        event_type=None, job_id=reassigned_job_id, scope=None,
        manual_only=False, limit=10, offset=0,
    )
    assert len(events) == 1
    assert events[0].is_mutable is False

    suggested_events = events_routes.list_events(
        event_type=None, job_id=suggested_job_id, scope=None,
        manual_only=False, limit=10, offset=0,
    )
    assert len(suggested_events) == 1
    assert suggested_events[0].id == manual_event_id
    assert suggested_events[0].is_mutable is True

    with pytest.raises(HTTPException) as exc:
        events_routes.update_manual_event(confirmed["confirmed_event_id"], EventUpdate(note="tamper"))
    assert exc.value.status_code == 403


def test_confirm_invalid_job_rolls_back_without_creating_an_event(tmp_path):
    dbfile = tmp_path / "confirm-rollback.db"
    run_migrations(dbfile)
    config = _config(tmp_path)
    db = get_connection(dbfile)
    try:
        job_id = _job(db, company="Acme", homepage="https://acme.com")
        message = _message()
        match = match_message(db, message, config.matcher)
        from seeker_os.inbound.repository import insert_message
        assert insert_message(db, config.account_key, message, match)
        inbound_id = db.execute("SELECT id FROM inbound_messages").fetchone()[0]
    finally:
        db.close()

    service = InboundService(config, gmail=_FakeGmail([]), connection_factory=_factory(dbfile))
    with pytest.raises(Exception, match="Job 999999 not found"):
        service.confirm(inbound_id, 999999)

    db = get_connection(dbfile)
    try:
        row = db.execute("SELECT state, confirmed_event_id FROM inbound_messages WHERE id = ?", (inbound_id,)).fetchone()
        assert row["state"] in ("matched", "unmatched")
        assert row["confirmed_event_id"] is None
        assert db.execute("SELECT COUNT(*) FROM application_events WHERE job_id = ?", (job_id,)).fetchone()[0] == 0
    finally:
        db.close()
