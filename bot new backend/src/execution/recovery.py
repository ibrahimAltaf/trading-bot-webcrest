"""
Restart recovery for in-memory paper / shadow trackers (Phase 2A track 3).

When the backend restarts, the SQLite/PostgreSQL DB still holds every paper
and shadow order/position, but the in-process ORDERS / SHADOW_ORDERS /
POSITIONS dicts are empty. Callers (proof endpoints, reconciler, drift
detection) see false drift until the trackers are re-hydrated.

`bootstrap_runtime_state()` rebuilds those trackers from DB on startup.
Idempotent: calling it again is a no-op (existing entries are not duplicated).

Also adds a tiny one-time `ALTER TABLE orders ADD COLUMN client_order_id`
shim for SQLite / PostgreSQL — Phase 2A track 3 introduces the column and
existing DBs need it patched in without a full migration framework.
"""
from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session


# --------------------------- column shim -------------------------------------


def ensure_client_order_id_column(engine: Engine) -> bool:
    """Add `client_order_id` to `orders` if missing. Returns True if added."""
    try:
        insp = inspect(engine)
        cols = {c["name"] for c in insp.get_columns("orders")}
    except Exception:
        return False
    if "client_order_id" in cols:
        return False
    try:
        with engine.begin() as conn:
            conn.execute(
                text("ALTER TABLE orders ADD COLUMN client_order_id VARCHAR(64)")
            )
        return True
    except Exception as e:  # SQLite versions ≥ 3.35 support this natively.
        print(f"[recovery] client_order_id ADD COLUMN skipped: {e}")
        return False


def ensure_trigger_tracking_columns(engine: Engine) -> bool:
    """Add `triggered_by`/`cycle_id` to `orders` + `trading_decisions` if missing.

    These columns record whether an order/decision came from an unattended
    scheduler cycle, a manual API call, or a proof_forced audit call — the
    authoritative signal external validators need to prove autonomous AI
    execution (see routes_safety._classify_order_origin). Returns True if any
    column was added.
    """
    added = False
    try:
        insp = inspect(engine)
    except Exception:
        return False
    for table in ("orders", "trading_decisions"):
        try:
            cols = {c["name"] for c in insp.get_columns(table)}
        except Exception:
            continue
        for col, coltype in (("triggered_by", "VARCHAR(20)"), ("cycle_id", "INTEGER")):
            if col in cols:
                continue
            try:
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}"))
                added = True
            except Exception as e:
                print(f"[recovery] {table}.{col} ADD COLUMN skipped: {e}")
    return added


# --------------------------- tracker rebuilders ------------------------------


def _rebuild_paper_orders(db: Session) -> int:
    """Re-hydrate ORDERS list from filled paper orders in DB."""
    from src.db.models import Order
    from src.execution.execution_engine import ORDERS

    rows: List[Any] = (
        db.query(Order).filter(Order.mode == "paper").order_by(Order.created_at.asc()).all()
    )
    existing = {str(o.get("orderId") or "") for o in ORDERS if isinstance(o, dict)}
    added = 0
    for r in rows:
        oid = str(r.exchange_order_id or "")
        if not oid or oid in existing:
            continue
        ORDERS.append(
            {
                "orderId": oid,
                "clientOrderId": r.client_order_id,
                "symbol": r.symbol,
                "side": r.side,
                "price": r.executed_price or r.requested_price,
                "status": (r.status or "FILLED").upper(),
                "execution_mode": "paper",
                "timestamp": r.created_at.isoformat() if r.created_at else None,
                "_restored": True,
            }
        )
        existing.add(oid)
        added += 1
    return added


def _rebuild_shadow_orders(db: Session) -> int:
    """Re-hydrate SHADOW_ORDERS list from filled shadow orders in DB."""
    from src.db.models import Order
    from src.execution.execution_engine import SHADOW_ORDERS

    rows: List[Any] = (
        db.query(Order).filter(Order.mode == "shadow").order_by(Order.created_at.asc()).all()
    )
    existing = {str(o.get("orderId") or "") for o in SHADOW_ORDERS if isinstance(o, dict)}
    added = 0
    for r in rows:
        oid = str(r.exchange_order_id or "")
        if not oid or oid in existing:
            continue
        SHADOW_ORDERS.append(
            {
                "orderId": oid,
                "clientOrderId": r.client_order_id,
                "symbol": r.symbol,
                "side": r.side,
                "price": r.executed_price or r.requested_price,
                "executedQty": f"{r.quantity:.8f}" if r.quantity is not None else "0",
                "status": (r.status or "FILLED").upper(),
                "type": r.order_type or "MARKET",
                "execution_mode": "shadow",
                "timestamp": r.created_at.isoformat() if r.created_at else None,
                "_restored": True,
            }
        )
        existing.add(oid)
        added += 1
    return added


def _rebuild_paper_positions(db: Session) -> int:
    """Re-hydrate POSITIONS list from open paper positions in DB."""
    from src.db.models import Position
    from src.execution.positions import POSITIONS

    rows: List[Any] = (
        db.query(Position)
        .filter(Position.is_open == True, Position.mode == "paper")  # noqa: E712
        .all()
    )
    existing_syms = {p.get("symbol") for p in POSITIONS if isinstance(p, dict)}
    added = 0
    for r in rows:
        sym = r.symbol
        if not sym or sym in existing_syms:
            continue
        POSITIONS.append(
            {
                "symbol": sym,
                "side": "LONG",
                "status": "OPEN",
                "quantity": float(r.entry_qty or 0.0),
                "entry_price": float(r.entry_price or 0.0),
                "entry_ts": r.entry_ts.isoformat() if r.entry_ts else None,
                "_restored": True,
            }
        )
        existing_syms.add(sym)
        added += 1
    return added


def bootstrap_runtime_state(db: Session) -> Dict[str, int]:
    """
    Top-level entry point — restores in-memory trackers from DB.
    Returns a summary dict for the startup log.
    """
    return {
        "paper_orders_restored": _rebuild_paper_orders(db),
        "shadow_orders_restored": _rebuild_shadow_orders(db),
        "paper_positions_restored": _rebuild_paper_positions(db),
    }
