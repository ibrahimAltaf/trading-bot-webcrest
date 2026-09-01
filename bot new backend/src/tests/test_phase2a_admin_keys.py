"""
Phase 2A.1 tests — runtime Binance key overlay + admin endpoints + live readiness.

Covers:
- AppSetting-backed overlay resolution (overlay → env → none)
- BinanceSpotClient instantiation reading from overlay
- /admin/binance-keys GET/PUT/DELETE + auth gates
- /admin/binance-keys/verify error handling
- /safety/live-readiness aggregation
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api import routes_admin as rad_routes
from src.api import routes_safety as rs_routes
from src.db.base import Base
import src.db.models  # noqa: F401
from src.main import app
from src.safety import kill_switch as ks


@pytest.fixture(autouse=True)
def _isolated_safety_data(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    yield


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
def patched_db(memory_session_factory, monkeypatch):
    import src.db.session as db_session

    orig = db_session.SessionLocal
    db_session.SessionLocal = memory_session_factory
    rs_routes.SessionLocal = memory_session_factory
    yield memory_session_factory
    db_session.SessionLocal = orig
    rs_routes.SessionLocal = orig


@pytest.fixture
def client(patched_db, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token")
    return TestClient(app)


# ============================== runtime_keys core ============================


class TestRuntimeKeys:
    def test_env_only_resolution(self, patched_db, monkeypatch):
        from src.exchange.runtime_keys import resolve_runtime_keys

        monkeypatch.setenv("BINANCE_API_KEY", "env-key")
        monkeypatch.setenv("BINANCE_API_SECRET", "env-secret")
        monkeypatch.setenv("BINANCE_TESTNET", "true")
        rk = resolve_runtime_keys()
        assert rk.api_key == "env-key"
        assert rk.api_secret == "env-secret"
        assert rk.testnet is True
        assert rk.source == "env"
        assert rk.api_key_set is True
        assert rk.api_secret_set is True

    def test_overlay_wins_over_env(self, patched_db, monkeypatch):
        from src.exchange.runtime_keys import resolve_runtime_keys, set_overlay

        monkeypatch.setenv("BINANCE_API_KEY", "env-key")
        monkeypatch.setenv("BINANCE_API_SECRET", "env-secret")
        monkeypatch.setenv("BINANCE_TESTNET", "true")
        set_overlay(api_key="overlay-key", api_secret="overlay-secret", testnet=False)
        rk = resolve_runtime_keys()
        assert rk.api_key == "overlay-key"
        assert rk.api_secret == "overlay-secret"
        assert rk.testnet is False
        assert rk.source == "overlay"

    def test_clear_overlay_falls_back_to_env(self, patched_db, monkeypatch):
        from src.exchange.runtime_keys import clear_overlay, resolve_runtime_keys, set_overlay

        monkeypatch.setenv("BINANCE_API_KEY", "env-key")
        monkeypatch.setenv("BINANCE_API_SECRET", "env-secret")
        set_overlay(api_key="x", api_secret="y", testnet=False)
        clear_overlay()
        rk = resolve_runtime_keys()
        assert rk.source == "env"
        assert rk.api_key == "env-key"

    def test_overlay_partial_update(self, patched_db, monkeypatch):
        from src.exchange.runtime_keys import resolve_runtime_keys, set_overlay

        monkeypatch.setenv("BINANCE_API_KEY", "env-key")
        monkeypatch.setenv("BINANCE_API_SECRET", "env-secret")
        # Save only the secret in overlay; key should still come from env.
        set_overlay(api_secret="just-secret")
        rk = resolve_runtime_keys()
        assert rk.api_key == "env-key"
        assert rk.api_secret == "just-secret"
        assert rk.source == "mixed"

    def test_overlay_secret_encrypted_when_key_material_present(
        self, patched_db, monkeypatch
    ):
        from src.exchange.runtime_keys import set_overlay
        from src.db.models import AppSetting
        from src.db.session import SessionLocal

        monkeypatch.setenv("SECRETS_ENCRYPTION_KEY", "test-master-32-bytes-aaaaaaaa")
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
        except ImportError:
            pytest.skip("cryptography lib not installed in test env")
        set_overlay(api_secret="super-secret")
        db = SessionLocal()
        try:
            row = (
                db.query(AppSetting)
                .filter_by(key="RUNTIME_BINANCE_API_SECRET")
                .first()
            )
            assert row is not None
            assert row.value.startswith("enc:v1:"), row.value
        finally:
            db.close()


# ============================== BinanceSpotClient init =======================


class TestBinanceClientUsesOverlay:
    def test_client_picks_up_overlay_keys(self, patched_db, monkeypatch):
        from src.exchange.runtime_keys import set_overlay
        from src.exchange.binance_spot_client import BinanceSpotClient

        # Force env empty so we KNOW the client only succeeds via overlay.
        monkeypatch.delenv("BINANCE_API_KEY", raising=False)
        monkeypatch.delenv("BINANCE_API_SECRET", raising=False)
        monkeypatch.setenv("BINANCE_TESTNET", "true")

        with pytest.raises(RuntimeError):
            BinanceSpotClient()

        set_overlay(api_key="ovl-k", api_secret="ovl-s", testnet=False)
        c = BinanceSpotClient()
        assert c.api_key == "ovl-k"
        assert c.api_secret == "ovl-s"
        assert c.testnet is False
        assert "api.binance.com" in c.base_url

    def test_client_falls_back_to_env_with_no_overlay(self, patched_db, monkeypatch):
        from src.exchange.binance_spot_client import BinanceSpotClient

        monkeypatch.setenv("BINANCE_API_KEY", "env-fallback-k")
        monkeypatch.setenv("BINANCE_API_SECRET", "env-fallback-s")
        monkeypatch.setenv("BINANCE_TESTNET", "true")

        c = BinanceSpotClient()
        assert c.api_key == "env-fallback-k"
        assert c.testnet is True
        assert "testnet.binance.vision" in c.base_url


# ============================== /admin/binance-keys ==========================


class TestAdminBinanceKeysAPI:
    def test_admin_endpoints_reject_unauth(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        r = client.get("/admin/binance-keys")
        assert r.status_code == 401

    def test_admin_token_auth_works(self, client):
        r = client.get(
            "/admin/binance-keys",
            headers={"X-Admin-Token": "test-admin-token"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert "effective_api_key_masked" in body

    def test_admin_token_wrong_value_rejected(self, client):
        r = client.get(
            "/admin/binance-keys",
            headers={"X-Admin-Token": "wrong-token"},
        )
        assert r.status_code == 401

    def test_put_saves_overlay(self, client, monkeypatch):
        r = client.put(
            "/admin/binance-keys",
            headers={"X-Admin-Token": "test-admin-token"},
            json={"api_key": "abcd1234efgh5678", "api_secret": "topsecret", "testnet": False},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["overlay_present"] is True
        assert body["effective_testnet"] is False
        # Secret never returned in clear.
        assert "topsecret" not in r.text

        r2 = client.get(
            "/admin/binance-keys",
            headers={"X-Admin-Token": "test-admin-token"},
        )
        body2 = r2.json()
        assert body2["overlay_api_secret_set"] is True
        assert body2["effective_api_secret_set"] is True
        assert body2["effective_api_key_masked"].startswith("abcd")

    def test_put_empty_body_rejected(self, client):
        r = client.put(
            "/admin/binance-keys",
            headers={"X-Admin-Token": "test-admin-token"},
            json={},
        )
        assert r.status_code == 400

    def test_delete_clears_overlay(self, client):
        client.put(
            "/admin/binance-keys",
            headers={"X-Admin-Token": "test-admin-token"},
            json={"api_key": "k", "api_secret": "s", "testnet": True},
        )
        r = client.delete(
            "/admin/binance-keys/override",
            headers={"X-Admin-Token": "test-admin-token"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["overlay_present"] is False

    def test_verify_missing_keys_returns_missing_stage(self, client, monkeypatch):
        monkeypatch.delenv("BINANCE_API_KEY", raising=False)
        monkeypatch.delenv("BINANCE_API_SECRET", raising=False)
        # No overlay configured either.
        r = client.post(
            "/admin/binance-keys/verify",
            headers={"X-Admin-Token": "test-admin-token"},
            json={},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False
        assert body["stage"] == "missing_keys"

    def test_verify_network_error_handled(self, client, monkeypatch):
        """Force the verify call to a host that does not exist — no crash."""
        import src.api.routes_admin as rad

        def _bad_call(api_key, api_secret, testnet):
            return {
                "ok": False,
                "stage": "network",
                "error": "Name or service not known",
                "base_url": "https://nope.invalid",
            }

        monkeypatch.setattr(rad, "_try_signed_account_call", _bad_call)
        r = client.post(
            "/admin/binance-keys/verify",
            headers={"X-Admin-Token": "test-admin-token"},
            json={"api_key": "x", "api_secret": "y", "testnet": True},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False
        assert body["stage"] == "network"


# ============================== /safety/live-readiness =======================


class TestLiveReadinessEndpoint:
    def test_blocks_when_paper_mode_or_testnet(self, client, monkeypatch):
        monkeypatch.setenv("BINANCE_API_KEY", "k")
        monkeypatch.setenv("BINANCE_API_SECRET", "s")
        monkeypatch.setenv("BINANCE_TESTNET", "true")
        # Reset persistence
        from src.execution.mode import clear_execution_mode_override

        clear_execution_mode_override()
        r = client.get("/safety/live-readiness")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["ready_for_live_capital"] is False
        # Either testnet or non-live mode should be in the snapshot.
        modes = body["snapshot"]["execution_mode"]["effective_mode"]
        assert modes in ("paper", "shadow", "live")

    def test_blocked_when_kill_switch_engaged(self, client, monkeypatch):
        monkeypatch.setenv("BINANCE_API_KEY", "k")
        monkeypatch.setenv("BINANCE_API_SECRET", "s")
        monkeypatch.setenv("BINANCE_TESTNET", "false")
        ks.engage("test-block", by="pytest")
        try:
            r = client.get("/safety/live-readiness")
            body = r.json()
            assert body["ready_for_live_capital"] is False
            assert "kill_switch_released" in body["blocking_checks"]
        finally:
            ks.release("cleanup", by="pytest")

    def test_passes_when_everything_set(self, client, patched_db, monkeypatch):
        """Synthesize a fully-ready state and confirm the gate flips green."""
        from src.execution.mode import ExecutionMode, set_execution_mode
        from src.exchange.runtime_keys import set_overlay
        from src.db.models import AppSetting
        from src.db.session import SessionLocal

        monkeypatch.delenv("BINANCE_API_KEY", raising=False)
        monkeypatch.delenv("BINANCE_API_SECRET", raising=False)
        monkeypatch.setenv("SECRETS_ENCRYPTION_KEY", "x" * 32)

        set_overlay(api_key="live-k", api_secret="live-s", testnet=False)
        set_execution_mode(ExecutionMode.LIVE, changed_by="pytest", reason="test")

        # Scheduler flag — purely informational, but flip it to true for completeness.
        db = SessionLocal()
        try:
            row = AppSetting(key="LIVE_SCHEDULER_ENABLED", value="true")
            db.add(row)
            db.commit()
        finally:
            db.close()

        r = client.get("/safety/live-readiness")
        body = r.json()
        assert body["ok"] is True
        assert body["ready_for_live_capital"] is True
        assert body["blocking_checks"] == []
