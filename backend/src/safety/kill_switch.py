"""
Hard kill switch — instantly disables trading.

When engaged, the AutoTradeEngine MUST refuse to execute new orders regardless of
mode (paper / shadow / live). Engagement persists across restarts via a small JSON
state file under `<data_dir>/safety/kill_switch.json` so the system stays safe
across deploys / crashes.

Engagement is *advisory* for paper mode (safe by definition) but **mandatory**
for shadow + live. Callers can also use it as a single "stop everything" toggle.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

_LOCK = threading.RLock()


def _state_path() -> Path:
    try:
        from src.core.config import get_settings

        data_dir = Path(get_settings().data_dir)
    except Exception:
        data_dir = Path(os.getenv("DATA_DIR", "./data")).resolve()
    return data_dir / "safety" / "kill_switch.json"


def _empty_state() -> Dict[str, Any]:
    return {
        "engaged": False,
        "engaged_at": None,
        "engaged_by": None,
        "reason": None,
        "released_at": None,
        "released_by": None,
        "release_reason": None,
        "history": [],
    }


def _read() -> Dict[str, Any]:
    p = _state_path()
    if not p.is_file():
        return _empty_state()
    try:
        with p.open("r", encoding="utf-8") as fh:
            doc = json.load(fh)
        # Forward-compat: ensure all expected keys exist.
        base = _empty_state()
        base.update(doc if isinstance(doc, dict) else {})
        if "history" not in base or not isinstance(base["history"], list):
            base["history"] = []
        return base
    except Exception:
        return _empty_state()


def _write(state: Dict[str, Any]) -> None:
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)


def get_state() -> Dict[str, Any]:
    """Return current kill-switch document (safe copy)."""
    with _LOCK:
        return dict(_read())


def is_engaged() -> bool:
    """Fast check used by the engine before every order."""
    with _LOCK:
        return bool(_read().get("engaged"))


def engage(reason: str, *, by: str = "system") -> Dict[str, Any]:
    """
    Engage the kill switch.

    Idempotent: re-engaging only records a history entry and refreshes
    `engaged_at` / `engaged_by` / `reason` only if not already engaged.
    """
    if not reason or not str(reason).strip():
        raise ValueError("kill switch engage requires a reason")
    with _LOCK:
        state = _read()
        ts = datetime.utcnow().isoformat() + "Z"
        history = state.get("history") or []
        history.append(
            {
                "event": "engage",
                "ts": ts,
                "by": by,
                "reason": str(reason)[:1000],
            }
        )
        # Trim history to last 50 entries to keep file small.
        history = history[-50:]
        if not state.get("engaged"):
            state.update(
                {
                    "engaged": True,
                    "engaged_at": ts,
                    "engaged_by": by,
                    "reason": str(reason)[:1000],
                    "released_at": None,
                    "released_by": None,
                    "release_reason": None,
                }
            )
        state["history"] = history
        _write(state)
    _emit_alert("ERROR", "kill_switch_engaged", str(reason)[:500], by=by)
    return dict(state)


def release(reason: str, *, by: str = "system") -> Dict[str, Any]:
    """Release the kill switch (allows trading to resume)."""
    if not reason or not str(reason).strip():
        raise ValueError("kill switch release requires a reason")
    with _LOCK:
        state = _read()
        ts = datetime.utcnow().isoformat() + "Z"
        history = state.get("history") or []
        history.append(
            {
                "event": "release",
                "ts": ts,
                "by": by,
                "reason": str(reason)[:1000],
            }
        )
        history = history[-50:]
        state.update(
            {
                "engaged": False,
                "released_at": ts,
                "released_by": by,
                "release_reason": str(reason)[:1000],
                "history": history,
            }
        )
        _write(state)
    _emit_alert("WARN", "kill_switch_released", str(reason)[:500], by=by)
    return dict(state)


def _emit_alert(level: str, category: str, message: str, **extra: Any) -> None:
    """Best-effort hook into the alerter; tolerate import cycles / failures."""
    try:
        from src.safety.alerts import send_alert

        send_alert(level, category, message, **extra)
    except Exception:
        pass


def reset_for_tests() -> None:
    """Test helper — never call in production code paths."""
    with _LOCK:
        p = _state_path()
        if p.is_file():
            p.unlink()
