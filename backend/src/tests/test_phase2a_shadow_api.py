"""
Shadow mode query API tests — fixes client audit findings (400/404 on ?mode=shadow).
"""
from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api import routes_exchange as rex
from src.api import routes_safety as rs
from src.db.base import Base
from src.db.models import Order, Position
import src.db.models  # noqa: F401
from src.main import app


@pytest.fixture(autouse=True)
def _clear_trackers():
    try:
        from src.execution.execution_engine import ORDERS, SHADOW_ORDERS

        ORDERS.clear()
        SHADOW_ORDERS.clear()
    except Exception:
        pass
    yield
    try:
        from src.execution.execution_engine import ORDERS, SHADOW_ORDERS

        ORDERS.clear()
        SHADOW_ORDERS.clear()
    except Exception:
        pass


@pytest.fixture
def db_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        autocommit=False, autoflush=False, expire_on_commit=False, bind=engine
    )
    return factory


@pytest.fixture
def client(db_factory):
    import src.db.session as db_session

    orig = db_session.SessionLocal
    db_session.SessionLocal = db_factory
    rex.SessionLocal = db_factory
    rs.SessionLocal = db_factory
    yield TestClient(app)
    db_session.SessionLocal = orig
    rex.SessionLocal = orig
    rs.SessionLocal = orig


class TestShadowQueryAPIs:
    def test_orders_all_returns_shadow_mode_not_live(self, client, db_factory):
        db = db_factory()
        db.add(
            Order(
                mode="shadow",
                symbol="BTCUSDT",
                side="BUY",
                order_type="MARKET",
                quantity=0.01,
                status="FILLED",
                exchange_order_id="shadow-test-abc",
                created_at=datetime.utcnow(),
            )
        )
        db.commit()
        db.close()

        r = client.get("/exchange/orders/all?symbol=BTCUSDT&mode=shadow&limit=10")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["mode"] == "shadow"
        assert body["count"] >= 1
        assert body["orders"][0]["orderId"].startswith("shadow-")

    def test_positions_history_accepts_shadow(self, client, db_factory):
        db = db_factory()
        db.add(
            Position(
                mode="shadow",
                symbol="BTCUSDT",
                is_open=False,
                entry_price=100.0,
                entry_qty=0.1,
                exit_price=110.0,
                exit_qty=0.1,
                entry_ts=datetime.utcnow(),
                exit_ts=datetime.utcnow(),
                pnl=1.0,
                pnl_pct=10.0,
            )
        )
        db.commit()
        db.close()

        r = client.get("/exchange/positions/history?mode=shadow&limit=5")
        assert r.status_code == 200, r.text
        assert r.json()["mode"] == "shadow"

    def test_proof_accepts_shadow(self, client, db_factory):
        db = db_factory()
        db.commit()
        db.close()

        r = client.get("/exchange/proof?symbol=BTCUSDT&mode=shadow")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["mode"] == "shadow"
        assert body["shadow_trading"]["active"] is True

    def test_exchange_reconcile_shadow_not_404(self, client, monkeypatch):
        class _Fake:
            def open_orders(self, symbol=None):
                return []

            def balances_map(self):
                return {"USDT": 1000.0, "BTC": 0.0}

        monkeypatch.setattr(
            "src.exchange.binance_spot_client.BinanceSpotClient",
            lambda *a, **k: _Fake(),
        )
        r = client.get("/safety/exchange-reconcile?mode=shadow")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["mode"] == "shadow"
        assert body["open_orders"].get("skipped") is True

    def test_invalid_mode_still_400(self, client):
        r = client.get("/exchange/proof?mode=banana")
        assert r.status_code == 400
