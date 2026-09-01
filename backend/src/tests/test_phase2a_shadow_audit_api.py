"""Phase 2A — /safety/shadow-audit, soak report, operational-readiness endpoints."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api import routes_safety as rs_routes
from src.api import routes_status as rs_status
from src.db.base import Base
import src.db.models  # noqa: F401
from src.main import app
from src.safety import kill_switch as ks


@pytest.fixture
def memory_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        autocommit=False, autoflush=False, expire_on_commit=False, bind=engine
    )
    factory._test_engine = engine  # type: ignore[attr-defined]
    return factory


@pytest.fixture
def client(memory_session_factory, monkeypatch):
    import src.db.session as db_session

    orig_session = db_session.SessionLocal
    orig_engine = db_session.engine
    db_session.SessionLocal = memory_session_factory
    db_session.engine = memory_session_factory._test_engine  # type: ignore[attr-defined]
    rs_routes.SessionLocal = memory_session_factory
    rs_status.SessionLocal = memory_session_factory

    fake_binance = SimpleNamespace(
        open_orders=lambda: [],
        account=lambda: {"balances": [{"asset": "USDT", "free": "10000"}]},
    )
    monkeypatch.setattr(
        "src.exchange.binance_spot_client.BinanceSpotClient",
        lambda *a, **k: fake_binance,
    )
    monkeypatch.setattr(
        "src.live.auto_trade_engine.BinanceSpotClient",
        lambda *a, **k: SimpleNamespace(
            account=lambda: {"balances": [{"asset": "USDT", "free": "10000"}]},
            get_symbol_filters=lambda symbol: {
                "minNotional": 5.0,
                "stepSize": 0.00001,
                "tickSize": 0.01,
            },
            get_price=lambda symbol: 100.0,
        ),
    )

    yield TestClient(app)

    db_session.SessionLocal = orig_session
    db_session.engine = orig_engine
    rs_routes.SessionLocal = orig_session
    rs_status.SessionLocal = orig_session


@pytest.fixture(autouse=True)
def _ks_release(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    try:
        ks.release("setup", by="pytest")
    except Exception:
        pass
    yield
    try:
        ks.release("teardown", by="pytest")
    except Exception:
        pass


def test_shadow_audit_returns_id_fields(client):
    r = client.get("/safety/shadow-audit?limit=10")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "unique_shadow_order_ids" in body
    assert "unique_client_order_ids" in body
    assert "verification_endpoints" in body
    assert "soak_closeout" in body["verification_endpoints"]
    assert body["shadow_use_fallback_balance"] is True


def test_operational_readiness(client):
    r = client.get("/safety/operational-readiness")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "restart_recovery" in body
    assert "alerting" in body
    assert "shadow_visibility" in body


def test_performance_shadow_mode_no_longer_400(client):
    r = client.get("/exchange/performance?mode=shadow")
    assert r.status_code == 200
    assert r.json().get("mode") == "shadow"


def test_phase2b_health_empty_db_reports_no_orphans(client):
    """No orders/decisions yet: integrity checks trivially pass, scheduler
    heartbeat fails (never ticked) — that's the correct signal, not a bug."""
    r = client.get("/safety/phase2b-health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    names = {c["name"] for c in body["checks"]}
    assert names == {
        "scheduler_heartbeat",
        "decision_order_integrity",
        "adaptive_engine",
        "risk_controls_active",
        "duplicate_order_protection",
    }
    integrity = next(c for c in body["checks"] if c["name"] == "decision_order_integrity")
    assert integrity["ok"] is True
    assert integrity["detail"]["executed_decisions_missing_order_id"] == 0
    heartbeat = next(c for c in body["checks"] if c["name"] == "scheduler_heartbeat")
    assert heartbeat["ok"] is False
    assert heartbeat["detail"]["last_scheduler_decision_ts"] is None


def test_phase2b_health_detects_orphaned_order(client, memory_session_factory):
    """An Order with no TradingDecisionLog pointing at it must fail integrity,
    even though every other check is healthy."""
    from src.db.models import Order

    db = memory_session_factory()
    try:
        db.add(
            Order(
                mode="shadow",
                symbol="BTCUSDT",
                side="BUY",
                quantity=0.001,
                status="FILLED",
                triggered_by="scheduler",
            )
        )
        db.commit()
    finally:
        db.close()

    r = client.get("/safety/phase2b-health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "FAIL"
    integrity = next(c for c in body["checks"] if c["name"] == "decision_order_integrity")
    assert integrity["ok"] is False
    assert integrity["detail"]["orders_without_a_linking_decision"] == 1


def test_phase2b_health_detects_duplicate_client_order_id(client, memory_session_factory):
    from src.db.models import Order

    db = memory_session_factory()
    try:
        db.add_all(
            [
                Order(
                    mode="shadow",
                    symbol="ETHUSDT",
                    side="BUY",
                    quantity=0.01,
                    status="FILLED",
                    client_order_id="dup-1",
                ),
                Order(
                    mode="shadow",
                    symbol="ETHUSDT",
                    side="SELL",
                    quantity=0.01,
                    status="FILLED",
                    client_order_id="dup-1",
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    r = client.get("/safety/phase2b-health")
    body = r.json()
    dup_check = next(c for c in body["checks"] if c["name"] == "duplicate_order_protection")
    assert dup_check["ok"] is False
    assert dup_check["detail"]["duplicate_client_order_ids"][0]["client_order_id"] == "dup-1"
    assert dup_check["detail"]["duplicate_client_order_ids"][0]["count"] == 2


def test_shadow_soak_report_flat_fields(client):
    r = client.get("/safety/shadow-soak-report?days=7")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["report_type"] == "shadow_soak_closeout"
    assert "ready_for_live_capital" in body
    assert body["ready_for_live_capital"] is False
    assert "safety_reconcile_drift_count" in body
    assert "exchange_shadow_drift_count" in body
    assert "endpoint_errors_explanation" in body
    assert "shadow_orders" in body
    assert "shadow_positions_history" in body
    assert "shadow_pnl_summary" in body
    assert "shadow_orders_origin_summary" in body


def test_reconcile_exposes_drift_count(client):
    r = client.get("/safety/reconcile")
    assert r.status_code == 200
    assert "drift_count" in r.json()


def test_shadow_soak_report_serializes_nan_pnl(client, memory_session_factory):
    import math
    from datetime import datetime

    from src.db.models import Order, Position, TradingDecisionLog

    db = memory_session_factory()
    order = Order(
        mode="shadow",
        symbol="BTCUSDT",
        side="BUY",
        quantity=0.01,
        executed_price=100.0,
        status="FILLED",
        exchange_order_id="shadow-nan-test",
        created_at=datetime.utcnow(),
    )
    db.add(order)
    db.flush()
    db.add(
        TradingDecisionLog(
            action="BUY",
            confidence=1.0,
            symbol="BTCUSDT",
            timeframe="1h",
            regime="UNKNOWN",
            price=100.0,
            reason="test",
            executed=True,
            order_id=order.id,
            signals_json='{"final_source":"rule_only","ml_confidence":NaN}',
        )
    )
    db.add(
        Position(
            mode="shadow",
            symbol="BTCUSDT",
            is_open=False,
            entry_price=100.0,
            entry_qty=0.01,
            entry_ts=datetime.utcnow(),
            exit_price=101.0,
            exit_qty=0.01,
            exit_ts=datetime.utcnow(),
            pnl=float("nan"),
            pnl_pct=float("nan"),
        )
    )
    db.commit()
    db.close()

    r = client.get("/safety/shadow-soak-report?days=7&symbol=BTCUSDT")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["shadow_pnl_summary"]["realized_pnl_usdt"] == 0.0
    assert math.isfinite(body["shadow_positions_history"][0]["pnl"])
