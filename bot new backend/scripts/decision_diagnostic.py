#!/usr/bin/env python3
"""
Read-only: aggregate TradingDecisionLog for ML / HOLD diagnostics (run on VPS with DATABASE_URL).
Usage: PYTHONPATH=. python scripts/decision_diagnostic.py [--limit N]
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from collections import Counter
from typing import Any, Dict, List, Optional

# Ensure project root on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import desc

from src.db.session import SessionLocal
from src.db.models import TradingDecisionLog


def _parse_signals(raw: Optional[str]) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=500)
    args = ap.parse_args()
    lim = max(1, min(5000, args.limit))

    if not os.getenv("DATABASE_URL", "").strip():
        print(
            json.dumps(
                {
                    "error": "DATABASE_URL not set",
                    "hint": "Run on the server with .env loaded, or: set DATABASE_URL=...",
                },
                indent=2,
            )
        )
        sys.exit(1)

    db = SessionLocal()
    try:
        rows: List[TradingDecisionLog] = (
            db.query(TradingDecisionLog)
            .order_by(desc(TradingDecisionLog.ts))
            .limit(lim)
            .all()
        )
    finally:
        db.close()

    if not rows:
        print(
            json.dumps(
                {
                    "step1": {
                        "total_cycles": 0,
                        "buy_count": 0,
                        "sell_count": 0,
                        "hold_count": 0,
                        "ml_used_percentage": None,
                        "avg_confidence_variation": None,
                    },
                    "note": "no rows in trading_decisions",
                },
                indent=2,
            )
        )
        return

    buy_c = sell_c = hold_c = 0
    ml_rows = 0
    confidences: List[float] = []
    final_sources: Counter[str] = Counter()
    gate_fail_counter: Counter[str] = Counter()
    ml_ok_false = 0
    exec_ineligible = 0
    example_cycle: Optional[Dict[str, Any]] = None

    for r in rows:
        sig = _parse_signals(r.signals_json)
        action = (r.action or "").upper()
        if action == "BUY":
            buy_c += 1
        elif action == "SELL":
            sell_c += 1
        else:
            hold_c += 1

        c = float(r.confidence) if r.confidence is not None else None
        if c is not None and c == c:
            confidences.append(c)

        env = sig.get("cycle_envelope") or {}
        fs = env.get("final_source") or sig.get("final_source") or sig.get(
            "cycle_debug", {}
        ).get("final_source")
        if fs:
            final_sources[str(fs)] += 1

        if (
            sig.get("ml_status") == "ok"
            or sig.get("ml_prediction")
            or sig.get("ml_signal") is not None
        ):
            ml_rows += 1

        gates = env.get("gates") or {}
        if gates.get("ml_ok") is False:
            ml_ok_false += 1
        failed = env.get("block_reason") or []
        if isinstance(failed, list):
            for f in failed:
                if isinstance(f, str) and f.startswith("gate:"):
                    gate_fail_counter[f.replace("gate:", "")] += 1

        ce = env.get("execution_eligible")
        if ce is False:
            exec_ineligible += 1
            if example_cycle is None and action == "HOLD":
                example_cycle = {
                    "ts": r.ts.isoformat() if r.ts else None,
                    "action": r.action,
                    "final_source": fs,
                    "gates": gates,
                    "block_reason": env.get("block_reason"),
                    "cycle_envelope": env,
                }

    total = len(rows)
    ml_pct = round(100.0 * ml_rows / total, 2) if total else 0.0
    conf_var = 0.0
    if len(confidences) >= 2:
        conf_var = float(statistics.pstdev(confidences))

    # Gate blocking: count failed gate keys from envelope
    gate_key_fails: Counter[str] = Counter()
    for r in rows:
        sig = _parse_signals(r.signals_json)
        env = sig.get("cycle_envelope") or {}
        g = env.get("gates") or {}
        for k, v in g.items():
            if v is False:
                gate_key_fails[k] += 1

    top_gate = None
    block_pct = None
    if gate_key_fails:
        top_gate, cnt = gate_key_fails.most_common(1)[0]
        block_pct = round(100.0 * cnt / total, 2)

    if example_cycle is None and rows:
        r = rows[0]
        sig = _parse_signals(r.signals_json)
        example_cycle = {
            "ts": r.ts.isoformat() if r.ts else None,
            "action": r.action,
            "cycle_envelope": sig.get("cycle_envelope"),
            "cycle_debug": sig.get("cycle_debug"),
        }

    out = {
        "step1": {
            "total_cycles": total,
            "buy_count": buy_c,
            "sell_count": sell_c,
            "hold_count": hold_c,
            "ml_used_percentage": ml_pct,
            "avg_confidence_variation": round(conf_var, 6),
            "sample_size": len(confidences),
            "final_source_distribution": dict(final_sources),
        },
        "step2": {
            "top_blocking_gate": top_gate,
            "block_percentage": block_pct,
            "gate_fail_counts_by_key": dict(gate_key_fails),
            "cycles_with_ml_ok_false": ml_ok_false,
            "cycles_with_execution_eligible_false": exec_ineligible,
            "example_cycle": example_cycle,
        },
    }
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
