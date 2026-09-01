"""
Technical Indicators for Adaptive Trading Strategy

Provides indicators required for regime detection and signal generation:
- ADX (Average Directional Index) - trend strength
- Bollinger Bands - volatility and mean-reversion levels
- ATR (Average True Range) - volatility for stop-loss sizing
- EMAs, RSI - already in build_features_from_klines
"""

import pandas as pd
import numpy as np


def calculate_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """
    Calculate ADX (Average Directional Index) for trend strength detection.

    ADX > 25 typically indicates trending market
    ADX < 25 typically indicates ranging market

    Returns DataFrame with columns: +DI, -DI, DX, ADX
    """
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)

    # True Range
    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()

    # Directional Movement
    up = high - high.shift()
    down = low.shift() - low

    plus_dm = np.where((up > down) & (up > 0), up, 0)
    minus_dm = np.where((down > up) & (down > 0), down, 0)

    plus_dm_smooth = pd.Series(plus_dm).rolling(window=period).mean()
    minus_dm_smooth = pd.Series(minus_dm).rolling(window=period).mean()

    # Directional Indicators
    plus_di = 100 * (plus_dm_smooth / atr)
    minus_di = 100 * (minus_dm_smooth / atr)

    # DX and ADX
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = dx.rolling(window=period).mean()

    result = df.copy()
    result["plus_di"] = plus_di
    result["minus_di"] = minus_di
    result["adx"] = adx

    return result


def calculate_bollinger_bands(
    df: pd.DataFrame, period: int = 20, std_dev: float = 2.0
) -> pd.DataFrame:
    """
    Calculate Bollinger Bands for mean-reversion signals in ranging markets.

    Returns DataFrame with columns: bb_upper, bb_middle, bb_lower, bb_width
    """
    close = df["close"].astype(float)

    middle = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()

    upper = middle + (std * std_dev)
    lower = middle - (std * std_dev)
    width = (upper - lower) / middle * 100  # width as % of price

    result = df.copy()
    result["bb_upper"] = upper
    result["bb_middle"] = middle
    result["bb_lower"] = lower
    result["bb_width"] = width

    return result


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """
    Calculate ATR (Average True Range) for volatility-based stop loss sizing.

    Returns DataFrame with column: atr
    """
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)

    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.rolling(window=period).mean()
    atr_pct = (atr / close) * 100  # ATR as % of price

    result = df.copy()
    result["atr"] = atr
    result["atr_pct"] = atr_pct

    return result


def calculate_ema(df: pd.DataFrame, period: int) -> pd.Series:
    """
    Calculate Exponential Moving Average.
    """
    return df["close"].astype(float).ewm(span=period, adjust=False).mean()


def calculate_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Calculate RSI (Relative Strength Index).

    RSI > 70: overbought
    RSI < 30: oversold
    """
    close = df["close"].astype(float)
    delta = close.diff()

    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))

    return rsi


def calculate_macd(
    df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.DataFrame:
    """
    Calculate MACD (Moving Average Convergence Divergence).

    MACD is a trend-following momentum indicator that shows the relationship
    between two moving averages of a security's price.

    Returns:
        DataFrame with columns: macd_line, macd_signal, macd_hist
    """
    close = df["close"].astype(float)

    # Calculate EMAs
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()

    # MACD Line = Fast EMA - Slow EMA
    macd_line = ema_fast - ema_slow

    # Signal Line = 9-period EMA of MACD Line
    macd_signal_line = macd_line.ewm(span=signal, adjust=False).mean()

    # MACD Histogram = MACD Line - Signal Line
    macd_hist = macd_line - macd_signal_line

    result = df.copy()
    result["macd_line"] = macd_line
    result["macd_signal"] = macd_signal_line
    result["macd_hist"] = macd_hist

    return result


def add_all_indicators(df: pd.DataFrame, config: dict = None) -> pd.DataFrame:
    """
    Add all indicators to a DataFrame for adaptive trading.

    Args:
        df: DataFrame with OHLCV data
        config: Optional dict with indicator parameters
            {
                'ema_fast': 20,
                'ema_slow': 50,
                'rsi_period': 14,
                'adx_period': 14,
                'bb_period': 20,
                'bb_std': 2.0,
                'atr_period': 14
            }

    Returns:
        DataFrame with all indicators added
    """
    if config is None:
        config = {}

    ema_fast = config.get("ema_fast", 20)
    ema_slow = config.get("ema_slow", 50)
    rsi_period = config.get("rsi_period", 14)
    adx_period = config.get("adx_period", 14)
    bb_period = config.get("bb_period", 20)
    bb_std = config.get("bb_std", 2.0)
    atr_period = config.get("atr_period", 14)
    macd_fast = config.get("macd_fast", 12)
    macd_slow = config.get("macd_slow", 26)
    macd_signal = config.get("macd_signal", 9)

    # Ensure required columns exist
    required_cols = ["open", "high", "low", "close", "volume"]
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"Missing required column: {col}")

    # Convert to float (use .loc to avoid pandas FutureWarning / chained assignment)
    for col in ["open", "high", "low", "close", "volume"]:
        df.loc[:, col] = df[col].astype(float)

    # EMAs
    df.loc[:, f"ema_{ema_fast}"] = calculate_ema(df, ema_fast)
    df.loc[:, f"ema_{ema_slow}"] = calculate_ema(df, ema_slow)

    # RSI
    df.loc[:, f"rsi_{rsi_period}"] = calculate_rsi(df, rsi_period)

    # MACD (trend and momentum)
    df = calculate_macd(df, macd_fast, macd_slow, macd_signal)
    # ML feature alias: 'macd' (build_features.py uses 'macd', not 'macd_line')
    df.loc[:, "macd"] = df["macd_line"].values

    # ADX (trend strength)
    df = calculate_adx(df, adx_period)

    # Bollinger Bands (mean reversion)
    df = calculate_bollinger_bands(df, bb_period, bb_std)

    # ATR (volatility)
    df = calculate_atr(df, atr_period)
    # ML feature alias: 'atr_14' and volume features used by inference
    df.loc[:, "atr_14"] = df["atr"].values
    df.loc[:, "vol_sma_20"] = df["volume"].rolling(window=20).mean().values
    df.loc[:, "vol_ratio"] = (df["volume"] / df["vol_sma_20"].replace(0, float("nan"))).values

    return df.dropna()
