"""
Fetch raw OHLCV data from Binance API and save to parquet

This will create the raw data file that your feature generation script expects.

Usage:
    python scripts/fetch_binance_data.py
    python scripts/fetch_binance_data.py --symbol ETHUSDT --timeframe 4h --days 180
"""

import argparse
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
import requests
import time
from typing import List, Dict
import sys

from src.core.config import get_settings

settings = get_settings()


def fetch_binance_klines(
    symbol: str, interval: str, start_time: int, end_time: int, limit: int = 1000
) -> List[List]:
    """
    Fetch klines/candlestick data from Binance

    Args:
        symbol: Trading pair (e.g., 'BTCUSDT')
        interval: Kline interval (1m, 5m, 15m, 1h, 4h, 1d, etc.)
        start_time: Start timestamp in milliseconds
        end_time: End timestamp in milliseconds
        limit: Number of candles per request (max 1000)

    Returns:
        List of kline data
    """
    base_url = "https://api.binance.com/api/v3/klines"

    all_klines = []
    current_start = start_time

    print(f"\n📡 Fetching {symbol} {interval} data from Binance API...")
    print(f"   Start: {datetime.fromtimestamp(start_time/1000)}")
    print(f"   End:   {datetime.fromtimestamp(end_time/1000)}")

    request_count = 0

    while current_start < end_time:
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": current_start,
            "endTime": end_time,
            "limit": limit,
        }

        try:
            response = requests.get(base_url, params=params, timeout=30)
            response.raise_for_status()

            klines = response.json()

            if not klines:
                print("   No more data available")
                break

            all_klines.extend(klines)
            request_count += 1

            # Update start time for next batch
            current_start = klines[-1][0] + 1

            # Progress update every 5 requests
            if request_count % 5 == 0:
                print(
                    f"   Progress: {len(all_klines)} candles fetched ({request_count} requests)"
                )

            # Rate limiting - Binance allows 1200 requests per minute
            # We'll be conservative and do 2 requests per second
            time.sleep(0.5)

        except requests.exceptions.HTTPError as e:
            if response.status_code == 429:
                print("   ⚠️  Rate limit hit, waiting 60 seconds...")
                time.sleep(60)
                continue
            else:
                print(f"   ❌ HTTP Error: {e}")
                if all_klines:
                    print(f"   Partial data available: {len(all_klines)} candles")
                    break
                else:
                    raise

        except requests.exceptions.RequestException as e:
            print(f"   ❌ Request Error: {e}")
            if all_klines:
                print(f"   Partial data available: {len(all_klines)} candles")
                break
            else:
                raise

    print(f"✅ Fetched {len(all_klines)} candles total")
    return all_klines


def klines_to_dataframe(klines: List[List]) -> pd.DataFrame:
    """
    Convert Binance klines to DataFrame

    Binance kline format:
    [
        [
            1499040000000,      // 0: Open time
            "0.01634790",       // 1: Open
            "0.80000000",       // 2: High
            "0.01575800",       // 3: Low
            "0.01577100",       // 4: Close
            "148976.11427815",  // 5: Volume
            1499644799999,      // 6: Close time
            "2434.19055334",    // 7: Quote asset volume
            308,                // 8: Number of trades
            "1756.87402397",    // 9: Taker buy base asset volume
            "28.46694368",      // 10: Taker buy quote asset volume
            "17928899.62484339" // 11: Ignore
        ]
    ]
    """
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
            "quote_volume",
            "trades",
            "taker_buy_base_volume",
            "taker_buy_quote_volume",
            "ignore",
        ],
    )

    # Convert timestamp to datetime
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms")

    # Convert price and volume columns to numeric
    numeric_columns = [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_volume",
        "taker_buy_base_volume",
        "taker_buy_quote_volume",
    ]

    for col in numeric_columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["trades"] = pd.to_numeric(df["trades"], errors="coerce").astype("Int64")

    # Drop the 'ignore' column
    df = df.drop("ignore", axis=1)

    # Remove any rows with NaN in critical columns
    df = df.dropna(subset=["open_time", "open", "high", "low", "close", "volume"])

    # Sort by open_time
    df = df.sort_values("open_time").reset_index(drop=True)

    return df


def save_raw_data(df: pd.DataFrame, symbol: str, timeframe: str) -> Path:
    """Save raw data to parquet file"""
    raw_dir = Path(settings.data_dir) / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    output_path = raw_dir / f"{symbol}_{timeframe}.parquet"

    df.to_parquet(output_path, index=False, compression="snappy")

    print(f"\n✅ Raw data saved to: {output_path}")
    print(f"📊 Shape: {df.shape[0]} rows × {df.shape[1]} columns")
    print(f"📅 Date range: {df['open_time'].min()} to {df['open_time'].max()}")
    print(f"💾 File size: {output_path.stat().st_size / 1024:.2f} KB")

    return output_path


def validate_symbol(symbol: str) -> bool:
    """Validate that the symbol exists on Binance"""
    try:
        url = "https://api.binance.com/api/v3/exchangeInfo"
        response = requests.get(url, timeout=10)
        response.raise_for_status()

        data = response.json()
        symbols = [s["symbol"] for s in data["symbols"]]

        if symbol not in symbols:
            print(f"❌ Symbol '{symbol}' not found on Binance")
            print(f"   Available symbols: {len(symbols)} total")
            print(f"   Examples: BTCUSDT, ETHUSDT, BNBUSDT, ADAUSDT, DOGEUSDT")
            return False

        return True

    except Exception as e:
        print(f"⚠️  Could not validate symbol: {e}")
        print(f"   Proceeding anyway...")
        return True


def main():
    parser = argparse.ArgumentParser(description="Fetch OHLCV data from Binance")
    parser.add_argument(
        "--symbol",
        type=str,
        default="BTCUSDT",
        help="Trading pair symbol (default: BTCUSDT)",
    )
    parser.add_argument(
        "--timeframe",
        type=str,
        default="1h",
        help="Timeframe: 1m, 5m, 15m, 1h, 4h, 1d (default: 1h)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=90,
        help="Number of days of historical data (default: 90)",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Start date in YYYY-MM-DD format (overrides --days)",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="End date in YYYY-MM-DD format (default: now)",
    )

    args = parser.parse_args()

    # Validate symbol
    print(f"\n🔍 Validating symbol: {args.symbol}")
    if not validate_symbol(args.symbol):
        return 1

    # Calculate time range
    if args.end_date:
        end_time = datetime.strptime(args.end_date, "%Y-%m-%d")
    else:
        end_time = datetime.now()

    if args.start_date:
        start_time = datetime.strptime(args.start_date, "%Y-%m-%d")
    else:
        start_time = end_time - timedelta(days=args.days)

    # Convert to milliseconds
    start_ms = int(start_time.timestamp() * 1000)
    end_ms = int(end_time.timestamp() * 1000)

    try:
        # Fetch data
        klines = fetch_binance_klines(
            symbol=args.symbol,
            interval=args.timeframe,
            start_time=start_ms,
            end_time=end_ms,
        )

        if not klines:
            print("❌ No data fetched")
            return 1

        # Convert to DataFrame
        print("\n🔄 Converting to DataFrame...")
        df = klines_to_dataframe(klines)

        # Save to parquet
        output_path = save_raw_data(df, args.symbol, args.timeframe)

        # Show sample
        print("\n📋 Sample data (first 5 rows):")
        print(df.head()[["open_time", "open", "high", "low", "close", "volume"]])

        print(f"\n✅ SUCCESS! Raw data ready at: {output_path}")
        print(f"\n📝 Next steps:")
        print(f"   1. Run feature generation:")
        print(f"      python src/data_pipeline/build_features.py")
        print(f"   2. Start backtesting:")
        print(f"      POST /backtest/run")

        return 0

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
