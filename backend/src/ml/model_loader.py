"""Resolve Keras / SavedModel artifacts under models/<SYMBOL>_<timeframe> or any model dir."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import tensorflow as tf
except Exception as exc:  # pragma: no cover
    tf = None
    TF_IMPORT_ERROR = str(exc)
else:
    TF_IMPORT_ERROR = None

# src/ml/model_loader.py -> parents[2] = project root (bot new backend)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODELS_ROOT = PROJECT_ROOT / "models"

SUPPORTED_MODEL_FILES = ("model.keras", "model.h5")
SUPPORTED_MODEL_DIRS = ("model_keras", "saved_model")


class ModelLoadError(RuntimeError):
    pass


def find_weight_artifact_in_dir(resolved_dir: Path) -> Optional[Path]:
    """First existing weight file or SavedModel-style directory under resolved_dir."""
    d = Path(resolved_dir).resolve()
    if not d.is_dir():
        return None
    for name in SUPPORTED_MODEL_FILES:
        p = d / name
        if p.is_file():
            return p
    for name in SUPPORTED_MODEL_DIRS:
        p = d / name
        if p.is_dir():
            return p
    return None


def resolve_model_artifact(symbol: str, timeframe: str) -> Dict[str, Any]:
    sym = symbol.upper().strip()
    tfm = timeframe.strip()
    resolved_dir = MODELS_ROOT / f"{sym}_{tfm}"

    candidates: List[Path] = []
    for name in SUPPORTED_MODEL_FILES:
        candidates.append(resolved_dir / name)
    for name in SUPPORTED_MODEL_DIRS:
        candidates.append(resolved_dir / name)

    hit = find_weight_artifact_in_dir(resolved_dir)
    if hit is not None:
        return {
            "ok": True,
            "symbol": sym,
            "timeframe": tfm,
            "resolved_dir": str(resolved_dir),
            "artifact_path": str(hit),
            "artifact_type": "directory" if hit.is_dir() else "file",
        }

    return {
        "ok": False,
        "symbol": sym,
        "timeframe": tfm,
        "resolved_dir": str(resolved_dir),
        "checked_candidates": [str(p) for p in candidates],
        "error": "No supported model artifact found",
    }


def load_keras_model(symbol: str, timeframe: str):
    """Load tf.keras model only (no scaler). Used for smoke tests if needed."""
    if tf is None:
        raise ModelLoadError(f"TensorFlow import failed: {TF_IMPORT_ERROR}")
    artifact = resolve_model_artifact(symbol, timeframe)
    if not artifact["ok"]:
        raise ModelLoadError(
            f"Model artifact not found for {symbol}_{timeframe}. "
            f"dir={artifact['resolved_dir']} checked={artifact.get('checked_candidates', [])}"
        )
    model = tf.keras.models.load_model(artifact["artifact_path"])
    return model, artifact
