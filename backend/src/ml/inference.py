from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Union

import numpy as np
import pandas as pd

from src.ml.exceptions import (
    MlFeatureMismatch,
    MlInsufficientRows,
    MlModelNotFound,
    MlRuntimeError,
)
from src.ml.features import FEATURE_COLUMNS_LEGACY, select_features
from src.ml.model_loader import find_weight_artifact_in_dir, ModelLoadError

_CLASSES = ["SELL", "HOLD", "BUY"]


def _import_tensorflow():
    """Lazy import so app starts without TensorFlow when ML_ENABLED=false."""
    try:
        import tensorflow as tf

        return tf
    except ImportError as e:
        raise ImportError(
            "TensorFlow is required for ML inference. Install with: pip install -r requirements-ml.txt "
            "(Use Python 3.11 or 3.12; TensorFlow does not support 3.14 yet)."
        ) from e


def validate_model_package(model_dir: Union[str, Path]) -> Dict[str, Any]:
    """Verify artifacts and consistency (scaler / meta / Keras input). Raises on failure."""
    d = Path(model_dir).resolve()
    keras_p = d / "model.keras"
    scaler_p = d / "scaler.json"
    meta_p = d / "meta.json"
    if not keras_p.is_file():
        raise MlModelNotFound(f"missing model.keras under {d}")
    if not scaler_p.is_file():
        raise MlModelNotFound(f"missing scaler.json under {d}")
    if not meta_p.is_file():
        raise MlModelNotFound(f"missing meta.json under {d}")

    scaler = json.loads(scaler_p.read_text())
    mean = np.asarray(scaler.get("mean"), dtype=np.float64)
    scale = np.asarray(scaler.get("scale"), dtype=np.float64)
    if mean.ndim != 1 or scale.ndim != 1:
        raise MlFeatureMismatch("scaler mean/scale must be 1-D arrays")
    if mean.size != scale.size:
        raise MlFeatureMismatch(
            f"scaler mean length {mean.size} != scale length {scale.size}"
        )

    meta = json.loads(meta_p.read_text())
    lookback = int(meta["lookback"])
    feature_columns = meta.get("feature_columns")
    if not feature_columns:
        feature_columns = list(FEATURE_COLUMNS_LEGACY)
    n_features = int(meta.get("n_features", len(feature_columns)))
    if len(feature_columns) != n_features:
        raise MlFeatureMismatch(
            f"meta feature_columns len {len(feature_columns)} != n_features {n_features}"
        )
    if mean.size != n_features:
        raise MlFeatureMismatch(
            f"scaler length {mean.size} != meta n_features {n_features}"
        )

    tf = _import_tensorflow()
    model = tf.keras.models.load_model(keras_p)
    inp = model.input_shape
    if inp is not None and len(inp) >= 3:
        t_in = inp[1]
        f_in = inp[2]
        if t_in is not None and int(t_in) != lookback:
            raise MlFeatureMismatch(
                f"model input time steps {int(t_in)} != meta lookback {lookback}"
            )
        if f_in is not None and int(f_in) != n_features:
            raise MlFeatureMismatch(
                f"model input features {int(f_in)} != meta n_features {n_features}"
            )

    return {
        "model_dir": str(d),
        "lookback": lookback,
        "n_features": n_features,
        "feature_columns": feature_columns,
    }


def runtime_health(model_dir: str) -> Dict[str, Any]:
    """Lightweight readiness probe for ops (uses validate_model_package)."""
    try:
        validate_model_package(model_dir)
        return {"ready": True, "error": None}
    except Exception as e:
        return {"ready": False, "error": str(e)[:1000]}


class LstmInfer:
    def __init__(self, model_dir: str):
        validate_model_package(model_dir)
        tf = _import_tensorflow()
        self.model_dir = Path(model_dir).resolve()
        weight = find_weight_artifact_in_dir(self.model_dir)
        if weight is None:
            checked = [str(self.model_dir / n) for n in ("model.keras", "model.h5")]
            checked += [str(self.model_dir / n) for n in ("model_keras", "saved_model")]
            raise ModelLoadError(
                f"No model.keras / model.h5 / model_keras / saved_model under {self.model_dir}. "
                f"Checked: {checked}"
            )
        self.model = tf.keras.models.load_model(str(weight))
        self._weight_path = weight

        scaler = json.loads((self.model_dir / "scaler.json").read_text())
        self.mean = np.asarray(scaler["mean"], dtype=np.float32)
        self.scale = np.asarray(scaler["scale"], dtype=np.float32)

        meta = json.loads((self.model_dir / "meta.json").read_text())
        self.lookback = int(meta["lookback"])
        self.feature_columns = meta.get("feature_columns")
        if not self.feature_columns:
            self.feature_columns = list(FEATURE_COLUMNS_LEGACY)
        self.n_features = int(meta.get("n_features", len(self.feature_columns)))
        if int(self.mean.size) != int(self.scale.size):
            raise MlFeatureMismatch(
                f"scaler mean length {self.mean.size} != scale length {self.scale.size}"
            )
        if len(self.feature_columns) != int(self.n_features):
            raise MlFeatureMismatch(
                f"feature_columns len {len(self.feature_columns)} != n_features {self.n_features}"
            )

    def _scale(self, X: np.ndarray) -> np.ndarray:
        return (X - self.mean) / self.scale

    def predict_window(self, window_df: pd.DataFrame) -> dict:
        validate_window(window_df, self)
        feats = select_features(window_df, self.feature_columns)
        last = feats.tail(self.lookback).to_numpy(dtype=np.float32)
        last = self._scale(last)
        if not np.isfinite(last).all():
            raise MlRuntimeError("scaled inference window contains NaN or Inf")
        X = last.reshape(1, self.lookback, self.n_features)

        probs = self.model.predict(X, verbose=0)[0]  # (3,)
        idx = int(np.argmax(probs))
        out = {
            "down": float(probs[0]),
            "hold": float(probs[1]),
            "up": float(probs[2]),
            "signal": _CLASSES[idx],
            "confidence": float(probs[idx]),
        }
        try:
            from src.core.ml_runtime_state import record_inference

            record_inference(
                action=out["signal"],
                confidence=out["confidence"],
                prediction=f"{out['signal']}:{out['confidence']:.4f}",
                features_shape=X.shape,
            )
        except Exception:
            pass
        return out


def validate_window(window_df: pd.DataFrame, infer: LstmInfer) -> None:
    """Strict checks before forward pass — raises on invalid input."""
    feats = select_features(window_df, infer.feature_columns)
    if len(feats) < infer.lookback:
        raise MlInsufficientRows(
            f"need at least {infer.lookback} rows after feature select, got {len(feats)}"
        )
    if int(feats.shape[1]) != int(infer.n_features):
        raise MlFeatureMismatch(
            f"window feature columns count {feats.shape[1]} != model n_features {infer.n_features}"
        )
    last = feats.tail(infer.lookback)
    arr = last.to_numpy(dtype=np.float64)
    if not np.isfinite(arr).all():
        raise MlRuntimeError("window contains NaN or Inf after feature selection")


_cache: dict[str, LstmInfer] = {}


def get_infer(model_dir: str) -> LstmInfer:
    key = str(Path(model_dir).resolve())
    infer = _cache.get(key)
    if infer is None:
        infer = LstmInfer(key)
        _cache[key] = infer
    return infer


def clear_infer_cache() -> None:
    _cache.clear()
