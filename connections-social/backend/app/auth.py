"""API key authentication dependency for protected routes."""

import logging

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.config import API_KEY

logger = logging.getLogger(__name__)

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(api_key: str | None = Security(_api_key_header)) -> None:
    """Validate X-API-Key header on protected routes.

    When API_KEY env var is unset (empty string), auth is disabled — safe for
    local development.  In production, always inject API_KEY via a K8s Secret
    (never hard-code or commit the key value).

    Interview note: this is a FastAPI dependency injected at the router level
    in main.py — all routes under /admin and /ingest inherit it automatically
    without touching individual route handlers.
    """
    if not API_KEY:
        # Dev mode: auth disabled so the app works out-of-the-box locally
        return

    if api_key != API_KEY:
        logger.warning("Rejected request: invalid or missing X-API-Key")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key. Provide a valid X-API-Key header.",
        )
