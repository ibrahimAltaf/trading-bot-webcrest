"""
Phase 2A — Track 3 tests:
  * client_order_id is persisted on every order (paper / shadow paths).
  * Restart recovery re-hydrates in-memory paper/shadow trackers from DB.
  * Idempotency: replaying a client_order_id within the dedupe window is
    rejected by the RiskEngine duplicate check.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.base import Base
from src.db.models import Order, Position  # noqa: F401
import src.db.models  # noqa: F401
from src.execution.execution_engine import ORDERS, SHADOW_ORDERS
from src.execution.positions import POSITIONS
from src.execution.recovery import (
    bootstrap_runtime_state,
    ensure_client_order_id_column,
)
from src.live.auto_trade_engine import AutoTradeEngine
from src.safety import kill_switch as ks


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RISK_MAX_TRADE_NOTIONAL_USDT", "100000")
    monkeypatch.setenv("RISK_MAX_EXPOSURE_PCT", "1.0")
    monkeypatch.setenv("RISK_DUPLICATE_WINDOW_SECONDS", "120")
    try:
        ks.release("setup", by="pytest")
    except Exception:
        pass
    ORDERS.clear()
    SHADOW_ORDERS.clear()
    POSITIONS.clear()
    yield
    try:
        ks.release("teardown", by="pytest")
    except Exception:
        pass
    ORDERS.clear()
    SHADOW_ORDERS.clear()
    POSITIONS.clear()


@pytest.fixture
def db_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def db_session(db_engine):
    factory = sessionmaker(
        autocommit=False, autoflush=False, expire_on_commit=False, bind=db_engine
    )
    s = factory()
    yield s
    s.close()


@pytest.fixture
def paper_engine(db_session, monkeypatch):
    monkeypatch.setattr(
        "src.live.auto_trade_engine.BinanceSpotClient",
        lambda *a, **k: object(),
    )
    monkeypatch.setenv("PHASE1_PAPER_EXECUTION", "true")
    monkeypatch.setenv("PAPER_USDT_BALANCE", "10000")
    eng = AutoTradeEngine(db=db_session)
    eng.execution_mode = "paper"
    return eng


# --------------------------- column shim -----------------------------------


class TestColumnShim:
    def test_ensure_client_order_id_column_idempotent(self, db_engine):
        # Schema is created via Base.metadata.create_all -> column already exists.
        assert ensure_client_order_id_column(db_engine) is False


# --------------------------- client_order_id persistence -------------------


class TestClientOrderIdPersistence:
    def test_paper_buy_persists_client_order_id(self, paper_engine, db_session):
        result = paper_engine._execute_buy_paper(
            symbol="BTCUSDT", price=100.0, risk_pct=0.001
        )
        assert result.executed is True
        order = db_session.query(Order).one()
        assert order.client_order_id is not None
        assert order.client_order_id.startswith("paper-BTCUSDT-")
        assert order.client_order_id != order.exchange_order_id

    def test_paper_sell_persists_client_order_id(self, paper_engine, db_session):
        pos = Position(
            mode="paper", symbol="BTCUSDT", is_open=True,
            entry_price=100.0, entry_qty=0.1, entry_ts=datetime.utcnow(),
        )
        db_session.add(pos)
        db_session.commit()
        db_session.refresh(pos)
        result = paper_engine._execute_sell_paper(
            symbol="BTCUSDT", position=pos, price=110.0
        )
        assert result.executed is True
        sell_order = (
            db_session.query(Order).filter(Order.side == "SELL").one()
        )
        assert sell_order.client_order_id is not None
        assert "close" in sell_order.client_order_id


# --------------------------- duplicate / idempotency -----------------------


class TestIdempotency:
    def test_replayed_client_order_id_rejected(self, paper_engine, db_session):
        coid = "paper-BTCUSDT-replay-1234"
        db_session.add(
            Order(
                mode="paper", symbol="BTCUSDT", side="BUY",
                order_type="MARKET", quantity=0.001, status="FILLED",
                client_order_id=coid, exchange_order_id="paper-prev",
                created_at=datetime.utcnow(),
            )
        )
        db_session.commit()

        decision, _ = paper_engine._run_pretrade_risk_check(
            symbol="BTCUSDT", side="BUY", price=100.0,
            quantity=0.001, client_order_id=coid,
        )
        assert decision.approved is False
        assert "duplicate_client_order_id" in decision.reason_codes

    def test_stale_client_order_id_outside_window_allowed(
        self, paper_engine, db_session, monkeypatch
    ):
        monkeypatch.setenv("RISK_DUPLICATE_WINDOW_SECONDS", "1")
        coid = "paper-BTCUSDT-old"
        db_session.add(
            Order(
                mode="paper", symbol="BTCUSDT", side="BUY",
                order_type="MARKET", quantity=0.001, status="FILLED",
                client_order_id=coid, exchange_order_id="paper-old",
                created_at=datetime.utcnow() - timedelta(minutes=10),
            )
        )
        db_session.commit()
        decision, _ = paper_engine._run_pretrade_risk_check(
            symbol="BTCUSDT", side="BUY", price=100.0,
            quantity=0.001, client_order_id=coid,
        )
        # Older than window -> not duplicate. (May still be rejected by other
        # checks but not by duplicate_client_order_id.)
        assert "duplicate_client_order_id" not in decision.reason_codes


# --------------------------- restart recovery ------------------------------


class TestRestartRecovery:
    def test_recovery_rebuilds_paper_orders(self, db_session):
        for i in range(3):
            db_session.add(
                Order(
                    mode="paper", symbol="BTCUSDT", side="BUY",
                    order_type="MARKET", quantity=0.01,
                    requested_price=100.0, executed_price=100.0,
                    status="FILLED", exchange_order_id=f"paper-test-{i}",
                    created_at=datetime.utcnow(),
                )
            )
        db_session.commit()

        # Simulate fresh process — ORDERS list is empty already.
        assert ORDERS == []
        summary = bootstrap_runtime_state(db_session)
        assert summary["paper_orders_restored"] == 3
        assert len(ORDERS) == 3
        assert all(o.get("_restored") is True for o in ORDERS)
        # Idempotent — running again does not duplicate.
        summary2 = bootstrap_runtime_state(db_session)
        assert summary2["paper_orders_restored"] == 0
        assert len(ORDERS) == 3

    def test_recovery_rebuilds_shadow_orders_and_positions(self, db_session):
        db_session.add(
            Order(
                mode="shadow", symbol="ETHUSDT", side="BUY",
                order_type="MARKET", quantity=0.05,
                requested_price=2000.0, executed_price=2000.0,
                status="FILLED", exchange_order_id="shadow-test-1",
                created_at=datetime.utcnow(),
            )
        )
        db_session.add(
            Position(
                mode="paper", symbol="BTCUSDT", is_open=True,
                entry_price=100.0, entry_qty=0.5,
                entry_ts=datetime.utcnow(),
            )
        )
        db_session.commit()

        summary = bootstrap_runtime_state(db_session)
        assert summary["shadow_orders_restored"] == 1
        assert summary["paper_positions_restored"] == 1
        assert len(SHADOW_ORDERS) == 1
        assert any(p.get("symbol") == "BTCUSDT" for p in POSITIONS)
