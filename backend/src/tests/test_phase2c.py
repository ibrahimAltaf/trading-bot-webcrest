"""
Phase 2C — Controlled Micro-Live tests.
"""
from __future__ import annotations

import pytest

from src.safety import phase2c as p2c
from src.safety.risk_engine import (
    OrderRequest,
    RiskEngine,
    RiskLimits,
    _State,
)
from src.execution.mode import ExecutionMode


@pytest.fixture(autouse=True)
def _isolated_phase2c(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PHASE_2C_MICRO_LIVE_ENABLED", "false")
    monkeypatch.setenv("EXECUTION_MODE", "shadow")
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token")
    yield


ADMIN_HEADERS = {"X-Admin-Token": "test-admin-token"}


class TestPhase2CGate:
    def test_default_disabled(self):
        snap = p2c.snapshot()
        assert snap["micro_live_enabled"] is False
        assert "DISABLED" in snap["status_label"]
        assert p2c.can_place_live_orders() is False

    def test_activate_enables_runtime(self, tmp_path):
        snap = p2c.activate(by="test", reason="unit test")
        assert snap["micro_live_enabled"] is True
        assert p2c.is_micro_live_enabled() is True

    def test_deactivate_blocks(self):
        p2c.activate(by="test", reason="on")
        p2c.deactivate(by="test", reason="off")
        assert p2c.is_micro_live_enabled() is False

    def test_live_orders_need_both_live_mode_and_micro_live(self, monkeypatch):
        p2c.activate(by="test", reason="on")
        monkeypatch.setenv("EXECUTION_MODE", "shadow")
        assert p2c.can_place_live_orders() is False
        monkeypatch.setenv("EXECUTION_MODE", "live")
        assert p2c.can_place_live_orders() is True


class TestPhase2CRiskLimits:
    def test_max_total_exposure_blocks_buy(self):
        limits = RiskLimits(
            max_trade_notional_usdt=5.0,
            max_total_exposure_usdt=6.0,
        )
        state = _State(current_total_exposure_usdt=4.0)
        eng = RiskEngine(limits=limits, state=state)
        req = OrderRequest(
            symbol="BTCUSDT",
            side="BUY",
            price=80000.0,
            quantity=0.0000625,
            notional_usdt=5.0,
            mode=ExecutionMode.LIVE,
        )
        d = eng.validate(req)
        assert not d.approved
        assert "max_total_exposure" in d.reason_codes

    def test_cumulative_loss_blocks_buy(self):
        limits = RiskLimits(max_cumulative_loss_usdt=3.0)
        state = _State(cumulative_realized_pnl_usdt=-3.5)
        eng = RiskEngine(limits=limits, state=state)
        req = OrderRequest(
            symbol="ETHUSDT",
            side="BUY",
            price=2500.0,
            quantity=0.002,
            notional_usdt=5.0,
            mode=ExecutionMode.LIVE,
        )
        d = eng.validate(req)
        assert not d.approved
        assert "max_cumulative_loss" in d.reason_codes

    def test_symbol_whitelist_live_only(self):
        limits = RiskLimits(allowed_symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"))
        eng = RiskEngine(limits=limits)
        bad = OrderRequest(
            symbol="DOGEUSDT",
            side="BUY",
            price=0.1,
            quantity=100,
            notional_usdt=5.0,
            mode=ExecutionMode.LIVE,
        )
        d = eng.validate(bad)
        assert not d.approved
        assert "symbol_not_allowed" in d.reason_codes

        paper = OrderRequest(
            symbol="DOGEUSDT",
            side="BUY",
            price=0.1,
            quantity=100,
            notional_usdt=5.0,
            mode=ExecutionMode.PAPER,
        )
        assert eng.validate(paper).approved

    def test_sell_bypasses_entry_caps(self):
        limits = RiskLimits(
            max_open_positions=0,
            max_total_exposure_usdt=0.0,
            max_cumulative_loss_usdt=0.0,
        )
        eng = RiskEngine(limits=limits, state=_State())
        req = OrderRequest(
            symbol="BTCUSDT",
            side="SELL",
            price=80000.0,
            quantity=0.0001,
            mode=ExecutionMode.LIVE,
        )
        d = eng.validate(req)
        assert d.approved


class TestPhase2CAPI:
    @pytest.fixture
    def client(self):
        pytest.importorskip("binance")
        from fastapi.testclient import TestClient
        from src.main import app

        return TestClient(app)

    def test_phase2c_status_endpoint(self, client):
        r = client.get("/safety/phase2c/status")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert "micro_live_enabled" in body
        assert "limits" in body

    def test_phase2c_evidence_endpoint(self, client):
        r = client.get("/safety/phase2c/evidence")
        assert r.status_code == 200
        body = r.json()
        assert "decisions" in body
        assert "monitoring_endpoints" in body

    def test_activate_requires_reason(self, client):
        r = client.post(
            "/safety/phase2c/activate",
            json={},
            headers=ADMIN_HEADERS,
        )
        assert r.status_code == 422

    def test_activate_requires_admin_auth(self, client):
        r = client.post(
            "/safety/phase2c/activate",
            json={"reason": "no auth"},
        )
        assert r.status_code == 401

    def test_live_run_endpoint_disabled(self, client):
        r = client.post("/live/run", json={"symbol": "BTCUSDT", "usdt_amount": 5})
        assert r.status_code == 410

    def test_activate_and_deactivate(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 't.db'}")
        from src.db.session import engine
        from src.db.base import Base
        import src.db.models  # noqa

        Base.metadata.create_all(bind=engine)

        r = client.post(
            "/safety/phase2c/activate",
            json={"reason": "test activation", "by": "pytest"},
            headers=ADMIN_HEADERS,
        )
        assert r.status_code == 200
        assert r.json()["micro_live_enabled"] is True

        r2 = client.post(
            "/safety/phase2c/deactivate",
            json={"reason": "test deactivation", "by": "pytest"},
            headers=ADMIN_HEADERS,
        )
        assert r2.status_code == 200
        assert r2.json()["micro_live_enabled"] is False
