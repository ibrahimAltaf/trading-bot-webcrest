#!/usr/bin/env python3
"""CLI: write stub LSTM artifacts under models/<SYMBOL>_<interval>/ (no network)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ml.bootstrap_stub_models import ensure_stub_models  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default=None, help="default: TRADE_TIMEFRAME or 5m")
    ap.add_argument("--lookback", type=int, default=None)
    ap.add_argument(
        "--force",
        action="store_true",
        help="overwrite even if artifacts already exist",
    )
    args = ap.parse_args()

    n, paths = ensure_stub_models(
        timeframe=args.interval,
        lookback=args.lookback,
        force=args.force,
    )
    print(f"bootstrap_phase1_models: wrote {n} dir(s)")
    for p in paths:
        print(" ", p)


if __name__ == "__main__":
    main()
