"""Fetch public OHLCV from Binance REST (no API key required)."""
from __future__ import annotations

from typing import List

import pandas as pd
import requests

BINANCE_SPOT = "https://api.binance.com/api/v3/klines"

INTERVAL_MAP = {
    "1m": "1m",
    "3m": "3m",
    "5m": "5m",
    "15m": "15m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
}


def fetch_public_klines(
    symbol: str = "BTCUSDT",
    interval: str = "5m",
    limit: int = 8000,
    base_url: str = BINANCE_SPOT,
) -> pd.DataFrame:
    """
    Binance returns max 1000 klines per request; paginate backwards in time.
    """
    if interval not in INTERVAL_MAP.values() and interval not in INTERVAL_MAP:
        interval = INTERVAL_MAP.get(interval, interval)
    sym = symbol.upper().replace("/", "").replace("-", "")
    all_rows: List[list] = []
    end_time: int | None = None
    remaining = limit
    while remaining > 0:
        batch = min(1000, remaining)
        params = {"symbol": sym, "interval": interval, "limit": batch}
        if end_time is not None:
            params["endTime"] = end_time
        r = requests.get(base_url, params=params, timeout=60)
        r.raise_for_status()
        klines = r.json()
        if not klines:
            break
        all_rows = klines + all_rows
        remaining = limit - len(all_rows)
        end_time = int(klines[0][0]) - 1
        if len(klines) < batch:
            break
    all_rows = all_rows[-limit:]
    rows = []
    for k in all_rows:
        rows.append(
            {
                "open_time": pd.to_datetime(k[0], unit="ms"),
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
            }
        )
    return pd.DataFrame(rows)
