"""Settings API routes."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from seeker_os.api.schemas import SettingsResponse, SettingUpdate, MessageResponse
from seeker_os.config import Settings
from seeker_os.database import get_connection

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=SettingsResponse)
def get_settings():
    """Get all configuration (sanitized — no API keys)."""
    settings = Settings()

    filters_data = None
    scoring_data = None
    sources_data = None

    if settings.filters:
        filters_data = settings.filters.model_dump()
        # Remove any sensitive data (filters.yml has no personal data, but be safe)
    if settings.scoring:
        scoring_data = settings.scoring.model_dump()
    if settings.sources:
        sources_data = settings.sources.model_dump()
        # Remove API keys from sources (none currently, but future-proof)
        for src in sources_data.get("sources", []):
            src.pop("api_key", None)

    return SettingsResponse(
        filters=filters_data,
        scoring=scoring_data,
        sources=sources_data,
        profile_loaded=settings.profile is not None,
        queries_count=len(settings.queries.queries) if settings.queries else 0,
    )


@router.get("/{key}", response_model=dict)
def get_setting(key: str):
    """Get a specific setting from the settings table."""
    db = get_connection()
    row = db.execute("SELECT * FROM settings WHERE key = ?", (key,)).fetchone()
    db.close()
    if not row:
        raise HTTPException(status_code=404, detail=f"Setting '{key}' not found")
    return {"key": row["key"], "value": json.loads(row["value"]), "updated_at": row["updated_at"]}


@router.patch("/{key}", response_model=MessageResponse)
def update_setting(key: str, body: SettingUpdate):
    """Update a setting in the settings table."""
    db = get_connection()
    now = datetime.now(timezone.utc).isoformat()
    db.execute(
        "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
        (key, body.value, now),
    )
    db.commit()
    db.close()
    return MessageResponse(message=f"Setting '{key}' updated")
