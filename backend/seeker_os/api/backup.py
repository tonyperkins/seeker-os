"""Backup / restore API — export and import all non-DB configuration.

Backup produces a zip containing:
  - config/*.yml and config/blacklist.txt (all real config files)
  - .env (API keys / env vars)
  - data/master_resume.* (if present)

Restore accepts the same zip, validates filenames (no path traversal),
and writes files back to their original locations.
"""

from __future__ import annotations

import io
import logging
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from seeker_os.config import CONFIG_DIR, DATA_DIR, PROJECT_ROOT

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/backup", tags=["backup"])

# Files/dirs included in a backup (relative to PROJECT_ROOT).
_BACKUP_CONFIG_GLOBS = ["*.yml", "blacklist.txt"]
_BACKUP_ENV = ".env"
_MASTER_RESUME_PREFIX = "master_resume."

# Allowed restore paths (relative to PROJECT_ROOT) — anything outside is rejected.
_ALLOWED_RESTORE_DIRS = {"config", "data"}


class BackupManifest(BaseModel):
    files: list[str]
    timestamp: str


def _collect_backup_files() -> list[Path]:
    """Gather all non-DB config files that should be included in the backup."""
    files: list[Path] = []

    # Config dir — all .yml and blacklist.txt
    for pattern in _BACKUP_CONFIG_GLOBS:
        files.extend(sorted(CONFIG_DIR.glob(pattern)))

    # .env
    env_path = PROJECT_ROOT / _BACKUP_ENV
    if env_path.exists():
        files.append(env_path)

    # Master resume (data/master_resume.*)
    if DATA_DIR.exists():
        for p in sorted(DATA_DIR.iterdir()):
            if p.is_file() and p.name.startswith(_MASTER_RESUME_PREFIX):
                files.append(p)

    return files


@router.get("")
def download_backup():
    """Download a zip of all non-DB configuration files."""
    files = _collect_backup_files()
    if not files:
        raise HTTPException(status_code=404, detail="No configuration files found to back up")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        manifest = BackupManifest(
            files=[str(f.relative_to(PROJECT_ROOT)) for f in files],
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        zf.writestr("_manifest.json", manifest.model_dump_json(indent=2))

        for f in files:
            arcname = str(f.relative_to(PROJECT_ROOT))
            zf.write(f, arcname)

    buf.seek(0)
    filename = f"seeker-os-backup-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/restore")
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
            _reload_env(target)

    # Invalidate settings cache so restored configs take effect
    from seeker_os.config import invalidate_settings_cache
    invalidate_settings_cache()

    return {
        "message": f"Restored {len(restored)} file(s)",
        "restored": restored,
        "skipped": skipped,
    }


def _reload_env(env_path: Path) -> None:
    """Parse .env and update os.environ with its values."""
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            os.environ[k.strip()] = v.strip()
