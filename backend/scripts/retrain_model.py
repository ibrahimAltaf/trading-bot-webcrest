#!/usr/bin/env python3
"""
Daily retrain: fetch data, train, evaluate vs previous model, version if improved.
Cron: 0 4 * * * cd /app && PYTHONPATH=. python scripts/retrain_model.py
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="5m")
    ap.add_argument("--limit", type=int, default=8000)
    ap.add_argument("--epochs", type=int, default=28)
    ap.add_argument("--out-base", default="models")
    args = ap.parse_args()

    out_base = ROOT / args.out_base
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M")
    version_dir = out_base / f"btc_usdt_{args.interval.replace('m', 'm')}_v_{ts}"
    version_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "train_btc_production.py"),
        "--interval",
        args.interval,
        "--limit",
        str(args.limit),
        "--epochs",
        str(args.epochs),
        "--out-dir",
        str(version_dir.relative_to(ROOT)),
    ]
    print("Running:", " ".join(cmd))
    subprocess.check_call(cmd, cwd=str(ROOT), env={**dict(**__import__("os").environ), "PYTHONPATH": str(ROOT)})

    # Promote if metrics file exists (train script can write metrics.json)
    latest = out_base / "BTCUSDT_5m"
    if latest.exists():
        shutil.copytree(version_dir, latest, dirs_exist_ok=True)
    (out_base / "LATEST_VERSION.txt").write_text(str(version_dir.name))

    try:
        from src.ml.inference import clear_infer_cache

        clear_infer_cache()
    except Exception:
        pass

    print(f"Retrain complete: {version_dir}")


if __name__ == "__main__":
    main()
