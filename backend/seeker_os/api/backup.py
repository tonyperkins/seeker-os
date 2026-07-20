"""Backup / restore API — export and import configuration and database.

Config backup produces a zip containing:
  - config/*.yml and config/blacklist.txt (all real config files)
  - .env (API keys / env vars)
  - data/master_resume.* (if present)

DB backup uses SQLite's online backup API for a consistent snapshot.
DB restore uses the same API to safely copy into the live DB.

Restore accepts the same config zip, validates filenames (no path traversal),
and writes files back to their original locations.
"""

from __future__ import annotations

import io
import logging
import os
import sqlite3
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from seeker_os.config import CONFIG_DIR, DATA_DIR, PROJECT_ROOT
from seeker_os.database import (
    MIGRATIONS,
    _PRE_SQUASH_HIGH_WATER_MARK,
    _db_path,
    run_migrations,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/backup", tags=["backup"])

# Maximum upload size for restore endpoints (50 MB).
MAX_UPLOAD_BYTES = 50 * 1024 * 1024

# Files/dirs included in a backup (relative to PROJECT_ROOT).
_BACKUP_CONFIG_GLOBS = ["*.yml", "blacklist.txt"]
_BACKUP_ENV = ".env"
_MASTER_RESUME_PREFIX = "master_resume."

# Allowed restore paths (relative to PROJECT_ROOT) — anything outside is rejected.
_ALLOWED_RESTORE_DIRS = {"config", "data"}

# Pre-restore safety snapshot settings
_PRE_RESTORE_DIR = DATA_DIR / "pre-restore-snapshots"
_PRE_RESTORE_TTL_DAYS = 7
_PRE_RESTORE_PREFIX = "pre-restore-"


class BackupManifest(BaseModel):
    files: list[str]
    timestamp: str


class BackupRestoreResponse(BaseModel):
    message: str
    restored: list[str]
    skipped: list[str]


class DatabaseRestoreResponse(BaseModel):
    message: str


def _collect_backup_files(include_secrets: bool = False) -> list[Path]:
    """Gather all non-DB config files that should be included in the backup.

    When include_secrets is False (default), .env is excluded to prevent
    API keys from leaking via the backup artifact.
    """
    files: list[Path] = []

    # Config dir — all .yml and blacklist.txt
    for pattern in _BACKUP_CONFIG_GLOBS:
        files.extend(sorted(CONFIG_DIR.glob(pattern)))

    # .env — only included when explicitly requested
    if include_secrets:
        env_path = PROJECT_ROOT / _BACKUP_ENV
        if env_path.exists():
            files.append(env_path)

    # Master resume (data/master_resume.*)
    if DATA_DIR.exists():
        for p in sorted(DATA_DIR.iterdir()):
            if p.is_file() and p.name.startswith(_MASTER_RESUME_PREFIX):
                files.append(p)

    return files


@router.get("", response_class=StreamingResponse)
def download_backup(include_secrets: bool = False):
    """Download a zip of all non-DB configuration files.

    By default, .env is excluded to prevent API keys from leaking via the
    backup artifact. Pass include_secrets=true to include .env.
    """
    files = _collect_backup_files(include_secrets=include_secrets)
    if not files:
        raise HTTPException(status_code=404, detail="No configuration files found to back up")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        manifest = BackupManifest(
            files=[str(f.relative_to(PROJECT_ROOT)) for f in files],
            timestamp=datetime.now(UTC).isoformat(),
        )
        zf.writestr("_manifest.json", manifest.model_dump_json(indent=2))

        for f in files:
            arcname = str(f.relative_to(PROJECT_ROOT))
            zf.write(f, arcname)

    buf.seek(0)
    filename = f"seeker-os-backup-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/restore", response_model=BackupRestoreResponse)
async def restore_backup(file: UploadFile = File(...)):
    """Upload a backup zip and restore all config files.

    Validates that:
    - The uploaded file is a valid zip
    - Every entry resolves to an allowed directory (config/ or data/)
    - No path traversal (.. or absolute paths)
    """
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Upload a .zip backup file")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"Upload exceeds maximum size of {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")

    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid zip file")

    restored: list[str] = []
    skipped: list[str] = []

    for info in zf.infolist():
        if info.is_dir():
            continue
        name = info.filename

        # Skip manifest
        if name == "_manifest.json":
            continue

        # Security: reject path traversal and absolute paths
        if name.startswith("/") or ".." in Path(name).parts:
            skipped.append(f"{name} (rejected: path traversal)")
            continue

        target = PROJECT_ROOT / name

        # Security: must land in an allowed directory
        try:
            rel = target.relative_to(PROJECT_ROOT)
        except ValueError:
            skipped.append(f"{name} (rejected: outside project root)")
            continue

        top_dir = rel.parts[0] if rel.parts else ""
        if top_dir not in _ALLOWED_RESTORE_DIRS and name != _BACKUP_ENV:
            skipped.append(f"{name} (rejected: not in allowed directory)")
            continue

        # .env is allowed at project root
        if name == _BACKUP_ENV:
            target = PROJECT_ROOT / _BACKUP_ENV
        else:
            target = PROJECT_ROOT / rel

        # Ensure parent directory exists
        target.parent.mkdir(parents=True, exist_ok=True)

        content = zf.read(info)
        target.write_bytes(content)
        restored.append(name)

        # If .env was restored, update os.environ so keys take effect
        if name == _BACKUP_ENV:
            _reload_env_after_restore(target)

    # Invalidate settings cache so restored configs take effect
    from seeker_os.config import invalidate_settings_cache
    invalidate_settings_cache()

    # Re-sync queries from restored queries.yml into DB
    from seeker_os.api.app import _sync_queries_from_yaml
    _sync_queries_from_yaml()

    return {
        "message": f"Restored {len(restored)} file(s)",
        "restored": restored,
        "skipped": skipped,
    }


def _reload_env_after_restore(env_path: Path) -> None:
    """Reload .env into os.environ after a restore, using python-dotenv for
    correct parsing of quotes, export prefixes, and multiline values."""
    if not env_path.exists():
        return
    from dotenv import load_dotenv
    load_dotenv(env_path, override=True)


# ---------------------------------------------------------------------------
# Database backup / restore — uses SQLite Online Backup API (safe under load)
# ---------------------------------------------------------------------------

def _create_pre_restore_snapshot() -> Path | None:
    """Snapshot the current DB before a destructive restore.

    Uses the SQLite Online Backup API for a consistent copy. The snapshot
    is stored in data/pre-restore-snapshots/ with a timestamped name.
    Returns the snapshot path, or None if the DB doesn't exist yet.
    """
    if not _db_path().exists():
        return None

    _PRE_RESTORE_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    snapshot_path = _PRE_RESTORE_DIR / f"{_PRE_RESTORE_PREFIX}{ts}.db"

    source = sqlite3.connect(str(_db_path()))
    try:
        dest = sqlite3.connect(str(snapshot_path))
        try:
            source.backup(dest)
        finally:
            dest.close()
    finally:
        source.close()

    logger.info("Pre-restore snapshot saved to %s", snapshot_path)
    return snapshot_path


def _cleanup_old_snapshots() -> None:
    """Delete pre-restore snapshots older than _PRE_RESTORE_TTL_DAYS."""
    if not _PRE_RESTORE_DIR.exists():
        return

    cutoff = time.time() - (_PRE_RESTORE_TTL_DAYS * 86400)
    for p in _PRE_RESTORE_DIR.iterdir():
        if p.is_file() and p.name.startswith(_PRE_RESTORE_PREFIX) and p.suffix == ".db":
            if p.stat().st_mtime < cutoff:
                p.unlink()
                logger.info("Deleted expired pre-restore snapshot %s", p.name)

@router.get("/db", response_class=StreamingResponse)
def download_db_backup():
    """Download a consistent snapshot of the SQLite database.

    Uses sqlite3.Connection.backup() (the SQLite Online Backup API) which
    produces a consistent copy even while the database is in active use.
    """
    if not _db_path().exists():
        raise HTTPException(status_code=404, detail="Database file not found")

    buf = io.BytesIO()
    # Create an in-memory destination DB and copy from the live DB into it
    dest = sqlite3.connect(":memory:")
    try:
        source = sqlite3.connect(str(_db_path()))
        try:
            source.backup(dest)
        finally:
            source.close()
        # Serialize the in-memory DB to bytes
        buf.write(dest.serialize())
    finally:
        dest.close()

    buf.seek(0)
    filename = f"seeker-os-db-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.db"
    return StreamingResponse(
        buf,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/db/restore", response_model=DatabaseRestoreResponse)
async def restore_db_backup(file: UploadFile = File(...)):
    """Upload a .db file and restore it into the live database.

    A pre-restore snapshot of the current DB is saved to
    data/pre-restore-snapshots/ before overwriting. Snapshots older
    than 7 days are cleaned up automatically.

    Uses SQLite's Online Backup API to safely copy the uploaded DB into
    the live seeker.db — no need to stop the server.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"Upload exceeds maximum size of {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")

    # Write uploaded bytes to a temp file
    tmp_path = _db_path().parent / f"_restore_tmp_{os.getpid()}.db"
    snapshot_path = None  # bound below; init so error paths can reference it safely
    try:
        tmp_path.write_bytes(raw)

        # Validate it's a real SQLite database
        try:
            test_conn = sqlite3.connect(str(tmp_path))
            test_conn.execute("SELECT 1")
            test_conn.close()
        except sqlite3.DatabaseError:
            raise HTTPException(status_code=400, detail="File is not a valid SQLite database")

        # Validate user_version is not from a future/incompatible schema
        try:
            ver_conn = sqlite3.connect(str(tmp_path))
            db_version = ver_conn.execute("PRAGMA user_version").fetchone()[0]
            ver_conn.close()
        except sqlite3.DatabaseError:
            raise HTTPException(status_code=400, detail="Could not read database version")
        if db_version > len(MIGRATIONS) and db_version > _PRE_SQUASH_HIGH_WATER_MARK:
            raise HTTPException(
                status_code=400,
                detail=f"Database version {db_version} is newer than this app supports (max {len(MIGRATIONS)}). Update Seeker OS before restoring.",
            )

        # Safety: snapshot the current DB before overwriting
        snapshot_path = _create_pre_restore_snapshot()
        _cleanup_old_snapshots()

        # Use the Online Backup API to copy from the temp DB into the live DB.
        # This is safe even while the server has open connections.
        source = sqlite3.connect(str(tmp_path))
        try:
            dest = sqlite3.connect(str(_db_path()))
            try:
                source.backup(dest)
            finally:
                dest.close()
        finally:
            source.close()

        logger.info("Database restored from uploaded file (%d bytes)", len(raw))

        # Bring an older restored DB up to the current schema immediately, rather
        # than relying on the next get_connection() to lazily migrate it.
        if db_version != len(MIGRATIONS):
            run_migrations(_db_path())
            logger.info(
                "Restored DB migrated from version %d to %d", db_version, len(MIGRATIONS)
            )
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    snapshot_msg = ""
    if snapshot_path:
        snapshot_msg = f" A pre-restore snapshot was saved to {snapshot_path.name}."

    return {"message": f"Database restored successfully.{snapshot_msg}"}
