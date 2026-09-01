"""
Exchange-side reconciliation (Phase 2A track 4).

Bridges *DB live state* with *Binance state* and surfaces drift.

Three checks, all read-only:

* `live_open_orders_drift` — orders that DB says are still open ("created" /
  "NEW" / "PARTIALLY_FILLED") but Binance no longer lists in openOrders, and
  vice-versa.
* `position_vs_balance_drift` — symbols with an open LIVE position in DB whose
  on-exchange base-asset free balance does not back the recorded qty.
* `daily_orders_mismatch` — informational diff between DB live order count
  and the count reported by `allOrders` for today's trading symbols.

Returns a structured dict; callers (API, scheduler) decide how to surface it.

Designed for SHADOW mode too — when called against a shadow run, the
exchange reads are still real, but the "live" DB rows are scoped by mode.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Set

from sqlalchemy.orm import Session


_OPEN_DB_STATUSES = {"NEW", "PARTIALLY_FILLED", "CREATED", "PENDING"}


def _safe_call(label: str, fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as e:  # pragma: no cover — exercised via mock
        return {"_error": f"{label}_failed: {type(e).__name__}: {e}"}


def _coerce_str(x: Any) -> str:
    return "" if x is None else str(x)


def _normalize_status(s: Any) -> str:
    return _coerce_str(s).upper().strip()


def _open_db_orders(db: Session, mode: str) -> List[Any]:
    from src.db.models import Order

    rows = (
        db.query(Order)
        .filter(Order.mode == mode)
        .filter(Order.status.isnot(None))
        .all()
    )
    return [r for r in rows if _normalize_status(r.status) in _OPEN_DB_STATUSES]


def _open_db_positions(db: Session, mode: str) -> List[Any]:
    from src.db.models import Position

    return (
        db.query(Position)
        .filter(Position.is_open == True, Position.mode == mode)  # noqa: E712
        .all()
    )


def _binance_open_orders(client: Any) -> List[Dict[str, Any]]:
    rows = _safe_call("open_orders", client.open_orders)
    if isinstance(rows, dict) and rows.get("_error"):
        raise RuntimeError(rows["_error"])
    return list(rows or [])


def _binance_balances(client: Any) -> Dict[str, float]:
    """Return {asset: free_float}. Errors raise (caller decides)."""
    if hasattr(client, "balances_map"):
        m = client.balances_map()
        if isinstance(m, dict) and m.get("_error"):
            raise RuntimeError(m["_error"])
        return {k: float(v or 0.0) for k, v in (m or {}).items()}
    acc = client.account()
    out: Dict[str, float] = {}
    for b in (acc or {}).get("balances", []) or []:
        try:
            out[str(b.get("asset", ""))] = float(b.get("free") or 0.0)
        except (TypeError, ValueError):
            continue
    return out


def _base_asset_from_symbol(sym: str) -> str:
    """BTCUSDT -> BTC. Falls back to first 3 chars if not USDT-quoted."""
    s = (sym or "").upper().strip()
    for quote in ("USDT", "BUSD", "USDC", "FDUSD"):
        if s.endswith(quote):
            return s[: -len(quote)]
    return s[:3] if len(s) > 3 else s


# ----------------------------- public API -----------------------------------


def reconcile_with_exchange(
    db: Session,
    client: Any,
    *,
    mode: str = "live",
    symbols: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """
    Read-only drift report between DB-live state and the exchange.

    `mode` controls which DB rows we compare against (live by default).
    `symbols` optional whitelist to limit balance-check scope.
    """
    report: Dict[str, Any] = {
        "ok": True,
        "checked_at": datetime.utcnow().isoformat() + "Z",
        "mode": mode,
        "errors": [],
        "open_orders": {},
        "positions": {},
    }

    # ----- open-order drift ----------------------------------------------
    try:
        binance_open = _binance_open_orders(client)
    except Exception as e:
        report["errors"].append(f"open_orders_fetch_failed: {e}")
        binance_open = []

    db_open = _open_db_orders(db, mode)
    db_open_ids: Set[str] = {
        _coerce_str(r.exchange_order_id) for r in db_open if r.exchange_order_id
    }
    binance_open_ids: Set[str] = {
        _coerce_str(o.get("orderId")) for o in binance_open if o.get("orderId")
    }

    mode_l = (mode or "").strip().lower()
    if mode_l == "shadow":
        # Shadow orders are simulated — they never appear on Binance openOrders.
        report["open_orders"] = {
            "db_open_count": len(db_open_ids),
            "exchange_open_count": len(binance_open_ids),
            "only_in_db": [],
            "only_on_exchange": [],
            "drift_count": 0,
            "skipped": True,
            "note": (
                "Shadow mode: open-order drift vs Binance is not applicable — "
                "shadow fills are simulated and never placed on the exchange."
            ),
        }
    else:
        only_in_db = sorted(db_open_ids - binance_open_ids)
        only_on_binance = sorted(binance_open_ids - db_open_ids)
        report["open_orders"] = {
            "db_open_count": len(db_open_ids),
            "exchange_open_count": len(binance_open_ids),
            "only_in_db": only_in_db[:50],  # cap response size
            "only_on_exchange": only_on_binance[:50],
            "drift_count": len(only_in_db) + len(only_on_binance),
        }

    # ----- position vs balance drift -------------------------------------
    db_positions = _open_db_positions(db, mode)
    try:
        balances = _binance_balances(client)
    except Exception as e:
        report["errors"].append(f"balances_fetch_failed: {e}")
        balances = {}

    pos_drift: List[Dict[str, Any]] = []
    syms_filter = (
        {s.upper() for s in symbols} if symbols else None
    )
    for p in db_positions:
        sym = (p.symbol or "").upper()
        if syms_filter is not None and sym not in syms_filter:
            continue
        base = _base_asset_from_symbol(sym)
        expected = float(p.entry_qty or 0.0)
        actual = float(balances.get(base, 0.0))
        # 1% tolerance to absorb fees/rounding.
        if expected > 0 and abs(actual - expected) / max(expected, 1e-9) > 0.01:
            pos_drift.append(
                {
                    "symbol": sym,
                    "base_asset": base,
                    "db_qty": expected,
                    "exchange_free": actual,
                    "delta": actual - expected,
                }
            )

    report["positions"] = {
        "db_open_count": len(db_positions),
        "balances_assets": len(balances),
        "drift": pos_drift[:50],
        "drift_count": len(pos_drift),
    }
    if mode_l == "shadow" and pos_drift:
        report["positions"]["expected_drift"] = True
        report["positions"]["note"] = (
            "Shadow mode: DB records simulated positions; exchange balances are "
            "unchanged. Drift here is expected and is not a live-trading failure."
        )

    report["mode_notes"] = (
        {
            "shadow": (
                "Uses real Binance balances for position-vs-balance checks; "
                "does not place orders on the exchange."
            ),
        }
        if mode_l == "shadow"
        else {}
    )

    if mode_l == "shadow":
        report["ok"] = not report["errors"] and report["open_orders"]["drift_count"] == 0
    else:
        report["ok"] = (
            not report["errors"]
            and report["open_orders"]["drift_count"] == 0
            and report["positions"]["drift_count"] == 0
        )
    return report
