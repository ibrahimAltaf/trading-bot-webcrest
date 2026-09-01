"""
In-process position tracker for paper trading.
POSITIONS list is read by /exchange/proof for audit proof.
"""
from typing import Any, Dict, List

POSITIONS: List[Dict[str, Any]] = []


def update_position(order: Dict[str, Any]) -> Dict[str, Any]:
    """
    Append a new OPEN position derived from a filled order.

    Parameters
    ----------
    order : dict returned by execution_engine.execute_trade()
    """
    position: Dict[str, Any] = {
        "symbol": order["symbol"],
        "entry_price": order["price"],
        "status": "OPEN",
        "timestamp": order["timestamp"],
    }
    POSITIONS.append(position)
    return position
