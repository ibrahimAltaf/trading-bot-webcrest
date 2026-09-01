"""
Admin runtime control endpoints (Phase 2A).

Phase 2A.1 — Binance key rotation from the frontend WITHOUT a service restart.

Authentication
--------------
Two paths are accepted; either is sufficient:

1. `X-Admin-Token: <ADMIN_TOKEN>` header matching the `ADMIN_TOKEN` env var.
2. A valid `Authorization: Bearer <jwt>` (any logged-in user).

If neither `ADMIN_TOKEN` is configured nor a JWT is supplied, the endpoints
return **401**. The admin token path is provided for the frontend to drive key
rotation before per-user RBAC is fully in place; it is **never** logged.

Endpoints
---------
* `GET    /admin/binance-keys`              — masked overlay + env snapshot
* `PUT    /admin/binance-keys`              — save runtime overlay (key/secret/testnet)
* `POST   /admin/binance-keys/verify`       — try a signed `account()` call now
* `DELETE /admin/binance-keys/override`     — remove overlay, fall back to .env

All write endpoints update the `app_settings` table; the next `BinanceSpotClient()`
instantiation (scheduler tick / API call) will pick up the new values.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field

from src.exchange.runtime_keys import (
    clear_overlay,
    get_overlay_snapshot,
    resolve_runtime_keys,
    set_overlay,
)


router = APIRouter(prefix="/admin", tags=["admin"])


# ----------------------------- auth ------------------------------------------


def _admin_required(
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> str:
    """Require either ADMIN_TOKEN match or a valid JWT. Returns the principal id."""
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


# ----------------------------- models ----------------------------------------


class BinanceKeysIn(BaseModel):
    api_key: Optional[str] = Field(
        default=None, max_length=512, description="Set to non-empty string to update; null leaves unchanged"
    )
    api_secret: Optional[str] = Field(
        default=None, max_length=512, description="Set to non-empty string to update; null leaves unchanged"
    )
    testnet: Optional[bool] = Field(
        default=None,
        description="true → testnet.binance.vision; false → api.binance.com (REAL MONEY)",
    )


class BinanceKeysVerifyIn(BaseModel):
    api_key: Optional[str] = Field(default=None, max_length=512)
    api_secret: Optional[str] = Field(default=None, max_length=512)
    testnet: Optional[bool] = Field(default=None)


# ----------------------------- helpers ---------------------------------------


def _try_signed_account_call(api_key: str, api_secret: str, testnet: bool) -> Dict[str, Any]:
    """Make a real signed Binance `GET /api/v3/account` with the given credentials."""
    import hmac
    import time
    from hashlib import sha256
    from urllib.parse import urlencode

    import requests

    base = (
        os.getenv("BINANCE_SPOT_TESTNET_URL", "https://testnet.binance.vision")
        if testnet
        else os.getenv("BINANCE_SPOT_MAINNET_URL", "https://api.binance.com")
    ).rstrip("/")

    # Sync server time to avoid -1021.
    try:
        st = requests.get(f"{base}/api/v3/time", timeout=10).json()
        offset_ms = int(st["serverTime"]) - int(time.time() * 1000)
    except Exception:
        offset_ms = 0

    params: Dict[str, Any] = {
        "timestamp": int(time.time() * 1000) + offset_ms,
        "recvWindow": 60000,
    }
    query = urlencode(params, doseq=True)
    sig = hmac.new(
        api_secret.encode("utf-8"), query.encode("utf-8"), sha256
    ).hexdigest()
    params["signature"] = sig

    try:
        r = requests.get(
            f"{base}/api/v3/account",
            params=params,
            headers={"X-MBX-APIKEY": api_key},
            timeout=15,
        )
    except requests.RequestException as exc:
        return {
            "ok": False,
            "stage": "network",
            "error": str(exc),
            "base_url": base,
        }

    if r.status_code != 200:
        try:
            err_body = r.json()
        except Exception:
            err_body = {"raw": r.text[:500]}
        return {
            "ok": False,
            "stage": "auth_or_permission",
            "status_code": r.status_code,
            "error": err_body,
            "base_url": base,
        }

    body = r.json()
    nonzero = [
        {"asset": b.get("asset"), "free": b.get("free"), "locked": b.get("locked")}
        for b in body.get("balances", [])
        if float(b.get("free", 0) or 0) > 0 or float(b.get("locked", 0) or 0) > 0
    ]
    return {
        "ok": True,
        "base_url": base,
        "testnet": testnet,
        "account_type": body.get("accountType"),
        "can_trade": bool(body.get("canTrade")),
        "can_withdraw": bool(body.get("canWithdraw")),
        "can_deposit": bool(body.get("canDeposit")),
        "balances_nonzero": nonzero,
    }


# ----------------------------- routes ----------------------------------------


@router.get("/binance-keys", summary="Masked overlay + env snapshot for current Binance keys")
def binance_keys_get(
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> Dict[str, Any]:
    """Read-only snapshot. Never returns the actual secret."""
    principal = _admin_required(x_admin_token, authorization)
    snap = get_overlay_snapshot()
    snap["_principal"] = principal
    return {"ok": True, **snap}


@router.put(
    "/binance-keys",
    summary="Save runtime overlay for Binance keys / testnet flag",
)
def binance_keys_put(
    body: BinanceKeysIn,
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> Dict[str, Any]:
    principal = _admin_required(x_admin_token, authorization)
    if (
        body.api_key is None
        and body.api_secret is None
        and body.testnet is None
    ):
        raise HTTPException(
            status_code=400,
            detail="provide at least one of api_key, api_secret, testnet",
        )

    snap = set_overlay(
        api_key=body.api_key,
        api_secret=body.api_secret,
        testnet=body.testnet,
        updated_by=principal,
    )
    return {"ok": True, **snap}


@router.post(
    "/binance-keys/verify",
    summary="Test the saved (or supplied) keys against Binance — no DB writes",
)
def binance_keys_verify(
    body: BinanceKeysVerifyIn,
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> Dict[str, Any]:
    _admin_required(x_admin_token, authorization)
    rk = resolve_runtime_keys()
    api_key = (body.api_key or rk.api_key or "").strip()
    api_secret = (body.api_secret or rk.api_secret or "").strip()
    testnet = body.testnet if body.testnet is not None else rk.testnet

    if not api_key or not api_secret:
        return {
            "ok": False,
            "stage": "missing_keys",
            "error": "api_key or api_secret is empty",
        }
    return _try_signed_account_call(api_key, api_secret, bool(testnet))


@router.delete(
    "/binance-keys/override",
    summary="Clear runtime overlay (fall back to .env)",
)
def binance_keys_clear(
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> Dict[str, Any]:
    _admin_required(x_admin_token, authorization)
    snap = clear_overlay()
    return {"ok": True, "cleared": True, **snap}
