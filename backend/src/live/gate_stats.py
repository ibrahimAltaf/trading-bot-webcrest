"""In-process counters for HOLD diagnostics (% by kind)."""
from __future__ import annotations

from typing import Any, Dict

_counts: Dict[str, int] = {}


def record_hold_kind(hold_kind: str) -> None:
    if not hold_kind:
        return
    _counts[hold_kind] = int(_counts.get(hold_kind, 0)) + 1


def distribution_pct() -> Dict[str, Any]:
    total = sum(_counts.values())
    if total <= 0:
        return {"total": 0, "percent_by_kind": {}}
    pct = {k: round(100.0 * v / total, 2) for k, v in _counts.items()}
    return {"total": total, "percent_by_kind": pct}


def reset() -> None:
    _counts.clear()
