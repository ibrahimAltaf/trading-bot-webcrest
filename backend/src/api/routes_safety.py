"""
Phase 2A safety + execution-mode + reconciliation API.

Public endpoints
----------------
GET    /safety/status                 — snapshot: mode, kill switch, limits, recon
GET    /safety/kill-switch            — kill switch state + history
POST   /safety/kill-switch/engage     — engage kill switch (body: {"reason": "..."})
POST   /safety/kill-switch/release    — release kill switch (body: {"reason": "..."})
GET    /safety/limits                 — current RiskLimits (resolved from env)
GET    /safety/reconcile              — DB / paper-tracker drift report (read only)
GET    /execution/mode                — current mode + resolution sources
POST   /execution/mode                — set mode override (body: {"mode": "paper|shadow|live", "reason": "..."})
DELETE /execution/mode/override       — clear runtime override, fall back to env

All write endpoints persist to disk under `<data_dir>/safety/` and are safe to
call repeatedly. They never touch the exchange.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from src.core.json_safe import finite_float, sanitize_for_json
from src.db.session import SessionLocal
from src.execution.mode import (
    ExecutionMode,
    clear_execution_mode_override,
    get_execution_mode,
    is_simulated,
    mode_snapshot,
    set_execution_mode,
)
from src.execution.reconciler import reconcile
from src.safety import kill_switch as ks
from src.safety.risk_engine import default_limits_from_env


router = APIRouter(tags=["safety"])


def _get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ----------------------------- Pydantic models -------------------------------


class KillSwitchActionBody(BaseModel):
    reason: str = Field(..., min_length=1, max_length=1000)
    by: Optional[str] = Field(default="api", max_length=64)


class ExecutionModeBody(BaseModel):
    mode: str = Field(..., description="paper | shadow | live")
    reason: Optional[str] = Field(default="", max_length=1000)
    by: Optional[str] = Field(default="api", max_length=64)


# ----------------------------- helpers ---------------------------------------


def _limits_dict() -> Dict[str, Any]:
    lim = default_limits_from_env()
    return {
        "max_trade_notional_usdt": lim.max_trade_notional_usdt,
        "max_open_positions": lim.max_open_positions,
        "max_daily_loss_usdt": lim.max_daily_loss_usdt,
        "max_daily_orders": lim.max_daily_orders,
        "max_exposure_pct_of_balance": lim.max_exposure_pct_of_balance,
        "min_order_notional_usdt": lim.min_order_notional_usdt,
        "cooldown_seconds_after_loss": lim.cooldown_seconds_after_loss,
        "duplicate_window_seconds": lim.duplicate_window_seconds,
        "require_kill_switch_release": lim.require_kill_switch_release,
        "min_ml_confidence_for_live": lim.min_ml_confidence_for_live,
        "max_total_exposure_usdt": lim.max_total_exposure_usdt,
        "max_cumulative_loss_usdt": lim.max_cumulative_loss_usdt,
        "allowed_symbols": list(lim.allowed_symbols) if lim.allowed_symbols else None,
    }


# ----------------------------- routes ----------------------------------------


@router.get("/safety/status", summary="Combined Phase 2A safety snapshot")
def safety_status(db: Session = Depends(_get_db)) -> Dict[str, Any]:
    from src.safety import phase2c as p2c

    eff_mode = get_execution_mode()
    return {
        "ok": True,
        "execution_mode": mode_snapshot(),
        "is_simulated": is_simulated(eff_mode),
        "kill_switch": ks.get_state(),
        "limits": _limits_dict(),
        "reconcile": reconcile(db),
        "phase2c": p2c.snapshot(),
    }


@router.get("/safety/kill-switch", summary="Kill switch state")
def kill_switch_state() -> Dict[str, Any]:
    return {"ok": True, "kill_switch": ks.get_state()}


@router.post("/safety/kill-switch/engage", summary="Engage kill switch")
def kill_switch_engage(body: KillSwitchActionBody) -> Dict[str, Any]:
    state = ks.engage(reason=body.reason, by=body.by or "api")
    return {"ok": True, "engaged": True, "kill_switch": state}


@router.post("/safety/kill-switch/release", summary="Release kill switch")
def kill_switch_release(body: KillSwitchActionBody) -> Dict[str, Any]:
    state = ks.release(reason=body.reason, by=body.by or "api")
    return {"ok": True, "engaged": False, "kill_switch": state}


@router.get("/safety/limits", summary="Current risk limits")
def safety_limits() -> Dict[str, Any]:
    return {"ok": True, "limits": _limits_dict()}


@router.get(
    "/safety/reconcile",
    summary="DB / in-memory paper tracker drift report (read only)",
)
def safety_reconcile(db: Session = Depends(_get_db)) -> Dict[str, Any]:
    return reconcile(db)


@router.get(
    "/safety/exchange-reconcile",
    summary="DB vs Binance drift (open orders + balances; read only)",
)
def safety_exchange_reconcile(
    mode: str = "live",
    symbols: Optional[str] = None,
    db: Session = Depends(_get_db),
) -> Dict[str, Any]:
    """
    Phase 2A track 4 — compares DB live/shadow state with the exchange.

    Query params
    ------------
    * `mode`     paper | shadow | live  (which DB rows to compare; default live)
    * `symbols`  comma-separated whitelist, e.g. `BTCUSDT,ETHUSDT`
    """
    from src.exchange.binance_spot_client import BinanceSpotClient
    from src.execution.exchange_reconciler import reconcile_with_exchange

    try:
        ExecutionMode.coerce(mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    syms = (
        [s.strip().upper() for s in symbols.split(",") if s.strip()]
        if symbols
        else None
    )
    try:
        client = BinanceSpotClient()
    except Exception as exc:
        # Surface key-config failure as a structured response, not a 500.
        return {
            "ok": False,
            "errors": [f"binance_client_init_failed: {exc}"],
            "mode": mode,
        }
    return reconcile_with_exchange(db, client, mode=mode, symbols=syms)


@router.get("/execution/mode", summary="Resolve current execution mode")
def execution_mode_get() -> Dict[str, Any]:
    return {"ok": True, **mode_snapshot()}


@router.post(
    "/execution/mode",
    summary="Set execution mode override (paper | shadow | live)",
)
def execution_mode_set(body: ExecutionModeBody) -> Dict[str, Any]:
    try:
        target = ExecutionMode.coerce(body.mode)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    # Safety rail: do not allow switching INTO live while kill switch engaged.
    if target == ExecutionMode.LIVE and ks.is_engaged():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="kill switch is engaged; release it before switching to live mode",
        )

    doc = set_execution_mode(
        target,
        changed_by=body.by or "api",
        reason=body.reason or "",
    )
    return {"ok": True, "mode": target.value, "override": doc, **mode_snapshot()}


@router.delete(
    "/execution/mode/override",
    summary="Clear runtime mode override (fall back to env / legacy)",
)
def execution_mode_clear_override() -> Dict[str, Any]:
    removed = clear_execution_mode_override()
    return {"ok": True, "removed": removed, **mode_snapshot()}


# ----------------------------- shadow audit (client Phase 2A) ------------------


@router.get(
    "/safety/shadow-audit",
    summary="Shadow order IDs, client IDs, and decision stats for external audits",
)
def safety_shadow_audit(
    symbol: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(_get_db),
) -> Dict[str, Any]:
    """
    Single endpoint for 7-day soak / audit scripts that need shadow order visibility.

    Includes DB + in-memory shadow orders with both camelCase and snake_case ID fields.
    """
    from src.db.models import Order, Position, TradingDecisionLog
    from src.execution.execution_engine import SHADOW_ORDERS
    from src.execution.mode import get_execution_mode, is_simulated, mode_snapshot
    from src.live.auto_trade_engine import AutoTradeEngine

    sym = (symbol or "").strip().upper() or None
    safe_limit = max(1, min(int(limit), 500))
    eff = get_execution_mode()

    q_orders = db.query(Order).filter(Order.mode == "shadow")
    if sym:
        q_orders = q_orders.filter(Order.symbol == sym)
    order_rows = (
        q_orders.order_by(Order.created_at.desc()).limit(safe_limit).all()
    )

    orders_out = []
    order_ids: List[str] = []
    client_ids: List[str] = []
    for r in order_rows:
        oid = str(r.exchange_order_id or r.id)
        cid = str(r.client_order_id or "") or None
        orders_out.append(
            {
                "orderId": oid,
                "clientOrderId": cid,
                "order_id": oid,
                "client_order_id": cid,
                "symbol": r.symbol,
                "side": r.side,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
        )
        if oid:
            order_ids.append(oid)
        if cid:
            client_ids.append(cid)

    open_pos = db.query(Position).filter(
        Position.mode == "shadow", Position.is_open == True  # noqa: E712
    )
    if sym:
        open_pos = open_pos.filter(Position.symbol == sym)
    open_count = open_pos.count()

    dec_q = db.query(TradingDecisionLog)
    if sym:
        dec_q = dec_q.filter(TradingDecisionLog.symbol == sym)
    recent = dec_q.order_by(TradingDecisionLog.ts.desc()).limit(500).all()
    action_counts = {"BUY": 0, "SELL": 0, "HOLD": 0, "other": 0}
    executed_buys = 0
    for d in recent:
        act = str(d.action or "").upper()
        if act in action_counts:
            action_counts[act] += 1
        else:
            action_counts["other"] += 1
        if act == "BUY" and d.executed:
            executed_buys += 1

    sizing_balance = None
    used_fallback = False
    try:
        eng = AutoTradeEngine(db=db)
        exchange_free = float(eng._get_usdt_balance())
        sizing_balance, _, used_fallback = eng._get_shadow_sizing_balance()
        exchange_err = None
    except Exception as exc:
        exchange_free = None
        exchange_err = str(exc)[:200]

    zero_explanation = None
    if len(order_ids) == 0:
        if action_counts.get("HOLD", 0) > 0 and executed_buys == 0:
            zero_explanation = (
                "No shadow orders in DB: recent decisions were mostly HOLD or "
                "BUY not executed (risk/balance/signal)."
            )
        elif exchange_free is not None and exchange_free <= 0:
            zero_explanation = (
                "Exchange USDT is zero; enable SHADOW_USE_FALLBACK_BALANCE=true "
                "or fund testnet USDT for shadow BUY sizing."
            )
        else:
            zero_explanation = "No shadow orders in DB yet for the selected scope."

    return {
        "ok": True,
        "execution_mode": mode_snapshot(),
        "effective_mode": eff.value,
        "is_simulated": is_simulated(eff),
        "symbol_filter": sym,
        "exchange_usdt_free": exchange_free,
        "exchange_usdt_error": exchange_err,
        "shadow_sizing_balance": sizing_balance,
        "shadow_sizing_used_fallback": used_fallback,
        "shadow_use_fallback_balance": AutoTradeEngine._shadow_fallback_balance_enabled(),
        "unique_shadow_order_ids_count": len(set(order_ids)),
        "unique_client_order_ids_count": len(set(client_ids)),
        "unique_shadow_order_ids": sorted(set(order_ids)),
        "unique_client_order_ids": sorted(set(client_ids)),
        "orders": orders_out,
        "open_shadow_positions_count": open_count,
        "memory_shadow_orders_count": len(SHADOW_ORDERS or []),
        "decision_window_sampled": len(recent),
        "decision_action_counts": action_counts,
        "executed_buy_count_in_sample": executed_buys,
        "zero_orders_explanation": zero_explanation,
        "verification_endpoints": {
            "soak_closeout": "/safety/shadow-soak-report?days=7&symbol=BTCUSDT",
            "orders": "/exchange/orders/all?mode=shadow&symbol=BTCUSDT",
            "proof": "/exchange/proof?mode=shadow&symbol=BTCUSDT",
            "positions_open": "/exchange/positions/open?mode=shadow",
            "positions_history": "/exchange/positions/history?mode=shadow&symbol=BTCUSDT",
            "forced_buy": "POST /exchange/auto-trade with force_signal=BUY, low risk_pct",
        },
    }


def _parse_decision_signals(raw: Optional[str]) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _classify_order_origin(
    signals: Dict[str, Any],
    reason: Optional[str],
    triggered_by: Optional[str] = None,
) -> Dict[str, str]:
    """Classify who/what caused this decision and which pipeline produced it.

    Returns {"origin": ..., "pipeline": ...}.

    origin (authoritative trigger provenance, from Order/TradingDecisionLog.triggered_by):
      - proof_forced: POST /exchange/auto-trade with force_signal=BUY|SELL (audit call).
      - ai_scheduler: an unattended APScheduler cycle (src/scheduler/runner.py) —
        the ONLY category that proves autonomous AI-origin execution.
      - api_manual_unforced: a human/script called /exchange/auto-trade directly
        without force_signal. The rule/ML pipeline genuinely ran, but this was
        NOT an unattended cycle, so it must never be counted as scheduler proof
        (this was Saad's exact concern — a manual curl during a deploy-verify
        call being indistinguishable from real autonomous execution).
      - unknown: legacy row written before triggered_by existed (column added
        for this validation round) — cannot be confidently classified.

    pipeline (which signal source produced the action, independent of origin):
      ai_rule | ai_ml | ai_combined | forced | unknown
    """
    if signals.get("forced") or signals.get("final_source") == "forced_signal":
        return {"origin": "proof_forced", "pipeline": "forced"}
    if str(reason or "").lower().startswith("forced signal"):
        return {"origin": "proof_forced", "pipeline": "forced"}

    fs = str(signals.get("final_source") or "").lower()
    if fs in ("rule_only", "rule_only_ml_disabled", "rule_based"):
        pipeline = "ai_rule"
    elif fs in (
        "ml_override",
        "ml_prioritize",
        "ml_hold_breakout",
        "ml_moderate_influence",
        "ml_rule_conflict_hold",
        "rule_directional_ml_neutral",
        "combined",
    ):
        pipeline = "ai_ml"
    elif fs:
        pipeline = "ai_combined"
    else:
        pipeline = "unknown"

    if triggered_by == "scheduler":
        origin = "ai_scheduler"
    elif triggered_by == "api_manual":
        origin = "api_manual_unforced"
    elif triggered_by == "proof_forced":
        origin = "proof_forced"
        pipeline = "forced"
    else:
        origin = "unknown"
    return {"origin": origin, "pipeline": pipeline}


@router.get(
    "/safety/shadow-soak-report",
    summary="7-day shadow soak close-out: orders, PnL, drift, live-readiness fields",
)
def shadow_soak_report(
    symbol: Optional[str] = None,
    days: int = 7,
    order_limit: int = 500,
    db: Session = Depends(_get_db),
) -> Dict[str, Any]:
    """
    Single close-out report for external 7-day soak audits.

    Populates flat fields that soak scripts expect (``ready_for_live_capital``,
    ``safety_reconcile_drift_count``, ``exchange_shadow_drift_count``) and
    explains how ``endpoint_errors_count`` from third-party scripts should be
    interpreted vs real server failures.
    """
    try:
        return _build_shadow_soak_report(
            db=db, symbol=symbol, days=days, order_limit=order_limit
        )
    except Exception as exc:
        return {
            "ok": False,
            "report_type": "shadow_soak_closeout",
            "error": type(exc).__name__,
            "detail": str(exc)[:500],
            "hint": (
                "Check journalctl -u tradingbot.service for traceback; "
                "retry after service restart."
            ),
        }


def _build_shadow_soak_report(
    *,
    db: Session,
    symbol: Optional[str],
    days: int,
    order_limit: int,
) -> Dict[str, Any]:
    from sqlalchemy import func

    from src.db.models import EventLog, Order, Position, Trade, TradingDecisionLog
    from src.exchange.binance_spot_client import BinanceSpotClient
    from src.execution.exchange_reconciler import reconcile_with_exchange
    from src.execution.mode import get_execution_mode, is_simulated, mode_snapshot
    from src.live.auto_trade_engine import AutoTradeEngine

    sym = (symbol or "").strip().upper() or None
    safe_days = max(1, min(int(days), 90))
    safe_limit = max(1, min(int(order_limit), 1000))
    since = datetime.utcnow() - timedelta(days=safe_days)
    eff = get_execution_mode()

    # --- live readiness (flat fields for soak scripts) -------------------------
    try:
        readiness = live_readiness()
    except Exception as exc:
        readiness = {
            "ready_for_live_capital": False,
            "ready_for_live_capital_reason": f"live_readiness_failed: {exc}",
            "checks": [],
        }
    ready_for_live = bool(readiness.get("ready_for_live_capital"))

    # --- reconcile drift -------------------------------------------------------
    recon = reconcile(db)
    safety_drift_count = int(recon.get("drift_count", len(recon.get("drift") or [])))

    exchange_shadow_drift_count = None
    exchange_recon_note = None
    try:
        ex_client = BinanceSpotClient()
        ex_report = reconcile_with_exchange(
            db, ex_client, mode="shadow", symbols=[sym] if sym else None
        )
        oo = ex_report.get("open_orders") or {}
        pos = ex_report.get("positions") or {}
        exchange_shadow_drift_count = int(oo.get("drift_count", 0)) + int(
            pos.get("drift_count", 0)
        )
        if oo.get("skipped"):
            exchange_recon_note = oo.get("note")
    except Exception as exc:
        exchange_shadow_drift_count = None
        exchange_recon_note = f"exchange_reconcile_unavailable: {exc}"

    # --- server-side error ground truth (not audit-script poll failures) -------
    err_q = db.query(func.count(EventLog.id)).filter(
        EventLog.level == "ERROR", EventLog.ts >= since
    )
    warn_q = db.query(func.count(EventLog.id)).filter(
        EventLog.level == "WARN", EventLog.ts >= since
    )
    if sym:
        err_q = err_q.filter(EventLog.symbol == sym)
        warn_q = warn_q.filter(EventLog.symbol == sym)
    server_error_count = int(err_q.scalar() or 0)
    server_warn_count = int(warn_q.scalar() or 0)

    endpoint_errors_explanation = {
        "what_external_scripts_often_count": (
            "Third-party soak monitors typically increment endpoint_errors on "
            "each HTTP non-2xx response OR each checklist row marked FAILED when "
            "polling /api/* on an interval (e.g. every 5–60s) for the full soak "
            "window. A count in the tens of thousands over 7 days usually means "
            "~1 expected failure per poll cycle (auth-gated routes, optional "
            "subsections), not tens of thousands of production outages."
        ),
        "common_expected_failures_in_checklists": [
            "GET /admin/binance-keys without X-Admin-Token → 401 (by design)",
            "Optional proof subsections when a symbol has no data yet",
            "Polling through nginx without correct Host header on some VPS setups",
        ],
        "what_we_count_as_real_failures": (
            "EventLog rows with level=ERROR in the application database during "
            "the soak window (see server_event_log_errors_in_window)."
        ),
        "server_event_log_errors_in_window": server_error_count,
        "server_event_log_warn_in_window": server_warn_count,
        "interpretation": (
            "If endpoint_errors_count from your script is ~76k but "
            "server_event_log_errors_in_window is orders of magnitude lower, "
            "the soak script counter is almost certainly audit-poll artifacts, "
            "not API instability."
        ),
    }

    # --- shadow orders (full list) ---------------------------------------------
    oq = db.query(Order).filter(Order.mode == "shadow").filter(
        or_(Order.created_at.is_(None), Order.created_at >= since)
    )
    if sym:
        oq = oq.filter(Order.symbol == sym)
    order_rows = oq.order_by(Order.created_at.asc()).limit(safe_limit).all()

    # --- decisions linked to shadow orders in this window ------------------------
    shadow_order_pks = [int(r.id) for r in order_rows]
    decisions_with_orders = (
        db.query(TradingDecisionLog)
        .filter(TradingDecisionLog.order_id.in_(shadow_order_pks))
        .all()
        if shadow_order_pks
        else []
    )
    decision_by_order_pk = {
        int(d.order_id): d for d in decisions_with_orders if d.order_id
    }

    shadow_orders: List[Dict[str, Any]] = []
    origin_counts: Dict[str, int] = {}
    for row in order_rows:
        oid = str(row.exchange_order_id or row.id)
        dec = decision_by_order_pk.get(int(row.id))
        sig = _parse_decision_signals(dec.signals_json if dec else None)
        row_triggered_by = getattr(row, "triggered_by", None) or (
            getattr(dec, "triggered_by", None) if dec else None
        )
        classified = _classify_order_origin(
            sig, dec.reason if dec else None, triggered_by=row_triggered_by
        )
        origin = classified["origin"]
        origin_counts[origin] = origin_counts.get(origin, 0) + 1
        shadow_orders.append(
            {
                "orderId": oid,
                "clientOrderId": row.client_order_id,
                "order_id": oid,
                "client_order_id": row.client_order_id,
                "db_id": row.id,
                "symbol": row.symbol,
                "side": row.side,
                "status": row.status,
                "quantity": finite_float(row.quantity, default=0.0),
                "executed_price": finite_float(row.executed_price, default=0.0),
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "decision_id": dec.id if dec else None,
                "decision_action": dec.action if dec else None,
                "decision_executed": bool(dec.executed) if dec else None,
                "final_source": sig.get("final_source"),
                "ml_signal": sig.get("ml_signal"),
                "ml_confidence": finite_float(sig.get("ml_confidence"), default=0.0)
                if sig.get("ml_confidence") is not None
                else None,
                "rule_signal": sig.get("rule_signal"),
                "cycle_id": getattr(row, "cycle_id", None)
                or (getattr(dec, "cycle_id", None) if dec else None),
                "order_origin": origin,
                "order_origin_pipeline": classified["pipeline"],
                "order_origin_label": {
                    "proof_forced": "proof / forced_signal audit trade",
                    "ai_scheduler": "unattended scheduler cycle — autonomous AI",
                    "api_manual_unforced": "manual API call (no force_signal) — pipeline ran, not an unattended cycle",
                    "unknown": "legacy row — no trigger provenance recorded",
                }.get(origin, origin),
                "active_thresholds": sig.get("active_thresholds"),
                "adaptive_posture": (sig.get("active_thresholds") or {}).get(
                    "adaptive_posture"
                ),
            }
        )

    # --- positions -------------------------------------------------------------
    pq_open = db.query(Position).filter(
        Position.mode == "shadow", Position.is_open == True  # noqa: E712
    )
    pq_closed = db.query(Position).filter(
        Position.mode == "shadow",
        Position.is_open == False,  # noqa: E712
        Position.exit_ts >= since,
    )
    if sym:
        pq_open = pq_open.filter(Position.symbol == sym)
        pq_closed = pq_closed.filter(Position.symbol == sym)

    open_positions = [
        {
            "id": p.id,
            "symbol": p.symbol,
            "entry_price": finite_float(p.entry_price, default=0.0),
            "entry_qty": finite_float(p.entry_qty, default=0.0),
            "entry_ts": p.entry_ts.isoformat() if p.entry_ts else None,
            "is_open": True,
        }
        for p in pq_open.order_by(Position.entry_ts.asc()).all()
    ]
    closed_positions = [
        {
            "id": p.id,
            "symbol": p.symbol,
            "entry_price": finite_float(p.entry_price, default=0.0),
            "entry_qty": finite_float(p.entry_qty, default=0.0),
            "entry_ts": p.entry_ts.isoformat() if p.entry_ts else None,
            "exit_price": finite_float(p.exit_price, default=0.0),
            "exit_qty": finite_float(p.exit_qty, default=0.0),
            "exit_ts": p.exit_ts.isoformat() if p.exit_ts else None,
            "pnl": finite_float(p.pnl, default=0.0),
            "pnl_pct": finite_float(p.pnl_pct, default=0.0),
            "is_open": False,
        }
        for p in pq_closed.order_by(Position.exit_ts.asc()).all()
    ]

    # --- PnL summary -----------------------------------------------------------
    closed_pnls = [
        finite_float(p.get("pnl"), default=0.0)
        for p in closed_positions
        if p.get("pnl") is not None
    ]
    realized_pnl = round(sum(closed_pnls), 4)
    winners = len([x for x in closed_pnls if x > 0])
    losers = len([x for x in closed_pnls if x <= 0])
    closed_count = len(closed_positions)

    # unrealized from open (best-effort ticker)
    unrealized_pnl = 0.0
    try:
        eng = AutoTradeEngine(db=db)
        for p in open_positions:
            px = float(eng.client.get_price(p["symbol"]))
            entry = float(p.get("entry_price") or 0)
            qty = float(p.get("entry_qty") or 0)
            unrealized_pnl += (px - entry) * qty
    except Exception:
        pass

    tq = db.query(Trade).filter(Trade.mode == "shadow", Trade.ts >= since)
    if sym:
        tq = tq.filter(Trade.symbol == sym)
    trade_count = int(tq.count())

    pnl_summary = {
        "window_days": safe_days,
        "shadow_orders_count": len(shadow_orders),
        "shadow_trades_count": trade_count,
        "open_positions_count": len(open_positions),
        "closed_positions_count": closed_count,
        "realized_pnl_usdt": realized_pnl,
        "unrealized_pnl_usdt_open_positions": round(unrealized_pnl, 4),
        "total_pnl_usdt_including_unrealized": round(realized_pnl + unrealized_pnl, 4),
        "win_rate_pct_closed": round((winners / closed_count) * 100, 2)
        if closed_count
        else None,
        "wins_closed": winners,
        "losses_closed": losers,
    }

    orders_origin_summary = {
        "total": len(shadow_orders),
        "proof_forced_count": origin_counts.get("proof_forced", 0),
        "ai_scheduler_count": origin_counts.get("ai_scheduler", 0),
        "api_manual_unforced_count": origin_counts.get("api_manual_unforced", 0),
        "unknown_origin_count": origin_counts.get("unknown", 0),
        "by_origin": origin_counts,
        "all_from_genuine_ai_decisions": (
            len(shadow_orders) > 0
            and origin_counts.get("ai_scheduler", 0) == len(shadow_orders)
        ),
        "note": (
            "ai_scheduler = order produced by an unattended APScheduler cycle "
            "(src/scheduler/runner.py) — the only category that proves autonomous "
            "AI-origin execution. proof_forced = POST /exchange/auto-trade with "
            "force_signal=BUY|SELL. api_manual_unforced = a human/script called "
            "/exchange/auto-trade directly without force_signal — the rule/ML "
            "pipeline ran genuinely, but this was not an unattended cycle, so it "
            "is intentionally NOT counted toward ai_scheduler_count. unknown = "
            "legacy rows written before triggered_by/cycle_id tracking existed."
        ),
    }

    payload = {
        "ok": True,
        "report_type": "shadow_soak_closeout",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "window_days": safe_days,
        "window_since": since.isoformat() + "Z",
        "symbol_filter": sym,
        "execution_mode": mode_snapshot(),
        "effective_mode": eff.value,
        "is_simulated": is_simulated(eff),
        "ready_for_live_capital": ready_for_live,
        "ready_for_live_capital_reason": readiness.get("ready_for_live_capital_reason"),
        "live_readiness_checks": readiness.get("checks"),
        "safety_reconcile_drift_count": safety_drift_count,
        "exchange_shadow_drift_count": exchange_shadow_drift_count,
        "exchange_shadow_reconcile_note": exchange_recon_note,
        "endpoint_errors_explanation": endpoint_errors_explanation,
        "shadow_orders": shadow_orders,
        "shadow_orders_origin_summary": orders_origin_summary,
        "shadow_positions_open": open_positions,
        "shadow_positions_history": closed_positions,
        "shadow_pnl_summary": pnl_summary,
        "data_sources": {
            "orders": "/exchange/orders/all?mode=shadow",
            "positions_open": "/exchange/positions/open?mode=shadow",
            "positions_history": "/exchange/positions/history?mode=shadow",
            "performance": "/exchange/performance?mode=shadow",
            "shadow_audit": "/safety/shadow-audit",
            "live_readiness": "/safety/live-readiness",
            "reconcile": "/safety/reconcile",
            "exchange_reconcile": "/safety/exchange-reconcile?mode=shadow",
        },
    }
    return sanitize_for_json(payload)


@router.get(
    "/safety/operational-readiness",
    summary="Restart recovery, alerts config, and idempotency column checks",
)
def operational_readiness(db: Session = Depends(_get_db)) -> Dict[str, Any]:
    """Pre–Phase 2A close checklist: recovery, alerts, shadow visibility."""
    import os
    from sqlalchemy import inspect

    from src.db.session import engine
    from src.execution.execution_engine import SHADOW_ORDERS
    from src.execution.recovery import bootstrap_runtime_state, ensure_client_order_id_column
    from src.safety import alerts as alert_mod

    cols = set()
    try:
        cols = {c["name"] for c in inspect(engine).get_columns("orders")}
    except Exception:
        pass

    from src.db.models import Order

    shadow_db = db.query(Order).filter(Order.mode == "shadow").count()

    recovery_summary = bootstrap_runtime_state(db)

    return {
        "ok": True,
        "restart_recovery": {
            "client_order_id_column_present": "client_order_id" in cols,
            "can_add_column": ensure_client_order_id_column(engine) if "client_order_id" not in cols else False,
            "bootstrap_if_called_now": recovery_summary,
            "note": "bootstrap_runtime_state runs on app startup; counts here are idempotent re-sync",
        },
        "duplicate_prevention": {
            "client_order_id_on_orders_table": "client_order_id" in cols,
            "risk_duplicate_window_seconds": _limits_dict().get("duplicate_window_seconds"),
            "note": "Risk engine rejects duplicate client_order_id within the configured window",
        },
        "shadow_visibility": {
            "db_shadow_orders": shadow_db,
            "memory_shadow_orders": len(SHADOW_ORDERS or []),
            "audit_endpoint": "/safety/shadow-audit",
        },
        "alerting": {
            "webhook_configured": bool((os.getenv("ALERT_WEBHOOK_URL") or "").strip()),
            "telegram_configured": bool(
                (os.getenv("ALERT_TELEGRAM_BOT_TOKEN") or "").strip()
                and (os.getenv("ALERT_TELEGRAM_CHAT_ID") or "").strip()
            ),
            "min_level": os.getenv("ALERT_MIN_LEVEL", "WARN"),
            "extra_sinks_registered": len(alert_mod._extra_sinks),
        },
    }


# ----------------------------- Phase 2B health --------------------------------


@router.get(
    "/safety/phase2b-health",
    summary="Continuous monitoring: scheduler heartbeat, decision-order integrity, adaptive status",
)
def phase2b_health(
    days: int = 30, db: Session = Depends(_get_db)
) -> Dict[str, Any]:
    """
    Self-check for Phase 2B's mandatory requirements (per Saad's approval —
    docs/CLIENT-SAAD-ORDER-ORIGIN-VS-DECISIONS.md), so integrity issues are
    caught between validation runs rather than only when an external audit
    happens to pull evidence. No DB writes, no exchange calls.

    `days` scopes the integrity/duplicate checks to orders created in the
    last N days (default 30) — pre-Phase-2A test orders predating trigger
    tracking would otherwise permanently show as orphaned/unlinked, which is
    a known historical artifact, not a current regression.

    Checks:
    - scheduler_heartbeat: is the unattended scheduler still ticking on schedule?
    - decision_order_integrity: any orphaned Order/TradingDecisionLog rows
      (within the `days` window)?
    - adaptive_engine: is FULLY_ADAPTIVE_ENGINE on, and is posture actually varying?
    - risk_controls: kill switch + risk limits still resolvable.
    - duplicate_orders: any client_order_id reused across orders (within the
      `days` window)?
    """
    import os

    from sqlalchemy import func

    from src.core.config import get_settings
    from src.db.models import Order, TradingDecisionLog

    settings = get_settings()
    checks: List[Dict[str, Any]] = []
    safe_days = max(1, min(int(days), 365))
    since = datetime.utcnow() - timedelta(days=safe_days)

    # --- 1. Scheduler heartbeat -------------------------------------------------
    last_cycle_ts = (
        db.query(func.max(TradingDecisionLog.ts))
        .filter(TradingDecisionLog.triggered_by == "scheduler")
        .scalar()
    )
    max_cycle_id = (
        db.query(func.max(TradingDecisionLog.cycle_id))
        .filter(TradingDecisionLog.triggered_by == "scheduler")
        .scalar()
    )
    try:
        interval_min = max(1, min(60, int(os.getenv("SCHEDULER_INTERVAL_MINUTES", "5"))))
    except ValueError:
        interval_min = 5
    minutes_since_last_cycle = None
    heartbeat_ok = False
    if last_cycle_ts is not None:
        minutes_since_last_cycle = (
            datetime.utcnow() - last_cycle_ts
        ).total_seconds() / 60.0
        # Allow 3x the configured interval before flagging a stall (covers
        # occasional slow cycles / misfire grace without false alarms).
        heartbeat_ok = minutes_since_last_cycle <= (interval_min * 3)
    checks.append(
        {
            "name": "scheduler_heartbeat",
            "ok": heartbeat_ok,
            "detail": {
                "last_scheduler_decision_ts": (
                    last_cycle_ts.isoformat() if last_cycle_ts else None
                ),
                "minutes_since_last_cycle": (
                    round(minutes_since_last_cycle, 2)
                    if minutes_since_last_cycle is not None
                    else None
                ),
                "expected_interval_minutes": interval_min,
                "max_cycle_id": max_cycle_id,
            },
        }
    )

    # --- 2. Decision -> Order integrity ------------------------------------------
    orphaned_executed_decisions = (
        db.query(func.count(TradingDecisionLog.id))
        .filter(TradingDecisionLog.executed == True)  # noqa: E712
        .filter(TradingDecisionLog.order_id.is_(None))
        .filter(TradingDecisionLog.ts >= since)
        .scalar()
        or 0
    )
    decision_order_ids = {
        row[0]
        for row in db.query(TradingDecisionLog.order_id).filter(
            TradingDecisionLog.order_id.isnot(None)
        )
    }
    non_backtest_order_ids = {
        row[0]
        for row in db.query(Order.id).filter(
            Order.mode != "backtest", Order.created_at >= since
        )
    }
    orphaned_orders = non_backtest_order_ids - decision_order_ids
    checks.append(
        {
            "name": "decision_order_integrity",
            "ok": orphaned_executed_decisions == 0 and len(orphaned_orders) == 0,
            "detail": {
                "window_days": safe_days,
                "executed_decisions_missing_order_id": int(orphaned_executed_decisions),
                "orders_without_a_linking_decision": len(orphaned_orders),
                "sample_orphaned_order_ids": sorted(orphaned_orders)[:10],
                "note": (
                    "paper/shadow/live orders only, within the window — backtest "
                    "orders are excluded since backtests don't log "
                    "TradingDecisionLog rows"
                ),
            },
        }
    )

    # --- 3. Adaptive engine status ------------------------------------------------
    recent_scheduler_decisions = (
        db.query(TradingDecisionLog.signals_json)
        .filter(TradingDecisionLog.triggered_by == "scheduler")
        .order_by(TradingDecisionLog.id.desc())
        .limit(200)
        .all()
    )
    postures: Dict[str, int] = {}
    for (raw,) in recent_scheduler_decisions:
        sig = _parse_decision_signals(raw)
        posture = (sig.get("active_thresholds") or {}).get("adaptive_posture")
        if posture:
            postures[posture] = postures.get(posture, 0) + 1
    fully_adaptive_on = bool(getattr(settings, "fully_adaptive_engine", False))
    checks.append(
        {
            "name": "adaptive_engine",
            "ok": fully_adaptive_on,
            "detail": {
                "fully_adaptive_engine_enabled": fully_adaptive_on,
                "posture_distribution_last_200_scheduler_decisions": postures,
                "dynamic_evidence": len(postures) > 1,
                "note": (
                    "dynamic_evidence=false with a single posture only means the "
                    "market stayed in one regime for this window, not that the "
                    "engine is static — compare against active_thresholds values "
                    "changing on /exchange/decisions/recent for confirmation"
                ),
            },
        }
    )

    # --- 4. Risk controls ----------------------------------------------------------
    ks_state = ks.get_state()
    try:
        limits_ok = bool(_limits_dict())
    except Exception:
        limits_ok = False
    checks.append(
        {
            "name": "risk_controls_active",
            "ok": (not bool(ks_state.get("engaged"))) and limits_ok,
            "detail": {
                "kill_switch_engaged": bool(ks_state.get("engaged")),
                "risk_limits_resolved": limits_ok,
            },
        }
    )

    # --- 5. Duplicate order protection ---------------------------------------------
    dup_rows = (
        db.query(Order.client_order_id, func.count(Order.id))
        .filter(Order.client_order_id.isnot(None), Order.created_at >= since)
        .group_by(Order.client_order_id)
        .having(func.count(Order.id) > 1)
        .all()
    )
    checks.append(
        {
            "name": "duplicate_order_protection",
            "ok": len(dup_rows) == 0,
            "detail": {
                "window_days": safe_days,
                "duplicate_client_order_ids": [
                    {"client_order_id": cid, "count": cnt} for cid, cnt in dup_rows
                ],
            },
        }
    )

    overall_ok = all(c["ok"] for c in checks)
    return sanitize_for_json(
        {
            "ok": True,
            "status": "PASS" if overall_ok else "FAIL",
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "checks": checks,
        }
    )


# ----------------------------- live readiness --------------------------------


@router.get(
    "/safety/live-readiness",
    summary="Single yes/no answer: is the system safe to trade REAL money now?",
)
def live_readiness() -> Dict[str, Any]:
    """
    Aggregates every safety/operational signal a human would check before
    flipping the system into LIVE on mainnet:

    * Kill switch released
    * Execution mode resolution
    * Binance key configuration (overlay + env)
    * Testnet vs mainnet
    * Risk limits resolved
    * Scheduler enabled state

    Returns `ready_for_live_capital: bool` plus a per-check breakdown so the
    dashboard can show actionable warnings. **No DB writes, no exchange calls.**
    """
    from src.exchange.runtime_keys import get_overlay_snapshot, resolve_runtime_keys

    keys = resolve_runtime_keys()
    keys_overlay = get_overlay_snapshot()
    ks_state = ks.get_state()
    mode = mode_snapshot()

    # Scheduler runtime flag (DB-backed, read only).
    scheduler_enabled = None
    try:
        from src.db.models import AppSetting
        from src.db.session import SessionLocal

        db = SessionLocal()
        try:
            row = db.query(AppSetting).filter_by(key="LIVE_SCHEDULER_ENABLED").first()
            scheduler_enabled = (row.value.lower() == "true") if row else False
        finally:
            db.close()
    except Exception:
        scheduler_enabled = None

    checks = []

    # 1. Kill switch must be released.
    checks.append(
        {
            "name": "kill_switch_released",
            "ok": not bool(ks_state.get("engaged")),
            "detail": (
                f"kill switch engaged: {ks_state.get('reason')!r}"
                if ks_state.get("engaged")
                else "kill switch released"
            ),
        }
    )

    # 2. Binance keys must be present.
    checks.append(
        {
            "name": "binance_keys_present",
            "ok": bool(keys.api_key_set and keys.api_secret_set),
            "detail": (
                f"key_set={keys.api_key_set} secret_set={keys.api_secret_set} "
                f"source={keys.source}"
            ),
        }
    )

    # 3. Secrets encryption configured (warn, not block).
    checks.append(
        {
            "name": "secrets_encryption_configured",
            "ok": bool(keys_overlay.get("encryption_available")),
            "detail": (
                "SECRETS_ENCRYPTION_KEY set — secret encrypted at rest"
                if keys_overlay.get("encryption_available")
                else "SECRETS_ENCRYPTION_KEY missing — secret stored as plaintext (set it before going live)"
            ),
            "severity": "warn",
        }
    )

    # 4. Testnet status — informational, since live capital can run on either.
    checks.append(
        {
            "name": "exchange_environment",
            "ok": True,
            "detail": (
                "TESTNET (paper-money exchange)"
                if keys.testnet
                else "MAINNET (REAL money exchange)"
            ),
            "severity": "info",
        }
    )

    # 5. Execution mode — paper/shadow is "ready=true; not live" — informational.
    is_live = mode["effective_mode"] == "live"
    checks.append(
        {
            "name": "execution_mode_is_live",
            "ok": is_live,
            "detail": f"effective execution mode: {mode['effective_mode']}",
            "severity": "info" if not is_live else None,
        }
    )

    # 6. Risk limits resolvable.
    try:
        lim = _limits_dict()
        checks.append(
            {
                "name": "risk_limits_resolved",
                "ok": True,
                "detail": lim,
            }
        )
    except Exception as exc:
        checks.append(
            {
                "name": "risk_limits_resolved",
                "ok": False,
                "detail": f"failed to resolve RISK_* env: {exc}",
            }
        )

    # 7. Scheduler state.
    checks.append(
        {
            "name": "scheduler_enabled",
            "ok": scheduler_enabled is True,
            "detail": f"LIVE_SCHEDULER_ENABLED={scheduler_enabled}",
            "severity": "info",
        }
    )

    blocking = [c for c in checks if not c["ok"] and c.get("severity") not in ("info", "warn")]
    warnings = [c for c in checks if not c["ok"] and c.get("severity") == "warn"]

    ready = (
        len(blocking) == 0
        and keys.api_key_set
        and keys.api_secret_set
        and not bool(ks_state.get("engaged"))
        and mode["effective_mode"] == "live"
        and keys.testnet is False
    )

    return {
        "ok": True,
        "ready_for_live_capital": bool(ready),
        "ready_for_live_capital_reason": (
            "all required checks pass; system is ready for live mainnet trading"
            if ready
            else "one or more required checks not satisfied — see `checks`"
        ),
        "checks": checks,
        "blocking_checks": [c["name"] for c in blocking],
        "warnings": [c["name"] for c in warnings],
        "snapshot": {
            "execution_mode": mode,
            "kill_switch": ks_state,
            "binance_keys": keys_overlay,
            "scheduler_enabled": scheduler_enabled,
        },
    }


# ----------------------------- Phase 2C micro-live -----------------------------


class Phase2CActionBody(BaseModel):
    reason: str = Field(..., min_length=1, max_length=1000)
    by: Optional[str] = Field(default="api", max_length=64)


@router.get(
    "/safety/phase2c/status",
    summary="Phase 2C micro-live gate status (read-only)",
)
def phase2c_status(db: Session = Depends(_get_db)) -> Dict[str, Any]:
    from src.live.auto_trade_engine import AutoTradeEngine
    from src.safety import phase2c as p2c

    snap = p2c.snapshot()
    limits = _limits_dict()
    risk_state = {}
    try:
        eng = AutoTradeEngine(db=db)
        rs = eng._build_risk_state()
        risk_state = {
            "open_positions_count": rs.open_positions_count,
            "daily_realized_pnl_usdt": rs.daily_realized_pnl_usdt,
            "current_total_exposure_usdt": rs.current_total_exposure_usdt,
            "cumulative_realized_pnl_usdt": rs.cumulative_realized_pnl_usdt,
            "account_balance_usdt": rs.account_balance_usdt,
        }
    except Exception as exc:
        risk_state = {"error": str(exc)[:200]}

    return {
        "ok": True,
        **snap,
        "limits": limits,
        "risk_state": risk_state,
        "adaptive_ai_note": (
            "Position-sizing limits are enforced at the RiskEngine layer only. "
            "Adaptive AI thresholds (active_thresholds, adaptive_posture) are unchanged."
        ),
    }


@router.get(
    "/safety/phase2c/evidence",
    summary="Read-only Phase 2C execution chain evidence for 72h validation",
)
def phase2c_evidence(
    symbol: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(_get_db),
) -> Dict[str, Any]:
    from src.db.models import Order, Position, TradingDecisionLog
    from src.safety import phase2c as p2c

    sym = (symbol or "").strip().upper() or None
    safe_limit = max(1, min(int(limit), 500))

    dec_q = db.query(TradingDecisionLog)
    ord_q = db.query(Order).filter(Order.mode == "live")
    pos_q = db.query(Position).filter(Position.mode == "live")
    if sym:
        dec_q = dec_q.filter(TradingDecisionLog.symbol == sym)
        ord_q = ord_q.filter(Order.symbol == sym)
        pos_q = pos_q.filter(Position.symbol == sym)

    decisions = (
        dec_q.order_by(TradingDecisionLog.ts.desc()).limit(safe_limit).all()
    )
    orders = ord_q.order_by(Order.created_at.desc()).limit(safe_limit).all()
    positions = pos_q.order_by(Position.entry_ts.desc()).limit(safe_limit).all()

    def _dec_row(d: TradingDecisionLog) -> Dict[str, Any]:
        return {
            "id": d.id,
            "ts": d.ts.isoformat() if d.ts else None,
            "symbol": d.symbol,
            "action": d.action,
            "executed": d.executed,
            "triggered_by": getattr(d, "triggered_by", None),
            "final_source": getattr(d, "final_source", None),
            "active_thresholds": getattr(d, "active_thresholds", None),
            "adaptive_posture": getattr(d, "adaptive_posture", None),
            "market_regime": getattr(d, "market_regime", None),
            "ml_confidence": getattr(d, "ml_confidence", None),
            "reason": (d.reason or "")[:500] if d.reason else None,
        }

    def _ord_row(o: Order) -> Dict[str, Any]:
        return {
            "id": o.id,
            "created_at": o.created_at.isoformat() if o.created_at else None,
            "symbol": o.symbol,
            "side": o.side,
            "quantity": o.quantity,
            "executed_price": o.executed_price,
            "status": o.status,
            "exchange_order_id": o.exchange_order_id,
            "client_order_id": o.client_order_id,
            "mode": o.mode,
        }

    return {
        "ok": True,
        "phase2c": p2c.snapshot(),
        "limits": _limits_dict(),
        "kill_switch": ks.get_state(),
        "execution_mode": mode_snapshot(),
        "decisions": [_dec_row(d) for d in decisions],
        "orders": [_ord_row(o) for o in orders],
        "positions": [
            {
                "id": p.id,
                "symbol": p.symbol,
                "is_open": p.is_open,
                "entry_price": p.entry_price,
                "entry_qty": p.entry_qty,
                "exit_price": p.exit_price,
                "pnl": p.pnl,
                "mode": p.mode,
            }
            for p in positions
        ],
        "monitoring_endpoints": {
            "phase2c_status": "/safety/phase2c/status",
            "safety_status": "/safety/status",
            "live_readiness": "/safety/live-readiness",
            "exchange_proof": "/exchange/proof?mode=live",
            "ai_observability": "/exchange/ai-observability",
            "decisions_recent": "/exchange/decisions/recent",
            "exchange_reconcile": "/safety/exchange-reconcile?mode=live",
        },
    }


@router.post(
    "/safety/phase2c/activate",
    summary="Enable Phase 2C micro-live (admin — does NOT switch execution mode)",
)
def phase2c_activate(body: Phase2CActionBody) -> Dict[str, Any]:
    from src.safety import phase2c as p2c

    if ks.is_engaged():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="kill switch engaged; release before activating micro-live",
        )
    snap = p2c.activate(by=body.by or "api", reason=body.reason)
    return {"ok": True, "activated": True, **snap}


@router.post(
    "/safety/phase2c/deactivate",
    summary="Disable Phase 2C micro-live",
)
def phase2c_deactivate(body: Phase2CActionBody) -> Dict[str, Any]:
    from src.safety import phase2c as p2c

    snap = p2c.deactivate(by=body.by or "api", reason=body.reason)
    return {"ok": True, "activated": False, **snap}
