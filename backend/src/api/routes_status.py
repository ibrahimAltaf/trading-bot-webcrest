"""
Performance Metrics API
-----------------------
Exposes real-time trading performance from the Position and TradingDecisionLog tables.
Metrics: profit, drawdown, win rate, average trade, Sharpe-like ratio.
"""

from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException
from sqlalchemy import func

from src.db.models import Position, TradingDecisionLog
from src.db.session import SessionLocal

router = APIRouter(prefix="/exchange/performance", tags=["performance"])


_PERF_MODES = frozenset({"live", "paper", "shadow"})


def _validate_mode(mode: str) -> str:
    m = (mode or "live").strip().lower()
    if m not in _PERF_MODES:
        raise HTTPException(
            status_code=400,
            detail="mode must be one of: live, paper, shadow",
        )
    return m


def _signals_dict(decision: Optional[TradingDecisionLog]) -> Dict[str, Any]:
    if not decision or not decision.signals_json:
        return {}
    try:
        return json.loads(decision.signals_json)
    except Exception:
        return {}


def _decision_source(signals: Dict[str, Any]) -> str:
    final_source = str(signals.get("final_source") or "").lower()
    if final_source in ("rule_only", "rule_only_ml_disabled", "rule_based"):
        return "rule_only"
    if final_source == "combined":
        return "combined"
    if final_source in (
        "ml_override",
        "ml_prioritize",
        "ml_hold_breakout",
        "ml_moderate_influence",
        "ml_rule_conflict_hold",
    ):
        return "ml_override"
    if final_source in ("ml_strict_failure", "ml_runtime_failure"):
        return "ml_strict_failure"
    return "other"


def _safe_num(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _compute_max_drawdown_pct(pnls: List[float]) -> float:
    cum_pnl = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl in pnls:
        cum_pnl += pnl
        if cum_pnl > peak:
            peak = cum_pnl
        dd = peak - cum_pnl
        if dd > max_dd:
            max_dd = dd
    return (max_dd / peak * 100.0) if peak > 0 else 0.0


def _compute_sharpe_like(values: List[float]) -> Optional[float]:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    std = math.sqrt(variance)
    if std <= 0:
        return None
    return (mean / std) * math.sqrt(len(values))


def _attach_decisions_to_positions(
    positions: List[Position], decisions: List[TradingDecisionLog]
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []

    for p in positions:
        entry_decision: Optional[TradingDecisionLog] = None
        exit_decision: Optional[TradingDecisionLog] = None

        for d in decisions:
            if d.symbol != p.symbol:
                continue
            if p.entry_ts and d.ts <= p.entry_ts:
                entry_decision = d
            if p.exit_ts and d.ts <= p.exit_ts:
                exit_decision = d

        entry_signals = _signals_dict(entry_decision)
        exit_signals = _signals_dict(exit_decision)
        entry_ctx = entry_signals.get("ml_context") or {}
        final_source = _decision_source(entry_signals)
        pnl = _safe_num(p.pnl)
        pnl_pct = _safe_num(p.pnl_pct)
        ml_changed_final_action = bool(
            isinstance(entry_ctx, dict) and entry_ctx.get("changed_final_action")
        )

        if ml_changed_final_action:
            ml_effect = "improved" if pnl > 0 else "worsened"
        elif entry_signals.get("ml_signal"):
            ml_effect = "assisted"
        else:
            ml_effect = "not_used"

        stop_loss = getattr(entry_decision, "stop_loss", None) if entry_decision else None
        take_profit = (
            getattr(entry_decision, "take_profit", None) if entry_decision else None
        )
        exit_reason = None
        if exit_decision and exit_decision.reason:
            exit_reason = exit_decision.reason
        elif stop_loss is not None and p.exit_price is not None and p.exit_price <= stop_loss:
            exit_reason = "Stop loss reached"
        elif (
            take_profit is not None
            and p.exit_price is not None
            and p.exit_price >= take_profit
        ):
            exit_reason = "Take profit reached"
        elif pnl > 0:
            exit_reason = "Profitable exit"
        elif pnl < 0:
            exit_reason = "Loss exit"
        else:
            exit_reason = "Flat exit"

        rows.append(
            {
                "position": p,
                "entry_decision": entry_decision,
                "exit_decision": exit_decision,
                "source_bucket": final_source,
                "symbol": p.symbol,
                "entry_ts": p.entry_ts.isoformat() if p.entry_ts else None,
                "exit_ts": p.exit_ts.isoformat() if p.exit_ts else None,
                "entry_price": p.entry_price,
                "entry_qty": p.entry_qty,
                "exit_price": p.exit_price,
                "exit_qty": p.exit_qty,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "entry_reason": entry_decision.reason if entry_decision else None,
                "ml_reason": entry_signals.get("override_reason"),
                "exit_reason": exit_reason,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "rule_signal": entry_signals.get("rule_signal"),
                "ml_signal": entry_signals.get("ml_signal"),
                "ml_confidence": entry_signals.get("ml_confidence"),
                "combined_signal": entry_signals.get("combined_signal"),
                "override_reason": entry_signals.get("override_reason"),
                "final_action": entry_decision.action if entry_decision else None,
                "ml_context": entry_ctx if isinstance(entry_ctx, dict) else {},
                "ml_effect": ml_effect,
                "ml_changed_final_action": ml_changed_final_action,
                "indicators": {
                    "adx": getattr(entry_decision, "adx", None) if entry_decision else None,
                    "ema_fast": getattr(entry_decision, "ema_fast", None)
                    if entry_decision
                    else None,
                    "ema_slow": getattr(entry_decision, "ema_slow", None)
                    if entry_decision
                    else None,
                    "rsi": getattr(entry_decision, "rsi", None) if entry_decision else None,
                    "atr": getattr(entry_decision, "atr", None) if entry_decision else None,
                    "risk_reward": getattr(entry_decision, "risk_reward", None)
                    if entry_decision
                    else None,
                },
            }
        )

    return rows


def _bucket_metrics(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    total_trades = len(rows)
    wins = [r for r in rows if _safe_num(r.get("pnl")) > 0]
    losses = [r for r in rows if _safe_num(r.get("pnl")) <= 0]
    pnl_values = [_safe_num(r.get("pnl")) for r in rows]
    pnl_pct_values = [_safe_num(r.get("pnl_pct")) for r in rows]

    return {
        "total_trades": total_trades,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round((len(wins) / total_trades) * 100, 2)
        if total_trades
        else 0.0,
        "false_signal_rate_pct": round((len(losses) / total_trades) * 100, 2)
        if total_trades
        else 0.0,
        "total_pnl_usdt": round(sum(pnl_values), 4),
        "average_return_per_trade_usdt": round(sum(pnl_values) / total_trades, 4)
        if total_trades
        else 0.0,
        "average_return_per_trade_pct": round(sum(pnl_pct_values) / total_trades, 4)
        if total_trades
        else 0.0,
        "max_drawdown_pct": round(_compute_max_drawdown_pct(pnl_values), 2),
        "sharpe_ratio": (
            round(_compute_sharpe_like(pnl_pct_values), 4)
            if _compute_sharpe_like(pnl_pct_values) is not None
            else None
        ),
        "ml_changed_action_count": len(
            [r for r in rows if bool(r.get("ml_changed_final_action"))]
        ),
    }


@router.get("")
def get_performance_metrics(mode: str = "live") -> Dict[str, Any]:
    """
    Return live trading performance metrics calculated from closed positions.

    Query params:
        mode: 'live' (default) | 'paper' | 'shadow'
    """
    mode = _validate_mode(mode)
    db = SessionLocal()
    try:
        # ---- Positions --------------------------------------------------------
        closed = (
            db.query(Position)
            .filter(Position.mode == mode, Position.is_open == False)  # noqa: E712
            .all()
        )
        open_pos = (
            db.query(Position)
            .filter(Position.mode == mode, Position.is_open == True)  # noqa: E712
            .all()
        )

        total_closed = len(closed)
        winners = [p for p in closed if (p.pnl or 0) > 0]
        losers = [p for p in closed if (p.pnl or 0) <= 0]

        total_pnl = sum(p.pnl or 0 for p in closed)
        gross_profit = sum(p.pnl for p in winners if p.pnl)
        gross_loss = abs(sum(p.pnl for p in losers if p.pnl))

        win_rate = (len(winners) / total_closed * 100) if total_closed > 0 else 0.0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None
        avg_win = (gross_profit / len(winners)) if winners else 0.0
        avg_loss = (gross_loss / len(losers)) if losers else 0.0

        # Max drawdown: running peak vs trough of cumulative PnL
        cum_pnl = 0.0
        peak = 0.0
        max_dd = 0.0
        for p in sorted(closed, key=lambda x: x.exit_ts or x.entry_ts):
            cum_pnl += p.pnl or 0
            if cum_pnl > peak:
                peak = cum_pnl
            dd = peak - cum_pnl
            if dd > max_dd:
                max_dd = dd

        max_dd_pct = (max_dd / peak * 100) if peak > 0 else 0.0

        # avg trade duration in hours
        durations_h = []
        for p in closed:
            if p.entry_ts and p.exit_ts:
                dt = (p.exit_ts - p.entry_ts).total_seconds() / 3600
                durations_h.append(dt)
        avg_duration_h = (sum(durations_h) / len(durations_h)) if durations_h else 0.0

        # ---- Decision log stats -----------------------------------------------
        total_decisions = db.query(func.count(TradingDecisionLog.id)).scalar() or 0
        buy_count = (
            db.query(func.count(TradingDecisionLog.id))
            .filter(TradingDecisionLog.action == "BUY")
            .scalar()
            or 0
        )
        sell_count = (
            db.query(func.count(TradingDecisionLog.id))
            .filter(TradingDecisionLog.action == "SELL")
            .scalar()
            or 0
        )
        hold_count = (
            db.query(func.count(TradingDecisionLog.id))
            .filter(TradingDecisionLog.action == "HOLD")
            .scalar()
            or 0
        )

        return {
            "mode": mode,
            "positions": {
                "total_closed": total_closed,
                "open": len(open_pos),
                "winners": len(winners),
                "losers": len(losers),
            },
            "pnl": {
                "total_pnl_usdt": round(total_pnl, 4),
                "gross_profit_usdt": round(gross_profit, 4),
                "gross_loss_usdt": round(gross_loss, 4),
                "max_drawdown_usdt": round(max_dd, 4),
                "max_drawdown_pct": round(max_dd_pct, 2),
            },
            "ratios": {
                "win_rate_pct": round(win_rate, 2),
                "profit_factor": round(profit_factor, 3) if profit_factor else None,
                "avg_win_usdt": round(avg_win, 4),
                "avg_loss_usdt": round(avg_loss, 4),
                "avg_trade_duration_hours": round(avg_duration_h, 2),
            },
            "decision_summary": {
                "total": total_decisions,
                "buy": buy_count,
                "sell": sell_count,
                "hold": hold_count,
                "hold_pct": (
                    round(hold_count / total_decisions * 100, 1)
                    if total_decisions
                    else 0
                ),
            },
        }
    except Exception as e:
        db.close()
        raise HTTPException(status_code=500, detail=f"Performance metrics failed: {e!s}")
    finally:
        db.close()


@router.get("/summary")
def get_performance_summary(mode: str = "live") -> Dict[str, Any]:
    """Short summary suitable for dashboard header cards."""
    mode = _validate_mode(mode)
    db = SessionLocal()
    try:
        closed = (
            db.query(Position)
            .filter(Position.mode == mode, Position.is_open == False)  # noqa: E712
            .all()
        )
        total_pnl = sum(p.pnl or 0 for p in closed)
        winners = [p for p in closed if (p.pnl or 0) > 0]
        win_rate = (len(winners) / len(closed) * 100) if closed else 0.0

        last_decision = (
            db.query(TradingDecisionLog).order_by(TradingDecisionLog.ts.desc()).first()
        )

        return {
            "total_pnl_usdt": round(total_pnl, 4),
            "win_rate_pct": round(win_rate, 2),
            "total_trades": len(closed),
            "last_signal": last_decision.action if last_decision else "N/A",
            "last_signal_reason": last_decision.reason if last_decision else "",
            "last_signal_ts": last_decision.ts.isoformat() if last_decision else None,
        }
    except Exception as e:
        db.close()
        raise HTTPException(status_code=500, detail=f"Performance summary failed: {e!s}")
    finally:
        db.close()


@router.get("/ml-vs-rules")
def get_ml_vs_rules_comparison(mode: str = "live") -> Dict[str, Any]:
    """
    Compare performance for trades entered from decisions that were:
    - rule_only / rule_only_ml_disabled
    - combined (rule+ML agree)
    - ml_override (ML overrode rule)
    """
    mode = _validate_mode(mode)
    db = SessionLocal()
    try:
        positions: List[Position] = (
            db.query(Position)
            .filter(Position.mode == mode, Position.is_open == False)  # noqa: E712
            .order_by(Position.entry_ts.asc())
            .all()
        )
        decisions: List[TradingDecisionLog] = (
            db.query(TradingDecisionLog)
            .order_by(TradingDecisionLog.ts.asc())
            .all()
        )

        trade_rows = _attach_decisions_to_positions(positions, decisions)
        bucketed_rows: Dict[str, List[Dict[str, Any]]] = {
            "rule_only": [],
            "combined": [],
            "ml_override": [],
            "ml_strict_failure": [],
            "other": [],
        }
        for row in trade_rows:
            bucketed_rows[row["source_bucket"]].append(row)

        buckets = {
            key: _bucket_metrics(items) for key, items in bucketed_rows.items()
        }

        return {
            "mode": mode,
            "overall": _bucket_metrics(trade_rows),
            "buckets": buckets,
        }
    except Exception as e:
        db.close()
        raise HTTPException(
            status_code=500, detail=f"ML vs rules comparison failed: {e!s}"
        )
    finally:
        db.close()


@router.get("/trades/evaluation")
def export_trade_evaluation(mode: str = "live") -> Dict[str, Any]:
    """
    Export trade-by-trade evaluation data.

    For each closed Position, returns:
    - timestamp, symbol, entry/exit, pnl, pnl_pct
    - an attached last TradingDecisionLog before entry with:
      - rule_signal, ml_signal, ml_confidence, combined_signal, override_reason
      - ml_context.model_name, model_version, changed_final_action
    """
    mode = _validate_mode(mode)
    db = SessionLocal()
    try:
        positions: List[Position] = (
            db.query(Position)
            .filter(Position.mode == mode, Position.is_open == False)  # noqa: E712
            .order_by(Position.entry_ts.asc())
            .all()
        )

        decisions: List[TradingDecisionLog] = (
            db.query(TradingDecisionLog)
            .order_by(TradingDecisionLog.ts.asc())
            .all()
        )
        rows = _attach_decisions_to_positions(positions, decisions)
        items: List[Dict[str, Any]] = []
        for row in rows:
            p: Position = row["position"]
            items.append(
                {
                    "position_id": p.id,
                    "symbol": row["symbol"],
                    "entry_ts": row["entry_ts"],
                    "exit_ts": row["exit_ts"],
                    "entry_price": row["entry_price"],
                    "entry_qty": row["entry_qty"],
                    "exit_price": row["exit_price"],
                    "exit_qty": row["exit_qty"],
                    "stop_loss": row["stop_loss"],
                    "take_profit": row["take_profit"],
                    "entry_reason": row["entry_reason"],
                    "ml_reason": row["ml_reason"],
                    "exit_reason": row["exit_reason"],
                    "realized_pnl": row["pnl"],
                    "realized_pnl_pct": row["pnl_pct"],
                    "rule_signal": row["rule_signal"],
                    "ml_signal": row["ml_signal"],
                    "ml_confidence": row["ml_confidence"],
                    "combined_signal": row["combined_signal"],
                    "override_reason": row["override_reason"],
                    "final_action": row["final_action"],
                    "ml_effect": row["ml_effect"],
                    "ml_changed_final_action": row["ml_changed_final_action"],
                    "ml_context": row["ml_context"],
                    "indicators": row["indicators"],
                }
            )

        return {"mode": mode, "count": len(items), "items": items}
    except Exception as e:
        db.close()
        raise HTTPException(
            status_code=500, detail=f"Trade evaluation export failed: {e!s}"
        )
    finally:
        db.close()


def _shannon_entropy(counts: Dict[str, int]) -> float:
    """Bits of entropy over a discrete distribution (diversity signal)."""
    total = sum(counts.values())
    if total <= 0:
        return 0.0
    h = 0.0
    for c in counts.values():
        if c <= 0:
            continue
        p = c / total
        h -= p * math.log(p, 2)
    return round(h, 4)


@router.get("/ai-observability")
def ai_observability_metrics(
    limit: int = 5000,
    symbol: Optional[str] = None,
) -> Dict[str, Any]:
    """ML usage, runtime posture, and decision diversity from recent ``signals_json`` rows."""
    from collections import Counter

    lim = max(1, min(int(limit), 20000))
    db = SessionLocal()
    try:
        q = db.query(TradingDecisionLog).order_by(TradingDecisionLog.ts.desc())
        if symbol:
            q = q.filter(TradingDecisionLog.symbol == symbol.strip().upper())
        rows = q.limit(lim).all()

        runtime_mode_c: Counter[str] = Counter()
        hold_kind_c: Counter[str] = Counter()
        final_source_c: Counter[str] = Counter()
        triple_c: Counter[str] = Counter()

        ml_signal_present = 0
        ml_confidence_present = 0
        degraded_cycles = 0
        strict_failure_cycles = 0

        for r in rows:
            sig = _signals_dict(r)
            cd = sig.get("cycle_debug") if isinstance(sig.get("cycle_debug"), dict) else {}
            env = (
                sig.get("cycle_envelope")
                if isinstance(sig.get("cycle_envelope"), dict)
                else {}
            )

            rm = str(
                cd.get("runtime_mode")
                or env.get("runtime_mode")
                or "unknown"
            ).lower()
            runtime_mode_c[rm] += 1

            hk = str(cd.get("hold_kind") or env.get("hold_kind") or "").lower()
            if hk:
                hold_kind_c[hk] += 1

            fs = str(sig.get("final_source") or "unknown").lower()
            final_source_c[fs] += 1
            if fs in ("ml_strict_failure", "ml_runtime_failure"):
                strict_failure_cycles += 1

            if rm in ("ai_degraded", "ai_unavailable"):
                degraded_cycles += 1

            rs = str(sig.get("rule_signal") or cd.get("rule_signal") or "?")
            ms = sig.get("ml_signal")
            if ms is None:
                pred = sig.get("ml_prediction")
                if isinstance(pred, dict) and pred.get("signal") is not None:
                    ms = pred.get("signal")
            if ms is not None:
                ml_signal_present += 1
            conf_any = sig.get("ml_confidence")
            if conf_any is None and isinstance(sig.get("ml_prediction"), dict):
                conf_any = sig["ml_prediction"].get("confidence")
            if conf_any is not None or cd.get("ml_confidence") is not None:
                ml_confidence_present += 1

            fin = str(sig.get("combined_signal") or r.action or "?")
            ms_key = str(ms) if ms is not None else "none"
            triple_c[f"{rs}|{ms_key}|{fin}"] += 1

        n = len(rows) or 1
        return {
            "ok": True,
            "sample_size": len(rows),
            "symbol_filter": symbol.strip().upper() if symbol else None,
            "ml_usage": {
                "cycles_with_ml_signal_field": ml_signal_present,
                "cycles_with_ml_confidence": ml_confidence_present,
                "pct_with_ml_signal": round(100.0 * ml_signal_present / n, 2),
                "pct_with_ml_confidence": round(100.0 * ml_confidence_present / n, 2),
            },
            "runtime_posture": {
                "counts_by_runtime_mode": dict(runtime_mode_c),
                "degraded_or_unavailable_cycles": degraded_cycles,
                "ml_strict_failure_cycles": strict_failure_cycles,
            },
            "decision_diversity": {
                "distinct_rule_ml_final_patterns": len(triple_c),
                "pattern_top": dict(triple_c.most_common(15)),
                "final_source_entropy_bits": _shannon_entropy(dict(final_source_c)),
                "hold_kind_counts": dict(hold_kind_c),
            },
            "final_source_counts": dict(final_source_c),
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"ai-observability failed: {e!s}"
        )
    finally:
        db.close()


@router.get("/decision-source-distribution")
def decision_source_distribution(limit: int = 5000) -> Dict[str, Any]:
    """Distribution of pipeline outcomes: rule_only, combined, ml_override, ml_strict_failure."""
    from collections import Counter

    lim = max(1, min(int(limit), 20000))
    db = SessionLocal()
    try:
        rows = (
            db.query(TradingDecisionLog)
            .order_by(TradingDecisionLog.ts.desc())
            .limit(lim)
            .all()
        )
        by_fs: Counter[str] = Counter()
        grouped: Dict[str, int] = {
            "rule_only": 0,
            "combined": 0,
            "ml_override": 0,
            "ml_strict_failure": 0,
            "other": 0,
        }
        for r in rows:
            sig = _signals_dict(r)
            fs = str(sig.get("final_source") or "unknown").lower()
            by_fs[fs] += 1
            bucket = _decision_source(sig)
            if bucket in grouped:
                grouped[bucket] += 1
            else:
                grouped["other"] += 1

        total = sum(grouped.values()) or 1
        pct = {k: round(100.0 * v / total, 2) for k, v in grouped.items()}
        return {
            "ok": True,
            "sample_size": len(rows),
            "grouped_counts": grouped,
            "grouped_pct": pct,
            "by_final_source": dict(by_fs),
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"decision-source-distribution failed: {e!s}"
        )
    finally:
        db.close()
