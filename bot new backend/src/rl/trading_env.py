"""
Multi-asset gymnasium environment for PPO training (synthetic walk; swap data source for production).

Actions (Discrete):
  0 HOLD
  1 BUY_BTC   2 SELL_BTC
  3 BUY_ETH   4 SELL_ETH
  5 BUY_SOL   6 SELL_SOL
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import numpy as np

try:
    import gymnasium as gym
    from gymnasium import spaces
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "Install gymnasium: pip install gymnasium (see requirements-rl.txt)"
    ) from e

N_ASSETS = 3
ACTION_HOLD = 0
ACTION_NAMES = (
    "HOLD",
    "BUY_BTC",
    "SELL_BTC",
    "BUY_ETH",
    "SELL_ETH",
    "BUY_SOL",
    "SELL_SOL",
)


class MultiCoinTradingEnv(gym.Env):
    """
    Simple spot-style env: 3 prices as random walk, USDT cash, per-asset inventory.
    Reward: PnL change - drawdown penalty - trade penalty.
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        *,
        initial_usdt: float = 10_000.0,
        max_steps: int = 256,
        drawdown_penalty: float = 2.0,
        trade_penalty: float = 0.0002,
        overtrade_penalty: float = 0.001,
    ):
        super().__init__()
        self.initial_usdt = float(initial_usdt)
        self.max_steps = int(max_steps)
        self.drawdown_penalty = float(drawdown_penalty)
        self.trade_penalty = float(trade_penalty)
        self.overtrade_penalty = float(overtrade_penalty)

        self.observation_space = spaces.Box(
            low=-10.0, high=10.0, shape=(24,), dtype=np.float32
        )
        self.action_space = spaces.Discrete(7)

        self.rng = np.random.default_rng()
        self._price = np.ones(N_ASSETS, dtype=np.float64) * 100.0
        self._cash = self.initial_usdt
        self._qty = np.zeros(N_ASSETS, dtype=np.float64)
        self._step_i = 0
        self._equity_peak = self.initial_usdt
        self._prev_equity = self.initial_usdt
        self._trade_count = 0

    def _equity(self) -> float:
        return float(self._cash + np.sum(self._qty * self._price))

    def _obs(self) -> np.ndarray:
        eq = self._equity()
        dd = max(0.0, (self._equity_peak - eq) / max(self._equity_peak, 1e-9))
        feat = np.concatenate(
            [
                (self._price / 100.0).astype(np.float64),
                (self._qty / 1.0).astype(np.float64),
                [self._cash / self.initial_usdt],
                [dd],
                [self._step_i / self.max_steps],
                np.zeros(24 - 2 * N_ASSETS - 3, dtype=np.float64),
            ]
        )
        return feat[:24].astype(np.float32)

    def reset(
        self,
        *,
        seed: Optional[int] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Tuple[np.ndarray, Dict[str, Any]]:
        super().reset(seed=seed)
        if seed is not None:
            self.rng = np.random.default_rng(seed)
        self._price = self.rng.uniform(80.0, 120.0, size=N_ASSETS).astype(np.float64)
        self._cash = self.initial_usdt
        self._qty = np.zeros(N_ASSETS, dtype=np.float64)
        self._step_i = 0
        self._equity_peak = self._equity()
        self._prev_equity = self._equity_peak
        self._trade_count = 0
        return self._obs(), {}

    def step(self, action: int) -> Tuple[np.ndarray, float, bool, bool, Dict[str, Any]]:
        self._step_i += 1
        # Random walk prices
        self._price *= 1.0 + self.rng.normal(0, 0.002, size=N_ASSETS)

        asset = -1
        side = None
        if action == ACTION_HOLD:
            pass
        elif action == 1:
            asset, side = 0, "BUY"
        elif action == 2:
            asset, side = 0, "SELL"
        elif action == 3:
            asset, side = 1, "BUY"
        elif action == 4:
            asset, side = 1, "SELL"
        elif action == 5:
            asset, side = 2, "BUY"
        elif action == 6:
            asset, side = 2, "SELL"

        traded = False
        if asset >= 0 and side == "BUY":
            spend = self._cash * 0.05
            if spend > 1.0:
                q = spend / self._price[asset]
                self._cash -= spend
                self._qty[asset] += q
                traded = True
        elif asset >= 0 and side == "SELL":
            if self._qty[asset] > 1e-12:
                q = self._qty[asset] * 0.25
                self._cash += q * self._price[asset]
                self._qty[asset] -= q
                traded = True

        if traded:
            self._trade_count += 1

        eq = self._equity()
        self._equity_peak = max(self._equity_peak, eq)
        pnl_delta = eq - self._prev_equity
        self._prev_equity = eq
        dd = max(0.0, (self._equity_peak - eq) / max(self._equity_peak, 1e-9))

        reward = pnl_delta / self.initial_usdt
        reward -= self.drawdown_penalty * (dd ** 2)
        reward -= self.trade_penalty * int(traded)
        reward -= self.overtrade_penalty * max(0, self._trade_count - 20) / 100.0

        terminated = self._step_i >= self.max_steps
        truncated = False
        return self._obs(), float(reward), terminated, truncated, {}
