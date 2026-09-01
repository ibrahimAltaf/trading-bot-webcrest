from __future__ import annotations

import argparse
from pathlib import Path
import sys
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data_pipeline.fetch_ohlcv import run_one as fetch_one
from src.features.build_features import run_one as build_features_one
from src.ml.dataset import DatasetConfig, prepare_from_parquet
from src.ml.train import train as train_model
from src.ml.inference import get_infer


def _parse_csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def run_pipeline(
    symbols: list[str],
    timeframes: list[str],
    limit: int,
    model_base: Path,
    lookback: int,
    thr: float,
    epochs: int,
    batch_size: int,
    infer_rows: int,
    do_infer: bool,
) -> None:
    for symbol in symbols:
        for timeframe in timeframes:
            print(f"\n=== {symbol} {timeframe} ===")

            fetch_one(symbol, timeframe, limit)
            features_path = build_features_one(symbol, timeframe)

            model_dir = model_base / f"{symbol}_{timeframe}"
            cfg = DatasetConfig(lookback=lookback, thr=thr, out_dir=str(model_dir))
            dataset_path = prepare_from_parquet(str(features_path), cfg)
            print(f"Dataset: {dataset_path}")

            metrics = train_model(
                model_dir=str(model_dir), epochs=epochs, batch_size=batch_size
            )
            print(f"Metrics: {metrics}")

            if do_infer:
                df = pd.read_parquet(features_path)
                infer = get_infer(str(model_dir))
                pred = infer.predict_window(df.tail(infer_rows))
                print(f"Infer: {pred}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="BTCUSDT,ETHUSDT")
    ap.add_argument("--timeframes", default="1h,4h,1d")
    ap.add_argument("--limit", type=int, default=15000)
    ap.add_argument("--model_base", default="models/lstm_v1")
    ap.add_argument("--lookback", type=int, default=100)
    ap.add_argument("--thr", type=float, default=0.015)
    ap.add_argument("--epochs", type=int, default=50)
    ap.add_argument("--batch_size", type=int, default=32)
    ap.add_argument("--infer_rows", type=int, default=150)
    ap.add_argument("--no_infer", action="store_true")
    args = ap.parse_args()

    symbols = _parse_csv(args.symbols)
    timeframes = _parse_csv(args.timeframes)
    model_base = Path(args.model_base)

    run_pipeline(
        symbols=symbols,
        timeframes=timeframes,
        limit=args.limit,
        model_base=model_base,
        lookback=args.lookback,
        thr=args.thr,
        epochs=args.epochs,
        batch_size=args.batch_size,
        infer_rows=args.infer_rows,
        do_infer=not args.no_infer,
    )


if __name__ == "__main__":
    main()
