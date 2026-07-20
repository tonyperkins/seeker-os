"""Tests for migration user_version desync fix (#134).

After the squash of 30 individual migrations into one, existing DBs with
user_version >= 30 would silently skip all new migrations because
range(30, len(MIGRATIONS)) is empty.  run_migrations() now remaps those
DBs to user_version = 1 (squash applied) so subsequent migrations run.
"""

import sqlite3
from pathlib import Path

import pytest

from seeker_os.database import (
    MIGRATIONS,
    _PRE_SQUASH_HIGH_WATER_MARK,
    _split_sql_statements,
    run_migrations,
)


def _make_pre_squash_db(db_path: Path) -> None:
    """Create a DB that simulates a pre-squash state.

    Applies only migration 0 (the squash schema) and sets user_version
    to the old high-water mark, simulating a DB that ran all 30 original
    migrations but none of the post-squash migrations.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.isolation_level = None
    conn.execute("BEGIN")
    for stmt in _split_sql_statements(MIGRATIONS[0]):
        conn.execute(stmt)
    conn.execute(f"PRAGMA user_version = {_PRE_SQUASH_HIGH_WATER_MARK}")
    conn.execute("COMMIT")
    conn.close()


def _set_user_version(db_path: Path, version: int) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(f"PRAGMA user_version = {version}")
    conn.close()


def _get_user_version(db_path: Path) -> int:
    conn = sqlite3.connect(str(db_path))
    v = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.close()
    return v


def _has_column(db_path: Path, table: str, column: str) -> bool:
    conn = sqlite3.connect(str(db_path))
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    conn.close()
    return column in cols


class TestPreSquashRemap:
    """Pre-squash DBs (user_version > len(MIGRATIONS)) are remapped and migrated."""

    def test_remap_applies_pending_migrations(self, tmp_path):
        """A DB at the old high-water mark gets remapped and receives new migrations."""
        db_path = tmp_path / "test.db"
        _make_pre_squash_db(db_path)

        # preference_rank should NOT exist yet (pre-squash schema)
        assert not _has_column(db_path, "jobs", "preference_rank")

        run_migrations(db_path)

        assert _get_user_version(db_path) == len(MIGRATIONS)
        assert _has_column(db_path, "jobs", "preference_rank")

    def test_remap_from_arbitrary_old_version(self, tmp_path):
        """Any user_version in the pre-squash range gets remapped."""
        db_path = tmp_path / "test.db"
        _make_pre_squash_db(db_path)
        _set_user_version(db_path, _PRE_SQUASH_HIGH_WATER_MARK - 5)

        run_migrations(db_path)

        assert _get_user_version(db_path) == len(MIGRATIONS)

    def test_remap_prints_message(self, tmp_path, capsys):
        """The remap should produce a visible log message."""
        db_path = tmp_path / "test.db"
        _make_pre_squash_db(db_path)

        run_migrations(db_path)

        captured = capsys.readouterr()
        assert "Remapping pre-squash" in captured.out

    def test_idempotent_remap(self, tmp_path):
        """Running run_migrations twice on a remapped DB is a no-op."""
        db_path = tmp_path / "test.db"
        _make_pre_squash_db(db_path)

        run_migrations(db_path)
        assert _get_user_version(db_path) == len(MIGRATIONS)

        # Second run should be a no-op
        run_migrations(db_path)
        assert _get_user_version(db_path) == len(MIGRATIONS)


class TestFutureVersionRejected:
    """DBs with user_version beyond the pre-squash range are rejected."""

    def test_future_version_raises(self, tmp_path):
        """A user_version higher than the pre-squash high-water mark raises."""
        db_path = tmp_path / "test.db"
        _make_pre_squash_db(db_path)
        _set_user_version(db_path, _PRE_SQUASH_HIGH_WATER_MARK + 10)

        with pytest.raises(RuntimeError, match="newer version"):
            run_migrations(db_path)


class TestFreshDbUnaffected:
    """Fresh DBs and current-version DBs are unaffected by the remap logic."""

    def test_fresh_db_migrates_normally(self, tmp_path):
        db_path = tmp_path / "fresh.db"
        run_migrations(db_path)
        assert _get_user_version(db_path) == len(MIGRATIONS)
        assert _has_column(db_path, "jobs", "preference_rank")

    def test_current_version_db_no_remap(self, tmp_path, capsys):
        """A DB already at len(MIGRATIONS) should not trigger remap."""
        db_path = tmp_path / "current.db"
        run_migrations(db_path)
        assert _get_user_version(db_path) == len(MIGRATIONS)

        run_migrations(db_path)
        captured = capsys.readouterr()
        assert "Remapping" not in captured.out
