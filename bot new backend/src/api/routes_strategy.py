"""
Strategy API – exposes adaptive engine state for the dashboard.

GET /strategy/adaptive?symbol=BTCUSDT&timeframe=1h
Returns: vol_bucket, trend_bucket, params, meta (price, adx, atr, atr_pct).
Used by the frontend "Adaptive Engine" page.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Dict

import pandas as pd
from fastapi import APIRouter, HTTPException

from src.core.config import get_settings
from src.exchange.binance_spot_client import BinanceSpotClient
from src.live.fully_adaptive_strategy import AdaptiveParams, FullyAdaptiveStrategy

router = APIRouter(tags=["strategy"])


def _klines_to_df(klines: list) -> pd.DataFrame:
    """Build OHLCV DataFrame from Binance klines (list of lists)."""
    if not klines:
        return pd.DataFrame()
    df = pd.DataFrame(
        klines,
        columns=[
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "qav",
            "num_trades",
            "taker_base",
            "taker_quote",
            "ignore",
        ],
    )
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    return df


def _params_to_dict(p: AdaptiveParams) -> Dict[str, Any]:
    return dataclasses.asdict(p)


@router.get("/adaptive")
def get_adaptive_state(symbol: str = "BTCUSDT", timeframe: str = "1h") -> Dict[str, Any]:
    """
    Return current Fully Adaptive Engine state for the given symbol and timeframe.

    Uses live klines from Binance, runs the same two-pass logic as the live engine,
    and returns vol_bucket, trend_bucket, params, and meta for the dashboard.
    """
    symbol = (symbol or "BTCUSDT").strip().upper()
    timeframe = (timeframe or "1h").strip().lower()

    try:
        client = BinanceSpotClient()
        raw = client.klines(symbol=symbol, interval=timeframe, limit=500)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch klines: {e!s}",
        ) from e

    if not raw or not isinstance(raw, list):
        raise HTTPException(
            status_code=502,
            detail="No klines data returned",
        )

    df = _klines_to_df(raw)
    if df.empty or len(df) < 50:
        raise HTTPException(
            status_code=400,
            detail=f"Not enough candles (got {len(df)}, need at least 50)",
        )

    try:
        settings = get_settings()
        strategy = FullyAdaptiveStrategy(settings)
        df2, params, meta = strategy._two_pass(df)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Adaptive state failed: {e!s}",
        ) from e

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "vol_bucket": meta.get("vol_bucket"),
        "trend_bucket": meta.get("trend_bucket"),
        "params": _params_to_dict(params),
        "meta": {
            "price": meta.get("price"),
            "adx": meta.get("adx"),
            "atr": meta.get("atr"),
            "atr_pct": meta.get("atr_pct"),
        },
    }
