"""
Deterministic position sizing: risk-per-trade with notional cap.

Long entry: stop must be below entry so (entry - stop) > 0 defines risk per unit.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def compute_position_size(
    equity: float,
    entry_price: float,
    stop_loss: float,
    max_position_pct: float,
    risk_per_trade_pct: float,
    max_notional_usdt: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Returns ``{"ok": bool, "qty": float, "reason": str}``.

    - ``qty`` is base-asset quantity (coin units), capped by max notional (``max_position_pct``).
    - Risk-based: ``(equity * risk_per_trade_pct) / (entry - stop)`` per unit risk.
    - Optional ``max_notional_usdt`` applies an absolute USDT ceiling (Phase 2A risk limit)
      without changing the configured max-trade risk cap itself.
    """
    if equity <= 0 or entry_price <= 0:
        return {"ok": False, "qty": 0.0, "reason": "invalid_equity_or_entry_price"}
    if stop_loss <= 0:
        return {"ok": False, "qty": 0.0, "reason": "invalid_stop_loss"}
    risk_per_unit = entry_price - stop_loss
    if risk_per_unit <= 0:
        return {
            "ok": False,
            "qty": 0.0,
            "reason": "stop_not_below_entry_for_long",
        }

    mp = max(0.0, min(1.0, float(max_position_pct)))
    rp = max(0.0, min(1.0, float(risk_per_trade_pct)))

    risk_budget = equity * rp
    qty_risk = risk_budget / risk_per_unit

    notional_cap = equity * mp
    if max_notional_usdt is not None and float(max_notional_usdt) > 0:
        notional_cap = min(notional_cap, float(max_notional_usdt))
    qty_cap = notional_cap / entry_price

    qty = min(qty_risk, qty_cap)
    if qty <= 0:
        return {"ok": False, "qty": 0.0, "reason": "qty_non_positive_after_caps"}

    return {
        "ok": True,
        "qty": float(qty),
        "reason": "ok",
        "notional_cap_usdt": float(notional_cap),
    }
