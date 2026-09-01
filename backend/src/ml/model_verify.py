"""Verify model weights + scaler.json + meta.json on disk (production gate)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from src.ml.model_loader import find_weight_artifact_in_dir


def check_model_artifacts(model_dir: Path) -> Dict[str, Any]:
    """Return existence flags + ok if weights + scaler + meta exist."""
    d = Path(model_dir).resolve()
    weight = find_weight_artifact_in_dir(d)
    scaler = d / "scaler.json"
    meta = d / "meta.json"
    has_weights = weight is not None
    return {
        "model_dir": str(d),
        "model_keras": has_weights,
        "model_artifact_path": str(weight) if weight else None,
        "scaler_json": scaler.is_file(),
        "meta_json": meta.is_file(),
        "all_present": has_weights and scaler.is_file() and meta.is_file(),
    }
