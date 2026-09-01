from datetime import datetime, timedelta
from types import SimpleNamespace
import json

from src.api.routes_status import _attach_decisions_to_positions, _bucket_metrics
from src.api.routes_stats import _aggregate_by_symbol


def _decision(
    *,
    symbol: str,
    ts: datetime,
    action: str = "BUY",
    reason: str = "entry",
    stop_loss: float | None = None,
    take_profit: float | None = None,
    risk_reward: float | None = None,
    final_source: str = "rule_only",
    rule_signal: str = "BUY",
    ml_signal: str | None = None,
    ml_confidence: float | None = None,
    changed_final_action: bool = False,
):
    signals = {
        "final_source": final_source,
        "rule_signal": rule_signal,
        "ml_signal": ml_signal,
        "ml_confidence": ml_confidence,
        "combined_signal": action,
        "override_reason": "ML override" if final_source == "ml_override" else None,
        "ml_context": {
            "model_name": "BTCUSDT_1h",
            "symbol": symbol,
            "timeframe": "1h",
            "model_version": "lstm_v1",
            "prediction": ml_signal,
            "confidence": ml_confidence,
            "changed_final_action": changed_final_action,
            "exact_match_exists": True,
            "fallback_used": False,
            "artifact_exists": True,
            "runtime_eligible": True,
        },
    }
    return SimpleNamespace(
        symbol=symbol,
        ts=ts,
        action=action,
        reason=reason,
        signals_json=json.dumps(signals),
        stop_loss=stop_loss,
        take_profit=take_profit,
        risk_reward=risk_reward,
        adx=20.0,
        ema_fast=100.0,
        ema_slow=95.0,
        rsi=55.0,
        atr=2.0,
    )


def _position(
    *,
    symbol: str,
    entry_ts: datetime,
    exit_ts: datetime,
    pnl: float,
    pnl_pct: float,
    entry_price: float = 100.0,
    exit_price: float = 110.0,
):
    return SimpleNamespace(
        id=1,
        symbol=symbol,
        entry_ts=entry_ts,
        exit_ts=exit_ts,
        entry_price=entry_price,
        entry_qty=1.0,
        exit_price=exit_price,
        exit_qty=1.0,
        pnl=pnl,
        pnl_pct=pnl_pct,
    )


def test_attach_decisions_to_positions_includes_ml_effect_and_exit_reason():
    base = datetime(2026, 1, 1, 12, 0, 0)
    pos = _position(
        symbol="BTCUSDT",
        entry_ts=base + timedelta(minutes=10),
        exit_ts=base + timedelta(minutes=40),
        pnl=12.5,
        pnl_pct=2.5,
        exit_price=110.0,
    )
    entry = _decision(
        symbol="BTCUSDT",
        ts=base + timedelta(minutes=5),
        action="BUY",
        reason="Entry decision",
        stop_loss=95.0,
        take_profit=108.0,
        risk_reward=2.0,
        final_source="ml_override",
        rule_signal="HOLD",
        ml_signal="BUY",
        ml_confidence=0.91,
        changed_final_action=True,
    )
    exit_decision = _decision(
        symbol="BTCUSDT",
        ts=base + timedelta(minutes=35),
        action="SELL",
        reason="Exit decision from strategy",
    )

    rows = _attach_decisions_to_positions([pos], [entry, exit_decision])

    assert len(rows) == 1
    row = rows[0]
    assert row["source_bucket"] == "ml_override"
    assert row["entry_reason"] == "Entry decision"
    assert row["exit_reason"] == "Exit decision from strategy"
    assert row["rule_signal"] == "HOLD"
    assert row["ml_signal"] == "BUY"
    assert row["ml_effect"] == "improved"
    assert row["stop_loss"] == 95.0
    assert row["take_profit"] == 108.0
    assert row["indicators"]["risk_reward"] == 2.0


def test_bucket_metrics_returns_requested_summary_fields():
    rows = [
        {"pnl": 10.0, "pnl_pct": 2.0, "ml_changed_final_action": True},
        {"pnl": -5.0, "pnl_pct": -1.0, "ml_changed_final_action": False},
        {"pnl": 8.0, "pnl_pct": 1.5, "ml_changed_final_action": True},
    ]

    metrics = _bucket_metrics(rows)

    assert metrics["total_trades"] == 3
    assert metrics["wins"] == 2
    assert metrics["losses"] == 1
    assert metrics["win_rate_pct"] > 60
    assert metrics["false_signal_rate_pct"] > 30
    assert metrics["total_pnl_usdt"] == 13.0
    assert metrics["average_return_per_trade_usdt"] > 4
    assert metrics["average_return_per_trade_pct"] > 0
    assert metrics["ml_changed_action_count"] == 2


def test_aggregate_by_symbol_includes_non_rule_only_sources():
    row = SimpleNamespace(
        symbol="BTCUSDT",
        action="BUY",
        confidence=0.81,
        signals_json=json.dumps(
            {
                "final_source": "ml_override",
                "ml_confidence": 0.91,
            }
        ),
    )

    grouped = _aggregate_by_symbol([row], [])

    assert grouped["BTC"]["final_source_counts"]["ml_override"] == 1
    assert grouped["BTC"]["non_rule_only_sources"]["ml_override"] == 1
