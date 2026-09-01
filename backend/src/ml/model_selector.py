from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from src.ml.model_loader import find_weight_artifact_in_dir


def _repo_root() -> Path:
    # src/ml/model_selector.py -> repo root is parents[2]
    return Path(__file__).resolve().parents[2]


def normalize_timeframe(timeframe: str) -> str:
    """Canonical timeframe for directory keys (Binance-style: 5m, 1h, etc.)."""
    return timeframe.strip().lower()


def resolve_model_selection(
    base_model_dir: str,
    symbol: str,
    timeframe: str,
    version: Optional[str] = None,
) -> Dict[str, object]:
    """Resolve **exact** symbol + timeframe model directory only (no generic fallback).

    Expected on-disk layout (examples):
    - ``ML_MODEL_DIR=models`` → ``models/BTCUSDT_5m/``
    - ``ML_MODEL_DIR=models/BTCUSDT_5m`` → that directory must be named ``BTCUSDT_5m``
    - With ``ML_MODEL_VERSION=v1`` → ``<repo>/models/v1/BTCUSDT_5m/`` (or sibling of base)

    Returns a structured dict; ``fallback_used`` is always False (legacy permissive
    selection removed).
    """
    norm_symbol = symbol.upper().strip()
    norm_tf = normalize_timeframe(timeframe)
    model_key = f"{norm_symbol}_{norm_tf}"

    base_dir = Path(base_model_dir).resolve()
    model_version = version.strip() if version else ""

    exact_path: Optional[Path] = None
    exact_match_exists = False

    if model_version:
        project_version_dir = _repo_root() / "models" / model_version
        sibling_version_dir = base_dir.parent / model_version
        if project_version_dir.is_dir():
            version_dir = project_version_dir
        elif sibling_version_dir.is_dir():
            version_dir = sibling_version_dir
        else:
            version_dir = project_version_dir
        cand = version_dir / model_key
        if cand.is_dir():
            exact_path = cand
            exact_match_exists = True
    else:
        if base_dir.name == model_key:
            exact_path = base_dir
            exact_match_exists = True
        else:
            cand = base_dir / model_key
            if cand.is_dir():
                exact_path = cand
                exact_match_exists = True

    if exact_path is None:
        # Expected path for diagnostics (no silent pick of a parent folder model)
        if model_version:
            vd = _repo_root() / "models" / model_version
            expected = vd / model_key
        else:
            expected = base_dir / model_key
        return {
            "model_dir": str(expected),
            "exact_match_exists": False,
            "fallback_used": False,
            "artifact_exists": False,
            "runtime_eligible": False,
            "reason": f"no_exact_model_dir_for_key:{model_key}",
            # legacy keys for callers still logging
            "symbol": norm_symbol,
            "timeframe": norm_tf,
            "model_version": model_version or base_dir.name,
            "model_name": "",
            "model_key": model_key,
            "model_exists": False,
            "specific_match": False,
            "artifact_path": None,
        }

    weight_path = find_weight_artifact_in_dir(exact_path)
    weights_ok = weight_path is not None
    scaler_ok = (exact_path / "scaler.json").is_file()
    meta_ok = (exact_path / "meta.json").is_file()
    artifact_exists = weights_ok and scaler_ok and meta_ok

    reason = "ok"
    if not weights_ok or not scaler_ok or not meta_ok:
        missing = []
        if not weights_ok:
            missing.append("model_weights")
        if not scaler_ok:
            missing.append("scaler.json")
        if not meta_ok:
            missing.append("meta.json")
        reason = f"missing_artifacts:{','.join(missing)}"

    runtime_eligible = bool(exact_match_exists and artifact_exists)
    if not runtime_eligible and reason == "ok":
        reason = "artifacts_incomplete"

    return {
        "model_dir": str(exact_path),
        "exact_match_exists": exact_match_exists,
        "fallback_used": False,
        "artifact_exists": artifact_exists,
        "runtime_eligible": runtime_eligible,
        "reason": reason,
        "symbol": norm_symbol,
        "timeframe": norm_tf,
        "model_version": model_version or base_dir.name,
        "model_name": exact_path.name,
        "model_key": model_key,
        "model_exists": weights_ok,
        "specific_match": exact_match_exists,
        "artifact_path": str(weight_path) if weight_path else None,
    }
