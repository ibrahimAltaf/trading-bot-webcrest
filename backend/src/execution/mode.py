"""
Tri-mode execution selector (paper / shadow / live).

Resolution priority (highest first):
    1. Runtime override file (data_dir/safety/execution_mode.json) — set via API.
    2. EXECUTION_MODE env var: "paper" | "shadow" | "live".
    3. Legacy PHASE1_PAPER_EXECUTION=true → "paper" (Phase 1 backwards compat).
    4. Default → "live" (matches Phase 1 default before the flag existed).

Notes
-----
* `paper`  — no exchange calls; orders generated in-process (Phase 1 audit flow).
* `shadow` — uses real Binance market data + balances but does NOT place real orders.
* `live`   — places real orders on Binance.

`is_simulated(mode)` returns True for paper and shadow — useful guard rail.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional


class ExecutionMode(str, Enum):
    PAPER = "paper"
    SHADOW = "shadow"
    LIVE = "live"

    @classmethod
    def coerce(cls, value: Any, default: "ExecutionMode" = None) -> "ExecutionMode":
        if isinstance(value, cls):
            return value
        if value is None:
            return default or cls.LIVE
        s = str(value).strip().lower()
        for m in cls:
            if s == m.value:
                return m
        raise ValueError(
            f"invalid execution mode {value!r}; expected one of "
            f"{[m.value for m in cls]}"
        )


def is_simulated(mode: ExecutionMode) -> bool:
    """True for paper and shadow — no real orders placed."""
    return mode in (ExecutionMode.PAPER, ExecutionMode.SHADOW)


def _override_path() -> Path:
    """Persistent override location; created lazily."""
    try:
        from src.core.config import get_settings

        data_dir = Path(get_settings().data_dir)
    except Exception:
        data_dir = Path(os.getenv("DATA_DIR", "./data")).resolve()
    return data_dir / "safety" / "execution_mode.json"


def _read_override() -> Optional[ExecutionMode]:
    p = _override_path()
    if not p.is_file():
        return None
    try:
        with p.open("r", encoding="utf-8") as fh:
            doc = json.load(fh)
        return ExecutionMode.coerce(doc.get("mode"))
    except Exception:
        return None


def _write_override(
    mode: ExecutionMode, *, changed_by: str = "system", reason: str = ""
) -> Dict[str, Any]:
    p = _override_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "mode": mode.value,
        "changed_at": datetime.utcnow().isoformat() + "Z",
        "changed_by": changed_by,
        "reason": reason,
    }
    with p.open("w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
    return doc


def get_execution_mode() -> ExecutionMode:
    """Resolve current effective execution mode (see module docstring)."""
    o = _read_override()
    if o is not None:
        return o

    env_raw = (os.getenv("EXECUTION_MODE") or "").strip().lower()
    if env_raw:
        try:
            return ExecutionMode.coerce(env_raw)
        except ValueError:
            pass

    legacy_paper = (os.getenv("PHASE1_PAPER_EXECUTION") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "y",
    )
    if legacy_paper:
        return ExecutionMode.PAPER

    return ExecutionMode.LIVE


def set_execution_mode(
    mode: Any, *, changed_by: str = "api", reason: str = ""
) -> Dict[str, Any]:
    """Persist a new mode override; returns the stored document."""
    m = ExecutionMode.coerce(mode)
    return _write_override(m, changed_by=changed_by, reason=reason)


def clear_execution_mode_override() -> bool:
    """Remove the runtime override, falling back to env/legacy resolution."""
    p = _override_path()
    if p.is_file():
        p.unlink()
        return True
    return False


def mode_snapshot() -> Dict[str, Any]:
    """Diagnostics-friendly view of current resolution."""
    override = _read_override()
    env_raw = (os.getenv("EXECUTION_MODE") or "").strip().lower() or None
    legacy = (os.getenv("PHASE1_PAPER_EXECUTION") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "y",
    )
    effective = get_execution_mode()
    return {
        "effective_mode": effective.value,
        "is_simulated": is_simulated(effective),
        "sources": {
            "override_file": override.value if override else None,
            "env_EXECUTION_MODE": env_raw,
            "legacy_PHASE1_PAPER_EXECUTION": legacy,
        },
        "override_path": str(_override_path()),
    }
