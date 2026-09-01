"""
Main Trading Loop
-----------------
Connects the ML-primary decision engine to the paper execution engine.

Usage example:
    from src.main_loop import run_trading_cycle
    result = run_trading_cycle(features_df, data)
"""
from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from src.strategy.decision_engine import make_decision
from src.execution.execution_engine import execute_trade
from src.execution.positions import update_position


def run_trading_cycle(
    features_df: pd.DataFrame,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Single trading cycle:
      1. Generate ML-primary decision
      2. Execute paper trade if BUY or SELL
      3. Track open position on BUY
      4. Return enriched decision dict

    Parameters
    ----------
    features_df : indicator-enriched OHLCV DataFrame for LSTM window
    data        : dict with keys: symbol (str), price (float),
                  ema_fast (float), ema_slow (float), rsi (float)
    """
    decision = make_decision(features_df, data)

    if decision.get("action") in ("BUY", "SELL"):
        order = execute_trade(
            symbol=data["symbol"],
            action=decision["action"],
            price=data["price"],
        )
        decision["executed"] = True
        decision["order"] = order

        if decision["action"] == "BUY":
            update_position(order)
    else:
        decision["executed"] = False
        decision["order"] = None

    return decision
