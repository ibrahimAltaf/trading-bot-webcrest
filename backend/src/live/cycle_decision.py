"""
Production decision envelope: one structured object per cycle (audit / ML / rules).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import math


class RuntimeMode(str, Enum):
    """High-level ML execution posture for the cycle."""

    AI_ACTIVE = "ai_active"
    AI_DEGRADED = "ai_degraded"
    AI_DISABLED_BY_CONFIG = "ai_disabled_by_config"
    AI_UNAVAILABLE = "ai_unavailable"


class HoldKind(str, Enum):
    """HOLD must never be silent — always typed + reasons."""

    NONE = "none"
    MARKET_HOLD = "market_hold"
    SAFETY_HOLD = "safety_hold"
    FALLBACK_HOLD = "fallback_hold"
    RUNTIME_HOLD = "runtime_hold"
    BLOCKED_EXECUTION_HOLD = "blocked_execution_hold"


def resolve_runtime_mode(
    *,
    ml_enabled: bool,
    runtime_eligible: bool,
    model_loaded: bool,
    ml_signal_present: bool,
    ml_error: Optional[str],
) -> RuntimeMode:
    if not ml_enabled:
        return RuntimeMode.AI_DISABLED_BY_CONFIG
    if not runtime_eligible:
        return RuntimeMode.AI_UNAVAILABLE
    if ml_error or not model_loaded:
        return RuntimeMode.AI_DEGRADED
    if not ml_signal_present:
        return RuntimeMode.AI_DEGRADED
    return RuntimeMode.AI_ACTIVE


def fuse_confidence(
    rule_action: str,
    ml_action: Optional[str],
    rule_conf: float,
    ml_conf: Optional[float],
) -> float:
    """Dynamic final confidence — not a flat 0.5."""
    rc = max(0.0, min(1.0, float(rule_conf)))
    if ml_conf is None or ml_action is None:
        return round(rc, 4)
    mc = max(0.0, min(1.0, float(ml_conf)))
    agree = rule_action == ml_action
    if agree:
        out = min(1.0, 0.6 * rc + 0.4 * mc + 0.1)
    else:
        if mc >= 0.6:
            out = 0.35 * rc + 0.65 * mc
        else:
            out = 0.5 * rc + 0.5 * mc
    return round(max(0.0, min(1.0, out)), 4)


def evaluate_entry_gates(
    *,
    adx: float,
    rsi: float,
    atr_pct: float,
    ema_fast: float,
    ema_slow: float,
    adx_threshold: float,
    atr_vol_threshold: float,
    rsi_buy_min: float,
    rsi_buy_max: float,
    ml_ok: bool = True,
    risk_ok: bool = True,
) -> Dict[str, Any]:
    """Transparent gate booleans + which failed (for HOLD diagnostics)."""
    trend_ok = bool(adx >= adx_threshold * 0.65) or (ema_fast != ema_slow)
    momentum_ok = (rsi_buy_min - 5) <= rsi <= (rsi_buy_max + 5) or rsi < 35 or rsi > 65

    volatility_ok = atr_vol_threshold * 0.08 <= atr_pct <= atr_vol_threshold * 6.0
    gates = {
        "trend_ok": trend_ok,
        "momentum_ok": momentum_ok,
        "volatility_ok": volatility_ok,
        "ml_ok": ml_ok,
        "risk_ok": risk_ok,
    }
    failed = [k for k, v in gates.items() if not v]
    return {"gates": gates, "failed_gates": failed}


def classify_hold(
    *,
    final_action: str,
    gate_failed: List[str],
    ml_error: Optional[str],
    model_loaded: bool,
    ml_enabled: bool,
    runtime_eligible: bool,
    runtime_mode: RuntimeMode,
    execution_blocked_reason: Optional[str],
    cooldown: bool,
) -> Tuple[HoldKind, List[str]]:
    """HOLD must never be silent — always typed + reasons."""
    if final_action != "HOLD":
        return HoldKind.NONE, []

    if cooldown:
        return HoldKind.SAFETY_HOLD, ["cooldown_active"]
    if ml_enabled and not runtime_eligible:
        return HoldKind.RUNTIME_HOLD, ["runtime_not_eligible_exact_model_or_artifacts"]
    if ml_enabled and runtime_eligible and not model_loaded:
        return HoldKind.RUNTIME_HOLD, ["model_not_loaded_or_missing"]
    if ml_error:
        return HoldKind.RUNTIME_HOLD, [f"ml_error:{ml_error[:200]}"]
    if execution_blocked_reason:
        return HoldKind.BLOCKED_EXECUTION_HOLD, [execution_blocked_reason]
    if gate_failed:
        return HoldKind.MARKET_HOLD, [f"gate:{g}" for g in gate_failed]
    if not ml_enabled:
        return HoldKind.FALLBACK_HOLD, ["ml_disabled_rule_only_hold"]
    return HoldKind.MARKET_HOLD, ["no_rule_or_ml_trade_signal_this_bar"]


@dataclass
class CycleEnvelope:
    symbol: str
    timeframe: str
    runtime_mode: str
    rule_signal: str
    rule_confidence: float
    ml_signal: Optional[str]
    ml_confidence: Optional[float]
    model_loaded: bool
    feature_columns_present: bool
    combined_signal: str
    combined_confidence: float
    final_signal: str
    final_confidence: float
    final_source: str
    execution_eligible: bool
    block_reason: List[str]
    hold_kind: str
    gates: Dict[str, bool] = field(default_factory=dict)
    ml_error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "runtime_mode": self.runtime_mode,
            "rule_signal": self.rule_signal,
            "rule_confidence": self.rule_confidence,
            "ml_signal": self.ml_signal,
            "ml_confidence": self.ml_confidence,
            "model_loaded": self.model_loaded,
            "feature_columns_present": self.feature_columns_present,
            "combined_signal": self.combined_signal,
            "combined_confidence": self.combined_confidence,
            "final_signal": self.final_signal,
            "final_confidence": self.final_confidence,
            "final_source": self.final_source,
            "execution_eligible": self.execution_eligible,
            "block_reason": self.block_reason,
            "hold_kind": self.hold_kind,
            "gates": self.gates,
            "ml_error": self.ml_error,
        }


def build_envelope_from_engine_state(
    *,
    symbol: str,
    timeframe: str,
    runtime_mode: str,
    rule_signal: str,
    rule_confidence: float,
    ml_signal: Optional[str],
    ml_confidence: Optional[float],
    model_loaded: bool,
    feature_columns_present: bool,
    final_action: str,
    final_confidence: float,
    final_source: str,
    execution_eligible: bool,
    gate_eval: Dict[str, Any],
    ml_error: Optional[str],
    ml_enabled: bool,
    runtime_eligible: bool,
    cooldown_blocked: bool,
    execution_block_reason: Optional[str] = None,
) -> CycleEnvelope:
    """Assemble envelope after rule+ML fusion (single place for audit)."""
    combined_signal = final_action
    combined_conf = fuse_confidence(
        rule_signal,
        ml_signal,
        rule_confidence,
        ml_confidence,
    )
    fc = final_confidence
    if math.isfinite(fc):
        fc = float(fc)
    else:
        fc = combined_conf

    try:
        rm = RuntimeMode(runtime_mode)
    except ValueError:
        rm = RuntimeMode.AI_UNAVAILABLE

    failed_gates = list(gate_eval.get("failed_gates") or [])
    hold_kind, hold_reasons = classify_hold(
        final_action=final_action,
        gate_failed=failed_gates,
        ml_error=ml_error,
        model_loaded=model_loaded,
        ml_enabled=ml_enabled,
        runtime_eligible=runtime_eligible,
        runtime_mode=rm,
        execution_blocked_reason=execution_block_reason,
        cooldown=cooldown_blocked,
    )
    block = list(hold_reasons)
    if final_action == "HOLD" and hold_kind == HoldKind.MARKET_HOLD:
        block = hold_reasons + ["see_override_reason_and_strategy_reason"]

    return CycleEnvelope(
        symbol=symbol,
        timeframe=timeframe,
        runtime_mode=runtime_mode,
        rule_signal=rule_signal,
        rule_confidence=round(rule_confidence, 4),
        ml_signal=ml_signal,
        ml_confidence=round(ml_confidence, 4) if ml_confidence is not None else None,
        model_loaded=model_loaded,
        feature_columns_present=feature_columns_present,
        combined_signal=combined_signal,
        combined_confidence=combined_conf,
        final_signal=final_action,
        final_confidence=round(fc, 4),
        final_source=final_source,
        execution_eligible=execution_eligible,
        block_reason=block,
        hold_kind=hold_kind.value,
        gates=gate_eval.get("gates") or {},
        ml_error=ml_error,
    )
