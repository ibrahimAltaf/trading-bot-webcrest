"""One forward pass at startup so inference_count > 0 for health checks (optional)."""
from __future__ import annotations

from typing import Any, Dict


def run_public_klines_smoke(
    *,
    model_dir: str,
    symbol: str,
    timeframe: str,
    settings: Any,
) -> Dict[str, Any]:
    """
    Fetch public OHLCV (no API keys), build features, run predict_window once.
    Returns {"ok": bool, "error": str | None}.
    """
    out: Dict[str, Any] = {"ok": False, "error": None}
    try:
        from src.ml.inference import get_infer
        from src.ml.data_fetch import fetch_public_klines
        from src.features.indicators import add_all_indicators
        from src.ml.dataset import append_ml_production_features

        inf = get_infer(model_dir)
        lb = int(getattr(inf, "lookback", 50) or 50)
        df = fetch_public_klines(
            symbol, timeframe, limit=max(lb + 120, 220)
        )
        for col in ["open", "high", "low", "close", "volume"]:
            df.loc[:, col] = df[col].astype(float)
        indicator_config = {
            "ema_fast": settings.ema_fast,
            "ema_slow": settings.ema_slow,
            "rsi_period": settings.rsi_len,
            "adx_period": 14,
            "bb_period": settings.bb_len,
            "bb_std": settings.bb_std,
            "atr_period": 14,
        }
        df = add_all_indicators(df, indicator_config)
        df = append_ml_production_features(df)
        df = df.dropna()
        if len(df) < lb + 2:
            out["error"] = f"not_enough_rows_after_features got={len(df)} need>={lb + 2}"
            return out
        _ = inf.predict_window(df)
        out["ok"] = True
        return out
    except Exception as e:
        out["error"] = str(e)[:500]
        return out
