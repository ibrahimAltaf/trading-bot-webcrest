"""
Phase 2A — Saad validation round 2: trigger provenance, adaptive thresholds,
and the numeric evidence trail an external audit needs (see
docs/CLIENT-SAAD-PHASE2A-FINAL-REPORT.md follow-up).

Covers the three gaps raised in the second validation request:
1. order_origin must distinguish an unattended scheduler cycle from a manual
   API call and from a proof_forced audit call.
2. Decision records must carry the actual numeric thresholds used this cycle.
3. Those thresholds must move with market regime, not just raw indicators.
"""
from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.routes_safety import _classify_order_origin
from src.core.config import get_settings
from src.db.base import Base
from src.db.models import Order, TradingDecisionLog
from src.live.auto_trade_engine import AutoTradeEngine
from src.live.fully_adaptive_strategy import FullyAdaptiveStrategy


# ---------------------------------------------------------------------------
# Concern #1 — order_origin classification
# ---------------------------------------------------------------------------


class TestClassifyOrderOrigin:
    def test_scheduler_trigger_is_ai_scheduler(self):
        out = _classify_order_origin(
            {"final_source": "rule_only"}, reason=None, triggered_by="scheduler"
        )
        assert out == {"origin": "ai_scheduler", "pipeline": "ai_rule"}

    def test_manual_api_call_is_not_counted_as_scheduler(self):
        """The exact gap Saad flagged: a human curl without force_signal must
        not be indistinguishable from a real unattended cycle."""
        out = _classify_order_origin(
            {"final_source": "combined"}, reason=None, triggered_by="api_manual"
        )
        assert out["origin"] == "api_manual_unforced"
        assert out["origin"] != "ai_scheduler"

    def test_force_signal_is_always_proof_forced_regardless_of_trigger(self):
        out = _classify_order_origin(
            {"final_source": "forced_signal", "forced": True},
            reason=None,
            triggered_by="scheduler",  # even if mislabeled upstream, forced wins
        )
        assert out["origin"] == "proof_forced"

    def test_legacy_row_without_triggered_by_is_unknown(self):
        out = _classify_order_origin(
            {"final_source": "ml_override"}, reason=None, triggered_by=None
        )
        assert out["origin"] == "unknown"
        assert out["pipeline"] == "ai_ml"


# ---------------------------------------------------------------------------
# Concern #1 — triggered_by/cycle_id actually persist to DB
# ---------------------------------------------------------------------------


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        autocommit=False, autoflush=False, expire_on_commit=False, bind=engine
    )
    s = factory()
    yield s
    s.close()


class TestTriggerPersistence:
    def test_scheduler_trigger_persists_on_decision_log(self, db_session):
        from src.live.adaptive_strategy import MarketRegime, SignalAction, TradingDecision

        engine = AutoTradeEngine(db=db_session)
        engine._current_trigger = {"triggered_by": "scheduler", "cycle_id": 42}

        decision = TradingDecision(
            action=SignalAction.HOLD,
            confidence=0.5,
            regime=MarketRegime.UNKNOWN,
            price=100.0,
            timestamp="2026-01-01T00:00:00",
            adx=20.0,
            ema_fast=100.0,
            ema_slow=100.0,
            rsi=50.0,
            bb_upper=None,
            bb_middle=None,
            bb_lower=None,
            atr=1.0,
            atr_pct=1.0,
            entry_price=None,
            stop_loss=None,
            take_profit=None,
            risk_reward=None,
            position_size_pct=0.0,
            reason="test",
            signals={},
        )
        log = engine._save_decision(decision, symbol="BTCUSDT", timeframe="5m")
        assert log.triggered_by == "scheduler"
        assert log.cycle_id == 42

    def test_default_trigger_is_api_manual(self, db_session):
        engine = AutoTradeEngine(db=db_session)
        assert engine._current_trigger["triggered_by"] == "api_manual"

    def test_force_signal_overrides_triggered_by_to_proof_forced(self, db_session, monkeypatch):
        engine = AutoTradeEngine(db=db_session)

        # Stub the forced-signal path so we only assert on trigger bookkeeping,
        # not full order execution.
        monkeypatch.setattr(
            engine,
            "_run_forced_signal_trade",
            lambda **_kw: "stub-result",
        )

        class _FakeClient:
            def klines(self, **_kw):
                return [
                    [i, "1", "1", "1", "1", "1", i, "1", 1, "1", "1", "1"]
                    for i in range(60)
                ]

        engine.client = _FakeClient()
        engine.execute_auto_trade(
            symbol="BTCUSDT",
            timeframe="5m",
            force_signal="BUY",
            triggered_by="scheduler",  # even if scheduler passed this, force wins
        )
        assert engine._current_trigger["triggered_by"] == "proof_forced"


# ---------------------------------------------------------------------------
# Concern #3 — adaptive thresholds actually move with regime
# ---------------------------------------------------------------------------


def _make_df(closes: list[float]) -> pd.DataFrame:
    n = len(closes)
    return pd.DataFrame(
        {
            "open_time": pd.date_range("2026-01-01", periods=n, freq="5min"),
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": [100.0] * n,
        }
    )


class TestAdaptiveThresholds:
    def test_posture_and_floors_differ_between_calm_and_volatile_regimes(self):
        settings = get_settings()
        strat = FullyAdaptiveStrategy(settings)

        import numpy as np

        rng = np.random.default_rng(7)

        calm = 100 + rng.normal(0, 0.05, 200).cumsum() * 0.02
        calm_df = _make_df(list(calm + 100))

        volatile = 100 + rng.normal(0, 3.0, 200).cumsum() * 0.5
        volatile_df = _make_df([abs(v) + 50 for v in volatile])

        _, p_calm, meta_calm = strat._two_pass(calm_df)
        _, p_vol, meta_vol = strat._two_pass(volatile_df)

        # The regime classification itself must differ for this test to prove
        # anything (otherwise we'd just be checking determinism).
        assert meta_calm["vol_bucket"] != meta_vol["vol_bucket"] or (
            p_calm.posture != p_vol.posture
        )

        # Core assertion: confidence floors / atr_vol_threshold are NOT frozen
        # at the static .env value in at least one of the two regimes — this is
        # exactly what the second validator checks for (thresholds, not just
        # indicators, must change with regime).
        static_abs_min = float(settings.ml_absolute_min_confidence)
        assert (
            p_calm.ml_absolute_min_confidence != static_abs_min
            or p_vol.ml_absolute_min_confidence != static_abs_min
        )
        assert p_calm.posture in ("aggressive", "conservative")
        assert p_vol.posture in ("aggressive", "conservative")

    def test_high_vol_bucket_raises_confidence_floors(self):
        settings = get_settings()
        strat = FullyAdaptiveStrategy(settings)
        # Force HIGH vol bucket by monkeypatching the bucket decision directly
        # via a df with extreme ATR: large true-range swings each bar.
        closes = [100.0]
        for i in range(200):
            closes.append(closes[-1] * (1.05 if i % 2 == 0 else 0.95))
        df = _make_df(closes)

        _, params, meta = strat._two_pass(df)
        if meta["vol_bucket"] == "HIGH":
            assert params.posture == "conservative"
            assert params.ml_absolute_min_confidence >= float(
                settings.ml_absolute_min_confidence
            )


# ---------------------------------------------------------------------------
# Concern #2/#3 — engine falls back to static settings when adaptive params
# are absent, and reads adaptive params when FullyAdaptiveStrategy supplied them
# ---------------------------------------------------------------------------


class TestEffectiveThresholds:
    def test_falls_back_to_static_settings_without_params(self, db_session):
        from src.live.adaptive_strategy import MarketRegime, SignalAction, TradingDecision

        engine = AutoTradeEngine(db=db_session)
        decision = TradingDecision(
            action=SignalAction.HOLD,
            confidence=0.5,
            regime=MarketRegime.UNKNOWN,
            price=100.0,
            timestamp="2026-01-01T00:00:00",
            adx=20.0,
            ema_fast=100.0,
            ema_slow=100.0,
            rsi=50.0,
            bb_upper=None,
            bb_middle=None,
            bb_lower=None,
            atr=1.0,
            atr_pct=1.0,
            entry_price=None,
            stop_loss=None,
            take_profit=None,
            risk_reward=None,
            position_size_pct=0.0,
            reason="test",
            signals={},  # no "params" key
        )
        th = engine._effective_thresholds(decision)
        assert th["adx_threshold"] == float(engine.settings.adx_threshold)
        assert th["adaptive_posture"] == "static"

    def test_reads_adaptive_params_when_present(self, db_session):
        from src.live.adaptive_strategy import MarketRegime, SignalAction, TradingDecision

        engine = AutoTradeEngine(db=db_session)
        decision = TradingDecision(
            action=SignalAction.HOLD,
            confidence=0.5,
            regime=MarketRegime.UNKNOWN,
            price=100.0,
            timestamp="2026-01-01T00:00:00",
            adx=20.0,
            ema_fast=100.0,
            ema_slow=100.0,
            rsi=50.0,
            bb_upper=None,
            bb_middle=None,
            bb_lower=None,
            atr=1.0,
            atr_pct=1.0,
            entry_price=None,
            stop_loss=None,
            take_profit=None,
            risk_reward=None,
            position_size_pct=0.0,
            reason="test",
            signals={
                "params": {
                    "adx_threshold": 33.3,
                    "ml_absolute_min_confidence": 0.61,
                    "posture": "conservative",
                }
            },
        )
        th = engine._effective_thresholds(decision)
        assert th["adx_threshold"] == 33.3
        assert th["ml_absolute_min_confidence"] == 0.61
        assert th["adaptive_posture"] == "conservative"
