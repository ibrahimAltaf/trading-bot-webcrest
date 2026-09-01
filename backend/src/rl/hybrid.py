"""
Hybrid LSTM + PPO: adjust execution risk from portfolio caps and optional PPO agreement.

LSTM provides signal/confidence; PPO (if RL_PPO_MODEL_PATH set) nudges size when actions align.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np

from src.rl.portfolio_risk import cap_risk_by_max_weight, reduce_risk_after_loss

_ppo_model: Any = None


def _load_ppo(path: str) -> Any:
    global _ppo_model
    if not path:
        return None
    p = Path(path)
    # SB3 saves as stem.zip; load() expects path without .zip
    if p.suffix.lower() == ".zip" and p.is_file():
        stem = str(p.with_suffix(""))
    elif p.is_file():
        stem = str(p.with_suffix(""))
    elif p.with_suffix(".zip").is_file():
        stem = str(p.with_suffix(""))
    else:
        return None
    if _ppo_model is None:
        try:
            from stable_baselines3 import PPO

            _ppo_model = PPO.load(stem)
        except Exception:
            return None
    return _ppo_model


def _symbol_to_asset_index(symbol: str) -> int:
    s = symbol.upper()
    if s.startswith("BTC"):
        return 0
    if s.startswith("ETH"):
        return 1
    if s.startswith("SOL"):
        return 2
    return 0


def build_observation(
    df,
    symbol: str,
    balances: Dict[str, str],
    obs_dim: int = 24,
) -> np.ndarray:
    """Match MultiCoinTradingEnv observation layout (first 24 dims)."""
    row = df.iloc[-1]
    close = float(row.get("close", 1.0))
    rsi = float(row.get("rsi", 50.0)) / 100.0
    adx = float(row.get("adx", 20.0)) / 100.0
    atr_pct = float(row.get("atr_pct", 1.0)) / 10.0

    prices = np.zeros(3, dtype=np.float32)
    idx = _symbol_to_asset_index(symbol)
    prices[idx] = float(close) / max(1.0, float(df["close"].iloc[-50:].mean()))

    qty_hint = np.zeros(3, dtype=np.float32)
    usdt = float(balances.get("USDT", 0) or 0)
    for i, asset in enumerate(["BTC", "ETH", "SOL"]):
        q = float(balances.get(asset, 0) or 0)
        qty_hint[i] = q * 0.01

    cash = min(2.0, usdt / max(1.0, usdt + 1.0))
    tail = np.array([rsi, adx, atr_pct, cash], dtype=np.float32)
    obs = np.concatenate([prices, qty_hint, tail, np.zeros(obs_dim, dtype=np.float32)])[
        :obs_dim
    ]
    return obs


def ppo_agrees_with_buy(ppo_action: int, asset_idx: int) -> float:
    """Return multiplier in (0,1]: strong agreement -> 1.0, conflict -> lower."""
    buy_a = 1 + 2 * asset_idx
    sell_a = 2 + 2 * asset_idx
    if ppo_action == 0:
        return 0.75
    if ppo_action == buy_a:
        return 1.0
    if ppo_action == sell_a:
        return 0.35
    return 0.85


def adjust_risk_for_trade(
    settings: Any,
    client: Any,
    symbol: str,
    base_risk: Optional[float],
    lstm_action: str,
    lstm_conf: Optional[float],
    df: Any,
    last_closed_pnl: Optional[float] = None,
) -> Tuple[Optional[float], Optional[str]]:
    """
    Apply max-per-asset cap, loss streak shrink, optional PPO multiplier on BUY risk.
    """
    if base_risk is None:
        return None, None

    r = float(base_risk)
    note_parts = []

    r = reduce_risk_after_loss(settings, r, last_closed_pnl)
    if last_closed_pnl is not None and last_closed_pnl < 0:
        note_parts.append("loss_reduce")

    try:
        balances = client.balances_map()
    except Exception:
        balances = {}

    usdt = float(balances.get("USDT", 0) or 0)
    asset = symbol.replace("USDT", "").upper()
    px = float(df.iloc[-1]["close"])
    val = 0.0
    if asset == "BTC":
        val = float(balances.get("BTC", 0) or 0) * px
    elif asset == "ETH":
        val = float(balances.get("ETH", 0) or 0) * px
    elif asset == "SOL":
        val = float(balances.get("SOL", 0) or 0) * px

    total = usdt + val
    for a in ("BTC", "ETH", "SOL"):
        if a == asset:
            continue
        # rough: ignore cross-asset for speed; total dominated by USDT in spot bots
        pass

    r = cap_risk_by_max_weight(settings, r, val, max(total, usdt))
    note_parts.append("weight_cap")

    if not getattr(settings, "rl_hybrid_enabled", False):
        return r, ",".join(note_parts) if note_parts else None

    path = getattr(settings, "rl_ppo_model_path", "") or ""
    if lstm_action != "BUY":
        return r, ",".join(note_parts) if note_parts else None

    ppo = _load_ppo(path)
    if ppo is None:
        if path:
            note_parts.append("ppo_missing")
        return r, ",".join(note_parts) if note_parts else None

    obs = build_observation(df, symbol, balances)
    action, _ = ppo.predict(obs, deterministic=True)
    ai = _symbol_to_asset_index(symbol)
    mult = ppo_agrees_with_buy(int(action), ai)
    r *= mult
    note_parts.append(f"ppo_x{mult:.2f}")
    return max(1e-8, r), ",".join(note_parts)
