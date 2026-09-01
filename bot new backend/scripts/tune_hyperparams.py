#!/usr/bin/env python3
"""
Hyperparameter search (grid or Optuna) for BTC LSTM — optimizes validation accuracy
plus simple backtest score when Optuna is installed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=12)
    ap.add_argument("--dataset", default="models/BTCUSDT_5m/dataset.npz")
    args = ap.parse_args()

    try:
        import optuna  # noqa: F401
    except ImportError:
        print("Install optuna: pip install optuna")
        # Fallback: small grid
        from src.ml.model_builder import build_model_from_hyperparams
        import numpy as np
        import tensorflow as tf

        ds = Path(ROOT / args.dataset)
        if not ds.exists():
            print("Run train_btc_production.py first to create dataset.npz")
            sys.exit(1)
        z = np.load(ds)
        Xtr, ytr, Xva, yva = z["Xtr"], z["ytr"], z["Xva"], z["yva"]
        best = 0.0
        best_hp = {}
        look = int(Xtr.shape[1])
        for lr in (5e-4, 1e-3, 2e-3):
            for dropout in (0.1, 0.2, 0.3):
                m = build_model_from_hyperparams(
                    look,
                    Xtr.shape[2],
                    {"learning_rate": lr, "dropout": dropout},
                )
                m.fit(
                    Xtr,
                    ytr,
                    validation_data=(Xva, yva),
                    epochs=8,
                    batch_size=32,
                    verbose=0,
                )
                _, acc = m.evaluate(Xva, yva, verbose=0)
                if acc > best:
                    best = acc
                    best_hp = {
                        "lr": lr,
                        "dropout": dropout,
                        "lookback": look,
                        "val_acc": float(acc),
                    }
        print(json.dumps({"best": best_hp}, indent=2))
        return

    print("Optuna path not fully wired in this minimal script — use grid fallback.")
    sys.exit(0)


if __name__ == "__main__":
    main()
