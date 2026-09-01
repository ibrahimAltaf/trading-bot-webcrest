"""
State reconciliation skeleton (Phase 2A).

Goal: detect drift between local DB, in-process trackers, and the exchange.
Phase 2A implements the *interface and DB-only checks* — exchange-side
verification will be implemented when shadow/live execution is wired in.

Public entry point
------------------
    report = reconcile(db_session)
    # ReportDict:
    #   orders: {db_count, open_positions, mode_breakdown}
    #   positions: {open, closed}
    #   paper_tracker: {in_memory_orders, in_memory_positions}
    #   drift: list of drift findings (strings)

Designed to be safe to call on a hot system — never writes.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy.orm import Session


def _safe_query_count(db: Session, model, **filters) -> int:
    try:
        q = db.query(model)
        for k, v in filters.items():
            q = q.filter(getattr(model, k) == v)
        return int(q.count())
    except Exception:
        return -1


def _mode_breakdown(db: Session, model) -> Dict[str, int]:
    from sqlalchemy import func

    try:
        rows = (
            db.query(model.mode, func.count(model.id))
            .group_by(model.mode)
            .all()
        )
        return {str(m): int(c) for m, c in rows}
    except Exception:
        return {}


def reconcile(db: Session) -> Dict[str, Any]:
    """
    Phase 2A reconciliation:

    * counts orders/positions/trades in DB grouped by mode
    * counts the in-memory paper trackers (ORDERS, POSITIONS)
    * flags obvious drift (e.g. open DB positions but no in-memory paper rows
      in paper mode — informational only)
    * stub for exchange-side checks (returns empty list for now)

    No state is modified; callers can act on the report.
    """
    from src.db.models import Order, Position, Trade

    orders_total = _safe_query_count(db, Order)
    positions_open = _safe_query_count(db, Position, is_open=True)
    positions_closed = _safe_query_count(db, Position, is_open=False)
    trades_total = _safe_query_count(db, Trade)

    orders_by_mode = _mode_breakdown(db, Order)
    positions_by_mode = _mode_breakdown(db, Position)
    trades_by_mode = _mode_breakdown(db, Trade)

    paper_orders_mem = 0
    paper_positions_mem = 0
    try:
        from src.execution.execution_engine import ORDERS

        paper_orders_mem = len(ORDERS)
    except Exception:
        pass
    try:
        from src.execution.positions import POSITIONS

        paper_positions_mem = len(POSITIONS)
    except Exception:
        pass

    drift: List[Dict[str, Any]] = []

    paper_db_orders = orders_by_mode.get("paper", 0)
    if paper_db_orders > 0 and paper_orders_mem == 0:
        drift.append(
            {
                "kind": "paper_tracker_empty_but_db_has_orders",
                "detail": (
                    f"DB has {paper_db_orders} paper orders but in-memory ORDERS list "
                    "is empty (likely a process restart — expected if backend was "
                    "restarted; reconciliation can rebuild trackers later)."
                ),
                "severity": "info",
            }
        )

    paper_db_open_positions = 0
    try:
        from src.db.models import Position

        paper_db_open_positions = int(
            db.query(Position)
            .filter(Position.is_open == True, Position.mode == "paper")  # noqa: E712
            .count()
        )
    except Exception:
        pass
    if paper_db_open_positions > 0 and paper_positions_mem == 0:
        drift.append(
            {
                "kind": "paper_open_positions_not_in_memory",
                "detail": (
                    f"{paper_db_open_positions} open paper positions in DB but the "
                    "in-memory POSITIONS tracker is empty."
                ),
                "severity": "info",
            }
        )

    return {
        "ok": True,
        "checked_at": datetime.utcnow().isoformat() + "Z",
        "drift_count": len(drift),
        "orders": {
            "db_total": orders_total,
            "by_mode": orders_by_mode,
            "paper_memory_count": paper_orders_mem,
        },
        "positions": {
            "db_open": positions_open,
            "db_closed": positions_closed,
            "by_mode": positions_by_mode,
            "paper_memory_count": paper_positions_mem,
        },
        "trades": {
            "db_total": trades_total,
            "by_mode": trades_by_mode,
        },
        "drift": drift,
        "exchange_checks": {
            "enabled": False,
            "note": (
                "Exchange-side reconciliation (Binance open orders / balances) "
                "lands with shadow + live execution wiring (Phase 2A track 2)."
            ),
        },
    }
