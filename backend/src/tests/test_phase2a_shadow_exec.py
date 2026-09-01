"""
Phase 2A — Shadow execution path tests.

Shadow mode = real Binance balances + symbol filters + market prices, but the
order itself is simulated. Every order/position/trade row persists with
mode='shadow' so live and shadow flows can be compared 1:1 by audits.
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.base import Base
from src.db.models import Order, Position, Trade, TradingDecisionLog  # noqa: F401
import src.db.models  # noqa: F401
from src.execution.mode import ExecutionMode
from src.live.auto_trade_engine import AutoTradeEngine
from src.safety import kill_switch as ks


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RISK_MAX_TRADE_NOTIONAL_USDT", "100000")
    monkeypatch.setenv("RISK_MAX_EXPOSURE_PCT", "1.0")
    try:
        ks.release("setup", by="pytest")
    except Exception:
        pass
    # Reset in-memory trackers.
    for mod_path, attr in (
        ("src.execution.execution_engine", "ORDERS"),
        ("src.execution.execution_engine", "SHADOW_ORDERS"),
        ("src.execution.positions", "POSITIONS"),
    ):
        try:
            mod = __import__(mod_path, fromlist=[attr])
            getattr(mod, attr).clear()
        except Exception:
            pass
    yield
    try:
        ks.release("teardown", by="pytest")
    except Exception:
        pass


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        autocommit=False, autoflush=False, expire_on_commit=False, bind=engine
    )
    s = factory()
    yield s
    s.close()


class _FakeBinanceClient:
    """Stand-in for BinanceSpotClient that returns deterministic balance + filters."""

    def __init__(self, usdt_free: float = 500.0, min_notional: float = 5.0):
        self._usdt = float(usdt_free)
        self._min = float(min_notional)
        self.placed_buy_calls = 0
        self.placed_sell_calls = 0

    def account(self):
        return {"balances": [{"asset": "USDT", "free": str(self._usdt)}]}

    def get_symbol_filters(self, symbol: str):
        return {"minNotional": self._min, "stepSize": 0.00001, "tickSize": 0.01}

    def create_order_market_buy(self, **_kw):
        # MUST NOT be called in shadow mode — assertion guard.
        self.placed_buy_calls += 1
        raise AssertionError("shadow mode placed a real buy order")

    def create_order_market_sell(self, **_kw):
        self.placed_sell_calls += 1
        raise AssertionError("shadow mode placed a real sell order")

    def klines(self, symbol: str, interval: str, limit: int):
        base_ms = 1_700_000_000_000
        rows = []
        for i in range(min(int(limit), 120)):
            t = base_ms + i * 3_600_000
            price = 100.0 + i * 0.1
            rows.append(
                [
                    t,
                    str(price),
                    str(price + 1),
                    str(price - 1),
                    str(price),
                    "1.0",
                    t + 3_599_999,
                    "0",
                    1,
                    "0",
                    "0",
                    "0",
                ]
            )
        return rows

    def get_price(self, symbol: str):
        return 100.0


@pytest.fixture
def shadow_engine(db_session, monkeypatch):
    """Engine in shadow mode with fake Binance client."""
    fake = _FakeBinanceClient(usdt_free=500.0, min_notional=5.0)
    monkeypatch.setattr(
        "src.live.auto_trade_engine.BinanceSpotClient",
        lambda *a, **k: fake,
    )
    monkeypatch.setenv("EXECUTION_MODE", "shadow")
    eng = AutoTradeEngine(db=db_session)
    eng.execution_mode = "shadow"
    eng.client = fake  # be explicit
    return eng


class TestShadowBuy:
    def test_shadow_buy_persists_mode_and_uses_real_balance(
        self, shadow_engine, db_session
    ):
        result = shadow_engine._execute_buy(
            symbol="BTCUSDT", price=100.0, risk_pct=0.02, stop_loss=None
        )
        assert result.executed is True, result.reason
        assert result.order_id and result.order_id.startswith("shadow-")
        # Balance is taken from fake exchange (500 USDT), not paper default (10k).
        assert result.balance_before == 500.0

        order = db_session.query(Order).filter(Order.mode == "shadow").one()
        assert order.side == "BUY"
        position = db_session.query(Position).filter(Position.mode == "shadow").one()
        assert position.is_open is True
        trade = db_session.query(Trade).filter(Trade.mode == "shadow").one()
        assert trade.side == "BUY"
        # CRITICAL: no real exchange call happened.
        assert shadow_engine.client.placed_buy_calls == 0

    def test_shadow_buy_blocked_by_kill_switch(self, shadow_engine, db_session):
        ks.engage("test", by="pytest")
        try:
            result = shadow_engine._execute_buy(
                symbol="BTCUSDT", price=100.0, risk_pct=0.02
            )
        finally:
            ks.release("cleanup", by="pytest")
        assert result.executed is False
        assert result.blocked is True
        assert db_session.query(Order).count() == 0
        assert shadow_engine.client.placed_buy_calls == 0

    def test_shadow_buy_rejects_when_balance_insufficient(
        self, shadow_engine, db_session
    ):
        # 0.5 USDT balance → cannot satisfy 5 USDT min_notional.
        shadow_engine.client._usdt = 0.5
        result = shadow_engine._execute_buy(
            symbol="BTCUSDT", price=100.0, risk_pct=0.02
        )
        assert result.executed is False
        # Either "Insufficient" guard or "spend<=0" path — both are valid rejections.
        assert "insufficient" in (result.reason or "").lower() or "spend" in (
            result.reason or ""
        )

    def test_shadow_buy_uses_fallback_when_exchange_usdt_zero(
        self, shadow_engine, db_session, monkeypatch
    ):
        monkeypatch.setenv("SHADOW_USE_FALLBACK_BALANCE", "true")
        monkeypatch.setenv("SHADOW_USDT_BALANCE", "10000")
        shadow_engine.client._usdt = 0.0
        result = shadow_engine._execute_buy_shadow(
            symbol="BTCUSDT", price=100.0, risk_pct=0.02, stop_loss=None
        )
        assert result.executed is True, result.reason
        assert result.order_id.startswith("shadow-")
        assert "fallback" in (result.reason or "").lower()
        assert shadow_engine.client.placed_buy_calls == 0


class TestShadowSell:
    def test_shadow_sell_closes_position_without_exchange_call(
        self, shadow_engine, db_session
    ):
        pos = Position(
            mode="shadow",
            symbol="BTCUSDT",
            is_open=True,
            entry_price=100.0,
            entry_qty=0.25,
            entry_ts=datetime.utcnow(),
        )
        db_session.add(pos)
        db_session.commit()
        db_session.refresh(pos)

        result = shadow_engine._execute_sell(
            symbol="BTCUSDT", position=pos, price=110.0
        )
        assert result.executed is True
        assert result.order_id.startswith("shadow-")
        # Position closed with correct mode.
        db_session.refresh(pos)
        assert pos.is_open is False
        assert pos.mode == "shadow"
        assert shadow_engine.client.placed_sell_calls == 0


class TestForcedSignalAudit:
    def test_force_signal_buy_bypasses_insufficient_data_gate(
        self, shadow_engine, monkeypatch
    ):
        """Auditors use force_signal=BUY when indicator dropna leaves <50 rows."""
        import pandas as pd

        tiny = pd.DataFrame(
            {
                "open_time": pd.to_datetime(
                    ["2024-01-01", "2024-01-02", "2024-01-03"], utc=True
                ),
                "open": [100.0, 100.0, 100.0],
                "high": [101.0, 101.0, 101.0],
                "low": [99.0, 99.0, 99.0],
                "close": [100.0, 100.5, 101.0],
                "volume": [1.0, 1.0, 1.0],
            }
        )
        monkeypatch.setattr(
            "src.live.auto_trade_engine.add_all_indicators",
            lambda df, cfg: tiny.copy(),
        )
        monkeypatch.setattr(
            "src.live.auto_trade_engine.append_ml_production_features",
            lambda df: tiny.copy(),
        )

        result = shadow_engine.execute_auto_trade(
            symbol="BTCUSDT",
            timeframe="1h",
            risk_pct=0.01,
            force_signal="BUY",
        )
        reason = result.reason or ""
        assert "Insufficient data after indicator calculation" not in reason
        assert result.signal == "BUY"
        assert result.executed is True, reason
        assert result.order_id and str(result.order_id).startswith("shadow-")


class TestShadowOrderIsolation:
    def test_shadow_orders_persist_with_shadow_mode_only(
        self, shadow_engine, db_session
    ):
        shadow_engine._execute_buy(
            symbol="BTCUSDT", price=100.0, risk_pct=0.02
        )
        # No paper-mode rows should leak into the shadow audit.
        assert db_session.query(Order).filter(Order.mode == "paper").count() == 0
        assert (
            db_session.query(Position).filter(Position.mode == "paper").count() == 0
        )
        assert db_session.query(Order).filter(Order.mode == "shadow").count() == 1


class TestAutonomousShadowExecution:
    def test_autonomous_shadow_buy_without_force_signal(
        self, shadow_engine, db_session, monkeypatch
    ):
        """Full chain: rule BUY + ML HOLD → shadow order (not proof_forced)."""
        from datetime import datetime as dt

        from src.live.adaptive_strategy import MarketRegime, SignalAction, TradingDecision
        from src.live.auto_trade_engine import SignalType, TradeSignal

        monkeypatch.setenv("ML_ENABLED", "true")

        fake_decision = TradingDecision(
            action=SignalAction.BUY,
            confidence=0.65,
            regime=MarketRegime.TRENDING,
            price=100.0,
            timestamp=dt.utcnow().isoformat(),
            adx=30.0,
            ema_fast=101.0,
            ema_slow=99.0,
            rsi=55.0,
            bb_upper=105.0,
            bb_middle=100.0,
            bb_lower=95.0,
            atr=2.0,
            atr_pct=2.0,
            entry_price=100.0,
            stop_loss=96.0,
            take_profit=108.0,
            risk_reward=2.0,
            position_size_pct=0.02,
            reason="TRENDING BUY test",
            signals={},
        )

        monkeypatch.setattr(
            shadow_engine.adaptive_strategy,
            "generate_decision",
            lambda df: fake_decision,
        )
        monkeypatch.setattr(
            shadow_engine,
            "_resolve_ml_context",
            lambda symbol, timeframe: {
                "runtime_eligible": True,
                "model_dir": "/tmp/fake-model",
                "model_name": "test",
                "symbol": symbol,
                "timeframe": timeframe,
                "exact_match_exists": True,
                "fallback_used": False,
                "artifact_exists": True,
            },
        )

        class _FakeInfer:
            def predict_window(self, df):
                return {
                    "signal": "HOLD",
                    "confidence": 0.48,
                    "up": 0.2,
                    "hold": 0.48,
                    "down": 0.32,
                }

        monkeypatch.setattr(
            "src.ml.inference.get_infer",
            lambda _path: _FakeInfer(),
        )
        monkeypatch.setattr(
            shadow_engine,
            "_generate_ml_signal",
            lambda df: TradeSignal(
                signal=SignalType.HOLD,
                confidence=0.48,
                price=100.0,
                timestamp=dt.utcnow(),
                source="ml",
                metadata={"up": 0.2, "hold": 0.48, "down": 0.32},
            ),
        )

        result = shadow_engine.execute_auto_trade(
            symbol="SOLUSDT",
            timeframe="1h",
            risk_pct=0.01,
        )

        assert result.executed is True, result.reason
        assert result.order_id and str(result.order_id).startswith("shadow-")
        assert result.signal == "BUY"

        order = db_session.query(Order).filter(Order.mode == "shadow").one()
        assert order.side == "BUY"
        assert shadow_engine.client.placed_buy_calls == 0

        dec = (
            db_session.query(TradingDecisionLog)
            .order_by(TradingDecisionLog.id.desc())
            .first()
        )
        assert dec is not None
        assert dec.executed is True
        import json

        sig = json.loads(dec.signals_json or "{}")
        assert sig.get("final_source") == "rule_directional_ml_neutral"
        assert sig.get("forced") is not True
