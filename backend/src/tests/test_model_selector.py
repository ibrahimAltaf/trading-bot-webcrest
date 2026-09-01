from pathlib import Path

from src.ml.model_selector import resolve_model_selection


def _touch_artifacts(model_dir: Path) -> None:
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "model.keras").write_bytes(b"x")
    (model_dir / "scaler.json").write_text('{"mean":[0.0,0.0],"scale":[1.0,1.0]}')
    (model_dir / "meta.json").write_text(
        '{"lookback":2,"n_features":2,"feature_columns":["a","b"]}'
    )


def test_exact_symbol_timeframe_model_resolves(tmp_path: Path):
    base = tmp_path / "models" / "lstm_v1"
    specific = base / "BTCUSDT_1h"
    _touch_artifacts(specific)

    resolved = resolve_model_selection(
        base_model_dir=str(base),
        symbol="BTCUSDT",
        timeframe="1h",
        version=None,
    )

    assert resolved["exact_match_exists"] is True
    assert resolved["fallback_used"] is False
    assert resolved["artifact_exists"] is True
    assert resolved["runtime_eligible"] is True
    assert resolved["reason"] == "ok"
    assert resolved["model_name"] == "BTCUSDT_1h"


def test_no_permissive_fallback_when_exact_missing(tmp_path: Path):
    base = tmp_path / "models" / "lstm_v1"
    other = base / "BTCUSDT_1h"
    _touch_artifacts(other)

    resolved = resolve_model_selection(
        base_model_dir=str(base),
        symbol="ETHUSDT",
        timeframe="15m",
        version=None,
    )

    assert resolved["exact_match_exists"] is False
    assert resolved["fallback_used"] is False
    assert resolved["runtime_eligible"] is False
    assert resolved["artifact_exists"] is False


def test_version_override_prefers_repo_models_folder(tmp_path: Path, monkeypatch):
    base = tmp_path / "models" / "lstm_v1"
    other = base / "BTCUSDT_1h"
    _touch_artifacts(other)

    repo_root = tmp_path / "repo"
    module_file = repo_root / "src" / "ml" / "model_selector.py"
    module_file.parent.mkdir(parents=True, exist_ok=True)
    module_file.write_text("# test module path")

    version_specific = repo_root / "models" / "lstm_v2" / "ETHUSDT_1h"
    _touch_artifacts(version_specific)

    monkeypatch.setattr(
        "src.ml.model_selector._repo_root",
        lambda: repo_root,
    )

    resolved = resolve_model_selection(
        base_model_dir=str(base),
        symbol="ETHUSDT",
        timeframe="1h",
        version="lstm_v2",
    )

    assert resolved["model_version"] == "lstm_v2"
    assert resolved["model_name"] == "ETHUSDT_1h"
    assert resolved["exact_match_exists"] is True
    assert resolved["runtime_eligible"] is True
