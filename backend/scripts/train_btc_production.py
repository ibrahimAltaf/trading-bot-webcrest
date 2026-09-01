#!/usr/bin/env python3
"""
Train production BTC/USDT LSTM (5m or 15m), profit-based labels, save model + scaler.
Usage (from repo root):
  set PYTHONPATH=.
  python scripts/train_btc_production.py --interval 5m --limit 8000 --epochs 30
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import tensorflow as tf  # noqa: E402

from src.ml.dataset import (  # noqa: E402
    DEFAULT_LABEL_HORIZON,
    DEFAULT_PROFIT_THRESHOLD,
    apply_scaler,
    build_sequences,
    enrich_ohlcv_for_ml,
    fit_standard_scaler,
    profit_labels,
    train_val_split_time,
)
from src.ml.feature_columns import FEATURE_COLUMNS_PRODUCTION  # noqa: E402
from src.ml.model_builder import build_production_lstm  # noqa: E402
from src.ml.data_fetch import fetch_public_klines  # noqa: E402
from src.ml.train import compute_class_weights  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--interval", default="5m")
    ap.add_argument("--limit", type=int, default=8000)
    ap.add_argument("--lookback", type=int, default=50)
    ap.add_argument("--epochs", type=int, default=32)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument(
        "--out-dir",
        default="models/BTCUSDT_5m",
        help="Must match models/<SYMBOL>_<interval> for multi-coin resolution (ML_MODEL_DIR=models).",
    )
    ap.add_argument("--label-horizon", type=int, default=DEFAULT_LABEL_HORIZON)
    ap.add_argument("--profit-th", type=float, default=DEFAULT_PROFIT_THRESHOLD)
    args = ap.parse_args()

    out_dir = ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Fetching {args.limit} candles {args.symbol} {args.interval}...")
    df = fetch_public_klines(args.symbol, args.interval, args.limit)
    print("Enriching features...")
    df = enrich_ohlcv_for_ml(df)
    df = df.dropna()
    if len(df) < args.lookback + 500:
        raise SystemExit(f"Not enough rows after dropna: {len(df)}")

    close = df["close"].astype(float)
    y = profit_labels(
        close, horizon=args.label_horizon, threshold=args.profit_th
    )
    X, yy = build_sequences(df, y, args.lookback)
    print(f"Sequences: X={X.shape}, y={yy.shape}, class dist={np.bincount(yy, minlength=3)}")

    Xtr, ytr, Xva, yva = train_val_split_time(X, yy, val_ratio=0.2)
    scaler = fit_standard_scaler(Xtr)
    Xtr_s = apply_scaler(Xtr, scaler)
    Xva_s = apply_scaler(Xva, scaler)

    np.savez_compressed(
        out_dir / "dataset.npz",
        Xtr=Xtr_s,
        ytr=ytr,
        Xva=Xva_s,
        yva=yva,
    )

    n_features = X.shape[2]
    model = build_production_lstm(args.lookback, n_features)
    cw = compute_class_weights(ytr)

    cb = [
        tf.keras.callbacks.EarlyStopping(
            monitor="val_loss", patience=6, restore_best_weights=True
        ),
        tf.keras.callbacks.ReduceLROnPlateau(
            monitor="val_loss", factor=0.5, patience=3, min_lr=1e-6
        ),
    ]

    model.fit(
        Xtr_s,
        ytr,
        validation_data=(Xva_s, yva),
        epochs=args.epochs,
        batch_size=args.batch_size,
        class_weight=cw,
        callbacks=cb,
        verbose=1,
    )

    model.save(out_dir / "model.keras")

    (out_dir / "scaler.json").write_text(json.dumps(scaler, indent=2))
    try:
        import joblib

        joblib.dump(scaler, out_dir / "scaler.pkl")
    except Exception:
        pass

    meta = {
        "lookback": args.lookback,
        "n_features": n_features,
        "feature_columns": FEATURE_COLUMNS_PRODUCTION,
        "symbol": args.symbol,
        "interval": args.interval,
        "label_horizon": args.label_horizon,
        "profit_threshold": args.profit_th,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    # Flat file copies for deployment docs
    flat = ROOT / "models"
    flat.mkdir(exist_ok=True)
    shutil.copy2(out_dir / "model.keras", flat / "btc_lstm_model.keras")
    shutil.copy2(out_dir / "scaler.json", flat / "scaler.json")
    try:
        shutil.copy2(out_dir / "scaler.pkl", flat / "scaler.pkl")
    except Exception:
        pass

    print(f"Saved model to {out_dir} and copied to models/btc_lstm_model.keras")


if __name__ == "__main__":
    main()
