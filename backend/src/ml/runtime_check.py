"""Validate ML inference prerequisites (features + one forward pass)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

from src.ml.feature_columns import FEATURE_COLUMNS_PRODUCTION
from src.ml.features import select_features


def feature_columns_valid(df: pd.DataFrame) -> bool:
    missing = [c for c in FEATURE_COLUMNS_PRODUCTION if c not in df.columns]
    return len(missing) == 0


def inference_smoke_test(ml_infer: Any, df: pd.DataFrame) -> Dict[str, Any]:
    """Returns inference_working + error string."""
    out: Dict[str, Any] = {"inference_working": False, "error": None}
    try:
        if not feature_columns_valid(df):
            out["error"] = "missing_feature_columns"
            return out
        _ = ml_infer.predict_window(df)
        out["inference_working"] = True
    except Exception as e:
        out["error"] = str(e)[:500]
    return out


def validate_symbol_ml_runtime(
    symbol: str,
    timeframe: str,
    base_model_dir: str,
    version: Optional[str] = None,
    load_model: bool = True,
) -> Dict[str, Any]:
    """Validate ML readiness for a single symbol/timeframe.

    Returns a dict with: symbol, timeframe, model_exists, specific_match,
    tensorflow_ok, model_load_ok, ready, reason, error.
    """
    from src.ml.model_selector import resolve_model_selection

    ctx = resolve_model_selection(
        base_model_dir=base_model_dir,
        symbol=symbol,
        timeframe=timeframe,
        version=version,
    )
    artifact_ok = bool(ctx.get("artifact_exists"))
    exact_ok = bool(ctx.get("exact_match_exists"))
    # Legacy field names (tests / older callers): "model" = complete artifacts on exact path
    model_exists = artifact_ok
    specific_match = exact_ok

    out: Dict[str, Any] = {
        "symbol": ctx["symbol"],
        "timeframe": ctx["timeframe"],
        "model_dir": ctx["model_dir"],
        "model_key": ctx["model_key"],
        "model_version": ctx.get("model_version", ""),
        "model_exists": model_exists,
        "specific_match": specific_match,
        "tensorflow_ok": False,
        "model_load_ok": False,
        "ready": False,
        "reason": None,
        "error": None,
    }
    if not exact_ok:
        out["reason"] = "model_artifacts_missing"
        return out
    if not artifact_ok:
        out["reason"] = "model_artifacts_missing"
        return out

    # Lightweight scheduler check: artifacts on disk + resolution OK; TensorFlow
    # load happens in execute_auto_trade or use load_model=true on /status/model-health/symbols.
    if not load_model:
        out["ready"] = True
        out["reason"] = "path_check_only"
        return out

    try:
        from src.ml.inference import get_infer

        infer = get_infer(str(ctx["model_dir"]))
        out["tensorflow_ok"] = True
        out["model_load_ok"] = infer is not None
        out["ready"] = infer is not None
    except ImportError:
        out["reason"] = "tensorflow_unavailable"
        out["error"] = "TensorFlow not installed"
    except Exception as e:
        out["tensorflow_ok"] = True  # import worked, load failed
        out["reason"] = "model_load_failed"
        out["error"] = str(e)[:500]

    return out


def validate_all_symbols_ml_runtime(
    symbols: List[str],
    timeframe: str,
    base_model_dir: str,
    version: Optional[str] = None,
    require_exact_match: bool = True,
    load_model: bool = True,
) -> Dict[str, Dict[str, Any]]:
    """Validate ML readiness for all symbols. Returns {symbol: health_dict}."""
    results: Dict[str, Dict[str, Any]] = {}
    for sym in symbols:
        health = validate_symbol_ml_runtime(
            symbol=sym,
            timeframe=timeframe,
            base_model_dir=base_model_dir,
            version=version,
            load_model=load_model,
        )
        results[sym] = health
    return results


def validate_features_or_raise(
    df: pd.DataFrame, columns: Optional[List[str]] = None
) -> None:
    """Strict path: no silent fallback."""
    from src.ml.feature_columns import FEATURE_COLUMNS_PRODUCTION

    select_features(df, columns or FEATURE_COLUMNS_PRODUCTION)
