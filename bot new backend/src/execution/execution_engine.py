"""
Paper / Shadow Trading Execution Engines
----------------------------------------
Both simulate order fills in-process (no real exchange calls).

* `execute_trade()` → paper mode (deterministic balance, prefix `paper-*`).
* `simulate_shadow_fill()` → shadow mode (real Binance balance + filters
  upstream, but fill itself simulated; prefix `shadow-*`).

`ORDERS` / `SHADOW_ORDERS` are convenience in-memory trackers; the canonical
source of truth is the DB (Order/Trade/Position rows tagged by `mode`).
"""
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

ORDERS: List[Dict[str, Any]] = []
SHADOW_ORDERS: List[Dict[str, Any]] = []


def execute_trade(symbol: str, action: str, price: float) -> Dict[str, Any]:
    """
    Record a paper trade order and return the filled order dict.

    Parameters
    ----------
    symbol : trading pair, e.g. "BTCUSDT"
    action : "BUY" or "SELL"
    price  : current market price
    """
    # Prefix paper ids for audit clarity and easy filtering.
    oid = f"paper-{uuid.uuid4()}"
    order: Dict[str, Any] = {
        "orderId": oid,
        "symbol": symbol,
        "side": action,
        "price": price,
        "status": "FILLED",
        "execution_mode": "paper",
        "timestamp": datetime.utcnow().isoformat(),
    }
    ORDERS.append(order)
    return order


def simulate_shadow_fill(
    symbol: str,
    action: str,
    price: float,
    quantity: float,
    *,
    client_order_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Record a shadow trade order — the engine has already validated balance,
    sizing and symbol filters against the real exchange; we just synthesize a
    deterministic fill so the audit trail is identical in shape to a live one.
    """
    oid = f"shadow-{uuid.uuid4()}"
    cum_quote = float(price or 0.0) * float(quantity or 0.0)
    order: Dict[str, Any] = {
        "orderId": oid,
        "clientOrderId": client_order_id,
        "order_id": oid,
        "client_order_id": client_order_id,
        "symbol": symbol,
        "side": action,
        "price": price,
        "executedQty": f"{quantity:.8f}",
        "cummulativeQuoteQty": f"{cum_quote:.8f}",
        "status": "FILLED",
        "type": "MARKET",
        "execution_mode": "shadow",
        "timestamp": datetime.utcnow().isoformat(),
    }
    SHADOW_ORDERS.append(order)
    return order
