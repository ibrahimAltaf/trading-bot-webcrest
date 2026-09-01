"""
Phase 2A — Track 4 tests for exchange-side reconciliation.

Uses a fake Binance client so tests are deterministic and offline-safe.
"""
from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.base import Base
from src.db.models import Order, Position  # noqa: F401
import src.db.models  # noqa: F401
# Import src.main (and therefore src.scheduler.runner) BEFORE any monkeypatch
# replaces BinanceSpotClient — runner has a class-level annotation that would
# otherwise blow up when the symbol gets swapped with a lambda.
from src.main import app  # noqa: F401  (must come before exchange patches)
from src.execution.exchange_reconciler import reconcile_with_exchange


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    yield


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


class _FakeClient:
    def __init__(self, open_orders=None, balances=None):
        self._open_orders = open_orders or []
        self._balances = balances or {}

    def open_orders(self, symbol=None):
        return list(self._open_orders)

    def balances_map(self):
        return {k: str(v) for k, v in self._balances.items()}

    def account(self):
        return {
            "balances": [
                {"asset": k, "free": str(v)} for k, v in self._balances.items()
            ]
        }


# -------------------------- open-order drift --------------------------------


class TestOpenOrderDrift:
    def test_clean_when_db_and_exchange_match(self, db_session):
        db_session.add(
            Order(
                mode="live", symbol="BTCUSDT", side="BUY",
                order_type="LIMIT", quantity=0.01,
                status="NEW", exchange_order_id="EX-1",
                created_at=datetime.utcnow(),
            )
        )
        db_session.commit()
        client = _FakeClient(open_orders=[{"orderId": "EX-1", "symbol": "BTCUSDT"}])
        report = reconcile_with_exchange(db_session, client, mode="live")
        assert report["open_orders"]["drift_count"] == 0
        assert report["open_orders"]["db_open_count"] == 1
        assert report["open_orders"]["exchange_open_count"] == 1
        assert report["ok"] is True

    def test_drift_when_db_thinks_open_but_exchange_doesnt(self, db_session):
        db_session.add(
            Order(
                mode="live", symbol="BTCUSDT", side="BUY",
                order_type="LIMIT", quantity=0.01,
                status="NEW", exchange_order_id="EX-LOST",
                created_at=datetime.utcnow(),
            )
        )
        db_session.commit()
        client = _FakeClient(open_orders=[])
        report = reconcile_with_exchange(db_session, client, mode="live")
        assert report["open_orders"]["drift_count"] == 1
        assert "EX-LOST" in report["open_orders"]["only_in_db"]
        assert report["ok"] is False

    def test_drift_when_exchange_has_unknown_order(self, db_session):
        client = _FakeClient(
            open_orders=[{"orderId": "EX-GHOST", "symbol": "ETHUSDT"}]
        )
        report = reconcile_with_exchange(db_session, client, mode="live")
        assert report["open_orders"]["drift_count"] == 1
        assert "EX-GHOST" in report["open_orders"]["only_on_exchange"]


# -------------------------- position vs balance drift ----------------------


class TestPositionBalanceDrift:
    def test_position_backed_by_balance_is_clean(self, db_session):
        db_session.add(
            Position(
                mode="live", symbol="BTCUSDT", is_open=True,
                entry_price=100.0, entry_qty=0.5,
                entry_ts=datetime.utcnow(),
            )
        )
        db_session.commit()
        client = _FakeClient(balances={"BTC": 0.5, "USDT": 1000})
        report = reconcile_with_exchange(db_session, client, mode="live")
        assert report["positions"]["drift_count"] == 0

    def test_missing_balance_is_drift(self, db_session):
        db_session.add(
            Position(
                mode="live", symbol="BTCUSDT", is_open=True,
                entry_price=100.0, entry_qty=0.5,
                entry_ts=datetime.utcnow(),
            )
        )
        db_session.commit()
        # No BTC on exchange at all.
        client = _FakeClient(balances={"USDT": 1000})
        report = reconcile_with_exchange(db_session, client, mode="live")
        assert report["positions"]["drift_count"] == 1
        drift = report["positions"]["drift"][0]
        assert drift["symbol"] == "BTCUSDT"
        assert drift["base_asset"] == "BTC"
        assert drift["db_qty"] == 0.5
        assert drift["exchange_free"] == 0.0

    def test_within_tolerance_is_not_drift(self, db_session):
        # Position says 1.0 BTC; exchange shows 0.995 — under 1% tolerance.
        db_session.add(
            Position(
                mode="live", symbol="BTCUSDT", is_open=True,
                entry_price=100.0, entry_qty=1.0,
                entry_ts=datetime.utcnow(),
            )
        )
        db_session.commit()
        client = _FakeClient(balances={"BTC": 0.995, "USDT": 1000})
        report = reconcile_with_exchange(db_session, client, mode="live")
        assert report["positions"]["drift_count"] == 0

    def test_shadow_position_drift_is_expected_ok_true(self, db_session):
        """Simulated shadow position vs zero exchange BTC — ok stays true."""
        db_session.add(
            Position(
                mode="shadow", symbol="BTCUSDT", is_open=True,
                entry_price=64000.0, entry_qty=0.0015,
                entry_ts=datetime.utcnow(),
            )
        )
        db_session.commit()
        client = _FakeClient(balances={"USDT": 1000})
        report = reconcile_with_exchange(db_session, client, mode="shadow")
        assert report["positions"]["drift_count"] == 1
        assert report["positions"].get("expected_drift") is True
        assert report["open_orders"]["skipped"] is True
        assert report["ok"] is True


# -------------------------- error handling ---------------------------------


class TestErrorHandling:
    def test_open_orders_fetch_failure_is_surfaced(self, db_session):
        class _Boom:
            def open_orders(self, symbol=None):
                raise RuntimeError("simulated 401")

            def balances_map(self):
                return {"USDT": 1000}

            def account(self):
                return {"balances": [{"asset": "USDT", "free": "1000"}]}

        report = reconcile_with_exchange(db_session, _Boom(), mode="live")
        assert any("open_orders_fetch_failed" in e for e in report["errors"])
        assert report["ok"] is False


# -------------------------- API endpoint -----------------------------------


class TestExchangeReconcileAPI:
    def test_endpoint_calls_reconciler_and_returns_report(
        self, db_session, monkeypatch
    ):
        from src.api import routes_safety as rs_routes

        # Patch SessionLocal so the endpoint uses our in-memory DB.
        bind = db_session.bind
        from sqlalchemy.orm import sessionmaker

        factory = sessionmaker(
            autocommit=False, autoflush=False, expire_on_commit=False, bind=bind
        )
        monkeypatch.setattr(rs_routes, "SessionLocal", factory)

        # Stub the Binance client construction so the endpoint stays offline.
        fake = _FakeClient(open_orders=[], balances={"USDT": 100})
        monkeypatch.setattr(
            "src.exchange.binance_spot_client.BinanceSpotClient",
            lambda *a, **k: fake,
        )

        client = TestClient(app)
        r = client.get("/safety/exchange-reconcile?mode=live")
        assert r.status_code == 200, r.text
        body = r.json()
        assert "open_orders" in body and "positions" in body
        assert body["mode"] == "live"

    def test_endpoint_rejects_invalid_mode(self, monkeypatch):
        client = TestClient(app)
        r = client.get("/safety/exchange-reconcile?mode=banana")
        assert r.status_code == 400
