from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, status

from .config import settings


def require_device_auth(
    x_device_id: str = Header(..., alias="X-Device-ID"),
    x_device_token: str = Header(..., alias="X-Device-Token"),
) -> str:
    expected = settings.device_tokens.get(x_device_id)
    if not expected or not secrets.compare_digest(expected, x_device_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid device credentials",
        )
    return x_device_id


def require_dashboard_auth(authorization: str = Header("", alias="Authorization")) -> None:
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
        )
    token = authorization[len(prefix) :]
    if not secrets.compare_digest(settings.dashboard_token, token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid dashboard token",
        )
