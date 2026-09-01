"""Canonical feature list for BTC production LSTM (must match training + live inference)."""
from __future__ import annotations

# Order is fixed — inference reshapes (1, lookback, len(FEATURE_COLUMNS_PRODUCTION))
FEATURE_COLUMNS_PRODUCTION = [
    "ret_1",
    "ret_5",
    "rsi_14",
    "ema_9_rel",
    "ema_21_rel",
    "ema_50_rel",
    "macd",
    "macd_signal",
    "macd_hist",
    "bb_width",
    "bb_pct",
    "atr_14",
    "atr_pct",
    "vol_change",
    "vol_ratio",
]
