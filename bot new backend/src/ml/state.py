"""
ML observability: runtime lives in src.core.ml_runtime_state.
This module keeps legacy names in sync for endpoints that read these globals.
"""
from __future__ import annotations

from typing import List, Optional

from src.core.ml_runtime_state import get_ml_state, record_inference as _record

ACTIVE_SYMBOLS: List[str] = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

LAST_PREDICTION: Optional[str] = None
LAST_CONFIDENCE: Optional[float] = None
INFERENCE_COUNTER: int = 0


def sync_from_runtime() -> None:
    global LAST_PREDICTION, LAST_CONFIDENCE, INFERENCE_COUNTER
    s = get_ml_state()
    lp = s.get("last_prediction")
    LAST_PREDICTION = str(lp) if lp is not None else None
    lc = s.get("last_confidence")
    LAST_CONFIDENCE = float(lc) if lc is not None else None
    INFERENCE_COUNTER = int(s.get("inference_count") or 0)


def record_legacy_inference(signal: str, confidence: float) -> None:
    _record(
        action=signal,
        confidence=confidence,
        prediction=signal,
        features_shape=None,
    )
    sync_from_runtime()
