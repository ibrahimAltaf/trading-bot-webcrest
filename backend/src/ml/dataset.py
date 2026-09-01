"""Build ML matrices from OHLCV: profit-based labels, sequences, scaling."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd

from src.ml.feature_columns import FEATURE_COLUMNS_PRODUCTION

# Profit-oriented labels (fractional return over horizon bars)
DEFAULT_LABEL_HORIZON = 5
DEFAULT_PROFIT_THRESHOLD = 0.004  # 0.4%


def enrich_ohlcv_for_ml(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add production features from a DataFrame that has open, high, low, close, volume.
    Expects BB/MACD/ATR/RSI from add_all_indicators or computes minimal set.
    """
    from src.features.indicators import (
        calculate_ema,
        calculate_rsi,
        calculate_macd,
        calculate_bollinger_bands,
        calculate_atr,
    )

    out = df.copy()
    for c in ["open", "high", "low", "close", "volume"]:
        out.loc[:, c] = out[c].astype(float)

    close = out["close"]
    out.loc[:, "ret_1"] = close.pct_change(1)
    out.loc[:, "ret_5"] = close.pct_change(5)

    out.loc[:, "rsi_14"] = calculate_rsi(out, 14)

    e9 = calculate_ema(out, 9)
    e21 = calculate_ema(out, 21)
    e50 = calculate_ema(out, 50)
    out.loc[:, "ema_9_rel"] = (e9 / close) - 1.0
    out.loc[:, "ema_21_rel"] = (e21 / close) - 1.0
    out.loc[:, "ema_50_rel"] = (e50 / close) - 1.0

    out = calculate_macd(out, 12, 26, 9)
    out.loc[:, "macd"] = out["macd_line"].astype(float)
    out.loc[:, "macd_signal"] = out["macd_signal"].astype(float)
    out.loc[:, "macd_hist"] = out["macd_hist"].astype(float)

    out = calculate_bollinger_bands(out, 20, 2.0)
    mid = out["bb_middle"].replace(0, np.nan)
    out.loc[:, "bb_width"] = ((out["bb_upper"] - out["bb_lower"]) / mid * 100.0).fillna(0.0)
    rng = (out["bb_upper"] - out["bb_lower"]).replace(0, np.nan)
    out.loc[:, "bb_pct"] = ((close - out["bb_lower"]) / rng).clip(0, 1).fillna(0.5)

    out = calculate_atr(out, 14)
    out.loc[:, "atr_14"] = out["atr"].astype(float)
    out.loc[:, "atr_pct"] = (out["atr_14"] / close * 100.0).fillna(0.0)

    vol_sma = out["volume"].rolling(20).mean()
    out.loc[:, "vol_ratio"] = (out["volume"] / vol_sma.replace(0, np.nan)).replace(
        [np.inf, -np.inf], np.nan
    )
    out.loc[:, "vol_change"] = out["volume"].pct_change().replace(
        [np.inf, -np.inf], np.nan
    )

    return out


def profit_labels(
    close: pd.Series,
    horizon: int = DEFAULT_LABEL_HORIZON,
    threshold: float = DEFAULT_PROFIT_THRESHOLD,
) -> np.ndarray:
    """0=SELL, 1=HOLD, 2=BUY aligned with inference _CLASSES order."""
    future = close.shift(-horizon)
    ret = (future - close) / close
    y = np.ones(len(close), dtype=np.int64)  # HOLD
    y[ret > threshold] = 2  # BUY
    y[ret < -threshold] = 0  # SELL
    return y


def build_sequences(
    feats: pd.DataFrame,
    y: np.ndarray,
    lookback: int,
) -> Tuple[np.ndarray, np.ndarray]:
    """X: (N, lookback, F), y: (N,) — label aligned with last bar of each window."""
    cols = FEATURE_COLUMNS_PRODUCTION
    missing = [c for c in cols if c not in feats.columns]
    if missing:
        raise ValueError(f"Missing ML columns: {missing}")
    data = feats[cols].to_numpy(dtype=np.float64)
    X_list = []
    y_list = []
    for i in range(lookback, len(data)):
        t = i - 1  # last timestep in window [i-lookback : i)
        if not np.isfinite(y[t]):
            continue
        window = data[i - lookback : i]
        if not np.isfinite(window).all():
            continue
        X_list.append(window)
        y_list.append(y[t])
    X = np.stack(X_list, axis=0)
    yy = np.asarray(y_list, dtype=np.int64)
    return X, yy


def train_val_split_time(
    X: np.ndarray, y: np.ndarray, val_ratio: float = 0.2
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    n = len(X)
    cut = int(n * (1.0 - val_ratio))
    return X[:cut], y[:cut], X[cut:], y[cut:]


def fit_standard_scaler(X: np.ndarray) -> Dict[str, Any]:
    """Per-feature mean/std on flattened training data (per feature dim)."""
    # X: (N, L, F) -> compute mean/std over N and L
    n, l, f = X.shape
    flat = X.reshape(-1, f)
    mean = flat.mean(axis=0)
    std = flat.std(axis=0)
    std = np.where(std < 1e-8, 1.0, std)
    return {"mean": mean.tolist(), "scale": std.tolist()}


def apply_scaler(X: np.ndarray, scaler: Dict[str, Any]) -> np.ndarray:
    mean = np.asarray(scaler["mean"], dtype=np.float32)
    scale = np.asarray(scaler["scale"], dtype=np.float32)
    return (X - mean) / scale


def save_dataset_npz(
    path: Path,
    Xtr: np.ndarray,
    ytr: np.ndarray,
    Xva: np.ndarray,
    yva: np.ndarray,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, Xtr=Xtr, ytr=ytr, Xva=Xva, yva=yva)


def append_ml_production_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    After add_all_indicators(): add columns required for FEATURE_COLUMNS_PRODUCTION.
    Does not drop rows (caller may already have dropped).
    """
    from src.features.indicators import calculate_ema

    out = df.copy()
    close = out["close"].astype(float)

    if "ret_1" not in out.columns:
        out.loc[:, "ret_1"] = close.pct_change(1)
    if "ret_5" not in out.columns:
        out.loc[:, "ret_5"] = close.pct_change(5)

    if "rsi_14" not in out.columns:
        from src.features.indicators import calculate_rsi

        out.loc[:, "rsi_14"] = calculate_rsi(out, 14)

    e9 = calculate_ema(out, 9)
    e21 = calculate_ema(out, 21)
    e50 = calculate_ema(out, 50)
    out.loc[:, "ema_9_rel"] = (e9 / close) - 1.0
    out.loc[:, "ema_21_rel"] = (e21 / close) - 1.0
    out.loc[:, "ema_50_rel"] = (e50 / close) - 1.0

    if "macd" not in out.columns:
        from src.features.indicators import calculate_macd

        out = calculate_macd(out, 12, 26, 9)
        out.loc[:, "macd"] = out["macd_line"].astype(float)
        out.loc[:, "macd_signal"] = out["macd_signal"].astype(float)
        out.loc[:, "macd_hist"] = out["macd_hist"].astype(float)

    if "bb_upper" in out.columns and "bb_lower" in out.columns:
        mid = out["bb_middle"].replace(0, np.nan)
        out.loc[:, "bb_width"] = (
            (out["bb_upper"] - out["bb_lower"]) / mid * 100.0
        ).fillna(0.0)
        rng = (out["bb_upper"] - out["bb_lower"]).replace(0, np.nan)
        out.loc[:, "bb_pct"] = (
            ((close - out["bb_lower"]) / rng).clip(0, 1).fillna(0.5)
        )
    else:
        from src.features.indicators import calculate_bollinger_bands

        out = calculate_bollinger_bands(out, 20, 2.0)
        mid = out["bb_middle"].replace(0, np.nan)
        out.loc[:, "bb_width"] = (
            (out["bb_upper"] - out["bb_lower"]) / mid * 100.0
        ).fillna(0.0)
        rng = (out["bb_upper"] - out["bb_lower"]).replace(0, np.nan)
        out.loc[:, "bb_pct"] = (
            ((close - out["bb_lower"]) / rng).clip(0, 1).fillna(0.5)
        )

    if "atr_14" not in out.columns:
        if "atr" in out.columns:
            out.loc[:, "atr_14"] = out["atr"].astype(float)
        else:
            from src.features.indicators import calculate_atr

            out = calculate_atr(out, 14)
            out.loc[:, "atr_14"] = out["atr"].astype(float)
    out.loc[:, "atr_pct"] = (out["atr_14"] / close * 100.0).fillna(0.0)

    vol = out["volume"].astype(float)
    vol_sma = vol.rolling(20).mean()
    out.loc[:, "vol_ratio"] = (vol / vol_sma.replace(0, np.nan)).replace(
        [np.inf, -np.inf], np.nan
    )
    out.loc[:, "vol_change"] = vol.pct_change().replace([np.inf, -np.inf], np.nan)

    return out
