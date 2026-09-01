"""
Phase 2A — RiskEngine ↔ AutoTradeEngine wiring tests.

Confirms every execution path (paper / live BUY / SELL) goes through the
centralized RiskEngine and that rejections are persisted + audited without
touching the exchange.
"""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.base import Base
from src.db.models import Order, Position  # noqa: F401 (model registration)
import src.db.models  # noqa: F401
from src.execution.mode import ExecutionMode
from src.live.auto_trade_engine import AutoTradeEngine
from src.safety import kill_switch as ks
from src.safety.risk_engine import RiskLimits


@pytest.fixture(autouse=True)
def _isolated_safety_data(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    # Make sure kill switch starts released for every test.
    try:
        ks.release("test-setup", by="pytest")
    except Exception:
        pass
    # Reset module-level paper trackers so cross-test bleed doesn't break
    # other suites' drift / reconciliation expectations.
    try:
        from src.execution.execution_engine import ORDERS

        ORDERS.clear()
    except Exception:
        pass
    try:
        from src.execution.positions import POSITIONS

        POSITIONS.clear()
    except Exception:
        pass
    yield
    try:
        ks.release("test-teardown", by="pytest")
    except Exception:
        pass
    try:
        from src.execution.execution_engine import ORDERS as _O

        _O.clear()
    except Exception:
        pass
    try:
        from src.execution.positions import POSITIONS as _P

        _P.clear()
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


@pytest.fixture
def paper_engine(db_session, monkeypatch):
    """Construct an AutoTradeEngine in paper mode with a stub Binance client."""
    monkeypatch.setattr(
        "src.live.auto_trade_engine.BinanceSpotClient",
        lambda *a, **k: object(),
    )
    monkeypatch.setenv("PHASE1_PAPER_EXECUTION", "true")
    monkeypatch.setenv("PAPER_USDT_BALANCE", "10000")

    eng = AutoTradeEngine(db=db_session)
    eng.execution_mode = "paper"
    return eng


# ---------------------------- _build_risk_state -----------------------------


class TestBuildRiskState:
    def test_empty_db_returns_zero_state(self, paper_engine):
        state = paper_engine._build_risk_state()
        assert state.open_positions_count == 0
        assert state.daily_orders_count == 0
        assert state.daily_realized_pnl_usdt == 0.0
        assert state.account_balance_usdt == 10000.0

    def test_open_positions_counted_per_mode(self, paper_engine, db_session):
        db_session.add(
            Position(mode="paper", symbol="BTCUSDT", is_open=True,
                     entry_price=1.0, entry_qty=1.0, entry_ts=datetime.utcnow())
        )
        db_session.add(
            Position(mode="paper", symbol="ETHUSDT", is_open=True,
                     entry_price=2.0, entry_qty=2.0, entry_ts=datetime.utcnow())
        )
        # Different mode → must not be counted.
        db_session.add(
            Position(mode="live", symbol="SOLUSDT", is_open=True,
                     entry_price=3.0, entry_qty=3.0, entry_ts=datetime.utcnow())
        )
        db_session.commit()
        state = paper_engine._build_risk_state()
        assert state.open_positions_count == 2

    def test_daily_orders_counted_per_mode(self, paper_engine, db_session):
        for _ in range(3):
            db_session.add(
                Order(
                    mode="paper", symbol="BTCUSDT", side="BUY",
                    order_type="MARKET", quantity=0.001, status="FILLED",
                    created_at=datetime.utcnow(),
                )
            )
        db_session.add(
            Order(
                mode="live", symbol="BTCUSDT", side="BUY",
                order_type="MARKET", quantity=0.001, status="FILLED",
                created_at=datetime.utcnow(),
            )
        )
        db_session.commit()
        state = paper_engine._build_risk_state()
        assert state.daily_orders_count == 3


# ---------------------------- _run_pretrade_risk_check -----------------------


class TestPretradeRiskCheck:
    def test_approves_clean_buy(self, paper_engine):
        decision, req = paper_engine._run_pretrade_risk_check(
            symbol="BTCUSDT", side="BUY", price=100.0, quantity=0.5,
        )
        assert decision.approved is True
        assert req.symbol == "BTCUSDT"
        assert req.mode == ExecutionMode.PAPER

    def test_rejects_when_kill_switch_engaged(self, paper_engine):
        ks.engage("audit", by="pytest")
        try:
            decision, _ = paper_engine._run_pretrade_risk_check(
                symbol="BTCUSDT", side="BUY", price=100.0, quantity=0.1,
            )
        finally:
            ks.release("cleanup", by="pytest")
        assert decision.approved is False
        assert "kill_switch_engaged" in decision.reason_codes

    def test_rejects_when_notional_exceeds_cap(self, paper_engine, monkeypatch):
        # default cap is 100 USDT — 100 * 5 = 500 > 100
        monkeypatch.setenv("RISK_MAX_TRADE_NOTIONAL_USDT", "100")
        decision, _ = paper_engine._run_pretrade_risk_check(
            symbol="BTCUSDT", side="BUY", price=100.0, quantity=5.0,
        )
        assert decision.approved is False
        assert "above_max_trade_notional" in decision.reason_codes

    def test_sell_skips_notional_cap(self, paper_engine, monkeypatch):
        """SELL must never be blocked from closing an existing position."""
        monkeypatch.setenv("RISK_MAX_TRADE_NOTIONAL_USDT", "10")
        decision, _ = paper_engine._run_pretrade_risk_check(
            symbol="BTCUSDT", side="SELL", price=1000.0, quantity=0.5,  # 500 USDT
        )
        # Only kill-switch / sanity checks apply on SELL — all OK here.
        assert decision.approved is True, decision.reason_codes


# ------------------------- paper BUY rejection path -------------------------


class TestPaperBuyRiskGate:
    def test_paper_buy_blocked_by_kill_switch(self, paper_engine):
        ks.engage("audit", by="pytest")
        try:
            result = paper_engine._execute_buy_paper(
                symbol="BTCUSDT", price=100.0, risk_pct=None
            )
        finally:
            ks.release("cleanup", by="pytest")
        assert result.executed is False
        assert result.signal == "BUY"
        assert result.blocked is True
        assert "risk_rejected" in (result.reason or "")
        assert "kill_switch_engaged" in (result.reason or "")

    def test_paper_buy_capped_to_max_notional(self, paper_engine, monkeypatch):
        """Sizing layer caps spend to RISK_MAX_TRADE_NOTIONAL (Phase 2C live path)."""
        monkeypatch.setenv("RISK_MAX_TRADE_NOTIONAL_USDT", "5")
        result = paper_engine._execute_buy_paper(
            symbol="BTCUSDT", price=100.0, risk_pct=None
        )
        assert result.executed is True
        assert result.quantity is not None
        assert result.quantity * 100.0 <= 5.01

    def test_paper_buy_blocked_below_min_notional(self, paper_engine, monkeypatch):
        monkeypatch.setenv("RISK_MAX_TRADE_NOTIONAL_USDT", "1")
        monkeypatch.setenv("RISK_MIN_ORDER_NOTIONAL_USDT", "5")
        result = paper_engine._execute_buy_paper(
            symbol="BTCUSDT", price=100.0, risk_pct=None
        )
        assert result.executed is False
        assert result.blocked is True
        assert "below_min_notional" in (result.reason or "")

    def test_paper_buy_executes_when_risk_ok(self, paper_engine, monkeypatch):
        # Raise the cap so the engine's default sizing (max_position_pct of 10k)
        # comfortably fits inside the audit-time risk envelope.
        monkeypatch.setenv("RISK_MAX_TRADE_NOTIONAL_USDT", "10000")
        monkeypatch.setenv("RISK_MAX_EXPOSURE_PCT", "1.0")
        result = paper_engine._execute_buy_paper(
            symbol="BTCUSDT", price=100.0, risk_pct=0.001  # tiny size, 10 USDT
        )
        assert result.executed is True, result.reason
        assert result.signal == "BUY"
        assert result.order_id  # paper orderId generated
        assert result.position_id is not None


# ------------------------- paper SELL rejection path ------------------------


class TestPaperSellRiskGate:
    def test_paper_sell_blocked_by_kill_switch(self, paper_engine, db_session):
        from src.db.models import Position as PModel

        pos = PModel(
            mode="paper",
            symbol="BTCUSDT",
            is_open=True,
            entry_price=100.0,
            entry_qty=0.5,
            entry_ts=datetime.utcnow(),
        )
        db_session.add(pos)
        db_session.commit()
        db_session.refresh(pos)

        ks.engage("audit", by="pytest")
        try:
            result = paper_engine._execute_sell_paper(
                symbol="BTCUSDT", position=pos, price=110.0
            )
        finally:
            ks.release("cleanup", by="pytest")
        assert result.executed is False
        assert result.signal == "SELL"
        assert result.blocked is True
        assert "kill_switch_engaged" in (result.reason or "")

    def test_paper_sell_succeeds_when_safe(self, paper_engine, db_session):
        from src.db.models import Position as PModel

        pos = PModel(
            mode="paper",
            symbol="BTCUSDT",
            is_open=True,
            entry_price=100.0,
            entry_qty=0.25,
            entry_ts=datetime.utcnow(),
        )
        db_session.add(pos)
        db_session.commit()
        db_session.refresh(pos)

        result = paper_engine._execute_sell_paper(
            symbol="BTCUSDT", position=pos, price=110.0
        )
        assert result.executed is True
        assert result.signal == "SELL"


# ------------------------ rejection audit / persistence ----------------------


class TestRejectionPersistence:
    def test_rejection_emits_event_log(self, paper_engine, db_session, monkeypatch):
        from src.db.models import EventLog

        monkeypatch.setenv("RISK_MAX_TRADE_NOTIONAL_USDT", "1")
        monkeypatch.setenv("RISK_MIN_ORDER_NOTIONAL_USDT", "5")
        paper_engine._execute_buy_paper(
            symbol="BTCUSDT", price=100.0, risk_pct=None
        )
        warns = (
            db_session.query(EventLog)
            .filter(EventLog.level == "WARN", EventLog.category == "risk")
            .all()
        )
        assert len(warns) >= 1
        assert "REJECTED" in warns[-1].message
        assert "below_min_notional" in warns[-1].message
