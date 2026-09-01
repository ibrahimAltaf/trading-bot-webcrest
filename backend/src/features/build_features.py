from pathlib import Path

import numpy as np
import pandas as pd

from src.core.config import get_settings
from src.features.indicators import calculate_atr, calculate_macd, calculate_rsi

settings = get_settings()

SYMBOL = "BTCUSDT"
TIMEFRAME = "1h"

RAW_PATH = Path(settings.data_dir) / "raw" / f"{SYMBOL}_{TIMEFRAME}.parquet"
OUT_DIR = Path(settings.data_dir) / "features"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PATH = OUT_DIR / f"{SYMBOL}_{TIMEFRAME}_features.parquet"


def load_raw() -> pd.DataFrame:
    if not RAW_PATH.exists():
        raise FileNotFoundError(f"Raw data not found: {RAW_PATH}")

    df = pd.read_parquet(RAW_PATH).sort_values("open_time").reset_index(drop=True)

    df["open_time"] = pd.to_datetime(df["open_time"], errors="coerce")
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.dropna(
        subset=["open_time", "open", "high", "low", "close", "volume"]
    ).reset_index(drop=True)
    return df


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    print("🧠 Building features...")

    if len(df) < 60:
        raise RuntimeError(
            f"Not enough rows for indicators: {len(df)}. Fetch more candles first."
        )

    df = df.copy()

    # Returns
    df.loc[:, "return"] = df["close"].pct_change()
    df.loc[:, "log_return"] = np.log(df["close"] / df["close"].shift(1))

    # EMAs / SMA
    close = df["close"].astype(float)
    volume = df["volume"].astype(float)
    df.loc[:, "ema_20"] = close.ewm(span=20, adjust=False).mean()
    df.loc[:, "ema_50"] = close.ewm(span=50, adjust=False).mean()
    df.loc[:, "sma_50"] = close.rolling(window=50).mean()

    # RSI
    df.loc[:, "rsi_14"] = calculate_rsi(df, period=14)

    # ATR
    atr_df = calculate_atr(df, period=14)
    df.loc[:, "atr_14"] = atr_df["atr"].values

    # MACD (safe)
    macd_df = calculate_macd(df, fast=12, slow=26, signal=9)
    df.loc[:, "macd"] = macd_df["macd_line"].values
    df.loc[:, "macd_signal"] = macd_df["macd_signal"].values
    df.loc[:, "macd_hist"] = macd_df["macd_hist"].values

    # Volume features
    df.loc[:, "vol_sma_20"] = volume.rolling(window=20).mean()
    df.loc[:, "vol_ratio"] = volume / df["vol_sma_20"].replace(0, np.nan)

    # Drop warmup NaNs (indicators start)
    required = ["open_time", "close", "ema_20", "ema_50", "rsi_14", "atr_14"]
    df = df.dropna(subset=required).reset_index(drop=True)

    if len(df) == 0:
        raise RuntimeError(
            "Features resulted in 0 rows. Likely not enough candles or indicator calc issue."
        )

    return df


def save(df: pd.DataFrame) -> None:
    df.to_parquet(OUT_PATH, index=False)
    print(f"✅ Features saved: {OUT_PATH}")
    print(f"📊 Rows: {len(df)} | Columns: {len(df.columns)}")


def run():
    df = load_raw()
    print(f"📦 Raw rows: {len(df)}")
    df = build_features(df)
    save(df)


if __name__ == "__main__":
    run()
