#!/usr/bin/env python3
"""
Train one LSTM per supported symbol; artifacts under models/<SYMBOL>_<interval>/.

Usage (repo root):
  set PYTHONPATH=.
  python scripts/train_multi_coin.py --interval 5m --limit 8000 --epochs 28
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.symbols import parse_supported_trading_symbols  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="5m")
    ap.add_argument("--limit", type=int, default=8000)
    ap.add_argument("--lookback", type=int, default=50)
    ap.add_argument("--epochs", type=int, default=28)
    ap.add_argument("--batch-size", type=int, default=32)
    args = ap.parse_args()

    symbols = parse_supported_trading_symbols()
    script = ROOT / "scripts" / "train_btc_production.py"
    if not script.is_file():
        raise SystemExit(f"Missing {script}")

    for sym in symbols:
        # Match src.ml.model_selector resolve_model_selection model_key: SYMBOL_TIMEFRAME
        model_key = f"{sym.upper()}_{args.interval}"
        out_dir = ROOT / "models" / model_key
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n=== Training {sym} -> {out_dir} ===\n")
        cmd = [
            sys.executable,
            str(script),
            "--symbol",
            sym,
            "--interval",
            args.interval,
            "--limit",
            str(args.limit),
            "--lookback",
            str(args.lookback),
            "--epochs",
            str(args.epochs),
            "--batch-size",
            str(args.batch_size),
            "--out-dir",
            str(out_dir.relative_to(ROOT)),
        ]
        subprocess.run(cmd, cwd=str(ROOT), check=True)

    print(
        "\nDone. Artifacts: models/<SYMBOL>_<interval>/{model.keras,scaler.json,meta.json}. "
        "For multi-coin live resolution, set ML_MODEL_DIR=models (parent folder)."
    )


if __name__ == "__main__":
    main()
