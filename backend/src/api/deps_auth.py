"""Shared admin authentication for critical control endpoints."""
from __future__ import annotations

import os
from typing import Optional

from fastapi import Header, HTTPException, status


def admin_required(
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> str:
    """
    Require either ADMIN_TOKEN match or a valid JWT.

    Used for Phase 2C activation, execution mode changes, kill switch writes,
    and other controls that must not be publicly accessible.
    """
    expected = (os.getenv("ADMIN_TOKEN") or "").strip()
    if expected and x_admin_token and x_admin_token.strip() == expected:
        return "admin-token"

    if authorization and authorization.startswith("Bearer "):
        try:
            from src.core.auth import decode_access_token

            token = authorization.replace("Bearer ", "").strip()
            payload = decode_access_token(token)
            if payload and "sub" in payload:
                return f"user:{payload['sub']}"
        except Exception:
            pass

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=(
            "admin auth required: provide X-Admin-Token (matching ADMIN_TOKEN env) "
            "or Authorization: Bearer <jwt>"
        ),
    )
