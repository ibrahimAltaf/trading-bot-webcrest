"""Regression: fusion + envelope sanity; strategy must not emit HOLD-only forever on synthetic extremes."""
from __future__ import annotations

import pandas as pd

from src.features.indicators import add_all_indicators
from src.live.cycle_decision import fuse_confidence, evaluate_entry_gates
from src.live.adaptive_strategy import AdaptiveStrategy


def _with_indicators(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    ic = {
        "ema_fast": cfg["ema_fast"],
        "ema_slow": cfg["ema_slow"],
        "rsi_period": cfg["rsi_len"],
        "adx_period": 14,
        "bb_period": cfg["bb_len"],
        "bb_std": cfg["bb_std"],
        "atr_period": 14,
    }
    return add_all_indicators(df, ic)


def test_fuse_agree_vs_disagree():
    a = fuse_confidence("BUY", "BUY", 0.6, 0.8)
    assert 0.0 < a <= 1.0
    assert a != 0.5
    d = fuse_confidence("BUY", "SELL", 0.6, 0.8)
    assert 0.0 < d < 1.0
    assert d != a


def test_gates_produce_failed_list_when_trend_bad():
    g = evaluate_entry_gates(
        adx=5.0,
        rsi=50.0,
        atr_pct=1.0,
        ema_fast=100.0,
        ema_slow=100.0,
        adx_threshold=25.0,
        atr_vol_threshold=2.0,
        rsi_buy_min=45.0,
        rsi_buy_max=70.0,
        ml_ok=True,
        risk_ok=True,
    )
    assert "failed_gates" in g
    assert isinstance(g["failed_gates"], list)


def test_bullish_synthetic_frame_prefers_buy_or_hold_not_only_hold():
    """Strong uptrend: RSI mid, ADX high — expect BUY or at least not forced HOLD-only."""
    rows = []
    price = 100.0
    for i in range(120):
        price += 0.5
        rows.append(
            {
                "open": price - 0.1,
                "high": price + 0.2,
                "low": price - 0.2,
                "close": price,
                "volume": 1000.0,
            }
        )
    df = pd.DataFrame(rows)
    df.loc[:, "open_time"] = pd.date_range("2024-01-01", periods=len(df), freq="h")
    cfg = {
        "adx_threshold": 25.0,
        "atr_vol_threshold": 2.0,
        "ema_fast": 20,
        "ema_slow": 50,
        "rsi_len": 14,
        "rsi_buy_min": 45.0,
        "rsi_buy_max": 70.0,
        "rsi_take_profit": 75.0,
        "bb_len": 20,
        "bb_std": 2.0,
        "rsi_range_buy": 35.0,
        "rsi_range_sell": 65.0,
        "max_risk_per_trade": 0.01,
        "stop_loss_atr_mult": 2.0,
        "take_profit_rr": 2.0,
        "relaxed_entry_for_testing": True,
    }
    df = _with_indicators(df, cfg)
    strat = AdaptiveStrategy(cfg)
    d = strat.generate_decision(df)
    assert d.action.value in ("BUY", "SELL", "HOLD")
    # Regression: if we only ever HOLD on this path, something is broken
    assert not (d.action.value == "HOLD" and d.confidence == 0.5)


def test_sideways_ranging_may_hold():
    """Flat noise: HOLD allowed."""
    import numpy as np

    rng = np.random.default_rng(42)
    rows = []
    price = 100.0
    for i in range(120):
        price += float(rng.normal(0, 0.05))
        rows.append(
            {
                "open": price,
                "high": price + 0.1,
                "low": price - 0.1,
                "close": price,
                "volume": 100.0,
            }
        )
    df = pd.DataFrame(rows)
    df.loc[:, "open_time"] = pd.date_range("2024-01-01", periods=len(df), freq="h")
    cfg = {
        "adx_threshold": 25.0,
        "atr_vol_threshold": 2.0,
        "ema_fast": 20,
        "ema_slow": 50,
        "rsi_len": 14,
        "rsi_buy_min": 45.0,
        "rsi_buy_max": 70.0,
        "rsi_take_profit": 75.0,
        "bb_len": 20,
        "bb_std": 2.0,
        "rsi_range_buy": 35.0,
        "rsi_range_sell": 65.0,
        "max_risk_per_trade": 0.01,
        "stop_loss_atr_mult": 2.0,
        "take_profit_rr": 2.0,
        "relaxed_entry_for_testing": False,
    }
    df = _with_indicators(df, cfg)
    strat = AdaptiveStrategy(cfg)
    d = strat.generate_decision(df)
    assert d.action.value in ("BUY", "SELL", "HOLD")
