from __future__ import annotations

from pathlib import Path
import pandas as pd
from binance.client import Client

from src.core.config import get_settings

settings = get_settings()

SYMBOL = "BTCUSDT"
TIMEFRAME = "1h"  
LIMIT = 10000

INTERVAL_MAP = {
    "1h": Client.KLINE_INTERVAL_1HOUR,
    "4h": Client.KLINE_INTERVAL_4HOUR,
    "15m": Client.KLINE_INTERVAL_15MINUTE,
    "1d": Client.KLINE_INTERVAL_1DAY,
}


def fetch_ohlcv(symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    print(f"📥 Fetching {limit} candles from Binance (batches of 1000)...")

    client = Client()
    interval = INTERVAL_MAP.get(timeframe)
    if not interval:
        raise ValueError(f"Unsupported timeframe: {timeframe}")

    # Binance API limit is 1000 per request, so fetch in batches
    # Fetch backwards from now, then reverse to get chronological order
    all_klines = []
    batch_size = 1000
    end_time = None  # None means "now"
    
    while len(all_klines) < limit:
        klines = client.get_klines(
            symbol=symbol, 
            interval=interval, 
            limit=batch_size,
            endTime=end_time
        )
        
        if not klines:
            break
        
        # Add in reverse order to build oldest→newest
        all_klines = klines + all_klines
        print(f"  ✓ Fetched {len(klines)} candles (total: {len(all_klines)})")
        
        if len(klines) < batch_size:
            break  # Reached the beginning of history
        
        # Next batch: fetch before the earliest candle we have
        end_time = klines[0][0] - 1

    # Trim to exact limit, keeping the most recent candles
    all_klines = all_klines[-limit:]

    # Binance kline format:
    # [
    #  0 open_time, 1 open, 2 high, 3 low, 4 close, 5 volume,
    #  6 close_time, 7 quote_asset_volume, 8 num_trades,
    #  9 taker_buy_base, 10 taker_buy_quote, 11 ignore
    # ]
    rows = []
    for k in klines:
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

    df = pd.DataFrame(rows)
    df = df.sort_values("open_time").reset_index(drop=True)
    return df


def run():
    df = fetch_ohlcv(SYMBOL, TIMEFRAME, LIMIT)
    print("🔍 Validating data...")

    if len(df) < 60:
        raise RuntimeError(f"Not enough candles fetched: {len(df)}. Expected at least 60+.")

    out_dir = Path(settings.data_dir) / "raw"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{SYMBOL}_{TIMEFRAME}.parquet"

    df.to_parquet(out_path, index=False)
    print(f"✅ Saved: {out_path}")
    print(f"📊 Rows: {len(df)}")


if __name__ == "__main__":
    run()
