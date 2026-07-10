"""Settings API routes."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException

from seeker_os.api.schemas import MessageResponse, SettingsResponse, SettingUpdate, SkipReasonOption
from seeker_os.config import get_settings as get_cached_settings
from seeker_os.database import get_connection

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=SettingsResponse)
def get_settings():
    """Get all configuration (sanitized — no API keys)."""
    settings = get_cached_settings()

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

    # Check if profile has real (non-placeholder) data
    profile_configured = False
    if settings.profile and settings.profile.user:
        name = settings.profile.user.name or ""
        email = settings.profile.user.email or ""
        # Placeholder values from the example template
        is_placeholder = (
            name in ("", "Your Name")
            or email in ("", "you@example.com")
        )
        profile_configured = not is_placeholder

    # Skip reasons from config
    skip_reasons = []
    if settings.skip_reasons and settings.skip_reasons.skip_reasons:
        skip_reasons = [
            SkipReasonOption(
                key=r.key, label=r.label, hint=r.hint, free_text=r.free_text,
            )
            for r in settings.skip_reasons.skip_reasons
        ]

    return SettingsResponse(
        filters=filters_data,
        scoring=scoring_data,
        sources=sources_data,
        profile_loaded=settings.profile is not None,
        profile_configured=profile_configured,
        queries_count=len(settings.queries.queries) if settings.queries else 0,
        skip_reasons=skip_reasons,
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
    now = datetime.now(UTC).isoformat()
    db.execute(
        "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
        (key, body.value, now),
    )
    db.commit()
    db.close()
    return MessageResponse(message=f"Setting '{key}' updated")


@router.post("/reload", response_model=MessageResponse)
def reload_config():
    """Reload all configuration from YAML files without restart.

    Invalidates the settings cache so the next cached read reloads all
    YAML files from disk. Also syncs queries from queries.yml into the
    search_queries table (inserts new, updates existing, deletes stale).
    """
    from seeker_os.config import invalidate_settings_cache
    invalidate_settings_cache()

    # Re-sync queries from YAML to DB
    from seeker_os.api.app import _sync_queries_from_yaml
    _sync_queries_from_yaml()

    return MessageResponse(message="Configuration reloaded from disk")
