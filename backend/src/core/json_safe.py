"""Strict JSON-serializable payloads for DB/API (no NaN/Inf in JSON)."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Optional


def iso_utc(value: Optional[datetime]) -> Optional[str]:
    """Serialize a timestamp as RFC 3339 UTC with an explicit ``Z`` designator.

    DB columns are written with ``datetime.utcnow()``, so stored values are UTC
    but tz-naive. A bare ``isoformat()`` emits no offset, which clients are free
    to read as local time — that shifts reported decision times by the reader's
    UTC offset. Tagging the offset removes the ambiguity.
    """
    if value is None:
        return None
    aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return aware.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


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
