"""
Phase 2C — Controlled Micro-Live activation gate.

Default state: READY FOR ACTIVATION / MICRO-LIVE DISABLED.

Even when execution mode is ``live``, real Binance orders are blocked until
micro-live is explicitly enabled via env or API. Adaptive AI thresholds are
NOT modified here — this module only gates live execution.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


def _data_dir() -> Path:
    try:
        from src.core.config import get_settings

        return Path(get_settings().data_dir)
    except Exception:
        return Path(os.getenv("DATA_DIR", "./data")).resolve()


def _state_path() -> Path:
    return _data_dir() / "safety" / "phase2c.json"


def _read_state() -> Dict[str, Any]:
    p = _state_path()
    if not p.is_file():
        return {}
    try:
        with p.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _write_state(doc: Dict[str, Any]) -> Dict[str, Any]:
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
    return doc


def _env_enabled() -> bool:
    return os.getenv("PHASE_2C_MICRO_LIVE_ENABLED", "false").strip().lower() in (
        "1",
        "true",
        "yes",
        "y",
    )


def is_micro_live_enabled() -> bool:
    """True only when env AND runtime override both allow micro-live."""
    state = _read_state()
    if state.get("enabled") is False:
        return False
    if state.get("enabled") is True:
        return True
    return _env_enabled()


def get_activation_at() -> Optional[datetime]:
    """UTC timestamp when micro-live was last activated (for cumulative PnL window)."""
    raw = _read_state().get("activated_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", ""))
    except Exception:
        return None


def activate(*, by: str = "api", reason: str = "") -> Dict[str, Any]:
    now = datetime.utcnow().isoformat() + "Z"
    doc = _read_state()
    doc.update(
        {
            "enabled": True,
            "activated_at": now,
            "activated_by": by,
            "activation_reason": reason,
            "deactivated_at": None,
            "deactivated_by": None,
        }
    )
    _write_state(doc)
    return snapshot()


def deactivate(*, by: str = "api", reason: str = "") -> Dict[str, Any]:
    now = datetime.utcnow().isoformat() + "Z"
    doc = _read_state()
    doc.update(
        {
            "enabled": False,
            "deactivated_at": now,
            "deactivated_by": by,
            "deactivation_reason": reason,
        }
    )
    _write_state(doc)
    return snapshot()


def can_place_live_orders() -> bool:
    """All conditions for placing a real Binance order."""
    if not is_micro_live_enabled():
        return False
    try:
        from src.execution.mode import ExecutionMode, get_execution_mode

        return get_execution_mode() == ExecutionMode.LIVE
    except Exception:
        return False


def snapshot() -> Dict[str, Any]:
    state = _read_state()
    enabled = is_micro_live_enabled()
    if enabled:
        status_label = "MICRO-LIVE ENABLED"
    else:
        status_label = "READY FOR ACTIVATION / MICRO-LIVE DISABLED"

    return {
        "phase": "2C",
        "micro_live_enabled": enabled,
        "status_label": status_label,
        "can_place_live_orders": can_place_live_orders(),
        "env_PHASE_2C_MICRO_LIVE_ENABLED": _env_enabled(),
        "runtime_override": state.get("enabled"),
        "activated_at": state.get("activated_at"),
        "activated_by": state.get("activated_by"),
        "activation_reason": state.get("activation_reason"),
        "deactivated_at": state.get("deactivated_at"),
        "deactivated_by": state.get("deactivated_by"),
        "state_path": str(_state_path()),
    }
