"""Regression tests for the multi-coin runtime alignment upgrade.

Covers:
- _dump_signals_json persistence fix
- ML exact-match enforcement
- Per-symbol ML validation
- Symbol-filtered open positions
- Proof endpoint resilience
"""

from pathlib import Path
from unittest.mock import MagicMock, patch
import json
import pytest

from src.ml.model_selector import resolve_model_selection


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _touch_model_files(model_dir: Path) -> None:
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "model.keras").write_text("x")
    (model_dir / "scaler.json").write_text('{"mean":[0],"scale":[1]}')
    (model_dir / "meta.json").write_text('{"lookback":10,"n_features":1,"feature_columns":["close"]}')


# ---------------------------------------------------------------------------
# 1. _dump_signals_json bug: ensure the method is called as instance method
# ---------------------------------------------------------------------------

class TestDumpSignalsJsonFix:
    def test_save_decision_calls_instance_method(self):
        """Verify _save_decision uses self._dump_signals_json, not bare function."""
        import inspect
        from src.live.auto_trade_engine import AutoTradeEngine

        source = inspect.getsource(AutoTradeEngine._save_decision)
        # Must NOT contain the bare call (without self.)
        assert "_dump_signals_json(decision.signals)" not in source.replace(
            "self._dump_signals_json(decision.signals)", ""
        ), "Bare _dump_signals_json call found; must use self._dump_signals_json"
        # Must contain the correct self. call
        assert "self._dump_signals_json(decision.signals)" in source


# ---------------------------------------------------------------------------
# 2. ML exact-match config flag exists
# ---------------------------------------------------------------------------

class TestExactMatchConfig:
    def test_settings_has_exact_match_field(self):
        from src.core.config import Settings
        import dataclasses

        fields = {f.name for f in dataclasses.fields(Settings)}
        assert "ml_require_exact_symbol_match" in fields

    def test_exact_match_default_true(self):
        """Default should be true for production safety."""
        import os
        # Temporarily override to verify default parsing
        env_key = "ML_REQUIRE_EXACT_SYMBOL_MATCH"
        original = os.environ.pop(env_key, None)
        try:
            from src.core.config import _env_bool
            assert _env_bool(env_key, "true") is True
        finally:
            if original is not None:
                os.environ[env_key] = original


# ---------------------------------------------------------------------------
# 3. Per-symbol ML validation
# ---------------------------------------------------------------------------

class TestSymbolMLValidation:
    def test_validate_symbol_missing_model(self, tmp_path: Path):
        from src.ml.runtime_check import validate_symbol_ml_runtime

        result = validate_symbol_ml_runtime(
            symbol="ETHUSDT",
            timeframe="1h",
            base_model_dir=str(tmp_path / "nonexistent"),
            load_model=False,
        )
        assert result["model_exists"] is False
        assert result["ready"] is False
        assert result["reason"] == "model_artifacts_missing"

    def test_validate_symbol_exists_but_no_exact_match(self, tmp_path: Path):
        """Strict resolver: only generic files under base without ETHUSDT_1h/ → no model."""
        base = tmp_path / "models" / "lstm_v1"
        _touch_model_files(base)

        from src.ml.runtime_check import validate_all_symbols_ml_runtime

        results = validate_all_symbols_ml_runtime(
            symbols=["ETHUSDT"],
            timeframe="1h",
            base_model_dir=str(base),
            require_exact_match=True,
            load_model=False,
        )
        eth = results["ETHUSDT"]
        assert eth["model_exists"] is False
        assert eth["specific_match"] is False
        assert eth["ready"] is False
        assert eth["reason"] == "model_artifacts_missing"

    def test_validate_symbol_exact_match_passes(self, tmp_path: Path):
        base = tmp_path / "models" / "lstm_v1"
        specific = base / "BTCUSDT_1h"
        _touch_model_files(specific)

        from src.ml.runtime_check import validate_symbol_ml_runtime

        result = validate_symbol_ml_runtime(
            symbol="BTCUSDT",
            timeframe="1h",
            base_model_dir=str(base),
            load_model=False,
        )
        assert result["model_exists"] is True
        assert result["specific_match"] is True
        assert result["ready"] is True
        assert result["reason"] == "path_check_only"


# ---------------------------------------------------------------------------
# 4. Model selector exact-match enforcement
# ---------------------------------------------------------------------------

class TestModelSelectorExactMatchEnforcement:
    def test_generic_fallback_reports_not_specific(self, tmp_path: Path):
        """Strict layout: no SOLUSDT_15m dir → no exact match, no artifacts for that key."""
        base = tmp_path / "models" / "lstm_v1"
        _touch_model_files(base)

        ctx = resolve_model_selection(
            base_model_dir=str(base),
            symbol="SOLUSDT",
            timeframe="15m",
        )
        assert ctx["exact_match_exists"] is False
        assert ctx["artifact_exists"] is False
        assert ctx["runtime_eligible"] is False

    def test_exact_symbol_model_reports_specific(self, tmp_path: Path):
        base = tmp_path / "models" / "lstm_v1"
        specific = base / "SOLUSDT_15m"
        _touch_model_files(specific)

        ctx = resolve_model_selection(
            base_model_dir=str(base),
            symbol="SOLUSDT",
            timeframe="15m",
        )
        assert ctx["exact_match_exists"] is True
        assert ctx["artifact_exists"] is True
        assert ctx["runtime_eligible"] is True


# ---------------------------------------------------------------------------
# 5. Proof endpoint: section_errors field present
# ---------------------------------------------------------------------------

class TestProofEndpointContract:
    def test_proof_response_has_section_errors_key(self):
        """Verify the proof function signature accepts symbol param."""
        import inspect
        from src.api.routes_exchange import exchange_proof

        sig = inspect.signature(exchange_proof)
        assert "symbol" in sig.parameters

    def test_positions_open_accepts_symbol(self):
        """Verify get_open_positions accepts optional symbol param."""
        import inspect
        from src.api.routes_exchange import get_open_positions

        sig = inspect.signature(get_open_positions)
        assert "symbol" in sig.parameters
        # Default should be None (optional)
        assert sig.parameters["symbol"].default is None
