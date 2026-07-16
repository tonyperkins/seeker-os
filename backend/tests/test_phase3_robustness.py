"""Phase 3 robustness regression tests.

Covers:
  * §3.2  LLM dossier JSON parsing tolerates minor malformation (bounded repair)
  * §3.3  Migrations are transactional — a failure rolls back, no partial apply
  * §3.4  HTML→text preserves block structure (lists/headings as separate lines)
  * §3.5  Unknown event types are logged (visible), not swallowed as a UserWarning

See ai-audit/REMEDIATION_PLAN_2026-07-02.md, Phase 3.
"""

import json
import logging
import sqlite3

import pytest


# --------------------------------------------------------------------------
# §3.2 — dossier JSON parse with bounded repair
# --------------------------------------------------------------------------

class TestDossierJsonParse:
    def _load(self, text):
        from seeker_os.llm.json_utils import extract_json_text
        return json.loads(extract_json_text(text))

    def test_clean_json(self):
        assert self._load('{"a": 1}') == {"a": 1}

    def test_repairs_prefix_and_suffix_noise(self):
        """A lead-in sentence / trailing note around the object is trimmed."""
        text = 'Sure! Here is the dossier:\n{"company": "X", "gaps": []}\nHope this helps.'
        assert self._load(text) == {"company": "X", "gaps": []}

    def test_unrepairable_raises_json_decode_error(self):
        with pytest.raises(json.JSONDecodeError):
            self._load("this is not json at all")

    def test_truncated_object_raises(self):
        # A cut-off object can't be repaired by brace-trimming → still raises.
        with pytest.raises(json.JSONDecodeError):
            self._load('{"company": "X", "funding": {')


# --------------------------------------------------------------------------
# §3.3 — transactional migrations
# --------------------------------------------------------------------------

class TestTransactionalMigrations:
    def test_failed_migration_rolls_back(self, tmp_path, monkeypatch):
        """A mid-migration failure leaves no partial columns and doesn't bump version."""
        import seeker_os.database as db

        dbfile = tmp_path / "rollback.db"
        good = "CREATE TABLE t (id INTEGER PRIMARY KEY);"
        # Second ADD COLUMN duplicates the first → fails mid-migration.
        bad = "ALTER TABLE t ADD COLUMN a TEXT; ALTER TABLE t ADD COLUMN a TEXT;"
        monkeypatch.setattr(db, "MIGRATIONS", [good, bad])

        with pytest.raises(sqlite3.OperationalError):
            db.run_migrations(dbfile)

        conn = sqlite3.connect(str(dbfile))
        try:
            ver = conn.execute("PRAGMA user_version").fetchone()[0]
            cols = [r[1] for r in conn.execute("PRAGMA table_info(t)").fetchall()]
        finally:
            conn.close()

        assert ver == 1, "only the first (good) migration should have committed"
        assert "a" not in cols, "partial ADD COLUMN must be rolled back"

    def test_real_migrations_apply_to_fresh_db(self, tmp_path):
        """All real migrations run cleanly through the new statement splitter.

        Guards against a migration string whose split produces a comment-only or
        otherwise unexecutable chunk (the existing test DB is already at head, so
        the real migrations never re-run there).
        """
        import seeker_os.database as db

        dbfile = tmp_path / "fresh.db"
        db.run_migrations(dbfile)

        conn = sqlite3.connect(str(dbfile))
        try:
            ver = conn.execute("PRAGMA user_version").fetchone()[0]
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            conn.close()

        assert ver == len(db.MIGRATIONS)
        assert {"jobs", "company_research", "pipeline_runs", "resumes"} <= tables

    def test_clean_migrations_apply_and_bump_version(self, tmp_path, monkeypatch):
        import seeker_os.database as db

        dbfile = tmp_path / "ok.db"
        m1 = "CREATE TABLE t (id INTEGER PRIMARY KEY);"
        m2 = "ALTER TABLE t ADD COLUMN a TEXT; ALTER TABLE t ADD COLUMN b TEXT;"
        monkeypatch.setattr(db, "MIGRATIONS", [m1, m2])

        db.run_migrations(dbfile)

        conn = sqlite3.connect(str(dbfile))
        try:
            ver = conn.execute("PRAGMA user_version").fetchone()[0]
            cols = {r[1] for r in conn.execute("PRAGMA table_info(t)").fetchall()}
        finally:
            conn.close()

        assert ver == 2
        assert {"a", "b"} <= cols


# --------------------------------------------------------------------------
# §3.4 — structure-preserving HTML→text
# --------------------------------------------------------------------------

class TestStripHtml:
    def _strip(self, html):
        from seeker_os.discovery.ats_fetch import _strip_html
        return _strip_html(html)

    def test_list_items_become_separate_bulleted_lines(self):
        out = self._strip("<ul><li>Python</li><li>Go</li></ul>")
        lines = out.splitlines()
        assert "- Python" in lines
        assert "- Go" in lines

    def test_headings_and_paragraphs_break(self):
        out = self._strip("<h2>Requirements</h2><p>5 years</p><p>Remote</p>")
        assert out.splitlines() == ["Requirements", "5 years", "Remote"]

    def test_br_becomes_newline(self):
        assert self._strip("a<br>b") == "a\nb"

    def test_script_and_style_removed(self):
        out = self._strip("<style>.x{}</style><p>Keep</p><script>evil()</script>")
        assert "evil" not in out and ".x" not in out
        assert "Keep" in out

    def test_entities_decoded(self):
        assert self._strip("<p>R&amp;D&nbsp;team</p>").startswith("R&D")

    def test_empty_input(self):
        assert self._strip("") == ""


# --------------------------------------------------------------------------
# §3.5 — unknown event types are logged, not a swallowed UserWarning
# --------------------------------------------------------------------------

class TestUnknownEventLogged:
    def test_record_event_logs_warning_for_unknown_type(self, caplog):
        from seeker_os.database import get_connection, run_migrations
        from seeker_os.events import record_event, Actor

        run_migrations()
        db = get_connection()
        try:
            cur = db.execute(
                "INSERT INTO jobs (title, company, url_hash, status, discovered_at) "
                "VALUES ('t', 'Phase3EvtCo', 'phase3-evt-unknown', 'discovered', "
                "'2026-07-02T00:00:00+00:00')"
            )
            job_id = cur.lastrowid
            db.commit()

            with caplog.at_level(logging.WARNING, logger="seeker_os.events"):
                record_event(db, job_id, "totally_unknown_type", Actor.SYSTEM)
            db.commit()

            messages = [r.getMessage() for r in caplog.records]
            assert any(
                "Unknown event_type" in m and "totally_unknown_type" in m for m in messages
            ), f"expected an Unknown event_type warning, got {messages}"
        finally:
            db.execute("DELETE FROM application_events WHERE job_id = ?", (job_id,))
            db.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            db.commit()
            db.close()
