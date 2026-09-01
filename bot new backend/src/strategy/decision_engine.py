"""
ML-Primary Decision Engine
--------------------------
ML confidence drives the final action:
  > 0.65  → BUY   (ml_prioritize)
  < 0.35  → SELL  (ml_prioritize)
  0.35-0.65 → HOLD (ml_neutral)
  ML unavailable → rule_fallback

Updates src.ml.state globals on every inference call for observability.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd

import src.ml.state as ml_state

_infer_by_symbol: Dict[str, Any] = {}


def _load_model(symbol: str | None = None):
    """Lazy-load LSTM inferencer per symbol (correct model dir per pair)."""
    try:
        from src.core.config import get_settings
        from src.ml.inference import get_infer
        from src.ml.model_selector import resolve_model_selection
        import os

        s = get_settings()
        if not getattr(s, "ml_enabled", False):
            return None

        sym = (symbol or getattr(s, "trade_symbol", "BTCUSDT")).upper().strip()
        if sym in _infer_by_symbol:
            return _infer_by_symbol[sym]

        version = os.getenv("ML_MODEL_VERSION", "").strip() or None
        ctx = resolve_model_selection(
            base_model_dir=s.ml_model_dir,
            symbol=sym,
            timeframe=getattr(s, "trade_timeframe", "1h"),
            version=version,
        )
        if not ctx.get("model_exists"):
            _infer_by_symbol[sym] = None
            return None

        inf = get_infer(str(ctx["model_dir"]))
        _infer_by_symbol[sym] = inf
        return inf
    except Exception:
        sym = (symbol or "").upper().strip()
        if sym:
            _infer_by_symbol[sym] = None
        return None


def get_rule_signal(data: Dict[str, Any]) -> str:
    """EMA-crossover + RSI rule-based fallback."""
    ema_fast = float(data.get("ema_fast") or 0)
    ema_slow = float(data.get("ema_slow") or 0)
    rsi = float(data.get("rsi") or 50)
    if ema_fast > ema_slow and rsi < 70:
        return "BUY"
    if ema_fast < ema_slow and rsi > 30:
        return "SELL"
    return "HOLD"


def make_decision(features_df: pd.DataFrame, data: Dict[str, Any]) -> Dict[str, Any]:
    """
    ML-primary decision.

    Parameters
    ----------
    features_df : DataFrame with indicator columns for LSTM window
    data        : dict with keys: symbol, price, ema_fast, ema_slow, rsi

    Returns
    -------
    dict with action, source, ml_confidence, ml_signal (and optional error)
    """
    rule_signal = get_rule_signal(data)
    sym = str(data.get("symbol") or "").upper().strip()
    ml_model = _load_model(sym if sym else None)

    if ml_model is None:
        return {
            "action": rule_signal,
            "source": "rule_fallback",
            "ml_confidence": None,
            "ml_signal": None,
        }

    try:
        ml_output = ml_model.predict_window(features_df)
        ml_confidence = float(ml_output.get("confidence", 0.5))
        ml_signal = str(ml_output.get("signal", "HOLD")).upper()

        ml_state.sync_from_runtime()

        if ml_confidence > 0.65:
            action = "BUY"
            source = "ml_prioritize"
        elif ml_confidence < 0.35:
            action = "SELL"
            source = "ml_prioritize"
        elif 0.35 <= ml_confidence <= 0.65:
            action = "HOLD"
            source = "ml_neutral"
        else:
            action = rule_signal
            source = "rule_fallback"

        return {
            "action": action,
            "source": source,
            "ml_confidence": round(ml_confidence, 4),
            "ml_signal": ml_signal,
        }

    except Exception as exc:
        return {
            "action": rule_signal,
            "source": "rule_fallback_error",
            "ml_confidence": None,
            "ml_signal": None,
            "error": str(exc)[:300],
        }
