"""Strict JSON-serializable payloads for DB/API (no NaN/Inf in JSON)."""
from __future__ import annotations

import math
from typing import Any


def finite_float(value: Any, default: float = 0.0) -> float:
    try:
        v = float(value)
        if math.isfinite(v):
            return float(v)
    except (TypeError, ValueError):
        pass
    return default


def sanitize_for_json(obj: Any) -> Any:
    """Recursively replace NaN/Inf with None; safe for json.dumps(..., allow_nan=False)."""
    if obj is None:
        return None
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, (str, bool, int)):
        return obj
    if isinstance(obj, dict):
        return {str(k): sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_for_json(x) for x in obj]
    return str(obj)
