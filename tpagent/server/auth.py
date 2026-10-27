"""Single shared bearer token. Accepted as `Authorization: Bearer <t>` or `?token=<t>`
(the query form is needed for WebSocket, <img>/<video> previews and download links)."""
from __future__ import annotations

import secrets

from fastapi import HTTPException, Request, WebSocket, status

from .settings import Settings


def _token_from_header(auth_header: str | None) -> str | None:
    if not auth_header:
        return None
    scheme, _, value = auth_header.partition(" ")
    return value.strip() if scheme.lower() == "bearer" and value.strip() else None


def token_matches(settings: Settings, presented: str | None) -> bool:
    return bool(presented) and secrets.compare_digest(str(presented), settings.token)


def require_token(request: Request) -> None:
    """FastAPI dependency for REST routes."""
    settings: Settings = request.app.state.settings
    presented = _token_from_header(request.headers.get("authorization")) or request.query_params.get("token")
    if not token_matches(settings, presented):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sai hoặc thiếu token")


def websocket_authorized(ws: WebSocket) -> bool:
    settings: Settings = ws.app.state.settings
    presented = ws.query_params.get("token") or _token_from_header(ws.headers.get("authorization"))
    return token_matches(settings, presented)
