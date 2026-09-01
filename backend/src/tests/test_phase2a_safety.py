"""
Phase 2A safety scaffolding tests:
- ExecutionMode tri-state (paper / shadow / live) + persistence
- KillSwitch engage / release / persistence
- RiskEngine validation paths
- Reconciler read-only drift report
- /safety/* and /execution/mode API endpoints
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api import routes_safety as rs_routes
from src.db.base import Base
from src.db.models import Order, Position, Trade
import src.db.models  # noqa: F401
from src.execution.mode import (
    ExecutionMode,
    clear_execution_mode_override,
    get_execution_mode,
    is_simulated,
    mode_snapshot,
    set_execution_mode,
)
from src.execution.reconciler import reconcile
from src.main import app
from src.safety import kill_switch as ks
from src.safety.risk_engine import (
    OrderRequest,
    RiskDecision,
    RiskEngine,
    RiskLimits,
    _State,
    default_limits_from_env,
)


@pytest.fixture(autouse=True)
def _isolated_safety_data(tmp_path, monkeypatch):
    """Point safety state files at a tmp dir per test (no cross-test bleed)."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token")
    yield


ADMIN_HEADERS = {"X-Admin-Token": "test-admin-token"}


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
    return factory


@pytest.fixture
def client(memory_session_factory, monkeypatch):
    import src.db.session as db_session

    orig = db_session.SessionLocal
    db_session.SessionLocal = memory_session_factory
    rs_routes.SessionLocal = memory_session_factory
    yield TestClient(app)
    db_session.SessionLocal = orig
    rs_routes.SessionLocal = orig


# ============================== ExecutionMode ================================


class TestExecutionMode:
    def test_coerce_accepts_known_values(self):
        assert ExecutionMode.coerce("paper") is ExecutionMode.PAPER
        assert ExecutionMode.coerce("Shadow") is ExecutionMode.SHADOW
        assert ExecutionMode.coerce("LIVE") is ExecutionMode.LIVE

    def test_coerce_rejects_unknown(self):
        with pytest.raises(ValueError):
            ExecutionMode.coerce("dryrun")

    def test_is_simulated(self):
        assert is_simulated(ExecutionMode.PAPER)
        assert is_simulated(ExecutionMode.SHADOW)
        assert not is_simulated(ExecutionMode.LIVE)

    def test_default_falls_back_to_live(self, monkeypatch):
        monkeypatch.delenv("EXECUTION_MODE", raising=False)
        monkeypatch.delenv("PHASE1_PAPER_EXECUTION", raising=False)
        clear_execution_mode_override()
        assert get_execution_mode() is ExecutionMode.LIVE

    def test_env_var_resolution(self, monkeypatch):
        clear_execution_mode_override()
        monkeypatch.setenv("EXECUTION_MODE", "shadow")
        assert get_execution_mode() is ExecutionMode.SHADOW

    def test_legacy_phase1_paper_flag(self, monkeypatch):
        clear_execution_mode_override()
        monkeypatch.delenv("EXECUTION_MODE", raising=False)
        monkeypatch.setenv("PHASE1_PAPER_EXECUTION", "true")
        assert get_execution_mode() is ExecutionMode.PAPER

    def test_override_wins_over_env(self, monkeypatch):
        monkeypatch.setenv("EXECUTION_MODE", "live")
        set_execution_mode(ExecutionMode.SHADOW, changed_by="t", reason="test")
        assert get_execution_mode() is ExecutionMode.SHADOW
        clear_execution_mode_override()
        assert get_execution_mode() is ExecutionMode.LIVE

    def test_snapshot_structure(self):
        snap = mode_snapshot()
        assert "effective_mode" in snap
        assert "is_simulated" in snap
        assert "sources" in snap


# ============================== KillSwitch ===================================


class TestKillSwitch:
    def test_default_not_engaged(self):
        assert ks.is_engaged() is False
        state = ks.get_state()
        assert state["engaged"] is False
        assert state["history"] == []

    def test_engage_then_release(self):
        ks.engage("manual test", by="tester")
        assert ks.is_engaged() is True
        state = ks.get_state()
        assert state["engaged"] is True
        assert state["reason"] == "manual test"
        assert state["engaged_by"] == "tester"
        ks.release("all clear", by="tester")
        assert ks.is_engaged() is False
        s2 = ks.get_state()
        assert s2["release_reason"] == "all clear"

    def test_engage_requires_reason(self):
        with pytest.raises(ValueError):
            ks.engage("", by="tester")

    def test_release_requires_reason(self):
        ks.engage("foo")
        with pytest.raises(ValueError):
            ks.release("", by="tester")

    def test_history_capped_at_50(self):
        for i in range(60):
            ks.engage(f"r{i}", by="t")
            ks.release(f"clr{i}", by="t")
        assert len(ks.get_state()["history"]) <= 50

    def test_persistence_across_reads(self):
        ks.engage("persist", by="t")
        assert ks.is_engaged() is True
        # Re-import would re-read from disk: state file should retain engaged=true.
        state = ks.get_state()
        assert state["engaged"] is True


# ============================== RiskEngine ===================================


def _req(**kw) -> OrderRequest:
    base = dict(
        symbol="BTCUSDT",
        side="BUY",
        price=50_000.0,
        quantity=0.001,  # 50 USDT notional
        mode=ExecutionMode.PAPER,
    )
    base.update(kw)
    return OrderRequest(**base)


class TestRiskEngine:
    def test_default_limits_accept_small_buy(self):
        eng = RiskEngine(kill_switch_is_engaged=lambda: False)
        d = eng.validate(_req())
        assert d.approved is True, d.as_dict()

    def test_kill_switch_blocks(self):
        eng = RiskEngine(kill_switch_is_engaged=lambda: True)
        d = eng.validate(_req())
        assert d.approved is False
        assert "kill_switch_engaged" in d.reason_codes

    def test_above_max_notional(self):
        eng = RiskEngine(
            limits=RiskLimits(max_trade_notional_usdt=10.0),
            kill_switch_is_engaged=lambda: False,
        )
        d = eng.validate(_req())
        assert d.approved is False
        assert "above_max_trade_notional" in d.reason_codes

    def test_below_min_notional(self):
        eng = RiskEngine(kill_switch_is_engaged=lambda: False)
        d = eng.validate(_req(quantity=0.00000001))  # 0.0005 USDT
        assert d.approved is False
        assert "below_min_notional" in d.reason_codes

    def test_max_open_positions(self):
        state = _State(open_positions_count=3)
        eng = RiskEngine(
            limits=RiskLimits(max_open_positions=3),
            state=state,
            kill_switch_is_engaged=lambda: False,
        )
        d = eng.validate(_req(side="BUY"))
        assert d.approved is False
        assert "max_open_positions" in d.reason_codes

    def test_sell_bypasses_open_positions_check(self):
        state = _State(open_positions_count=99)
        eng = RiskEngine(
            limits=RiskLimits(max_open_positions=3),
            state=state,
            kill_switch_is_engaged=lambda: False,
        )
        d = eng.validate(_req(side="SELL"))
        assert d.approved is True

    def test_daily_loss_breach(self):
        state = _State(daily_realized_pnl_usdt=-100.0)
        eng = RiskEngine(
            limits=RiskLimits(max_daily_loss_usdt=50.0),
            state=state,
            kill_switch_is_engaged=lambda: False,
        )
        d = eng.validate(_req())
        assert d.approved is False
        assert "max_daily_loss" in d.reason_codes

    def test_daily_loss_triggers_at_exact_boundary(self):
        state = _State(daily_realized_pnl_usdt=-1.50)
        eng = RiskEngine(
            limits=RiskLimits(max_daily_loss_usdt=1.50),
            state=state,
            kill_switch_is_engaged=lambda: False,
        )
        d = eng.validate(_req())
        assert d.approved is False
        assert "max_daily_loss" in d.reason_codes
        assert ">=" in (d.reasons[0] if d.reasons else "")

    def test_daily_orders_breach(self):
        state = _State(daily_orders_count=50)
        eng = RiskEngine(
            limits=RiskLimits(max_daily_orders=50),
            state=state,
            kill_switch_is_engaged=lambda: False,
        )
        d = eng.validate(_req())
        assert d.approved is False
        assert "max_daily_orders" in d.reason_codes

    def test_cooldown_after_loss(self):
        now = datetime.utcnow()
        state = _State(last_loss_at=now - timedelta(seconds=5))
        eng = RiskEngine(
            limits=RiskLimits(cooldown_seconds_after_loss=60),
            state=state,
            kill_switch_is_engaged=lambda: False,
            now_fn=lambda: now,
        )
        d = eng.validate(_req())
        assert d.approved is False
        assert "cooldown_after_loss" in d.reason_codes

    def test_duplicate_client_order_id(self):
        now = datetime.utcnow()
        state = _State(
            recent_client_order_ids={"abc-123": now - timedelta(seconds=3)}
        )
        eng = RiskEngine(
            limits=RiskLimits(duplicate_window_seconds=10),
            state=state,
            kill_switch_is_engaged=lambda: False,
            now_fn=lambda: now,
        )
        d = eng.validate(_req(client_order_id="abc-123"))
        assert d.approved is False
        assert "duplicate_client_order_id" in d.reason_codes

    def test_exposure_pct_breach(self):
        state = _State(account_balance_usdt=100.0)  # 50 USDT notional = 50% > 30%
        eng = RiskEngine(
            limits=RiskLimits(max_exposure_pct_of_balance=0.30),
            state=state,
            kill_switch_is_engaged=lambda: False,
        )
        d = eng.validate(_req())
        assert d.approved is False
        assert "exposure_pct_exceeded" in d.reason_codes

    def test_ml_confidence_only_enforced_for_live(self):
        eng = RiskEngine(
            limits=RiskLimits(min_ml_confidence_for_live=0.8),
            kill_switch_is_engaged=lambda: False,
        )
        ok = eng.validate(_req(mode=ExecutionMode.PAPER, ml_confidence=0.1))
        assert ok.approved is True
        bad = eng.validate(_req(mode=ExecutionMode.LIVE, ml_confidence=0.1))
        assert bad.approved is False
        assert "ml_confidence_below_min_for_live" in bad.reason_codes

    def test_default_limits_from_env_picks_up_overrides(self, monkeypatch):
        monkeypatch.setenv("RISK_MAX_TRADE_NOTIONAL_USDT", "42.5")
        monkeypatch.setenv("RISK_MAX_OPEN_POSITIONS", "7")
        lim = default_limits_from_env()
        assert lim.max_trade_notional_usdt == 42.5
        assert lim.max_open_positions == 7


# ============================== Reconciler ===================================


class TestReconciler:
    def test_empty_db_returns_drift_clean(self, memory_session_factory):
        db = memory_session_factory()
        report = reconcile(db)
        db.close()
        assert report["ok"] is True
        assert report["orders"]["db_total"] == 0
        assert report["positions"]["db_open"] == 0
        assert report["drift"] == []

    def test_paper_drift_detected(self, memory_session_factory):
        db = memory_session_factory()
        db.add(
            Order(
                mode="paper",
                symbol="BTCUSDT",
                side="BUY",
                order_type="MARKET",
                quantity=0.001,
                status="filled",
            )
        )
        db.add(Position(mode="paper", symbol="BTCUSDT", is_open=True))
        db.commit()
        report = reconcile(db)
        db.close()
        kinds = {d["kind"] for d in report["drift"]}
        assert "paper_tracker_empty_but_db_has_orders" in kinds
        assert "paper_open_positions_not_in_memory" in kinds


# ============================== API endpoints ================================


class TestSafetyAPI:
    def test_status_endpoint(self, client):
        r = client.get("/safety/status")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert "execution_mode" in body
        assert "kill_switch" in body
        assert "limits" in body
        assert "reconcile" in body

    def test_kill_switch_engage_and_release_via_api(self, client):
        r = client.post(
            "/safety/kill-switch/engage",
            json={"reason": "manual audit", "by": "test"},
            headers=ADMIN_HEADERS,
        )
        assert r.status_code == 200, r.text
        assert r.json()["engaged"] is True

        r2 = client.get("/safety/kill-switch")
        assert r2.json()["kill_switch"]["engaged"] is True

        r3 = client.post(
            "/safety/kill-switch/release",
            json={"reason": "audit done", "by": "test"},
            headers=ADMIN_HEADERS,
        )
        assert r3.status_code == 200
        assert r3.json()["engaged"] is False

    def test_kill_switch_mutations_require_auth(self, client):
        r = client.post(
            "/safety/kill-switch/engage",
            json={"reason": "no auth"},
        )
        assert r.status_code == 401

    def test_engage_requires_reason(self, client):
        r = client.post(
            "/safety/kill-switch/engage",
            json={"reason": ""},
            headers=ADMIN_HEADERS,
        )
        # Pydantic min_length=1 → 422
        assert r.status_code == 422

    def test_execution_mode_get_set_clear(self, client):
        r = client.get("/execution/mode")
        assert r.status_code == 200
        assert "effective_mode" in r.json()

        r2 = client.post(
            "/execution/mode",
            json={"mode": "shadow", "reason": "phase2a-test"},
            headers=ADMIN_HEADERS,
        )
        assert r2.status_code == 200, r2.text
        assert r2.json()["mode"] == "shadow"

        r3 = client.get("/execution/mode")
        assert r3.json()["effective_mode"] == "shadow"

        r4 = client.delete("/execution/mode/override", headers=ADMIN_HEADERS)
        assert r4.status_code == 200
        assert r4.json()["removed"] is True

    def test_cannot_switch_to_live_while_kill_switch_engaged(self, client):
        client.post(
            "/safety/kill-switch/engage",
            json={"reason": "lock"},
            headers=ADMIN_HEADERS,
        )
        r = client.post(
            "/execution/mode",
            json={"mode": "live", "reason": "should_fail"},
            headers=ADMIN_HEADERS,
        )
        assert r.status_code == 409
        # Cleanup so other tests are not affected — though autouse fixture isolates.
        client.post(
            "/safety/kill-switch/release",
            json={"reason": "cleanup"},
            headers=ADMIN_HEADERS,
        )

    def test_invalid_mode_rejected(self, client):
        r = client.post(
            "/execution/mode",
            json={"mode": "dryrun"},
            headers=ADMIN_HEADERS,
        )
        assert r.status_code == 400

    def test_reconcile_endpoint(self, client):
        r = client.get("/safety/reconcile")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert "orders" in body and "positions" in body and "drift" in body


# ============================== AutoTradeEngine hook =========================


class TestEngineKillSwitchHook:
    def test_execute_auto_trade_short_circuits_when_engaged(self, monkeypatch):
        """The engine must refuse execution as soon as the kill switch is on,
        before any market data or ML call is made."""
        from src.live.auto_trade_engine import AutoTradeEngine

        # Stub the heavy collaborators so we can construct the engine cheaply.
        monkeypatch.setattr(
            "src.live.auto_trade_engine.BinanceSpotClient",
            lambda *a, **k: object(),
        )

        eng = AutoTradeEngine.__new__(AutoTradeEngine)  # type: ignore[call-arg]
        # Minimal attributes needed for the kill-switch short-circuit path.
        eng.settings = type(
            "S",
            (),
            {"trade_symbol": "BTCUSDT", "trade_timeframe": "5m"},
        )()
        eng.cooldown = type("C", (), {"blocked": lambda self, now: False})()
        eng._log_event = lambda *a, **k: None  # noqa: E501

        ks.engage("test-block", by="pytest")
        try:
            result = AutoTradeEngine.execute_auto_trade(eng)  # type: ignore[arg-type]
            assert result.executed is False
            assert "Kill switch engaged" in (result.reason or "")
            assert result.blocked is True
        finally:
            ks.release("test-cleanup", by="pytest")
