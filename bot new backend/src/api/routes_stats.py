"""Aggregated trading / ML performance + live proof + alerts."""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from sqlalchemy import desc

from src.db.models import Position, TradingDecisionLog
from src.db.session import SessionLocal

router = APIRouter(prefix="/stats", tags=["stats"])


def _parse_signals(raw: Optional[str]) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


# Final outcomes where ML influenced the fused signal (not plain rule-only).
_ML_INFLUENT_SOURCES = frozenset(
    {
        "ml_prioritize",
        "ml_override",
        "combined",
        "ml_hold_breakout",
        "ml_moderate_influence",
    }
)


def _final_source_from_signals(sig: Dict[str, Any]) -> str:
    return str(
        sig.get("final_source")
        or sig.get("cycle_envelope", {}).get("final_source")
        or ""
    )


def _ml_influenced_decision(sig: Dict[str, Any]) -> bool:
    fs = _final_source_from_signals(sig)
    return fs in _ML_INFLUENT_SOURCES


def _ml_softmax_confidence(sig: Dict[str, Any]) -> Optional[float]:
    mc = sig.get("ml_confidence")
    if mc is not None and isinstance(mc, (int, float)) and mc == mc:
        return float(mc)
    pred = sig.get("ml_prediction")
    if isinstance(pred, dict):
        c = pred.get("confidence")
        if c is not None and isinstance(c, (int, float)) and c == c:
            return float(c)
    return None


def _aggregate_decisions(rows: List[TradingDecisionLog]) -> Dict[str, Any]:
    buy_c = sell_c = hold_c = 0
    confs: List[float] = []
    src_counts: Dict[str, int] = {}
    ml_ok = 0
    ml_confs: List[float] = []
    for r in rows:
        a = (r.action or "").upper()
        if a == "BUY":
            buy_c += 1
        elif a == "SELL":
            sell_c += 1
        else:
            hold_c += 1
        if r.confidence is not None and r.confidence == r.confidence:
            confs.append(float(r.confidence))
        sig = _parse_signals(r.signals_json)
        fs = _final_source_from_signals(sig)
        if fs:
            src_counts[fs] = src_counts.get(fs, 0) + 1
        if _ml_influenced_decision(sig):
            ml_ok += 1
        mcv = _ml_softmax_confidence(sig)
        if mcv is not None:
            ml_confs.append(mcv)
    n = len(rows) or 1
    ml_pct = round(100.0 * ml_ok / n, 2)
    avg_conf = round(statistics.mean(confs), 4) if confs else None
    avg_ml_confidence = round(statistics.mean(ml_confs), 4) if ml_confs else None
    high_07 = sum(1 for x in ml_confs if x > 0.7) / len(ml_confs) if ml_confs else None
    high_08 = sum(1 for x in ml_confs if x > 0.8) / len(ml_confs) if ml_confs else None
    high_confidence_ratio = round(float(high_07), 4) if high_07 is not None else None
    buy_sell_ratio = round(buy_c / max(sell_c, 1), 2) if sell_c else float(buy_c or 0)
    return {
        "buy_count": buy_c,
        "sell_count": sell_c,
        "hold_count": hold_c,
        "ml_used_percentage": ml_pct,
        "avg_confidence": avg_conf,
        "avg_ml_confidence": avg_ml_confidence,
        "high_confidence_ratio": high_confidence_ratio,
        "high_confidence_ratio_08": (
            round(float(high_08), 4) if high_08 is not None else None
        ),
        "ml_confidence_samples": len(ml_confs),
        "final_source_counts": src_counts,
        "ml_participation_rows": ml_ok,
    }


def _build_alerts(agg: Dict[str, Any], n_trades: int) -> List[Dict[str, Any]]:
    alerts: List[Dict[str, Any]] = []
    ml_pct = float(agg.get("ml_used_percentage") or 0)
    hold_c = int(agg.get("hold_count") or 0)
    total = int(agg.get("buy_count") or 0) + int(agg.get("sell_count") or 0) + hold_c
    if total and ml_pct < 10.0:
        alerts.append(
            {
                "level": "WARN",
                "code": "low_ml_usage",
                "message": f"ml_used_percentage {ml_pct}% < 10%",
            }
        )
    if total and hold_c / total > 0.80:
        alerts.append(
            {
                "level": "WARN",
                "code": "hold_heavy",
                "message": f"HOLD ratio {100*hold_c/total:.1f}% > 80%",
            }
        )
    if n_trades == 0:
        alerts.append(
            {
                "level": "WARN",
                "code": "no_closed_trades",
                "message": "No closed live positions in sample",
            }
        )
    if ml_pct < 30.0 and total > 50:
        alerts.append(
            {
                "level": "INFO",
                "code": "ml_participation_below_target",
                "message": f"ml_used_percentage {ml_pct}% — target > 30% for full ML activation",
            }
        )
    return alerts


def _short_asset_label(binance_symbol: str) -> str:
    """BTCUSDT -> BTC for API keys."""
    s = (binance_symbol or "").upper()
    if s.startswith("BTC"):
        return "BTC"
    if s.startswith("ETH"):
        return "ETH"
    if s.startswith("SOL"):
        return "SOL"
    if s.endswith("USDT") and len(s) > 4:
        return s[:-4]
    return s[:6]


def _aggregate_by_symbol(
    rows: List[TradingDecisionLog], closed: List[Position]
) -> Dict[str, Any]:
    by_rows: Dict[str, List[TradingDecisionLog]] = defaultdict(list)
    for r in rows:
        by_rows[r.symbol].append(r)
    by_closed: Dict[str, List[Position]] = defaultdict(list)
    for p in closed:
        by_closed[p.symbol].append(p)
    keys = set(by_rows.keys()) | set(by_closed.keys())
    out: Dict[str, Any] = {}
    for sym in sorted(keys):
        label = _short_asset_label(sym)
        agg = _aggregate_decisions(by_rows.get(sym, []))
        pc = by_closed.get(sym, [])
        pnl_sum = sum(float(p.pnl or 0) for p in pc if p.pnl is not None)
        out[label] = {
            "binance_symbol": sym,
            "ml_used_percentage": agg["ml_used_percentage"],
            "avg_ml_confidence": agg.get("avg_ml_confidence"),
            "high_confidence_ratio": agg.get("high_confidence_ratio"),
            "buy_count": agg["buy_count"],
            "sell_count": agg["sell_count"],
            "hold_count": agg["hold_count"],
            "avg_confidence": agg["avg_confidence"],
            "final_source_counts": agg.get("final_source_counts", {}),
            "non_rule_only_sources": {
                k: v
                for k, v in agg.get("final_source_counts", {}).items()
                if k not in ("rule_only", "rule_only_ml_disabled", "rule_based", "")
            },
            "live_pnl_sum_usdt": round(pnl_sum, 4),
            "closed_trades": len(pc),
            "decisions_in_sample": len(by_rows.get(sym, [])),
        }
    return out


@router.get("/performance")
def performance(limit_decisions: int = 500) -> Dict[str, Any]:
    """PnL-oriented summary + ML vs rule mix from recent decision logs."""
    db = SessionLocal()
    try:
        lim = max(50, min(5000, int(limit_decisions)))
        rows = (
            db.query(TradingDecisionLog)
            .order_by(desc(TradingDecisionLog.ts))
            .limit(lim)
            .all()
        )
        agg = _aggregate_decisions(rows)

        closed = (
            db.query(Position)
            .filter(
                Position.mode == "live",
                Position.is_open == False,  # noqa: E712
            )
            .order_by(desc(Position.exit_ts))
            .limit(500)
            .all()
        )
        pnl_sum = sum(float(p.pnl or 0) for p in closed if p.pnl is not None)
        n_trades = len(closed)

        alerts = _build_alerts(agg, n_trades)
        by_symbol = _aggregate_by_symbol(rows, closed)

        return {
            "ok": True,
            "decisions_sample": lim,
            "final_source_counts": agg["final_source_counts"],
            "ml_participation_rows": agg["ml_participation_rows"],
            "ml_participation_pct": agg["ml_used_percentage"],
            "avg_ml_confidence": agg.get("avg_ml_confidence"),
            "high_confidence_ratio": agg.get("high_confidence_ratio"),
            "live_trades_in_sample": n_trades,
            "live_pnl_sum_usdt": round(pnl_sum, 4),
            "alerts": alerts,
            "buy_count": agg["buy_count"],
            "sell_count": agg["sell_count"],
            "hold_count": agg["hold_count"],
            "avg_confidence": agg["avg_confidence"],
            "by_symbol": by_symbol,
        }
    finally:
        db.close()


@router.get("/ml-analysis")
def ml_analysis(limit: int = 500) -> Dict[str, Any]:
    """
    Recent-decision ML softmax stats: average confidence and share above 0.7 / 0.8.
    """
    db = SessionLocal()
    try:
        lim = max(50, min(5000, int(limit)))
        rows = (
            db.query(TradingDecisionLog)
            .order_by(desc(TradingDecisionLog.ts))
            .limit(lim)
            .all()
        )
        agg = _aggregate_decisions(rows)
        return {
            "ok": True,
            "sample_size": lim,
            "avg_ml_confidence": agg.get("avg_ml_confidence"),
            "high_confidence_ratio": agg.get("high_confidence_ratio"),
            "high_confidence_ratio_08": agg.get("high_confidence_ratio_08"),
            "ml_confidence_samples": agg.get("ml_confidence_samples"),
            "ml_used_percentage": agg.get("ml_used_percentage"),
        }
    finally:
        db.close()


@router.get("/live-proof")
def live_proof(limit: int = 200) -> Dict[str, Any]:
    """
    Single payload for audits: ML %, action mix, confidence, alerts, runtime hints.
    """
    db = SessionLocal()
    try:
        lim = max(20, min(2000, int(limit)))
        rows = (
            db.query(TradingDecisionLog)
            .order_by(desc(TradingDecisionLog.ts))
            .limit(lim)
            .all()
        )
        agg = _aggregate_decisions(rows)
        closed = (
            db.query(Position)
            .filter(
                Position.mode == "live",
                Position.is_open == False,  # noqa: E712
            )
            .order_by(desc(Position.exit_ts))
            .limit(200)
            .all()
        )
        n_trades = len(closed)
        pnl_sum = sum(float(p.pnl or 0) for p in closed if p.pnl is not None)
        alerts = _build_alerts(agg, n_trades)

        ml_status_summary = {
            "ml_used_percentage": agg["ml_used_percentage"],
            "non_rule_only_sources": {
                k: v
                for k, v in agg["final_source_counts"].items()
                if k not in ("rule_only", "rule_only_ml_disabled", "rule_based", "")
            },
        }
        return {
            "ok": True,
            "ml_used_percentage": agg["ml_used_percentage"],
            "avg_ml_confidence": agg.get("avg_ml_confidence"),
            "high_confidence_ratio": agg.get("high_confidence_ratio"),
            "buy_sell_ratio": agg.get("buy_count", 0)
            / max(agg.get("sell_count", 1), 1),
            "avg_confidence": agg["avg_confidence"],
            "runtime_status": "api_ok",
            "ml_status_summary": ml_status_summary,
            "buy_count": agg["buy_count"],
            "sell_count": agg["sell_count"],
            "hold_count": agg["hold_count"],
            "final_source_counts": agg["final_source_counts"],
            "live_pnl_sum_usdt": round(pnl_sum, 4),
            "closed_trades_sample": n_trades,
            "alerts": alerts,
            "sample_size": lim,
        }
    finally:
        db.close()


@router.get("/final-proof")
def final_proof_alias() -> Dict[str, Any]:
    """Alias matching audit naming — same as /stats/live-proof?limit=200."""
    return live_proof(200)
