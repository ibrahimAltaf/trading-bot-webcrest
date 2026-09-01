"""Single source of truth for ML observability (audits /status + /exchange)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

ML_STATE: Dict[str, Any] = {
    "model_loaded": False,
    "model_symbol": None,
    "model_timeframe": None,
    "model_artifact_path": None,
    "last_prediction": None,
    "last_action": None,
    "last_confidence": None,
    "last_features_shape": None,
    "last_used_at": None,
    "inference_count": 0,
    "last_error": None,
}


def set_model_loaded(symbol: str, timeframe: str, artifact_path: str) -> None:
    ML_STATE.update(
        {
            "model_loaded": True,
            "model_symbol": symbol,
            "model_timeframe": timeframe,
            "model_artifact_path": artifact_path,
            "last_error": None,
        }
    )


def set_model_error(error: str) -> None:
    ML_STATE.update({"model_loaded": False, "last_error": error})


def record_inference(
    action: str,
    confidence: float,
    prediction: Any,
    features_shape: Any,
) -> None:
    ML_STATE["last_prediction"] = str(prediction)
    ML_STATE["last_action"] = action
    ML_STATE["last_confidence"] = float(confidence)
    ML_STATE["last_features_shape"] = str(features_shape)
    ML_STATE["last_used_at"] = datetime.utcnow().isoformat()
    ML_STATE["inference_count"] = int(ML_STATE.get("inference_count", 0)) + 1
    ML_STATE["last_error"] = None


def get_ml_state() -> Dict[str, Any]:
    return dict(ML_STATE)
