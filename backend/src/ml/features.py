from __future__ import annotations

from typing import List, Optional

import pandas as pd

from src.ml.feature_columns import FEATURE_COLUMNS_PRODUCTION

# Older lstm_v1 checkpoints used this layout
FEATURE_COLUMNS_LEGACY = [
    "open",
    "high",
    "low",
    "close",
    "volume",
    "ema_20",
    "ema_50",
    "rsi_14",
    "atr_14",
    "macd",
    "macd_signal",
    "macd_hist",
    "vol_sma_20",
    "vol_ratio",
]

# Default export for docs / backward compat
FEATURE_COLUMNS = FEATURE_COLUMNS_PRODUCTION


def select_features(
    df: pd.DataFrame, columns: Optional[List[str]] = None
) -> pd.DataFrame:
    cols = columns if columns is not None else FEATURE_COLUMNS_LEGACY
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing feature columns: {missing}")
    return df[cols].copy()
