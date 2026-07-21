"""Human-reviewed Gmail inbound API.

Deployment note: Seeker OS has no built-in user authentication. Keep this API
bound to localhost or behind the deployment's authenticated reverse proxy.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from urllib.parse import urlsplit
from fastapi.responses import RedirectResponse

from seeker_os.api.schemas import (
    InboundConfirmRequest,
    InboundMessage,
    InboundPollResponse,
    InboundStatus,
    OAuthStartResponse,
)
from seeker_os.config import get_settings
from seeker_os.inbound.oauth import OAuthError
from seeker_os.inbound.service import (
    InboundDisabled,
    InboundNotFound,
    InboundService,
    InvalidDecision,
    SyncLocked,
)

router = APIRouter(prefix="/api/inbound", tags=["inbound"])


def _service() -> InboundService:
    config = get_settings().email
    if config is None:
        raise HTTPException(
            status_code=503,
            detail="Inbound email is not configured; copy config/email.example.yml to config/email.yml",
        )
    return InboundService(config)


def _raise_service_error(exc: Exception) -> None:
    if isinstance(exc, InboundDisabled):
        raise HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, SyncLocked):
        raise HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, InboundNotFound):
        raise HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, InvalidDecision):
        raise HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, OAuthError):
        raise HTTPException(status_code=502, detail=str(exc))
    raise exc


@router.get("/status", response_model=InboundStatus)
def inbound_status():
    return _service().status()


@router.get("/messages", response_model=list[InboundMessage])
def list_inbound_messages(
    state: str | None = Query(None, description="Comma-separated review states"),
    job_id: int | None = None,
):
    return _service().list_messages(state=state, job_id=job_id)


@router.post("/check", response_model=InboundPollResponse)
def check_now():
    try:
        return _service().poll().__dict__
    except Exception as exc:
        _raise_service_error(exc)


@router.post("/messages/{inbound_id}/confirm", response_model=InboundMessage)
def confirm_inbound(inbound_id: int, body: InboundConfirmRequest):
    try:
        return _service().confirm(inbound_id, body.job_id)
    except Exception as exc:
        _raise_service_error(exc)


@router.post("/messages/{inbound_id}/dismiss", response_model=InboundMessage)
def dismiss_inbound(inbound_id: int):
    try:
        return _service().dismiss(inbound_id)
    except Exception as exc:
        _raise_service_error(exc)


@router.post("/oauth/start", response_model=OAuthStartResponse)
def start_oauth(request: Request):
    try:
        # The Next.js proxy supplies its explicit origin header. A production
        # deployment may instead expose the backend directly; browsers send the
        # standard Origin header on this POST, which is still checked against
        # the configured redirect allowlist by OAuthManager.
        origin = request.headers.get("x-seekeros-origin") or request.headers.get("origin")
        if not origin:
            raise OAuthError("OAuth must be started through the Seeker OS frontend")
        return {"authorization_url": _service().authorization_url(origin)}
    except Exception as exc:
        _raise_service_error(exc)


@router.get("/oauth/callback", include_in_schema=False)
def oauth_callback(code: str, state: str):
    service = _service()
    try:
        result = service.oauth_callback(code, state)
    except Exception as exc:
        _raise_service_error(exc)
    origin = urlsplit(result["redirect_uri"])
    return RedirectResponse(
        url=f"{origin.scheme}://{origin.netloc}/inbound?oauth=connected",
        status_code=303,
    )
