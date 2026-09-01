#!/usr/bin/env python3
"""
Export Phase 2A shadow soak evidence from the database to JSON files.

Usage (on machine with DATABASE_URL pointing at the ORIGINAL soak DB):

    cd "bot new backend"
    export PYTHONPATH=.
    export DATABASE_URL='postgresql+psycopg2://...'
    python scripts/export_shadow_soak_evidence.py --days 7 --symbol BTCUSDT --out ./soak-evidence

Outputs:
    soak-evidence/shadow_soak_closeout.json   (full close-out payload)
    soak-evidence/shadow_orders.json
    soak-evidence/shadow_positions.json
    soak-evidence/shadow_orders_origin_summary.json
    soak-evidence/shadow_pnl_summary.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Export shadow soak evidence JSON")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--symbol", type=str, default="BTCUSDT")
    parser.add_argument("--out", type=str, default="./soak-evidence")
    parser.add_argument(
        "--dated",
        action="store_true",
        help="Append UTC date subfolder (YYYY-MM-DD) under --out",
    )
    args = parser.parse_args()

    if not os.getenv("DATABASE_URL", "").strip():
        print("ERROR: DATABASE_URL is not set", file=sys.stderr)
        return 1

    from src.api.routes_safety import _build_shadow_soak_report
    from src.db.session import SessionLocal

    db = SessionLocal()
    try:
        report = _build_shadow_soak_report(
            db=db,
            symbol=args.symbol.strip().upper() or None,
            days=args.days,
            order_limit=1000,
        )
    finally:
        db.close()

    out_root = Path(args.out)
    if args.dated:
        out_dir = out_root / datetime.now(timezone.utc).strftime("%Y-%m-%d")
    else:
        out_dir = out_root
    out_dir.mkdir(parents=True, exist_ok=True)

    slices = {
        "shadow_soak_closeout.json": report,
        "shadow_orders.json": {
            "ok": report.get("ok"),
            "symbol_filter": report.get("symbol_filter"),
            "window_days": report.get("window_days"),
            "shadow_orders": report.get("shadow_orders", []),
        },
        "shadow_positions.json": {
            "ok": report.get("ok"),
            "shadow_positions_open": report.get("shadow_positions_open", []),
            "shadow_positions_history": report.get("shadow_positions_history", []),
        },
        "shadow_orders_origin_summary.json": report.get(
            "shadow_orders_origin_summary", {}
        ),
        "shadow_pnl_summary.json": report.get("shadow_pnl_summary", {}),
    }

    for name, payload in slices.items():
        path = out_dir / name
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {path}")

    manifest = {
        "exported_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": args.symbol.strip().upper(),
        "window_days": args.days,
        "output_dir": str(out_dir),
        "shadow_order_count": len(report.get("shadow_orders", [])),
        "shadow_orders_origin_summary": report.get("shadow_orders_origin_summary"),
        "files": list(slices.keys()),
    }
    manifest_path = out_dir / "export_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {manifest_path}")

    print(
        f"done: orders={len(report.get('shadow_orders', []))} "
        f"origin={report.get('shadow_orders_origin_summary')}"
    )
    return 0 if report.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
