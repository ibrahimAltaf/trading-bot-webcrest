from datetime import datetime, timezone
import pandas as pd
from binance.client import Client
from src.core.config import get_settings

settings = get_settings()

# Don't initialize client at module level
_client = None

def get_client():
    """Lazy initialization of Binance client"""
    global _client
    if _client is None:
        _client = Client(
            api_key=settings.binance_api_key,
            api_secret=settings.binance_api_secret,
            testnet=settings.binance_testnet,
        )
    return _client

def get_latest_price(symbol: str) -> float:
    client = get_client()
    ticker = client.get_symbol_ticker(symbol=symbol)
    return float(ticker["price"])

def get_klines_df(symbol: str, interval: str = "1h", limit: int = 200) -> pd.DataFrame:
    """
    Returns OHLCV dataframe sorted by open_time ascending.
    limit must be >= lookback you use (e.g., 100).
    """
    client = get_client()
    klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)
    rows = []
    for k in klines:
        rows.append({
            "open_time": datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc).replace(tzinfo=None),
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
        })
    return pd.DataFrame(rows).sort_values("open_time").reset_index(drop=True)