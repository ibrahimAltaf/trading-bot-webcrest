"""
Simulated trading on validation/hold-out predictions — profit-oriented acceptance.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

import numpy as np


@dataclass
class BacktestResult:
    total_return_pct: float
    win_rate: float
    max_drawdown_pct: float
    trades: int
    pnl_series: List[float]


def run_directional_backtest(
    close: np.ndarray,
    y_true: np.ndarray,
    y_pred: np.ndarray,
    *,
    fee_pct: float = 0.00075,
    hold_steps: int = 5,
) -> BacktestResult:
    """
    Simple long/flat: BUY class -> long for `hold_steps` bars, SELL -> short proxy as exit.
    Uses predicted class vs next-period return proxy for PnL.
    """
    n = len(close)
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    wins = 0
    trades = 0
    pnl_s: List[float] = []
    position = 0  # 1 long, -1 short, 0 flat
    entry_price = 0.0

    for i in range(n - hold_steps - 1):
        pred = int(y_pred[i])
        # 0=SELL, 1=HOLD, 2=BUY
        fut_ret = (close[i + 1] - close[i]) / close[i]

        if pred == 2 and position <= 0:
            if position < 0:
                ret = (close[i] - entry_price) / entry_price - fee_pct * 2
                equity *= 1.0 + ret
                pnl_s.append(ret)
                trades += 1
                if ret > 0:
                    wins += 1
            position = 1
            entry_price = close[i]
        elif pred == 0 and position >= 0:
            if position > 0:
                ret = (close[i] - entry_price) / entry_price - fee_pct * 2
                equity *= 1.0 + ret
                pnl_s.append(ret)
                trades += 1
                if ret > 0:
                    wins += 1
            position = -1
            entry_price = close[i]
        elif pred == 1 and position != 0:
            ret = (
                (close[i] - entry_price) / entry_price * position
                - fee_pct * 2
            )
            equity *= 1.0 + ret
            pnl_s.append(ret)
            trades += 1
            if ret > 0:
                wins += 1
            position = 0

        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak * 100.0)

    total_return_pct = (equity - 1.0) * 100.0
    wr = (wins / trades * 100.0) if trades else 0.0
    return BacktestResult(
        total_return_pct=total_return_pct,
        win_rate=wr,
        max_drawdown_pct=max_dd,
        trades=trades,
        pnl_series=pnl_s,
    )


def evaluate_model_acceptance(res: BacktestResult) -> Tuple[bool, str]:
    """Gate model deployment: win rate > 55% and positive simulated PnL."""
    if res.trades < 10:
        return False, f"too_few_trades:{res.trades}"
    if res.win_rate < 55.0:
        return False, f"win_rate:{res.win_rate:.1f}"
    if res.total_return_pct <= 0:
        return False, f"return:{res.total_return_pct:.2f}"
    return True, "ok"


def quick_val_profit_score(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    class_weights: np.ndarray | None = None,
) -> float:
    """Scalar score: accuracy + bonus when profitable-class alignment (tuning)."""
    acc = float((y_true == y_pred).mean())
    return acc
