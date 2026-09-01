"""
Phase 2A — Track 5 alerter tests.

Confirms:
* Level filtering (ALERT_MIN_LEVEL).
* Webhook + extra sink dispatch.
* Sync mode is deterministic (no thread / queue dependency).
* Risk-rejection path emits a structured alert.
* Kill-switch engage / release emit alerts.
* The alerter never raises into the caller, even when sinks blow up.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.base import Base
from src.db.models import Position  # noqa: F401
import src.db.models  # noqa: F401
from src.live.auto_trade_engine import AutoTradeEngine
from src.safety import alerts as _alerts
from src.safety import kill_switch as ks


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    # Wipe any previous extra sinks registered by other tests.
    _alerts._extra_sinks.clear()
    try:
        ks.release("setup", by="pytest")
    except Exception:
        pass
    yield
    _alerts._extra_sinks.clear()
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


class TestLevelFiltering:
    def test_info_dropped_when_min_warn(self, monkeypatch):
        monkeypatch.setenv("ALERT_MIN_LEVEL", "WARN")
        sink: List[Dict[str, Any]] = []
        _alerts.register_alerter(sink.append)
        _alerts.send_alert("INFO", "test", "should be dropped", sync=True)
        _alerts.send_alert("WARN", "test", "should pass", sync=True)
        assert len(sink) == 1
        assert sink[0]["level"] == "WARN"

    def test_min_level_default_is_warn(self, monkeypatch):
        monkeypatch.delenv("ALERT_MIN_LEVEL", raising=False)
        sink: List[Dict[str, Any]] = []
        _alerts.register_alerter(sink.append)
        _alerts.send_alert("INFO", "test", "noise", sync=True)
        _alerts.send_alert("ERROR", "test", "signal", sync=True)
        assert [s["level"] for s in sink] == ["ERROR"]


class TestSinkResilience:
    def test_sink_exception_does_not_propagate(self, monkeypatch):
        monkeypatch.setenv("ALERT_MIN_LEVEL", "INFO")
        called = []

        def bad(_p):
            raise RuntimeError("boom")

        def good(p):
            called.append(p)

        _alerts.register_alerter(bad)
        _alerts.register_alerter(good)
        # Must NOT raise.
        _alerts.send_alert("WARN", "test", "still works", sync=True)
        assert len(called) == 1


class TestRiskRejectionEmitsAlert:
    def test_risk_blocked_buy_calls_alerter(
        self, db_session, monkeypatch
    ):
        monkeypatch.setenv("ALERT_MIN_LEVEL", "INFO")
        monkeypatch.setattr(
            "src.live.auto_trade_engine.BinanceSpotClient",
            lambda *a, **k: object(),
        )
        monkeypatch.setenv("PHASE1_PAPER_EXECUTION", "true")
        monkeypatch.setenv("PAPER_USDT_BALANCE", "10000")
        # Force a rejection via tiny notional cap.
        monkeypatch.setenv("RISK_MAX_TRADE_NOTIONAL_USDT", "1")

        captured: List[Dict[str, Any]] = []
        _alerts.register_alerter(captured.append)

        # Hijack send_alert into sync mode for determinism — the engine path
        # uses the default (async) call, so we wrap and call _dispatch directly.
        orig_send = _alerts.send_alert

        def sync_send(level, category, message, **extra):
            return orig_send(level, category, message, sync=True, **extra)

        monkeypatch.setattr("src.safety.alerts.send_alert", sync_send)

        eng = AutoTradeEngine(db=db_session)
        eng.execution_mode = "paper"
        result = eng._execute_buy_paper(
            symbol="BTCUSDT", price=100.0, risk_pct=0.01
        )
        assert result.blocked is True
        assert any(
            p["category"] == "risk_rejected" and p["level"] == "WARN"
            for p in captured
        ), captured


class TestKillSwitchEmitsAlerts:
    def test_engage_release_emit_alerts(self, monkeypatch):
        monkeypatch.setenv("ALERT_MIN_LEVEL", "INFO")
        captured: List[Dict[str, Any]] = []
        _alerts.register_alerter(captured.append)
        orig_send = _alerts.send_alert
        monkeypatch.setattr(
            "src.safety.alerts.send_alert",
            lambda l, c, m, **kw: orig_send(l, c, m, sync=True, **kw),
        )

        ks.engage("manual", by="pytest")
        ks.release("manual", by="pytest")

        cats = [p["category"] for p in captured]
        assert "kill_switch_engaged" in cats
        assert "kill_switch_released" in cats
