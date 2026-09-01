"""
Portfolio risk: drawdown halt, loss streak sizing, per-asset cap.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Protocol


class SettingsLike(Protocol):
    portfolio_max_drawdown_pct: float
    portfolio_loss_reduce_factor: float
    rl_max_weight_per_asset: float


@dataclass
class PortfolioRiskState:
    """Rolling equity peak for drawdown (caller updates from snapshots)."""
    peak_equity_usdt: float = 0.0
    last_equity_usdt: float = 0.0


def drawdown_pct(state: PortfolioRiskState, equity_usdt: float) -> float:
    if equity_usdt <= 0:
        return 0.0
    if state.peak_equity_usdt <= 0:
        state.peak_equity_usdt = equity_usdt
    state.peak_equity_usdt = max(state.peak_equity_usdt, equity_usdt)
    state.last_equity_usdt = equity_usdt
    peak = state.peak_equity_usdt
    if peak <= 0:
        return 0.0
    return max(0.0, (peak - equity_usdt) / peak)


def should_halt_trading(settings: SettingsLike, dd: float) -> bool:
    cap = float(getattr(settings, "portfolio_max_drawdown_pct", 0.0) or 0.0)
    return cap > 0 and dd >= cap


def reduce_risk_after_loss(
    settings: SettingsLike, base_risk: float, last_trade_pnl: Optional[float]
) -> float:
    if last_trade_pnl is None or last_trade_pnl >= 0:
        return base_risk
    f = float(getattr(settings, "portfolio_loss_reduce_factor", 0.65) or 0.65)
    return max(1e-6, base_risk * f)


def cap_risk_by_max_weight(
    settings: SettingsLike,
    base_risk: float,
    asset_value_usdt: float,
    total_equity_usdt: float,
) -> float:
    """Cap new risk so post-trade allocation stays under rl_max_weight_per_asset of equity."""
    cap = float(getattr(settings, "rl_max_weight_per_asset", 0.4) or 0.4)
    if total_equity_usdt <= 0 or cap <= 0:
        return base_risk
    current_pct = asset_value_usdt / total_equity_usdt
    if current_pct >= cap:
        return 0.0
    headroom = cap - current_pct
    return min(base_risk, headroom)
