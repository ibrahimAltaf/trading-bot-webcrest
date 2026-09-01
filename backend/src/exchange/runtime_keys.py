"""
Runtime Binance key overlay (Phase 2A).

The bot's `BinanceSpotClient` historically read keys from `.env` only — meaning
the frontend could not rotate live trading credentials without an SSH session +
service restart. This module adds a **persistent runtime overlay** stored in
the `app_settings` table:

    RUNTIME_BINANCE_API_KEY      — plaintext (key is not a secret by itself)
    RUNTIME_BINANCE_API_SECRET   — encrypted via secrets_crypto when possible
    RUNTIME_BINANCE_TESTNET      — "true"/"false"

Resolution priority (highest first):
    1. Overlay values from `app_settings` (set via /admin/binance-keys).
    2. Environment variables (`BINANCE_API_KEY`, `BINANCE_API_SECRET`,
       `BINANCE_TESTNET`) — the original .env path.

A change in the overlay is picked up by the **next** `BinanceSpotClient()`
instantiation (scheduler / engine create new clients per cycle).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.core.secrets_crypto import decrypt_optional, encrypt_optional


_OVERLAY_KEY_API_KEY = "RUNTIME_BINANCE_API_KEY"
_OVERLAY_KEY_API_SECRET = "RUNTIME_BINANCE_API_SECRET"
_OVERLAY_KEY_TESTNET = "RUNTIME_BINANCE_TESTNET"
_OVERLAY_KEY_UPDATED_BY = "RUNTIME_BINANCE_UPDATED_BY"


def _mask(value: Optional[str], keep: int = 4) -> Optional[str]:
    if not value:
        return None
    v = str(value)
    if len(v) <= keep:
        return "*" * len(v)
    return v[:keep] + "…" + "*" * max(0, len(v) - keep)


def _bool_from(value: Any, default: bool = True) -> bool:
    s = str(value).strip().lower()
    if s in ("1", "true", "yes", "y"):
        return True
    if s in ("0", "false", "no", "n"):
        return False
    return default


@dataclass
class ResolvedKeys:
    api_key: str
    api_secret: str
    testnet: bool
    source: str  # "overlay" | "env" | "mixed"
    api_key_set: bool
    api_secret_set: bool


def _read_overlay() -> Dict[str, Optional[str]]:
    """Best-effort read of the AppSetting overlay. Never raises."""
    try:
        from src.db.models import AppSetting
        from src.db.session import SessionLocal
    except Exception:
        return {}

    out: Dict[str, Optional[str]] = {}
    try:
        db = SessionLocal()
        try:
            rows = (
                db.query(AppSetting)
                .filter(
                    AppSetting.key.in_(
                        [
                            _OVERLAY_KEY_API_KEY,
                            _OVERLAY_KEY_API_SECRET,
                            _OVERLAY_KEY_TESTNET,
                            _OVERLAY_KEY_UPDATED_BY,
                        ]
                    )
                )
                .all()
            )
            for r in rows:
                out[r.key] = r.value
        finally:
            db.close()
    except Exception:
        # Table may not exist yet during very early bootstrap.
        return {}
    return out


def _encryption_key() -> str:
    try:
        from src.core.config import get_settings

        return get_settings().secrets_encryption_key or ""
    except Exception:
        return os.getenv("SECRETS_ENCRYPTION_KEY", "") or ""


def resolve_runtime_keys() -> ResolvedKeys:
    """
    Resolve the effective Binance credentials the next BinanceSpotClient will use.

    Falls back to env when no overlay value is set; mixes are tracked in `source`.
    """
    overlay = _read_overlay()
    overlay_key = (overlay.get(_OVERLAY_KEY_API_KEY) or "").strip()
    overlay_secret_blob = (overlay.get(_OVERLAY_KEY_API_SECRET) or "").strip()
    overlay_testnet_raw = overlay.get(_OVERLAY_KEY_TESTNET)

    env_key = (os.getenv("BINANCE_API_KEY", "") or "").strip()
    env_secret = (os.getenv("BINANCE_API_SECRET", "") or "").strip()
    env_testnet = _bool_from(os.getenv("BINANCE_TESTNET", "true"), default=True)

    overlay_secret = ""
    if overlay_secret_blob:
        try:
            overlay_secret = decrypt_optional(overlay_secret_blob, _encryption_key())
        except Exception:
            # Stored as plaintext or malformed — treat as not set rather than crash.
            overlay_secret = overlay_secret_blob

    api_key = overlay_key or env_key
    api_secret = overlay_secret or env_secret
    testnet = (
        _bool_from(overlay_testnet_raw, default=env_testnet)
        if overlay_testnet_raw is not None
        else env_testnet
    )

    used_overlay_key = bool(overlay_key)
    used_overlay_secret = bool(overlay_secret)
    if used_overlay_key and used_overlay_secret:
        source = "overlay"
    elif not used_overlay_key and not used_overlay_secret:
        source = "env"
    else:
        source = "mixed"

    return ResolvedKeys(
        api_key=api_key,
        api_secret=api_secret,
        testnet=testnet,
        source=source,
        api_key_set=bool(api_key),
        api_secret_set=bool(api_secret),
    )


def get_overlay_snapshot() -> Dict[str, Any]:
    """Diagnostics view for /admin/binance-keys (masked, never returns the secret)."""
    overlay = _read_overlay()
    resolved = resolve_runtime_keys()
    return {
        "overlay_present": bool(
            overlay.get(_OVERLAY_KEY_API_KEY)
            or overlay.get(_OVERLAY_KEY_API_SECRET)
            or overlay.get(_OVERLAY_KEY_TESTNET) is not None
        ),
        "overlay_api_key_masked": _mask(overlay.get(_OVERLAY_KEY_API_KEY)),
        "overlay_api_secret_set": bool(overlay.get(_OVERLAY_KEY_API_SECRET)),
        "overlay_testnet": (
            _bool_from(overlay.get(_OVERLAY_KEY_TESTNET))
            if overlay.get(_OVERLAY_KEY_TESTNET) is not None
            else None
        ),
        "overlay_updated_by": overlay.get(_OVERLAY_KEY_UPDATED_BY),
        "env_api_key_set": bool((os.getenv("BINANCE_API_KEY") or "").strip()),
        "env_api_secret_set": bool((os.getenv("BINANCE_API_SECRET") or "").strip()),
        "env_testnet": _bool_from(os.getenv("BINANCE_TESTNET", "true")),
        "effective_api_key_masked": _mask(resolved.api_key),
        "effective_api_secret_set": resolved.api_secret_set,
        "effective_testnet": resolved.testnet,
        "source": resolved.source,
        "ready_for_signed_requests": resolved.api_key_set and resolved.api_secret_set,
        "encryption_available": _encryption_key() != "",
    }


def set_overlay(
    *,
    api_key: Optional[str] = None,
    api_secret: Optional[str] = None,
    testnet: Optional[bool] = None,
    updated_by: str = "api",
) -> Dict[str, Any]:
    """
    Upsert overlay values. Any field set to None is left untouched (partial update).
    Secret is encrypted at rest when SECRETS_ENCRYPTION_KEY is configured.
    """
    from src.db.models import AppSetting
    from src.db.session import SessionLocal

    db = SessionLocal()
    try:
        def _upsert(k: str, v: str) -> None:
            row = db.query(AppSetting).filter_by(key=k).first()
            if row is None:
                row = AppSetting(key=k, value=v)
                db.add(row)
            else:
                row.value = v

        if api_key is not None:
            _upsert(_OVERLAY_KEY_API_KEY, str(api_key).strip())
        if api_secret is not None:
            blob = encrypt_optional(str(api_secret).strip(), _encryption_key())
            _upsert(_OVERLAY_KEY_API_SECRET, blob)
        if testnet is not None:
            _upsert(_OVERLAY_KEY_TESTNET, "true" if bool(testnet) else "false")
        _upsert(_OVERLAY_KEY_UPDATED_BY, str(updated_by or "api")[:128])
        db.commit()
    finally:
        db.close()

    return get_overlay_snapshot()


def clear_overlay() -> Dict[str, Any]:
    """Remove all runtime overlay rows; engine falls back to env on next client init."""
    from src.db.models import AppSetting
    from src.db.session import SessionLocal

    db = SessionLocal()
    try:
        (
            db.query(AppSetting)
            .filter(
                AppSetting.key.in_(
                    [
                        _OVERLAY_KEY_API_KEY,
                        _OVERLAY_KEY_API_SECRET,
                        _OVERLAY_KEY_TESTNET,
                        _OVERLAY_KEY_UPDATED_BY,
                    ]
                )
            )
            .delete(synchronize_session=False)
        )
        db.commit()
    finally:
        db.close()
    return get_overlay_snapshot()
