"""Authentication and authorization dependencies for administrative API endpoints."""

from __future__ import annotations

import hmac
import os
from typing import Annotated

from fastapi import HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.security.api_key import APIKeyHeader

DEFAULT_ADMIN_TOKEN_ENV_VARS = ("ECU_HOCKEY_ADMIN_TOKEN", "ADMIN_TOKEN")

bearer_scheme = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def resolve_admin_token(request: Request) -> str | None:
    """Resolve configured administrative authentication token from app state or env.

    Args:
        request: Incoming FastAPI HTTP request.

    Returns:
        Configured token string if set, or None.
    """
    state_token = getattr(request.app.state, "admin_token", None)
    if state_token is not None:
        return str(state_token)

    for var in DEFAULT_ADMIN_TOKEN_ENV_VARS:
        env_val = os.environ.get(var)
        if env_val:
            return env_val.strip()

    return None


def _extract_provided_token(
    bearer_creds: HTTPAuthorizationCredentials | None,
    api_key: str | None,
) -> str | None:
    """Extract token string from bearer credentials or API key header."""
    if bearer_creds and bearer_creds.credentials:
        return bearer_creds.credentials.strip()

    if api_key:
        return api_key.strip()

    return None


def verify_admin_token(
    request: Request,
    bearer_creds: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(bearer_scheme),
    ] = None,
    api_key: Annotated[
        str | None,
        Security(api_key_header),
    ] = None,
) -> str:
    """Verify administrator token credentials via Bearer header or X-API-Key.

    Args:
        request: Incoming FastAPI request.
        bearer_creds: HTTPBearer credentials if provided.
        api_key: X-API-Key header value if provided.

    Returns:
        The validated admin token string.

    Raises:
        HTTPException: 401 Unauthorized if token is missing or invalid.
    """
    configured_token = resolve_admin_token(request)
    if not configured_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin authentication is not configured on this server.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    provided_token = _extract_provided_token(bearer_creds, api_key)
    if not provided_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing administrative authentication credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not hmac.compare_digest(provided_token, configured_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid administrative authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return provided_token


__all__ = [
    "DEFAULT_ADMIN_TOKEN_ENV_VARS",
    "resolve_admin_token",
    "verify_admin_token",
]
