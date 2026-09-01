from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import json
import os

from sqlalchemy import desc
from sqlalchemy.orm import Session

from src.core.config import get_settings
from src.core.json_safe import finite_float, sanitize_for_json
from src.db.models import EventLog, Order, Position, Trade, TradingDecisionLog
from src.exchange.binance_spot_client import BinanceSpotClient
from src.risk.rules import CooldownState, RiskConfig
from src.features.indicators import add_all_indicators
from src.ml.dataset import append_ml_production_features
from src.live.adaptive_strategy import (
    AdaptiveStrategy,
    MarketRegime,
    TradingDecision,
    SignalAction,
)
from src.live.fully_adaptive_strategy import FullyAdaptiveStrategy
from src.ml.model_selector import resolve_model_selection
from src.live.cycle_decision import (
    RuntimeMode,
    build_envelope_from_engine_state,
    evaluate_entry_gates,
    fuse_confidence,
    resolve_runtime_mode,
)
from src.live.gate_stats import record_hold_kind
from src.ml.runtime_check import feature_columns_valid


class SignalType(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class TradeSignal:
    signal: SignalType
    confidence: float
    price: float
    timestamp: datetime
    source: str  # "rule_based" | "ml" | "combined" | "forced"
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class TradeResult:
    success: bool
    executed: bool
    signal: str
    reason: str
    # True when ML_STRICT aborted the cycle (persisted as action BLOCKED, not HOLD)
    blocked: bool = False

    order_id: Optional[str] = None
    price: Optional[float] = None
    quantity: Optional[float] = None
    balance_before: Optional[float] = None
    balance_after: Optional[float] = None
    position_id: Optional[int] = None

    exchange_status: Optional[str] = None
    executed_qty: Optional[float] = None
    cummulative_quote_qty: Optional[float] = None
    raw_order: Optional[Dict[str, Any]] = None


class AutoTradeEngine:
    """
    Live auto-trading engine:
    - Signal generation (rule-based + optional ML)
    - Position management
    - Risk checks
    - Market order execution (for deterministic Phase-1 demo)
    - Binance order status verification (GET /api/v3/order)
    - Database logging (EventLog + Order + Position)
    """

    def __init__(
        self,
        db: Session,
        client: Optional[BinanceSpotClient] = None,
        risk_config: Optional[RiskConfig] = None,
    ):
        self.db = db
        self.client = client or BinanceSpotClient()
        self.risk_config = risk_config or RiskConfig()
        self.settings = get_settings()
        self.cooldown = CooldownState()
        # Phase-2A: tri-mode resolution (paper / shadow / live) with runtime override.
        # Falls back to legacy PHASE1_PAPER_EXECUTION when no override / env is set.
        try:
            from src.execution.mode import get_execution_mode as _get_mode

            self.execution_mode = _get_mode().value
        except Exception:
            self.execution_mode = (
                "paper"
                if bool(getattr(self.settings, "phase1_paper_execution", False))
                else "live"
            )

        if getattr(self.settings, "fully_adaptive_engine", False):
            # Fully Adaptive Engine (dynamic params per bar)
            self.adaptive_strategy = FullyAdaptiveStrategy(self.settings)
        else:
            # Baseline adaptive strategy (static params from .env)
            strategy_config = {
                "adx_threshold": self.settings.adx_threshold,
                "atr_vol_threshold": self.settings.atr_vol_threshold,
                "ema_fast": self.settings.ema_fast,
                "ema_slow": self.settings.ema_slow,
                "rsi_len": self.settings.rsi_len,
                "rsi_buy_min": self.settings.rsi_buy_min,
                "rsi_buy_max": self.settings.rsi_buy_max,
                "rsi_take_profit": self.settings.rsi_take_profit,
                "bb_len": self.settings.bb_len,
                "bb_std": self.settings.bb_std,
                "rsi_range_buy": self.settings.rsi_range_buy,
                "rsi_range_sell": self.settings.rsi_range_sell,
                "max_risk_per_trade": self.settings.max_risk_per_trade,
                "stop_loss_atr_mult": self.settings.stop_loss_atr_mult,
                "take_profit_rr": self.settings.take_profit_rr,
                "relaxed_entry_for_testing": getattr(
                    self.settings, "relaxed_entry_for_testing", False
                ),
            }
            self.adaptive_strategy = AdaptiveStrategy(strategy_config)

        # ML inference (optional)
        self.ml_infer = None
        self.ml_enabled = bool(getattr(self.settings, "ml_enabled", False))
        self.ml_model_version = os.getenv("ML_MODEL_VERSION", "").strip() or None

        # Phase 2A: trigger provenance for this instance's cycle — a fresh
        # AutoTradeEngine is constructed per request/per scheduler cycle (see
        # scheduler/runner.py and routes_exchange.py), so instance state here is
        # safe (no cross-request sharing). Overwritten at the top of
        # execute_auto_trade(); this default only covers edge paths that never
        # call it directly.
        self._current_trigger: Dict[str, Any] = {
            "triggered_by": "api_manual",
            "cycle_id": None,
        }

    def _effective_thresholds(self, decision: TradingDecision) -> Dict[str, Any]:
        """Per-cycle thresholds actually in force this cycle.

        When FullyAdaptiveStrategy produced this decision, ``decision.signals["params"]``
        holds regime-adapted values (see fully_adaptive_strategy.py); otherwise the
        static .env-configured Settings values are used unchanged (adaptive engine
        off, or AdaptiveStrategy baseline). Stored on every decision as
        ``active_thresholds`` and returned by /exchange/decisions/recent — this is
        the numeric evidence trail external audits need to verify thresholds move
        with market regime, not just raw indicators (Saad validation, concern #3).
        """
        sig = decision.signals if isinstance(decision.signals, dict) else {}
        p = sig.get("params")
        p = p if isinstance(p, dict) else {}
        s = self.settings
        return {
            "adx_threshold": float(p.get("adx_threshold", s.adx_threshold)),
            "atr_vol_threshold": float(p.get("atr_vol_threshold", s.atr_vol_threshold)),
            "rsi_buy_min": float(p.get("rsi_buy_min", s.rsi_buy_min)),
            "rsi_buy_max": float(p.get("rsi_buy_max", s.rsi_buy_max)),
            "ml_absolute_min_confidence": float(
                p.get("ml_absolute_min_confidence", s.ml_absolute_min_confidence)
            ),
            "ml_min_trade_confidence": float(
                p.get("ml_min_trade_confidence", s.ml_min_trade_confidence)
            ),
            "rule_directional_min_confidence": float(
                p.get(
                    "rule_directional_min_confidence",
                    s.rule_directional_min_confidence,
                )
            ),
            "adaptive_posture": p.get("posture", "static"),
        }

    def _resolve_ml_context(self, symbol: str, timeframe: str) -> Dict[str, Any]:
        return resolve_model_selection(
            base_model_dir=self.settings.ml_model_dir,
            symbol=symbol,
            timeframe=timeframe,
            version=self.ml_model_version,
        )

    # ---------------------------
    # Logging / DB helpers
    # ---------------------------

    def _dump_signals_json(self, signals: Any) -> str:
        try:
            payload = sanitize_for_json(signals if isinstance(signals, dict) else {})
            return json.dumps(payload, allow_nan=False)
        except Exception as e:
            return json.dumps(
                {"error": "signals_serialization_failed", "detail": str(e)[:500]},
                allow_nan=False,
            )

    def _log_event(
        self,
        level: str,
        category: str,
        message: str,
        symbol: Optional[str] = None,
    ) -> None:
        log = EventLog(
            level=level,
            category=category,
            message=message,
            symbol=symbol,
            ts=datetime.utcnow(),
        )
        self.db.add(log)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def _resolve_local_order_id(
        self, exchange_order_id: Optional[Any]
    ) -> Optional[int]:
        """
        Convert Binance exchange orderId -> local DB Order.id (FK target).
        """
        if exchange_order_id is None:
            return None

        exchange_id = str(exchange_order_id).strip()
        if not exchange_id:
            return None

        row = (
            self.db.query(Order.id)
            .filter(Order.exchange_order_id == exchange_id)
            .order_by(Order.created_at.desc())
            .first()
        )
        if not row:
            return None

        return int(row[0])

    def _save_decision(
        self,
        decision: TradingDecision,
        symbol: str,
        timeframe: str,
        executed: bool = False,
        order_id: Optional[Any] = None,
    ) -> TradingDecisionLog:
        """
        Save trading decision to database for transparency/explainability.
        This is critical for dashboard display showing WHY decisions were made.
        """
        local_order_id = self._resolve_local_order_id(order_id)

        decision_log = TradingDecisionLog(
            action=decision.action.value,
            confidence=finite_float(decision.confidence, 0.0),
            symbol=symbol,
            timeframe=timeframe,
            regime=decision.regime.value,
            price=finite_float(decision.price, 0.0),
            ts=datetime.utcnow(),
            adx=finite_float(decision.adx, 0.0),
            ema_fast=finite_float(decision.ema_fast, 0.0),
            ema_slow=finite_float(decision.ema_slow, 0.0),
            rsi=finite_float(decision.rsi, 0.0),
            bb_upper=(
                finite_float(decision.bb_upper, 0.0)
                if decision.bb_upper is not None
                else None
            ),
            bb_lower=(
                finite_float(decision.bb_lower, 0.0)
                if decision.bb_lower is not None
                else None
            ),
            atr=finite_float(decision.atr, 0.0),
            entry_price=(
                finite_float(decision.entry_price, 0.0)
                if decision.entry_price is not None
                else None
            ),
            stop_loss=(
                finite_float(decision.stop_loss, 0.0)
                if decision.stop_loss is not None
                else None
            ),
            take_profit=(
                finite_float(decision.take_profit, 0.0)
                if decision.take_profit is not None
                else None
            ),
            risk_reward=(
                finite_float(decision.risk_reward, 0.0)
                if decision.risk_reward is not None
                else None
            ),
            reason=(decision.reason or "")[:20000],
            signals_json=self._dump_signals_json(decision.signals),
            executed=executed,
            order_id=local_order_id,
            triggered_by=self._current_trigger.get("triggered_by"),
            cycle_id=self._current_trigger.get("cycle_id"),
        )
        self.db.add(decision_log)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(decision_log)
        return decision_log

    def _persist_engine_exception_audit(
        self,
        *,
        symbol: str,
        timeframe: str,
        exc: BaseException,
    ) -> None:
        """Persist a HOLD decision when the engine raises so audits never miss a cycle."""
        err_msg = str(exc)[:8000]
        sig: Dict[str, Any] = {
            "final_source": "engine_exception",
            "rule_signal": None,
            "ml_signal": None,
            "ml_confidence": None,
            "combined_signal": "HOLD",
            "override_reason": f"Unexpected engine exception: {type(exc).__name__}",
            "runtime_mode": RuntimeMode.AI_DEGRADED.value,
            "cycle_debug": {
                "symbol": symbol,
                "timeframe": timeframe,
                "runtime_mode": RuntimeMode.AI_DEGRADED.value,
                "rule_signal": None,
                "rule_confidence": None,
                "ml_signal": None,
                "ml_confidence": None,
                "combined_signal": "HOLD",
                "final_signal": "HOLD",
                "final_source": "engine_exception",
                "execution_eligible": False,
                "hold_kind": "runtime_hold",
                "block_reasons": [
                    f"exception_type:{type(exc).__name__}",
                    err_msg[:2000],
                ],
            },
            "engine_exception": {
                "type": type(exc).__name__,
                "message": err_msg,
            },
        }
        decision = TradingDecision(
            action=SignalAction.HOLD,
            confidence=0.0,
            regime=MarketRegime.UNKNOWN,
            price=0.0,
            timestamp=datetime.utcnow().isoformat(),
            adx=0.0,
            ema_fast=0.0,
            ema_slow=0.0,
            rsi=0.0,
            bb_upper=None,
            bb_middle=None,
            bb_lower=None,
            atr=0.0,
            atr_pct=0.0,
            entry_price=None,
            stop_loss=None,
            take_profit=None,
            risk_reward=None,
            position_size_pct=0.0,
            reason=f"Engine exception ({type(exc).__name__}): {err_msg[:19000]}",
            signals=sig,
        )
        self._attach_confidence_audit_fields(
            decision,
            rule_confidence_before_ml=None,
        )
        self._save_decision(
            decision, symbol=symbol, timeframe=timeframe, executed=False
        )

    def _enrich_cycle_debug(
        self,
        decision: TradingDecision,
        *,
        symbol: str,
        timeframe: str,
        runtime_mode: str,
        rule_signal_value: str,
        ml_signal_value: Optional[str],
        rule_confidence_before_ml: float,
        has_open_position: bool,
    ) -> None:
        """Structured audit: cycle_debug (envelope fills hold_kind / block_reasons)."""
        sig = decision.signals if isinstance(decision.signals, dict) else {}
        ml_pred = sig.get("ml_prediction") or {}
        ml_conf = ml_pred.get("confidence")
        if ml_conf is not None:
            try:
                ml_conf = float(ml_conf)
            except Exception:
                ml_conf = None
        final_src = str(sig.get("final_source", "rule_only"))
        action = decision.action.value

        block_reasons: List[str] = []
        if action == "HOLD":
            ov = sig.get("override_reason")
            if ov:
                block_reasons.append(str(ov))
            block_reasons.append(str(decision.reason or "")[:800])
            if sig.get("ml_load_error"):
                block_reasons.append(f"ml_load_error: {sig['ml_load_error']}")
        elif action == "BUY" and has_open_position:
            block_reasons.append("BUY signal ignored: open position exists for symbol")
        elif action == "SELL" and not has_open_position:
            block_reasons.append("SELL signal ignored: no open position")

        execution_eligible = (action == "BUY" and not has_open_position) or (
            action == "SELL" and has_open_position
        )

        combined = sig.get("combined_signal") or action
        sig["cycle_debug"] = {
            "symbol": symbol,
            "timeframe": timeframe,
            "runtime_mode": runtime_mode,
            "rule_signal": rule_signal_value,
            "rule_confidence": round(finite_float(rule_confidence_before_ml, 0.0), 4),
            "ml_signal": ml_signal_value,
            "ml_confidence": (
                round(finite_float(ml_conf, 0.0), 4) if ml_conf is not None else None
            ),
            "combined_signal": combined,
            "final_signal": action,
            "final_source": final_src,
            "hold_kind": None,
            "block_reasons": block_reasons,
            "execution_eligible": execution_eligible,
            "final_confidence": round(finite_float(decision.confidence, 0.0), 4),
            "has_open_position": has_open_position,
        }
        decision.signals = sig

    def _patch_cycle_execution_block(
        self, decision: TradingDecision, reason: str
    ) -> None:
        if not isinstance(decision.signals, dict):
            return
        cd = decision.signals.get("cycle_debug") or {}
        cd["hold_kind"] = "blocked_execution_hold"
        cd["execution_block_reason"] = reason
        decision.signals["cycle_debug"] = cd

    def _attach_cycle_envelope(
        self,
        decision: TradingDecision,
        *,
        symbol: str,
        timeframe: str,
        runtime_mode: str,
        runtime_eligible: bool,
        rule_signal_value: str,
        rule_confidence_before_ml: float,
        ml_signal_str: Optional[str],
        ml_conf: Optional[float],
        model_loaded: bool,
        feature_columns_present: bool,
        final_source: str,
        open_position: Optional[Position],
        gate_eval: Dict[str, Any],
        ml_error: Optional[str],
        cooldown_blocked: bool,
    ) -> None:
        sig = decision.signals if isinstance(decision.signals, dict) else {}
        cd = sig.get("cycle_debug") or {}
        exec_eligible = bool(cd.get("execution_eligible")) if cd else False
        env = build_envelope_from_engine_state(
            symbol=symbol,
            timeframe=timeframe,
            runtime_mode=runtime_mode,
            rule_signal=rule_signal_value,
            rule_confidence=rule_confidence_before_ml,
            ml_signal=ml_signal_str,
            ml_confidence=ml_conf,
            model_loaded=model_loaded,
            feature_columns_present=feature_columns_present,
            final_action=decision.action.value,
            final_confidence=float(decision.confidence),
            final_source=final_source,
            execution_eligible=exec_eligible,
            gate_eval=gate_eval,
            ml_error=ml_error
            or sig.get("ml_load_error")
            or sig.get("ml_prediction_error"),
            ml_enabled=self.ml_enabled,
            runtime_eligible=runtime_eligible,
            cooldown_blocked=cooldown_blocked,
            execution_block_reason=cd.get("execution_block_reason"),
        )
        sig["cycle_envelope"] = env.to_dict()
        cd["hold_kind"] = env.hold_kind
        cd["block_reasons"] = env.block_reason
        cd["runtime_mode"] = env.runtime_mode
        sig["cycle_debug"] = cd
        decision.signals = sig
        if env.final_signal == "HOLD" and env.hold_kind and env.hold_kind != "none":
            record_hold_kind(env.hold_kind)

    def _ml_strict_abort_trading_cycle(
        self,
        *,
        decision: TradingDecision,
        symbol: str,
        timeframe: str,
        rule_signal_value: str,
        rule_confidence_before_ml: float,
        current_price: float,
        df: Any,
        err: str,
        model_loaded: bool,
        ml_context: Dict[str, Any],
    ) -> TradeResult:
        """ML_STRICT: no silent rule-only path when ML pipeline is required.

        Persists action BLOCKED (not HOLD) so audits distinguish system failure from flat market HOLD.
        """
        decision.action = SignalAction.BLOCKED
        decision.confidence = 0.0
        if not ml_context.get("runtime_eligible"):
            decision.reason = f"AI runtime blocked: {err}"
        else:
            decision.reason = f"AI runtime blocked: {err}"
        # Canonical failure source (legacy dashboards may still search ml_strict_failure)
        decision.signals["final_source"] = "ml_runtime_failure"
        decision.signals["legacy_final_source"] = "ml_strict_failure"
        decision.signals["decision_status"] = "blocked"
        decision.signals["error_class"] = "ml_runtime_failure"
        decision.signals["combined_signal"] = "BLOCKED"
        decision.signals["rule_signal"] = rule_signal_value
        decision.signals["runtime_truth"] = {
            "ml_signal": decision.signals.get("ml_signal"),
            "ml_confidence": decision.signals.get("ml_confidence"),
            "final_source": "ml_runtime_failure",
            "blocked": True,
            "executed": False,
            "rule_signal": rule_signal_value,
        }
        self._apply_ml_audit_fields(
            decision,
            ml_context=ml_context,
            ml_out=None,
            ml_infer_present=model_loaded,
            rule_signal_value=rule_signal_value,
        )
        open_position = self._get_open_position(symbol)
        th = self._effective_thresholds(decision)
        decision.signals["active_thresholds"] = th
        gate_eval = evaluate_entry_gates(
            adx=float(decision.adx),
            rsi=float(decision.rsi),
            atr_pct=float(decision.atr_pct),
            ema_fast=float(decision.ema_fast),
            ema_slow=float(decision.ema_slow),
            adx_threshold=th["adx_threshold"],
            atr_vol_threshold=th["atr_vol_threshold"],
            rsi_buy_min=th["rsi_buy_min"],
            rsi_buy_max=th["rsi_buy_max"],
            ml_ok=False,
            risk_ok=True,
        )
        rt_mode = resolve_runtime_mode(
            ml_enabled=self.ml_enabled,
            runtime_eligible=bool(ml_context.get("runtime_eligible")),
            model_loaded=model_loaded,
            ml_signal_present=False,
            ml_error=err,
        ).value
        self._enrich_cycle_debug(
            decision,
            symbol=symbol,
            timeframe=timeframe,
            runtime_mode=rt_mode,
            rule_signal_value=rule_signal_value,
            ml_signal_value=None,
            rule_confidence_before_ml=rule_confidence_before_ml,
            has_open_position=open_position is not None,
        )
        cd_blk = decision.signals.setdefault("cycle_debug", {})
        if isinstance(cd_blk, dict):
            cd_blk["runtime_blocked"] = True
            cd_blk["block_reason"] = "ml_runtime_failure"
            cd_blk["final_signal"] = "BLOCKED"

        self._attach_cycle_envelope(
            decision,
            symbol=symbol,
            timeframe=timeframe,
            runtime_mode=rt_mode,
            runtime_eligible=bool(ml_context.get("runtime_eligible")),
            rule_signal_value=rule_signal_value,
            rule_confidence_before_ml=rule_confidence_before_ml,
            ml_signal_str=decision.signals.get("ml_signal"),
            ml_conf=decision.signals.get("ml_confidence"),
            model_loaded=model_loaded,
            feature_columns_present=feature_columns_valid(df),
            final_source="ml_runtime_failure",
            open_position=open_position,
            gate_eval=gate_eval,
            ml_error=err,
            cooldown_blocked=False,
        )
        self._attach_confidence_audit_fields(
            decision,
            rule_confidence_before_ml=rule_confidence_before_ml,
        )
        self._save_decision(decision, symbol, timeframe, executed=False)
        self._log_event(
            "ERROR",
            "ml",
            f"ML_STRICT abort: {err} (symbol={symbol} tf={timeframe})",
            symbol=symbol,
        )
        return TradeResult(
            success=False,
            executed=False,
            signal="BLOCKED",
            reason=decision.reason,
            price=current_price,
            blocked=True,
        )

    def _apply_ml_audit_fields(
        self,
        decision: TradingDecision,
        *,
        ml_context: Dict[str, Any],
        ml_out: Optional[TradeSignal],
        ml_infer_present: bool,
        rule_signal_value: str,
    ) -> None:
        """Always persist ml_signal, ml_confidence, ml_status, final_source for diagnostics."""
        sig = decision.signals if isinstance(decision.signals, dict) else {}
        ml_strict = bool(getattr(self.settings, "ml_strict", False))
        if not self.ml_enabled:
            sig["ml_signal"] = None
            sig["ml_confidence"] = None
            sig["ml_status"] = "ml_disabled"
            sig["final_source"] = sig.get("final_source", "rule_only_ml_disabled")
            decision.signals = sig
            return

        if not ml_context.get("runtime_eligible"):
            sig["ml_signal"] = None
            sig["ml_confidence"] = None
            sig["ml_status"] = "runtime_not_eligible"
            if not ml_strict:
                self._log_event(
                    "WARN",
                    "ml",
                    "ML_ENABLED but model not runtime_eligible for symbol/timeframe — rules-only path",
                    symbol=ml_context.get("symbol"),
                )
        elif not ml_infer_present:
            sig["ml_signal"] = None
            sig["ml_confidence"] = None
            sig["ml_status"] = "model_load_failed"
        elif ml_out is None:
            sig["ml_signal"] = None
            sig["ml_confidence"] = None
            sig["ml_status"] = "inference_failed"
        else:
            sig["ml_signal"] = ml_out.signal.value
            sig["ml_confidence"] = round(float(ml_out.confidence), 4)
            sig["ml_status"] = "ok"
            pred = sig.get("ml_prediction") or {}
            if not pred:
                ml_meta = ml_out.metadata or {}
                sig["ml_prediction"] = {
                    "signal": ml_out.signal.value,
                    "confidence": round(ml_out.confidence, 3),
                    "up": round(float(ml_meta.get("up", 0)), 3),
                    "hold": round(float(ml_meta.get("hold", 0)), 3),
                    "down": round(float(ml_meta.get("down", 0)), 3),
                }

        fs = str(sig.get("final_source", "rule_only"))
        if (
            self.ml_enabled
            and ml_out is not None
            and sig.get("ml_status") == "ok"
            and fs == "rule_only"
            and not ml_strict
        ):
            self._log_event(
                "WARN",
                "ml",
                f"ML did not change final decision (rules retained): rule={rule_signal_value} "
                f"vs ml={ml_out.signal.value} @ {ml_out.confidence:.2f}",
                symbol=ml_context.get("symbol"),
            )
        decision.signals = sig

    def _attach_confidence_audit_fields(
        self,
        decision: TradingDecision,
        *,
        rule_confidence_before_ml: Optional[float],
    ) -> None:
        sig = decision.signals if isinstance(decision.signals, dict) else {}
        sig["rule_confidence"] = (
            round(finite_float(rule_confidence_before_ml, 0.0), 4)
            if rule_confidence_before_ml is not None
            else None
        )
        sig["final_confidence"] = round(finite_float(decision.confidence, 0.0), 4)
        sig["confidence_source"] = str(sig.get("final_source") or "rule_only")

        cycle_debug = sig.get("cycle_debug")
        if isinstance(cycle_debug, dict):
            cycle_debug["rule_confidence"] = sig["rule_confidence"]
            cycle_debug["ml_confidence"] = sig.get("ml_confidence")
            cycle_debug["final_confidence"] = sig["final_confidence"]
            cycle_debug["confidence_source"] = sig["confidence_source"]

        cycle_envelope = sig.get("cycle_envelope")
        if isinstance(cycle_envelope, dict):
            cycle_envelope["rule_confidence"] = sig["rule_confidence"]
            cycle_envelope["ml_confidence"] = sig.get("ml_confidence")
            cycle_envelope["final_confidence"] = sig["final_confidence"]
            cycle_envelope["confidence_source"] = sig["confidence_source"]

        decision.signals = sig

    def _get_open_position(self, symbol: str) -> Optional[Position]:
        return (
            self.db.query(Position)
            .filter(
                Position.symbol == symbol,
                Position.is_open == True,  # noqa: E712
                Position.mode == self.execution_mode,
            )
            .first()
        )

    def _get_usdt_balance(self) -> float:
        if self.execution_mode == "paper":
            # Deterministic default balance for paper execution.
            try:
                return float(os.getenv("PAPER_USDT_BALANCE", "10000").strip())
            except Exception:
                return 10000.0
        account = self.client.account()
        usdt = next(
            (b for b in account.get("balances", []) if b.get("asset") == "USDT"),
            {"free": "0"},
        )
        return float(usdt.get("free", "0") or 0)

    @staticmethod
    def _shadow_fallback_balance_enabled() -> bool:
        raw = (os.getenv("SHADOW_USE_FALLBACK_BALANCE", "true") or "").strip().lower()
        return raw in ("1", "true", "yes", "on")

    @staticmethod
    def _shadow_fallback_usdt_amount() -> float:
        try:
            return float(
                os.getenv(
                    "SHADOW_USDT_BALANCE",
                    os.getenv("PAPER_USDT_BALANCE", "10000"),
                ).strip()
            )
        except Exception:
            return 10000.0

    def _get_shadow_sizing_balance(self) -> tuple[float, float, bool]:
        """
        Shadow sizing balance: prefer real exchange USDT; optional fallback when
        free USDT is zero so audits can still exercise shadow-* order IDs.
        Returns (sizing_balance, exchange_free_usdt, used_fallback).
        """
        exchange_free = float(self._get_usdt_balance())
        if exchange_free > 0:
            return exchange_free, exchange_free, False
        if not self._shadow_fallback_balance_enabled():
            return 0.0, exchange_free, False
        fallback = self._shadow_fallback_usdt_amount()
        return fallback, exchange_free, True

    def _create_position(
        self, symbol: str, entry_price: float, quantity: float, *, mode: Optional[str] = None
    ) -> Position:
        position = Position(
            mode=(mode or self.execution_mode),
            symbol=symbol,
            is_open=True,
            entry_price=entry_price,
            entry_qty=quantity,
            entry_ts=datetime.utcnow(),
        )
        self.db.add(position)
        self.db.commit()
        self.db.refresh(position)
        return position

    def _close_position(
        self, position: Position, exit_price: float, exit_qty: float
    ) -> None:
        position.is_open = False
        position.exit_price = exit_price
        position.exit_qty = exit_qty
        position.exit_ts = datetime.utcnow()

        # P&L
        position.pnl = (exit_price - position.entry_price) * exit_qty
        position.pnl_pct = (
            (exit_price - position.entry_price) / position.entry_price
        ) * 100

        self.db.commit()

    def _record_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        requested_price: float,
        order_response: Dict[str, Any],
        order_type: str,
        status: str,
        executed_price: Optional[float] = None,
        *,
        mode: Optional[str] = None,
        client_order_id: Optional[str] = None,
    ) -> Order:
        """
        Records an order in DB with REAL orderType + REAL status.
        Note: if your Order model doesn't have some fields, remove them accordingly.
        """
        # Phase 2A: prefer an explicit client_order_id arg, then any value the
        # exchange / simulator echoed back. Stored alongside exchange_order_id
        # for idempotency lookups across retries and process restarts.
        coid = (
            client_order_id
            or (order_response.get("clientOrderId") if isinstance(order_response, dict) else None)
        )
        o = Order(
            mode=(mode or self.execution_mode),
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            requested_price=requested_price,
            executed_price=executed_price,
            status=status,
            exchange_order_id=str(order_response.get("orderId", "")),
            client_order_id=str(coid) if coid else None,
            created_at=datetime.utcnow(),
            triggered_by=self._current_trigger.get("triggered_by"),
            cycle_id=self._current_trigger.get("cycle_id"),
        )
        self.db.add(o)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(o)
        return o

    def _record_trade(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        order_row: Optional[Order] = None,
        mode: Optional[str] = None,
    ) -> Optional[Trade]:
        try:
            t = Trade(
                mode=(mode or self.execution_mode),
                symbol=symbol,
                side=side,
                quantity=float(quantity),
                price=float(price),
                fee=None,
                fee_asset=None,
                order_id=(order_row.id if order_row is not None else None),
            )
            self.db.add(t)
            self.db.commit()
            self.db.refresh(t)
            return t
        except Exception:
            self.db.rollback()
            return None

    # ---------------------------
    # Signals
    # ---------------------------

    def _generate_rule_based_signal(self, df) -> TradeSignal:
        from src.backtest.engine import generate_signal

        last_row = df.iloc[-1]
        signal_str = generate_signal(last_row)

        if signal_str == "BUY":
            sig = SignalType.BUY
        elif signal_str == "SELL":
            sig = SignalType.SELL
        else:
            sig = SignalType.HOLD

        return TradeSignal(
            signal=sig,
            confidence=0.7,
            price=float(last_row["close"]),
            timestamp=datetime.utcnow(),
            source="rule_based",
        )

    def _generate_ml_signal(self, df) -> Optional[TradeSignal]:
        if not self.ml_infer:
            return None
        result = self.ml_infer.predict_window(df)

        # NOTE: inference.py returns _CLASSES = ["SELL","HOLD","BUY"]
        raw_signal = str(result.get("signal", "HOLD")).upper()
        if raw_signal == "BUY":
            sig = SignalType.BUY
        elif raw_signal == "SELL":
            sig = SignalType.SELL
        else:
            sig = SignalType.HOLD

        self._log_event(
            "INFO",
            "ml",
            f"ML prediction: signal={raw_signal} confidence={result.get('confidence', 0):.3f} "
            f"up={result.get('up', 0):.3f} hold={result.get('hold', 0):.3f} down={result.get('down', 0):.3f}",
        )

        return TradeSignal(
            signal=sig,
            confidence=float(result.get("confidence", 0.0)),
            price=float(df.iloc[-1]["close"]),
            timestamp=datetime.utcnow(),
            source="ml",
            metadata=result,
        )

    def _combine_signals(
        self,
        rule_signal: TradeSignal,
        ml_signal: Optional[TradeSignal],
        *,
        strict_ai: bool = False,
    ) -> TradeSignal:
        if not ml_signal:
            return rule_signal

        prioritize_th = float(getattr(self.settings, "ml_prioritize_threshold", 0.80))
        override_th = float(getattr(self.settings, "ml_override_threshold", 0.70))
        agree_th = float(getattr(self.settings, "ml_agree_threshold", 0.70))

        if ml_signal.confidence >= prioritize_th:
            self._log_event(
                "INFO",
                "signal",
                f"ML prioritize (high conf): {ml_signal.signal.value} @ {ml_signal.confidence:.2f}",
            )
            return TradeSignal(
                signal=ml_signal.signal,
                confidence=ml_signal.confidence,
                price=ml_signal.price,
                timestamp=ml_signal.timestamp,
                source="ml_prioritize",
                metadata=ml_signal.metadata,
            )

        if ml_signal.confidence >= override_th:
            self._log_event(
                "INFO",
                "signal",
                f"ML override: {ml_signal.signal.value} @ {ml_signal.confidence:.2f}",
            )
            return TradeSignal(
                signal=ml_signal.signal,
                confidence=ml_signal.confidence,
                price=ml_signal.price,
                timestamp=ml_signal.timestamp,
                source="ml_override",
                metadata=ml_signal.metadata,
            )

        if rule_signal.signal == ml_signal.signal and rule_signal.signal in (
            SignalType.BUY,
            SignalType.SELL,
        ):
            combined_conf = (rule_signal.confidence + ml_signal.confidence) / 2
            self._log_event(
                "INFO",
                "signal",
                f"Signals agree (no threshold): {rule_signal.signal.value} @ {combined_conf:.2f}",
            )
            return TradeSignal(
                signal=rule_signal.signal,
                confidence=combined_conf,
                price=rule_signal.price,
                timestamp=rule_signal.timestamp,
                source="combined",
                metadata={"rule": rule_signal.metadata, "ml": ml_signal.metadata},
            )
        if (
            rule_signal.signal == ml_signal.signal
            and ml_signal.signal == SignalType.HOLD
            and ml_signal.confidence >= agree_th
        ):
            combined_conf = (rule_signal.confidence + ml_signal.confidence) / 2
            self._log_event(
                "INFO",
                "signal",
                f"Signals agree (HOLD): {rule_signal.signal.value} @ {combined_conf:.2f}",
            )
            return TradeSignal(
                signal=rule_signal.signal,
                confidence=combined_conf,
                price=rule_signal.price,
                timestamp=rule_signal.timestamp,
                source="combined",
                metadata={"rule": rule_signal.metadata, "ml": ml_signal.metadata},
            )

        abs_floor = float(getattr(self.settings, "ml_absolute_min_confidence", 0.50))
        # Directional conflict (BUY vs SELL): let ML win below override threshold but above safety floor
        if (
            rule_signal.signal in (SignalType.BUY, SignalType.SELL)
            and ml_signal.signal in (SignalType.BUY, SignalType.SELL)
            and rule_signal.signal != ml_signal.signal
            and abs_floor <= float(ml_signal.confidence) < override_th
        ):
            blended = min(
                0.95,
                0.35 * float(rule_signal.confidence)
                + 0.65 * float(ml_signal.confidence),
            )
            self._log_event(
                "INFO",
                "signal",
                f"ML moderate influence: {ml_signal.signal.value} @ {ml_signal.confidence:.2f} "
                f"(rule={rule_signal.signal.value}, blended={blended:.2f})",
            )
            return TradeSignal(
                signal=ml_signal.signal,
                confidence=blended,
                price=ml_signal.price,
                timestamp=ml_signal.timestamp,
                source="ml_moderate_influence",
                metadata=ml_signal.metadata,
            )

        # Stronger AI: rules say HOLD but ML has directional conviction (reduces HOLD-only stagnation)
        if getattr(self.settings, "ml_hold_breakout_enabled", True):
            hb_min = float(
                getattr(self.settings, "ml_hold_breakout_min_confidence", 0.58)
            )
            if (
                rule_signal.signal == SignalType.HOLD
                and ml_signal.signal in (SignalType.BUY, SignalType.SELL)
                and float(ml_signal.confidence) >= hb_min
            ):
                blended = min(
                    0.95,
                    0.4 * float(rule_signal.confidence)
                    + 0.6 * float(ml_signal.confidence),
                )
                self._log_event(
                    "INFO",
                    "signal",
                    f"ML hold-breakout: {ml_signal.signal.value} @ {ml_signal.confidence:.2f} "
                    f"(rule=HOLD, blended_conf={blended:.2f})",
                )
                return TradeSignal(
                    signal=ml_signal.signal,
                    confidence=blended,
                    price=ml_signal.price,
                    timestamp=ml_signal.timestamp,
                    source="ml_hold_breakout",
                    metadata=ml_signal.metadata,
                )

        # Symmetric to ml_hold_breakout: rules directional, ML neutral (HOLD).
        # Fixes production stagnation where rule=BUY + ml=HOLD always became conflict HOLD.
        if getattr(self.settings, "rule_directional_ml_neutral_enabled", True):
            rd_min = float(
                getattr(self.settings, "rule_directional_min_confidence", 0.55)
            )
            if (
                rule_signal.signal in (SignalType.BUY, SignalType.SELL)
                and ml_signal.signal == SignalType.HOLD
                and float(rule_signal.confidence) >= rd_min
            ):
                blended = min(
                    0.95,
                    0.7 * float(rule_signal.confidence)
                    + 0.3 * float(ml_signal.confidence),
                )
                self._log_event(
                    "INFO",
                    "signal",
                    f"Rule directional + ML neutral: {rule_signal.signal.value} @ "
                    f"{rule_signal.confidence:.2f} (ml=HOLD @ {ml_signal.confidence:.2f}, "
                    f"blended={blended:.2f})",
                )
                return TradeSignal(
                    signal=rule_signal.signal,
                    confidence=blended,
                    price=rule_signal.price,
                    timestamp=rule_signal.timestamp,
                    source="rule_directional_ml_neutral",
                    metadata={
                        "rule": rule_signal.metadata,
                        "ml": ml_signal.metadata,
                    },
                )

        if strict_ai:
            # Only true directional opposition (BUY vs SELL) forces HOLD under ML_STRICT.
            opposing = (
                rule_signal.signal in (SignalType.BUY, SignalType.SELL)
                and ml_signal.signal in (SignalType.BUY, SignalType.SELL)
                and rule_signal.signal != ml_signal.signal
            )
            if opposing:
                self._log_event(
                    "INFO",
                    "signal",
                    f"Strict AI: rule/ML oppose → HOLD (rule={rule_signal.signal.value}, "
                    f"ml={ml_signal.signal.value})",
                )
                blend = min(
                    0.55,
                    0.5 * float(rule_signal.confidence)
                    + 0.5 * float(ml_signal.confidence),
                )
                return TradeSignal(
                    signal=SignalType.HOLD,
                    confidence=blend,
                    price=ml_signal.price,
                    timestamp=ml_signal.timestamp,
                    source="ml_rule_conflict_hold",
                    metadata={"rule": rule_signal.metadata, "ml": ml_signal.metadata},
                )

        self._log_event(
            "INFO",
            "signal",
            f"Signal conflict - using rule-based: {rule_signal.signal.value}",
        )
        return TradeSignal(
            signal=rule_signal.signal,
            confidence=rule_signal.confidence,
            price=rule_signal.price,
            timestamp=rule_signal.timestamp,
            source="rule_only",
            metadata={"ml_conflict": getattr(ml_signal, "metadata", None)},
        )

    # ---------------------------
    # Binance verification helpers
    # ---------------------------

    def _sync_order_status(self, symbol: str, exchange_order_id: int) -> Dict[str, Any]:
        """
        Query Binance for order status (Phase 1 proof)
        """
        info = self.client.get_order(symbol=symbol, order_id=exchange_order_id)
        self._log_event(
            "INFO",
            "order",
            f"Order status: orderId={exchange_order_id} status={info.get('status')} "
            f"executedQty={info.get('executedQty')} cumQuote={info.get('cummulativeQuoteQty')}",
            symbol=symbol,
        )
        return info

    # ---------------------------
    # Phase 2A: centralized pre-trade risk gate
    # ---------------------------

    def _build_risk_state(self) -> Any:
        """
        Snapshot the runtime state the centralized RiskEngine evaluates against.

        Cheap to compute; called once per execution candidate. Errors are swallowed
        and replaced with empty state — the risk engine then runs with conservative
        defaults rather than breaking the cycle.
        """
        from datetime import datetime, timedelta

        from src.safety.risk_engine import _State as _RiskState

        try:
            open_positions = int(
                self.db.query(Position)
                .filter(
                    Position.is_open == True,  # noqa: E712
                    Position.mode == self.execution_mode,
                )
                .count()
            )
        except Exception:
            open_positions = 0

        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            daily_orders = int(
                self.db.query(Order)
                .filter(Order.created_at >= today, Order.mode == self.execution_mode)
                .count()
            )
        except Exception:
            daily_orders = 0

        try:
            from sqlalchemy import func as _f

            daily_pnl = (
                self.db.query(_f.coalesce(_f.sum(Position.pnl), 0.0))
                .filter(
                    Position.exit_ts >= today,
                    Position.is_open == False,  # noqa: E712
                    Position.mode == self.execution_mode,
                )
                .scalar()
                or 0.0
            )
        except Exception:
            daily_pnl = 0.0

        try:
            last_loss_row = (
                self.db.query(Position)
                .filter(
                    Position.is_open == False,  # noqa: E712
                    Position.mode == self.execution_mode,
                    Position.pnl < 0,
                )
                .order_by(Position.exit_ts.desc())
                .first()
            )
            last_loss_at = last_loss_row.exit_ts if last_loss_row else None
        except Exception:
            last_loss_at = None

        try:
            balance = float(self._get_usdt_balance())
        except Exception:
            balance = 0.0

        current_exposure = 0.0
        cumulative_pnl = 0.0
        try:
            open_rows = (
                self.db.query(Position)
                .filter(
                    Position.is_open == True,  # noqa: E712
                    Position.mode == self.execution_mode,
                )
                .all()
            )
            for pos in open_rows:
                ep = float(pos.entry_price or 0.0)
                eq = float(pos.entry_qty or 0.0)
                current_exposure += ep * eq
        except Exception:
            pass

        try:
            from src.safety.phase2c import get_activation_at
            from sqlalchemy import func as _fn

            activation_at = get_activation_at()
            pnl_q = self.db.query(_fn.coalesce(_fn.sum(Position.pnl), 0.0)).filter(
                Position.is_open == False,  # noqa: E712
                Position.mode == self.execution_mode,
            )
            if activation_at is not None:
                pnl_q = pnl_q.filter(Position.exit_ts >= activation_at)
            cumulative_pnl = float(pnl_q.scalar() or 0.0)
        except Exception:
            cumulative_pnl = 0.0

        # Phase 2A: seed duplicate-detection window from the DB. After a
        # restart we want recently-replayed client_order_ids to still be
        # rejected by RiskEngine._check_duplicate.
        recent_coids: Dict[str, datetime] = {}
        try:
            window_start = datetime.utcnow() - timedelta(minutes=5)
            rows = (
                self.db.query(Order.client_order_id, Order.created_at)
                .filter(
                    Order.client_order_id.isnot(None),
                    Order.created_at >= window_start,
                )
                .all()
            )
            for coid, ts in rows:
                if coid:
                    recent_coids[str(coid)] = ts or datetime.utcnow()
        except Exception:
            pass

        return _RiskState(
            open_positions_count=open_positions,
            daily_realized_pnl_usdt=float(daily_pnl),
            daily_orders_count=daily_orders,
            account_balance_usdt=balance,
            last_loss_at=last_loss_at,
            recent_client_order_ids=recent_coids,
            current_total_exposure_usdt=float(current_exposure),
            cumulative_realized_pnl_usdt=float(cumulative_pnl),
        )

    def _phase2c_blocks_live(self) -> Optional[str]:
        """Return reason string if Phase 2C gate blocks live Binance orders."""
        if self.execution_mode != "live":
            return None
        try:
            from src.safety.phase2c import can_place_live_orders, snapshot

            if not can_place_live_orders():
                return snapshot().get("status_label") or "phase2c_micro_live_disabled"
        except Exception as exc:
            return f"phase2c_gate_error:{exc}"
        return None

    def _run_pretrade_risk_check(
        self,
        *,
        symbol: str,
        side: str,
        price: float,
        quantity: float,
        ml_confidence: Optional[float] = None,
        client_order_id: Optional[str] = None,
    ) -> Any:
        """
        Single chokepoint every order passes through (paper / shadow / live).

        Returns (decision, request). Caller persists rejection via _persist_risk_rejection().
        """
        from src.execution.mode import ExecutionMode
        from src.safety.risk_engine import (
            OrderRequest,
            RiskEngine,
            default_limits_from_env,
        )

        try:
            mode = ExecutionMode.coerce(self.execution_mode)
        except Exception:
            mode = ExecutionMode.PAPER

        request = OrderRequest(
            symbol=symbol,
            side=side,
            price=float(price or 0.0),
            quantity=float(quantity or 0.0),
            mode=mode,
            client_order_id=client_order_id,
            ml_confidence=ml_confidence,
            source="auto_trade_engine",
        )
        engine = RiskEngine(
            limits=default_limits_from_env(),
            state=self._build_risk_state(),
        )
        decision = engine.validate(request)
        return decision, request

    def _persist_risk_rejection(
        self,
        *,
        symbol: str,
        side: str,
        decision: Any,
        price: float,
        quantity: float,
    ) -> None:
        """Log + alert on every rejection so audits/observability show every block."""
        codes = ",".join(getattr(decision, "reason_codes", []) or []) or "risk_rejected"
        reasons = "; ".join(getattr(decision, "reasons", []) or [])[:1500]
        try:
            self._log_event(
                "WARN",
                "risk",
                f"{side}(REJECTED) {quantity:.8f} {symbol} @ {price:.2f} "
                f"codes=[{codes}] reasons={reasons}",
                symbol=symbol,
            )
        except Exception:
            pass
        try:
            from src.safety.alerts import send_alert

            send_alert(
                "WARN",
                "risk_rejected",
                f"{side} {symbol} blocked by risk gate",
                symbol=symbol,
                side=side,
                price=float(price),
                quantity=float(quantity),
                reason_codes=list(getattr(decision, "reason_codes", []) or []),
                reasons=list(getattr(decision, "reasons", []) or []),
                mode=self.execution_mode,
            )
        except Exception:
            pass

    # ---------------------------
    # Risk sizing
    # ---------------------------

    def _calculate_position_size(
        self, balance: float, price: float, risk_pct: Optional[float] = None
    ) -> tuple[float, float]:
        risk_pct = (
            risk_pct
            if risk_pct is not None
            else float(self.risk_config.max_position_pct)
        )
        spend = balance * float(risk_pct)
        # Respect Phase 2A absolute max-trade notional WITHOUT raising the risk limit:
        # e.g. 10% of a $10k shadow balance is $1000, which would always fail a $100 cap.
        try:
            from src.safety.risk_engine import default_limits_from_env

            max_n = float(default_limits_from_env().max_trade_notional_usdt)
            if max_n > 0:
                spend = min(spend, max_n)
        except Exception:
            pass
        quantity = spend / price if price > 0 else 0.0
        return quantity, spend

    def _position_size_from_risk(
        self,
        *,
        balance: float,
        price: float,
        stop_loss: Optional[float],
        risk_pct: Optional[float],
    ) -> tuple[bool, float, float, str]:
        """Returns (ok, quantity, spend, reason) using deterministic risk sizing when stop is set."""
        from src.risk.position_sizing import compute_position_size

        max_pos_pct = float(
            risk_pct if risk_pct is not None else self.risk_config.max_position_pct
        )
        rp = float(self.settings.max_risk_per_trade)
        max_notional: Optional[float] = None
        try:
            from src.safety.risk_engine import default_limits_from_env

            max_notional = float(default_limits_from_env().max_trade_notional_usdt)
        except Exception:
            max_notional = None

        if stop_loss is not None and stop_loss > 0 and price > 0 and stop_loss < price:
            out = compute_position_size(
                equity=balance,
                entry_price=price,
                stop_loss=float(stop_loss),
                max_position_pct=max_pos_pct,
                risk_per_trade_pct=rp,
                max_notional_usdt=max_notional,
            )
            if not out["ok"]:
                return False, 0.0, 0.0, str(out["reason"])
            qty = float(out["qty"])
            spend = qty * price
            return True, qty, spend, "risk_and_notional_cap"
        qty, spend = self._calculate_position_size(balance, price, risk_pct)
        return True, qty, spend, "notional_cap_only"

    def _price_for_forced_signal(self, symbol: str, df: Any) -> float:
        """Last close from klines frame, or live ticker if indicators emptied the frame."""
        import pandas as pd

        if df is not None and len(df) > 0:
            return float(df.iloc[-1]["close"])
        return float(self.client.get_price(symbol))

    def _run_forced_signal_trade(
        self,
        *,
        symbol: str,
        timeframe: str,
        risk_pct: Optional[float],
        force_signal: str,
        df: Any,
    ) -> TradeResult:
        """
        Audit / proof path: execute BUY|SELL|HOLD without requiring 50+ indicator rows.
        """
        fs = force_signal.upper().strip()
        if fs not in ("BUY", "SELL", "HOLD"):
            raise ValueError(f"force_signal must be BUY/SELL/HOLD, got {force_signal!r}")

        try:
            last_price = self._price_for_forced_signal(symbol, df)
        except Exception as exc:
            return TradeResult(
                success=False,
                executed=False,
                signal="HOLD",
                reason=f"Forced signal: cannot resolve price: {exc}",
            )

        try:
            regime = (
                self.adaptive_strategy.detect_regime(df).regime
                if df is not None and len(df) >= 20
                else MarketRegime.UNKNOWN
            )
        except Exception:
            regime = MarketRegime.UNKNOWN

        decision_log = self._save_decision(
            decision=TradingDecision(
                action=SignalAction[fs],
                confidence=1.0,
                regime=regime,
                price=last_price,
                timestamp=datetime.utcnow().isoformat(),
                adx=0,
                ema_fast=0,
                ema_slow=0,
                rsi=0,
                bb_upper=None,
                bb_middle=None,
                bb_lower=None,
                atr=0,
                atr_pct=0,
                entry_price=last_price if fs != "HOLD" else None,
                stop_loss=None,
                take_profit=None,
                risk_reward=None,
                position_size_pct=0,
                reason=f"Forced signal: {fs}",
                signals={
                    "forced": True,
                    "force_signal": fs,
                    "final_source": "forced_signal",
                    "combined_signal": fs,
                    "rule_signal": fs,
                    "ml_signal": None,
                    "final_action": fs,
                    "cycle_debug": {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "final_signal": fs,
                        "final_source": "forced_signal",
                        "execution_eligible": fs in ("BUY", "SELL"),
                    },
                },
            ),
            symbol=symbol,
            timeframe=timeframe,
        )

        if fs == "BUY":
            if self.execution_mode == "paper":
                result = self._execute_buy_paper(symbol, last_price, risk_pct)
            else:
                open_position = self._get_open_position(symbol)
                if open_position:
                    return TradeResult(
                        success=True,
                        executed=False,
                        signal=fs,
                        reason="Forced BUY skipped: position already open",
                    )
                result = self._execute_buy(
                    symbol=symbol, price=last_price, risk_pct=risk_pct
                )
            if result.executed:
                decision_log.executed = True
                decision_log.order_id = self._resolve_local_order_id(result.order_id)
                try:
                    self.db.commit()
                except Exception:
                    self.db.rollback()
                    raise
            return result

        if fs == "SELL":
            open_position = self._get_open_position(symbol)
            if open_position:
                result = (
                    self._execute_sell_paper(
                        symbol=symbol, position=open_position, price=last_price
                    )
                    if self.execution_mode == "paper"
                    else self._execute_sell(
                        symbol=symbol, position=open_position, price=last_price
                    )
                )
                if result.executed:
                    decision_log.executed = True
                    decision_log.order_id = self._resolve_local_order_id(
                        result.order_id
                    )
                    try:
                        self.db.commit()
                    except Exception:
                        self.db.rollback()
                        raise
                return result
            return TradeResult(
                success=True,
                executed=False,
                signal=fs,
                reason="Forced SELL skipped: no open position",
            )

        return TradeResult(
            success=True,
            executed=False,
            signal=fs,
            reason=f"Forced {fs} (no execution for HOLD)",
        )

    # ---------------------------
    # Main entry
    # ---------------------------

    def execute_auto_trade(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        risk_pct: Optional[float] = None,
        force_signal: Optional[str] = None,  # "BUY" | "SELL"
        triggered_by: str = "api_manual",  # "scheduler" | "api_manual" | "proof_forced"
        cycle_id: Optional[int] = None,
    ) -> TradeResult:
        now = datetime.utcnow()
        symbol = symbol or self.settings.trade_symbol
        timeframe = timeframe or self.settings.trade_timeframe

        # Phase 2A: record trigger provenance for every Order/TradingDecisionLog
        # written during this cycle. force_signal always means a proof/audit call
        # regardless of what the caller passed for triggered_by — this is what
        # lets the shadow-soak report distinguish genuine unattended scheduler
        # execution from manual test curls (Saad validation, concern #1).
        self._current_trigger = {
            "triggered_by": "proof_forced" if force_signal else triggered_by,
            "cycle_id": cycle_id,
        }

        # Re-resolve mode each cycle so POST /execution/mode applies without restart.
        try:
            from src.execution.mode import get_execution_mode

            self.execution_mode = get_execution_mode().value
        except Exception:
            pass

        # Phase 2A: hard kill switch — blocks every mode (paper / shadow / live).
        try:
            from src.safety import kill_switch as _ks

            if _ks.is_engaged():
                state = _ks.get_state()
                reason = state.get("reason") or "kill_switch_engaged"
                self._log_event(
                    "WARN",
                    "safety",
                    f"Kill switch engaged — refusing execution. reason={reason}",
                    symbol=symbol,
                )
                return TradeResult(
                    success=True,
                    executed=False,
                    signal="HOLD",
                    reason=f"Kill switch engaged: {reason}",
                    blocked=True,
                )
        except Exception:
            # Safety check must never crash the engine — fall through to normal flow.
            pass

        if self.cooldown.blocked(now):
            return TradeResult(
                success=True,
                executed=False,
                signal="HOLD",
                reason=f"Cooldown active until {self.cooldown.until}",
            )

        try:
            lookback = int(getattr(self.settings, "trade_lookback", 500))
            klines = self.client.klines(
                symbol=symbol, interval=timeframe, limit=lookback
            )

            # Convert klines to DataFrame
            import pandas as pd

            df = pd.DataFrame(
                klines,
                columns=[
                    "open_time",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "close_time",
                    "qav",
                    "num_trades",
                    "taker_base",
                    "taker_quote",
                    "ignore",
                ],
            )
            df.loc[:, "open_time"] = pd.to_datetime(df["open_time"], unit="ms")
            for col in ["open", "high", "low", "close", "volume"]:
                df.loc[:, col] = df[col].astype(float)

            indicator_config = {
                "ema_fast": self.settings.ema_fast,
                "ema_slow": self.settings.ema_slow,
                "rsi_period": self.settings.rsi_len,
                "adx_period": 14,
                "bb_period": self.settings.bb_len,
                "bb_std": self.settings.bb_std,
                "atr_period": 14,
            }
            df = add_all_indicators(df, indicator_config)
            df = append_ml_production_features(df)
            df = df.dropna()

            if force_signal:
                fs = force_signal.upper().strip()
                if fs in ("BUY", "SELL", "HOLD"):
                    return self._run_forced_signal_trade(
                        symbol=symbol,
                        timeframe=timeframe,
                        risk_pct=risk_pct,
                        force_signal=fs,
                        df=df,
                    )
                raise ValueError(
                    f"force_signal must be BUY/SELL/HOLD, got {force_signal!r}"
                )

            if len(df) < 50:
                return TradeResult(
                    success=False,
                    executed=False,
                    signal="HOLD",
                    reason="Insufficient data after indicator calculation",
                )

            decision: TradingDecision = self.adaptive_strategy.generate_decision(df)

            rule_confidence_before_ml = float(decision.confidence)
            current_price = decision.price
            rule_signal_value: str = (
                decision.action.value
            )  # capture rule output for audit

            self._log_event(
                "INFO",
                "signal",
                f"[RULE] {symbol} {timeframe}: {decision.action.value} "
                f"conf={decision.confidence:.2f} regime={decision.regime.value} | {decision.reason}",
                symbol=symbol,
            )

            ml_signal_value: Optional[str] = None  # set if ML runs, for audit log
            ml_context: Dict[str, Any] = self._resolve_ml_context(symbol, timeframe)
            ml_changed_final_action = False
            ml_out: Optional[TradeSignal] = None
            runtime_eligible = bool(ml_context.get("runtime_eligible"))
            strict_ai = bool(
                self.ml_enabled
                and runtime_eligible
                and getattr(self.settings, "ml_strict", True)
            )

            # Exact symbol+TF resolution + artifact checks live in resolve_model_selection
            # (runtime_eligible False → ml_strict_failure abort below).

            self.ml_infer = None

            if self.ml_enabled and not runtime_eligible:
                decision.signals["ml_load_error"] = ml_context.get(
                    "reason", "runtime_not_eligible"
                )
                return self._ml_strict_abort_trading_cycle(
                    decision=decision,
                    symbol=symbol,
                    timeframe=timeframe,
                    rule_signal_value=rule_signal_value,
                    rule_confidence_before_ml=rule_confidence_before_ml,
                    current_price=current_price,
                    df=df,
                    err=str(ml_context.get("reason", "runtime_not_eligible")),
                    model_loaded=False,
                    ml_context=ml_context,
                )

            if self.ml_enabled and runtime_eligible:
                try:
                    from src.ml.inference import get_infer

                    self.ml_infer = get_infer(str(ml_context["model_dir"]))
                except Exception as e:
                    decision.signals["ml_load_error"] = str(e)
                    self.ml_infer = None

            if self.ml_enabled and runtime_eligible and not self.ml_infer:
                err = str(decision.signals.get("ml_load_error") or "model_load_failed")
                return self._ml_strict_abort_trading_cycle(
                    decision=decision,
                    symbol=symbol,
                    timeframe=timeframe,
                    rule_signal_value=rule_signal_value,
                    rule_confidence_before_ml=rule_confidence_before_ml,
                    current_price=current_price,
                    df=df,
                    err=err,
                    model_loaded=False,
                    ml_context=ml_context,
                )

            if self.ml_infer:
                try:
                    ml_out = self._generate_ml_signal(df)
                except Exception as e:
                    self._log_event(
                        "ERROR", "ml", f"ML prediction failed: {e}", symbol=symbol
                    )
                    decision.signals["ml_prediction_error"] = str(e)
                    return self._ml_strict_abort_trading_cycle(
                        decision=decision,
                        symbol=symbol,
                        timeframe=timeframe,
                        rule_signal_value=rule_signal_value,
                        rule_confidence_before_ml=rule_confidence_before_ml,
                        current_price=current_price,
                        df=df,
                        err=str(e),
                        model_loaded=True,
                        ml_context=ml_context,
                    )
                if ml_out:
                    ml_signal_value = ml_out.signal.value
                    rule_signal = TradeSignal(
                        signal=SignalType[decision.action.value],
                        confidence=decision.confidence,
                        price=decision.price,
                        timestamp=datetime.utcnow(),
                        source="rule_based",
                    )
                    final_signal = self._combine_signals(
                        rule_signal, ml_out, strict_ai=strict_ai
                    )

                    fused = fuse_confidence(
                        rule_signal_value,
                        ml_out.signal.value,
                        rule_confidence_before_ml,
                        ml_out.confidence,
                    )
                    if final_signal.source in ("ml_override", "ml_prioritize"):
                        decision.confidence = final_signal.confidence
                    elif final_signal.source in (
                        "ml_hold_breakout",
                        "ml_moderate_influence",
                        "rule_directional_ml_neutral",
                    ):
                        decision.confidence = min(
                            1.0, max(fused, final_signal.confidence)
                        )
                    elif final_signal.source == "ml_rule_conflict_hold":
                        decision.confidence = final_signal.confidence
                    else:
                        decision.confidence = fused

                    self._log_event(
                        "INFO",
                        "signal",
                        f"[COMBINED] source={final_signal.source} "
                        f"signal={final_signal.signal.value} conf={final_signal.confidence:.2f} "
                        f"(rule={rule_signal.signal.value}, ml={ml_out.signal.value} @ {ml_out.confidence:.2f})",
                        symbol=symbol,
                    )

                    ml_meta = ml_out.metadata or {}
                    decision.signals["ml_prediction"] = {
                        "signal": ml_out.signal.value,
                        "confidence": round(ml_out.confidence, 3),
                        "up": round(float(ml_meta.get("up", 0)), 3),
                        "hold": round(float(ml_meta.get("hold", 0)), 3),
                        "down": round(float(ml_meta.get("down", 0)), 3),
                    }
                    decision.signals["rule_signal"] = rule_signal.signal.value
                    decision.signals["final_source"] = final_signal.source

                    if final_signal.signal.value != decision.action.value:
                        ml_changed_final_action = True
                        decision.action = SignalAction[final_signal.signal.value]
                        decision.reason = (
                            f"[{final_signal.source.upper()}] {decision.reason}"
                        )
            else:
                decision.signals["final_source"] = (
                    "rule_only" if self.ml_enabled else "rule_only_ml_disabled"
                )

            # -------------------------------------------------------
            # Transparency: always write all five audit fields so the
            # dashboard /decisions/recent endpoint never returns nulls.
            # -------------------------------------------------------
            _final_source = decision.signals.get("final_source", "rule_only")
            _ml_pred = decision.signals.get("ml_prediction") or {}

            decision.signals["rule_signal"] = decision.signals.get(
                "rule_signal", rule_signal_value
            )
            decision.signals["ml_signal"] = _ml_pred.get("signal")  # None when ML off
            decision.signals["ml_confidence"] = _ml_pred.get("confidence")

            # combined_signal = what the pipeline ultimately decided to act on
            decision.signals["combined_signal"] = decision.action.value

            # override_reason: human-readable explanation of the pipeline outcome
            if _final_source == "ml_prioritize":
                decision.signals["override_reason"] = (
                    f"ML prioritize high confidence (>="
                    f"{getattr(self.settings, 'ml_prioritize_threshold', 0.8)}): "
                    f"{_ml_pred.get('confidence', '?')}"
                )
            elif _final_source == "ml_override":
                decision.signals["override_reason"] = (
                    f"ML override (conf={_ml_pred.get('confidence', '?')})"
                )
            elif _final_source == "combined":
                decision.signals["override_reason"] = (
                    f"Rule + ML agree on {decision.action.value}"
                )
            elif _final_source == "ml_hold_breakout":
                decision.signals["override_reason"] = (
                    f"ML directional while rules HOLD (min conf "
                    f"{getattr(self.settings, 'ml_hold_breakout_min_confidence', 0.58)}) → "
                    f"{decision.action.value}"
                )
            elif _final_source == "ml_moderate_influence":
                decision.signals["override_reason"] = (
                    f"ML moderate influence (floor–override): "
                    f"{_ml_pred.get('confidence', '?')} vs rule conflict → {decision.action.value}"
                )
            elif _final_source == "rule_directional_ml_neutral":
                decision.signals["override_reason"] = (
                    f"Rules directional ({decision.signals.get('rule_signal')}) while ML HOLD "
                    f"(min rule conf "
                    f"{getattr(self.settings, 'rule_directional_min_confidence', 0.55)}) → "
                    f"{decision.action.value}"
                )
            elif _final_source == "ml_rule_conflict_hold":
                decision.signals["override_reason"] = (
                    "Strict AI: rule and ML disagree — HOLD (no rule-only fallback)"
                )
            elif _final_source in ("rule_only", "rule_based"):
                if ml_out is not None and self.ml_enabled:
                    decision.signals["override_reason"] = (
                        f"ML produced {ml_out.signal.value} @ {ml_out.confidence:.2f} "
                        f"but rules retained (conflict or thresholds)"
                    )
                else:
                    decision.signals["override_reason"] = (
                        "ML signal absent or ambiguous; rule-based used"
                    )
            elif _final_source == "rule_only_ml_disabled":
                decision.signals["override_reason"] = "ML disabled"
            elif _final_source in ("ml_strict_failure", "ml_runtime_failure"):
                decision.signals["override_reason"] = (
                    "AI runtime blocked — cycle not a trade decision (ML_STRICT)"
                )
            else:
                decision.signals["override_reason"] = _final_source

            self._apply_ml_audit_fields(
                decision,
                ml_context=ml_context,
                ml_out=ml_out,
                ml_infer_present=self.ml_infer is not None,
                rule_signal_value=rule_signal_value,
            )

            # Explicit ML alignment proof for each decision cycle
            decision.signals["ml_context"] = {
                "model_name": ml_context.get("model_name"),
                "symbol": ml_context.get("symbol"),
                "timeframe": ml_context.get("timeframe"),
                "model_version": ml_context.get("model_version"),
                "prediction": decision.signals.get("ml_signal"),
                "confidence": decision.signals.get("ml_confidence"),
                "ml_status": decision.signals.get("ml_status"),
                "changed_final_action": ml_changed_final_action,
                "model_dir": ml_context.get("model_dir"),
                "exact_match_exists": ml_context.get("exact_match_exists"),
                "fallback_used": ml_context.get("fallback_used"),
                "artifact_exists": ml_context.get("artifact_exists"),
                "runtime_eligible": ml_context.get("runtime_eligible"),
            }

            open_position = self._get_open_position(symbol)

            re_for_gate = (
                bool(ml_context.get("runtime_eligible")) if self.ml_enabled else False
            )
            if not self.ml_enabled:
                ml_ok_gate = True
            elif not re_for_gate:
                ml_ok_gate = False
            else:
                ml_ok_gate = self.ml_infer is not None and ml_out is not None
            th = self._effective_thresholds(decision)
            decision.signals["active_thresholds"] = th
            gate_eval = evaluate_entry_gates(
                adx=float(decision.adx),
                rsi=float(decision.rsi),
                atr_pct=float(decision.atr_pct),
                ema_fast=float(decision.ema_fast),
                ema_slow=float(decision.ema_slow),
                adx_threshold=th["adx_threshold"],
                atr_vol_threshold=th["atr_vol_threshold"],
                rsi_buy_min=th["rsi_buy_min"],
                rsi_buy_max=th["rsi_buy_max"],
                ml_ok=ml_ok_gate,
                risk_ok=True,
            )
            if getattr(self.settings, "strict_entry_gates", False):
                if decision.action == SignalAction.BUY and not open_position:
                    failed = gate_eval.get("failed_gates") or []
                    if failed:
                        decision.action = SignalAction.HOLD
                        decision.reason = f"[STRICT_GATE] {failed} | {decision.reason}"

            rt_mode = resolve_runtime_mode(
                ml_enabled=self.ml_enabled,
                runtime_eligible=re_for_gate,
                model_loaded=self.ml_infer is not None,
                ml_signal_present=ml_out is not None,
                ml_error=(
                    decision.signals.get("ml_load_error")
                    or decision.signals.get("ml_prediction_error")
                ),
            ).value
            self._enrich_cycle_debug(
                decision,
                symbol=symbol,
                timeframe=timeframe,
                runtime_mode=rt_mode,
                rule_signal_value=rule_signal_value,
                ml_signal_value=ml_signal_value,
                rule_confidence_before_ml=rule_confidence_before_ml,
                has_open_position=open_position is not None,
            )
            self._attach_cycle_envelope(
                decision,
                symbol=symbol,
                timeframe=timeframe,
                runtime_mode=rt_mode,
                runtime_eligible=re_for_gate,
                rule_signal_value=rule_signal_value,
                rule_confidence_before_ml=rule_confidence_before_ml,
                ml_signal_str=decision.signals.get("ml_signal"),
                ml_conf=decision.signals.get("ml_confidence"),
                model_loaded=self.ml_infer is not None,
                feature_columns_present=feature_columns_valid(df),
                final_source=str(decision.signals.get("final_source", "rule_only")),
                open_position=open_position,
                gate_eval=gate_eval,
                ml_error=(
                    decision.signals.get("ml_load_error")
                    or decision.signals.get("ml_prediction_error")
                ),
                cooldown_blocked=False,
            )
            self._attach_confidence_audit_fields(
                decision,
                rule_confidence_before_ml=rule_confidence_before_ml,
            )

            # Audit log: pipeline visibility for diagnostics (rule / ML / final / source)
            source = decision.signals.get("final_source", "?")
            ml_str = ml_signal_value if ml_signal_value is not None else "disabled"
            self._log_event(
                "INFO",
                "decision",
                f"DECISION_PIPELINE | RULE={rule_signal_value} | ML={ml_str} | "
                f"FINAL={decision.action.value} | SOURCE={source}",
                symbol=symbol,
            )
            self._log_event(
                "INFO",
                "decision",
                f"[FINAL] {symbol} {timeframe}: {decision.action.value} @ {current_price:.2f} "
                f"| Regime: {decision.regime.value} | Conf: {decision.confidence:.2f} | {decision.reason}",
                symbol=symbol,
            )

            if decision.action == SignalAction.SELL and open_position:
                result = self._execute_sell(
                    symbol=symbol, position=open_position, price=current_price
                )
                if not result.executed:
                    self._patch_cycle_execution_block(decision, result.reason)

                # Save decision with execution status
                decision_log = self._save_decision(
                    decision=decision,
                    symbol=symbol,
                    timeframe=timeframe,
                    executed=result.executed,
                    order_id=result.order_id,
                )

                return result

            if decision.action == SignalAction.BUY and not open_position:
                fs = str(decision.signals.get("final_source", ""))
                ml_driven_sources = (
                    "ml_prioritize",
                    "ml_override",
                    "combined",
                    "ml_hold_breakout",
                    "ml_moderate_influence",
                )
                if (
                    self.ml_enabled
                    and ml_out is not None
                    and fs in ml_driven_sources
                ):
                    abs_min = float(th["ml_absolute_min_confidence"])
                    thr = max(abs_min, float(th["ml_min_trade_confidence"]))
                    gate_conf = float(ml_out.confidence)
                    if fs == "combined":
                        gate_conf = max(gate_conf, float(decision.confidence))
                    if gate_conf < abs_min:
                        decision.signals["ml_execution_gate"] = (
                            f"blocked_ml_conf_{gate_conf:.3f}<{abs_min}"
                        )
                        self._save_decision(decision, symbol, timeframe, executed=False)
                        return TradeResult(
                            success=True,
                            executed=False,
                            signal="BUY",
                            reason=(
                                f"ML confidence {gate_conf:.3f} below "
                                f"ML_ABSOLUTE_MIN_CONFIDENCE ({abs_min})"
                            ),
                            price=current_price,
                        )
                    if gate_conf < thr:
                        decision.signals["ml_execution_gate"] = (
                            f"blocked_ml_conf_{gate_conf:.3f}<{thr}"
                        )
                        self._save_decision(decision, symbol, timeframe, executed=False)
                        return TradeResult(
                            success=True,
                            executed=False,
                            signal="BUY",
                            reason=(
                                f"ML confidence {gate_conf:.3f} below "
                                f"ML_MIN_TRADE_CONFIDENCE ({thr})"
                            ),
                            price=current_price,
                        )
                if fs == "rule_directional_ml_neutral":
                    rd_min = float(th["rule_directional_min_confidence"])
                    if float(rule_confidence_before_ml) < rd_min:
                        decision.signals["ml_execution_gate"] = (
                            f"blocked_rule_conf_{float(rule_confidence_before_ml):.3f}<{rd_min}"
                        )
                        self._save_decision(decision, symbol, timeframe, executed=False)
                        return TradeResult(
                            success=True,
                            executed=False,
                            signal="BUY",
                            reason=(
                                f"Rule confidence {float(rule_confidence_before_ml):.3f} below "
                                f"RULE_DIRECTIONAL_MIN_CONFIDENCE ({rd_min})"
                            ),
                            price=current_price,
                        )
                adx_min = float(getattr(self.settings, "ml_min_adx_for_trade", 0) or 0)
                if adx_min > 0 and float(decision.adx) < adx_min:
                    decision.signals["market_filter"] = "low_adx"
                    self._save_decision(decision, symbol, timeframe, executed=False)
                    return TradeResult(
                        success=True,
                        executed=False,
                        signal="BUY",
                        reason=f"Blocked: ADX {decision.adx:.1f} < {adx_min}",
                        price=current_price,
                    )
                atr_min = float(
                    getattr(self.settings, "ml_min_atr_pct_for_trade", 0) or 0
                )
                if atr_min > 0 and float(decision.atr_pct) < atr_min:
                    decision.signals["market_filter"] = "low_volatility"
                    self._save_decision(decision, symbol, timeframe, executed=False)
                    return TradeResult(
                        success=True,
                        executed=False,
                        signal="BUY",
                        reason=f"Blocked: ATR% {decision.atr_pct:.3f} < {atr_min}",
                        price=current_price,
                    )

                effective_risk = risk_pct
                try:
                    skip_portfolio_cap = (
                        str(getattr(self, "execution_mode", "") or "").lower()
                        in ("shadow", "paper")
                        or not getattr(self.settings, "rl_hybrid_enabled", False)
                    )
                    if not skip_portfolio_cap:
                        from src.rl.hybrid import adjust_risk_for_trade

                        last_pnl: Optional[float] = None
                        try:
                            lp = (
                                self.db.query(Position)
                                .filter(
                                    Position.symbol == symbol,
                                    Position.mode == "live",
                                    Position.is_open == False,  # noqa: E712
                                )
                                .order_by(desc(Position.exit_ts))
                                .limit(1)
                                .first()
                            )
                            if lp is not None and lp.pnl is not None:
                                last_pnl = float(lp.pnl)
                        except Exception:
                            pass

                        effective_risk, hnote = adjust_risk_for_trade(
                            self.settings,
                            self.client,
                            symbol,
                            risk_pct,
                            decision.action.value,
                            float(ml_out.confidence) if ml_out else None,
                            df,
                            last_closed_pnl=last_pnl,
                        )
                        if hnote:
                            decision.signals["hybrid_risk"] = hnote
                        if effective_risk is not None and effective_risk <= 0:
                            self._save_decision(decision, symbol, timeframe, executed=False)
                            return TradeResult(
                                success=True,
                                executed=False,
                                signal="BUY",
                                reason="Portfolio cap: no headroom for this asset",
                                price=current_price,
                            )
                except Exception as hy_err:
                    decision.signals["hybrid_risk_error"] = str(hy_err)[:200]

                result = self._execute_buy(
                    symbol=symbol,
                    price=current_price,
                    risk_pct=effective_risk,
                    stop_loss=decision.stop_loss,
                )
                if not result.executed:
                    self._patch_cycle_execution_block(decision, result.reason)

                # Save decision with execution status
                decision_log = self._save_decision(
                    decision=decision,
                    symbol=symbol,
                    timeframe=timeframe,
                    executed=result.executed,
                    order_id=result.order_id,
                )

                return result

            # Still save decision for transparency
            decision_log = self._save_decision(
                decision=decision,
                symbol=symbol,
                timeframe=timeframe,
                executed=False,
            )

            if open_position:
                reason = f"Position open, signal is {decision.action.value}: {decision.reason}"
            else:
                reason = (
                    f"No position, signal is {decision.action.value}: {decision.reason}"
                )

            return TradeResult(
                success=True,
                executed=False,
                signal=decision.action.value,
                reason=reason,
                price=current_price,
            )

        except Exception as e:
            self.db.rollback()
            try:
                self._persist_engine_exception_audit(
                    symbol=symbol,
                    timeframe=timeframe,
                    exc=e,
                )
            except Exception as persist_err:
                try:
                    self._log_event(
                        "ERROR",
                        "auto_trade",
                        f"Failed to persist exception audit: {persist_err}",
                        symbol=symbol,
                    )
                except Exception:
                    pass
            try:
                self._log_event(
                    "ERROR", "auto_trade", f"Error: {str(e)}", symbol=symbol
                )
            except Exception:
                pass
            return TradeResult(
                success=False, executed=False, signal="ERROR", reason=str(e)
            )

    # ---------------------------
    # Execution paths (MARKET + verify)
    # ---------------------------
    def _execute_buy(
        self,
        symbol: str,
        price: float,
        risk_pct: Optional[float],
        stop_loss: Optional[float] = None,
    ) -> TradeResult:
        if self.execution_mode == "paper":
            return self._execute_buy_paper(symbol, price, risk_pct)
        if self.execution_mode == "shadow":
            return self._execute_buy_shadow(symbol, price, risk_pct, stop_loss=stop_loss)

        blocked = self._phase2c_blocks_live()
        if blocked:
            return TradeResult(
                success=True,
                executed=False,
                signal="BUY",
                reason=f"phase2c_blocked:{blocked}",
                blocked=True,
            )

        balance = self._get_usdt_balance()

        # Basic safety
        if balance <= 0:
            return TradeResult(
                success=True,
                executed=False,
                signal="BUY",
                reason="No USDT balance available",
                balance_before=balance,
            )

        ok_sz, _qty, spend, sz_reason = self._position_size_from_risk(
            balance=balance,
            price=price,
            stop_loss=stop_loss,
            risk_pct=risk_pct,
        )
        if not ok_sz:
            return TradeResult(
                success=True,
                executed=False,
                signal="BUY",
                reason=f"position_sizing_blocked:{sz_reason}",
                balance_before=balance,
            )

        if spend <= 0:
            return TradeResult(
                success=False,
                executed=False,
                signal="BUY",
                reason="Calculated spend is 0",
                balance_before=balance,
            )

        try:
            f = self.client.get_symbol_filters(symbol)
            min_notional = float(f.get("minNotional") or 0)
        except Exception as e:
            self._log_event(
                "WARN", "filters", f"Failed to load symbol filters: {e}", symbol=symbol
            )
            min_notional = 0.0

        try:
            from src.safety.risk_engine import default_limits_from_env

            max_cap = float(default_limits_from_env().max_trade_notional_usdt)
        except Exception:
            max_cap = 0.0

        spend_f = float(spend)
        if min_notional > 0 and spend_f < min_notional:
            return TradeResult(
                success=True,
                executed=False,
                signal="BUY",
                reason=(
                    f"exchange minNotional ({min_notional:.2f}) exceeds "
                    f"requested spend ({spend_f:.2f}); order not increased"
                ),
                balance_before=balance,
            )

        target_spend = spend_f
        if max_cap > 0 and target_spend > max_cap:
            return TradeResult(
                success=True,
                executed=False,
                signal="BUY",
                reason=(
                    f"requested spend ({target_spend:.2f}) exceeds "
                    f"max_trade_notional ({max_cap:.2f})"
                ),
                balance_before=balance,
            )

        # Can't spend more than balance
        if target_spend > balance:
            return TradeResult(
                success=True,
                executed=False,
                signal="BUY",
                reason=f"Insufficient balance for MIN_NOTIONAL. balance={balance:.2f}, "
                f"required≈{target_spend:.2f}",
                balance_before=balance,
            )

        # Binance expects quoteOrderQty with proper precision (2 decimals is usually OK for USDT)
        quote_order_qty = f"{target_spend:.2f}"
        if float(quote_order_qty) <= 0:
            return TradeResult(
                success=False,
                executed=False,
                signal="BUY",
                reason="quoteOrderQty rounded to 0",
                balance_before=balance,
            )

        # Phase 2A: centralized pre-trade risk gate (last line of defence before live order).
        approx_qty = float(target_spend) / float(price) if price > 0 else 0.0
        client_order_id = (
            f"live-{symbol}-{int(datetime.utcnow().timestamp() * 1000)}"
        )
        decision, _req = self._run_pretrade_risk_check(
            symbol=symbol, side="BUY", price=float(price), quantity=approx_qty,
            client_order_id=client_order_id,
        )
        if not decision.approved:
            self._persist_risk_rejection(
                symbol=symbol, side="BUY", decision=decision,
                price=float(price), quantity=approx_qty,
            )
            return TradeResult(
                success=True,
                executed=False,
                signal="BUY",
                reason="risk_rejected:" + ",".join(decision.reason_codes or ["unknown"]),
                price=float(price),
                quantity=approx_qty,
                balance_before=balance,
                blocked=True,
            )

        order_response = self.client.create_order_market_buy(
            symbol=symbol,
            quote_order_qty=quote_order_qty,
        )

        order_id_raw = order_response.get("orderId")
        if order_id_raw is None:
            return TradeResult(
                success=False,
                executed=False,
                signal="BUY",
                reason="Binance did not return orderId",
                raw_order=order_response,
                balance_before=balance,
            )

        order_id = int(order_id_raw)

        order_info = self._sync_order_status(symbol, order_id)

        executed_qty = float(order_info.get("executedQty", "0") or 0)
        cum_quote = float(order_info.get("cummulativeQuoteQty", "0") or 0)
        status = str(order_info.get("status") or "NEW")
        order_type = str(order_info.get("type") or "MARKET")

        # Record DB order with actual status/type
        self._record_order(
            symbol=symbol,
            side="BUY",
            quantity=executed_qty,
            requested_price=price,
            executed_price=price,  # better: avg fill price if you compute it; ok for Phase-1
            order_response=order_response,
            order_type=order_type,
            status=status,
            client_order_id=client_order_id,
        )

        if executed_qty <= 0:
            return TradeResult(
                success=False,
                executed=False,
                signal="BUY",
                reason="Market buy returned zero executedQty",
                order_id=str(order_id),
                exchange_status=status,
                executed_qty=executed_qty,
                cummulative_quote_qty=cum_quote,
                raw_order=order_info,
                balance_before=balance,
            )

        position = self._create_position(
            symbol=symbol,
            entry_price=price,
            quantity=executed_qty,
        )

        self._log_event(
            "INFO",
            "trade",
            f"BUY(MARKET) {executed_qty:.8f} {symbol} @ {price:.2f} "
            f"(spend≈{cum_quote:.2f} USDT) status={status}",
            symbol=symbol,
        )

        return TradeResult(
            success=True,
            executed=True,
            signal="BUY",
            reason="Market buy executed + verified",
            order_id=str(order_id),
            price=price,
            quantity=executed_qty,
            balance_before=balance,
            balance_after=balance - float(cum_quote or target_spend),
            position_id=position.id,
            exchange_status=status,
            executed_qty=executed_qty,
            cummulative_quote_qty=cum_quote,
            raw_order=order_info,
        )

    def _execute_buy_paper(
        self, symbol: str, price: float, risk_pct: Optional[float]
    ) -> TradeResult:
        """Simulated market buy for Phase-1 audits (orderId paper-* in ORDERS + DB)."""
        from src.execution.execution_engine import execute_trade
        from src.execution.positions import update_position

        balance = self._get_usdt_balance()
        if balance <= 0:
            balance = 10_000.0
        _, spend = self._calculate_position_size(balance, price, risk_pct)
        if spend <= 0 or price <= 0:
            spend = 15.0
        qty = float(spend) / float(price)
        client_order_id = (
            f"paper-{symbol}-{int(datetime.utcnow().timestamp() * 1000)}"
        )

        # Phase 2A: centralized pre-trade risk gate (kill switch / caps / cooldown / dupes).
        decision, _req = self._run_pretrade_risk_check(
            symbol=symbol, side="BUY", price=float(price), quantity=qty,
            client_order_id=client_order_id,
        )
        if not decision.approved:
            self._persist_risk_rejection(
                symbol=symbol, side="BUY", decision=decision,
                price=float(price), quantity=qty,
            )
            return TradeResult(
                success=True,
                executed=False,
                signal="BUY",
                reason="risk_rejected:" + ",".join(decision.reason_codes or ["unknown"]),
                price=float(price),
                quantity=qty,
                balance_before=balance,
                blocked=True,
            )

        order = execute_trade(symbol, "BUY", float(price))
        oid = str(order.get("orderId", ""))
        order_row = self._record_order(
            symbol=symbol,
            side="BUY",
            quantity=qty,
            requested_price=price,
            executed_price=price,
            order_response={"orderId": oid, "paper": True, "clientOrderId": client_order_id},
            order_type="MARKET",
            status="FILLED",
            mode="paper",
            client_order_id=client_order_id,
        )
        position = self._create_position(
            symbol=symbol,
            entry_price=price,
            quantity=qty,
            mode="paper",
        )
        # Keep in-memory paper proof tracker in sync (used by /exchange/proof paper_trading.*).
        try:
            update_position(order)
        except Exception:
            pass
        self._record_trade(
            symbol=symbol,
            side="BUY",
            quantity=qty,
            price=float(price),
            order_row=order_row,
            mode="paper",
        )
        self._log_event(
            "INFO",
            "trade",
            f"BUY(PAPER) {qty:.8f} {symbol} @ {price:.2f} orderId={oid}",
            symbol=symbol,
        )
        return TradeResult(
            success=True,
            executed=True,
            signal="BUY",
            reason="Phase-1 paper execution (PHASE1_PAPER_EXECUTION=true)",
            order_id=oid,
            price=price,
            quantity=qty,
            balance_before=balance,
            balance_after=balance - spend,
            position_id=position.id,
            exchange_status="FILLED",
        )

    def _execute_buy_shadow(
        self,
        symbol: str,
        price: float,
        risk_pct: Optional[float],
        stop_loss: Optional[float] = None,
    ) -> TradeResult:
        """
        Shadow market buy — real Binance balance + filters used for sizing,
        but the order itself is simulated. Persisted with mode='shadow' so
        live and shadow flows can be reconciled side-by-side.
        """
        from src.execution.execution_engine import simulate_shadow_fill

        balance, exchange_free, used_fallback = self._get_shadow_sizing_balance()
        if balance <= 0:
            return TradeResult(
                success=True,
                executed=False,
                signal="BUY",
                reason=(
                    "Shadow: no USDT on exchange and SHADOW_USE_FALLBACK_BALANCE=false"
                ),
                balance_before=exchange_free,
            )

        ok_sz, _qty, spend, sz_reason = self._position_size_from_risk(
            balance=balance, price=price, stop_loss=stop_loss, risk_pct=risk_pct,
        )
        if not ok_sz or spend <= 0:
            return TradeResult(
                success=True,
                executed=False,
                signal="BUY",
                reason=f"position_sizing_blocked:{sz_reason or 'spend<=0'}",
                balance_before=balance,
            )

        try:
            f = self.client.get_symbol_filters(symbol)
            min_notional = float(f.get("minNotional") or 0)
        except Exception as e:
            self._log_event(
                "WARN", "filters", f"shadow filters lookup failed: {e}", symbol=symbol
            )
            min_notional = 0.0

        target_spend = (
            max(float(spend), min_notional * 1.05) if min_notional > 0 else float(spend)
        )
        # Never let exchange minNotional bump push the order above the Phase 2A
        # absolute max-trade notional (limit itself is unchanged).
        try:
            from src.safety.risk_engine import default_limits_from_env

            max_n = float(default_limits_from_env().max_trade_notional_usdt)
            if max_n > 0 and target_spend > max_n:
                if min_notional > 0 and (min_notional * 1.05) > max_n:
                    return TradeResult(
                        success=True,
                        executed=False,
                        signal="BUY",
                        reason=(
                            f"shadow: exchange minNotional ({min_notional:.2f}) "
                            f"exceeds max_trade_notional ({max_n:.2f})"
                        ),
                        balance_before=balance,
                    )
                target_spend = max_n
        except Exception:
            pass
        if target_spend > balance:
            return TradeResult(
                success=True,
                executed=False,
                signal="BUY",
                reason=f"shadow: insufficient real balance for MIN_NOTIONAL "
                f"(balance={balance:.2f}, required≈{target_spend:.2f})",
                balance_before=balance,
            )

        qty = float(target_spend) / float(price) if price > 0 else 0.0

        client_order_id = f"shadow-{symbol}-{int(datetime.utcnow().timestamp() * 1000)}"
        decision, _req = self._run_pretrade_risk_check(
            symbol=symbol, side="BUY", price=float(price), quantity=qty,
            client_order_id=client_order_id,
        )
        if not decision.approved:
            self._persist_risk_rejection(
                symbol=symbol, side="BUY", decision=decision,
                price=float(price), quantity=qty,
            )
            return TradeResult(
                success=True,
                executed=False,
                signal="BUY",
                reason="risk_rejected:" + ",".join(decision.reason_codes or ["unknown"]),
                price=float(price),
                quantity=qty,
                balance_before=balance,
                blocked=True,
            )

        order = simulate_shadow_fill(
            symbol=symbol, action="BUY", price=float(price),
            quantity=qty, client_order_id=client_order_id,
        )
        oid = str(order.get("orderId", ""))
        order_row = self._record_order(
            symbol=symbol,
            side="BUY",
            quantity=qty,
            requested_price=price,
            executed_price=price,
            order_response={"orderId": oid, "clientOrderId": client_order_id,
                            "shadow": True},
            order_type="MARKET",
            status="FILLED",
            mode="shadow",
            client_order_id=client_order_id,
        )
        position = self._create_position(
            symbol=symbol, entry_price=price, quantity=qty, mode="shadow",
        )
        self._record_trade(
            symbol=symbol, side="BUY", quantity=qty,
            price=float(price), order_row=order_row, mode="shadow",
        )
        self._log_event(
            "INFO",
            "trade",
            f"BUY(SHADOW) {qty:.8f} {symbol} @ {price:.2f} orderId={oid} "
            f"clientOrderId={client_order_id}",
            symbol=symbol,
        )
        shadow_reason = (
            "Phase-2A shadow execution (fallback sizing balance; "
            f"exchange USDT={exchange_free:.2f}, simulated fill)"
            if used_fallback
            else "Phase-2A shadow execution (real balance, simulated fill)"
        )
        return TradeResult(
            success=True,
            executed=True,
            signal="BUY",
            reason=shadow_reason,
            order_id=oid,
            price=price,
            quantity=qty,
            balance_before=balance,
            balance_after=balance - target_spend,
            position_id=position.id,
            exchange_status="FILLED",
            executed_qty=qty,
            cummulative_quote_qty=float(target_spend),
        )

    def _execute_sell(
        self, symbol: str, position: Position, price: float
    ) -> TradeResult:
        if self.execution_mode == "paper":
            return self._execute_sell_paper(symbol=symbol, position=position, price=price)
        if self.execution_mode == "shadow":
            return self._execute_sell_shadow(symbol=symbol, position=position, price=price)

        blocked = self._phase2c_blocks_live()
        if blocked:
            return TradeResult(
                success=True,
                executed=False,
                signal="SELL",
                reason=f"phase2c_blocked:{blocked}",
                position_id=position.id,
                blocked=True,
            )

        qty = float(position.entry_qty or 0)

        if qty <= 0:
            return TradeResult(
                success=False,
                executed=False,
                signal="SELL",
                reason="Position has invalid quantity",
                position_id=position.id,
            )

        # Phase 2A: pre-trade risk gate (kill switch + sanity; exit-only checks skipped).
        client_order_id = (
            f"live-{symbol}-close-{int(datetime.utcnow().timestamp() * 1000)}"
        )
        decision, _req = self._run_pretrade_risk_check(
            symbol=symbol, side="SELL", price=float(price), quantity=qty,
            client_order_id=client_order_id,
        )
        if not decision.approved:
            self._persist_risk_rejection(
                symbol=symbol, side="SELL", decision=decision,
                price=float(price), quantity=qty,
            )
            return TradeResult(
                success=True,
                executed=False,
                signal="SELL",
                reason="risk_rejected:" + ",".join(decision.reason_codes or ["unknown"]),
                price=float(price),
                quantity=qty,
                position_id=position.id,
                blocked=True,
            )

        order_response = self.client.create_order_market_sell(
            symbol=symbol,
            quantity=f"{qty:.8f}",
        )

        order_id_raw = order_response.get("orderId")
        if order_id_raw is None:
            return TradeResult(
                success=False,
                executed=False,
                signal="SELL",
                reason="Binance did not return orderId",
                raw_order=order_response,
                position_id=position.id,
            )

        order_id = int(order_id_raw)

        order_info = self._sync_order_status(symbol, order_id)

        executed_qty = float(order_info.get("executedQty", "0") or 0)
        cum_quote = float(order_info.get("cummulativeQuoteQty", "0") or 0)
        status = str(order_info.get("status") or "NEW")
        order_type = str(order_info.get("type") or "MARKET")

        self._record_order(
            symbol=symbol,
            side="SELL",
            quantity=executed_qty,
            requested_price=price,
            executed_price=price,
            order_response=order_response,
            order_type=order_type,
            status=status,
            client_order_id=client_order_id,
        )

        # Close position using executed qty if available, otherwise fallback
        self._close_position(position, price, executed_qty or qty)

        # cooldown after loss
        if position.pnl is not None and position.pnl < 0:
            self.cooldown.trigger(
                datetime.utcnow(),
                self.risk_config.cooldown_minutes_after_loss,
            )
            self._log_event(
                "WARN",
                "trade",
                f"Loss trade - cooldown for {self.risk_config.cooldown_minutes_after_loss} min",
                symbol=symbol,
            )

        pnl_val = position.pnl if position.pnl is not None else 0.0
        pnl_pct = position.pnl_pct if position.pnl_pct is not None else 0.0

        self._log_event(
            "INFO",
            "trade",
            f"SELL(MARKET) {executed_qty:.8f} {symbol} @ {price:.2f} "
            f"(recv≈{cum_quote:.2f} USDT) status={status} P&L={pnl_val:.2f} ({pnl_pct:.2f}%)",
            symbol=symbol,
        )

        return TradeResult(
            success=True,
            executed=True,
            signal="SELL",
            reason=f"Market sell executed + verified (P&L: {pnl_pct:.2f}%)",
            order_id=str(order_id),
            price=price,
            quantity=executed_qty,
            position_id=position.id,
            exchange_status=status,
            executed_qty=executed_qty,
            cummulative_quote_qty=cum_quote,
            raw_order=order_info,
        )

    def _execute_sell_paper(
        self, *, symbol: str, position: Position, price: float
    ) -> TradeResult:
        """Simulated market sell for Phase-1 audits (orderId paper-* in ORDERS + DB)."""
        from src.execution.execution_engine import execute_trade

        qty = float(position.entry_qty or 0.0)
        if qty <= 0:
            return TradeResult(
                success=False,
                executed=False,
                signal="SELL",
                reason="Paper sell: position entry_qty is 0",
                position_id=position.id,
            )

        client_order_id = (
            f"paper-{symbol}-close-{int(datetime.utcnow().timestamp() * 1000)}"
        )
        # Phase 2A: pre-trade risk gate (mostly kill switch / sanity for exit flow).
        decision, _req = self._run_pretrade_risk_check(
            symbol=symbol, side="SELL", price=float(price), quantity=qty,
            client_order_id=client_order_id,
        )
        if not decision.approved:
            self._persist_risk_rejection(
                symbol=symbol, side="SELL", decision=decision,
                price=float(price), quantity=qty,
            )
            return TradeResult(
                success=True,
                executed=False,
                signal="SELL",
                reason="risk_rejected:" + ",".join(decision.reason_codes or ["unknown"]),
                price=float(price),
                quantity=qty,
                position_id=position.id,
                blocked=True,
            )

        order = execute_trade(symbol, "SELL", float(price))
        oid = str(order.get("orderId", ""))
        order_row = self._record_order(
            symbol=symbol,
            side="SELL",
            quantity=qty,
            requested_price=price,
            executed_price=price,
            order_response={"orderId": oid, "paper": True, "clientOrderId": client_order_id},
            order_type="MARKET",
            status="FILLED",
            mode="paper",
            client_order_id=client_order_id,
        )
        self._close_position(position, float(price), qty)
        self._record_trade(
            symbol=symbol,
            side="SELL",
            quantity=qty,
            price=float(price),
            order_row=order_row,
            mode="paper",
        )
        self._log_event(
            "INFO",
            "trade",
            f"SELL(PAPER) {qty:.8f} {symbol} @ {price:.2f} orderId={oid}",
            symbol=symbol,
        )
        return TradeResult(
            success=True,
            executed=True,
            signal="SELL",
            reason="Phase-1 paper execution (PHASE1_PAPER_EXECUTION=true)",
            order_id=oid,
            price=float(price),
            quantity=qty,
            position_id=position.id,
            exchange_status="FILLED",
        )

    def _execute_sell_shadow(
        self, *, symbol: str, position: Position, price: float
    ) -> TradeResult:
        """Shadow market sell — simulated fill, mode='shadow' rows in DB."""
        from src.execution.execution_engine import simulate_shadow_fill

        qty = float(position.entry_qty or 0.0)
        if qty <= 0:
            return TradeResult(
                success=False,
                executed=False,
                signal="SELL",
                reason="Shadow sell: position entry_qty is 0",
                position_id=position.id,
            )

        client_order_id = (
            f"shadow-{symbol}-close-{int(datetime.utcnow().timestamp() * 1000)}"
        )
        decision, _req = self._run_pretrade_risk_check(
            symbol=symbol, side="SELL", price=float(price), quantity=qty,
            client_order_id=client_order_id,
        )
        if not decision.approved:
            self._persist_risk_rejection(
                symbol=symbol, side="SELL", decision=decision,
                price=float(price), quantity=qty,
            )
            return TradeResult(
                success=True,
                executed=False,
                signal="SELL",
                reason="risk_rejected:" + ",".join(decision.reason_codes or ["unknown"]),
                price=float(price),
                quantity=qty,
                position_id=position.id,
                blocked=True,
            )

        order = simulate_shadow_fill(
            symbol=symbol, action="SELL", price=float(price),
            quantity=qty, client_order_id=client_order_id,
        )
        oid = str(order.get("orderId", ""))
        order_row = self._record_order(
            symbol=symbol,
            side="SELL",
            quantity=qty,
            requested_price=price,
            executed_price=price,
            order_response={"orderId": oid, "clientOrderId": client_order_id,
                            "shadow": True},
            order_type="MARKET",
            status="FILLED",
            mode="shadow",
            client_order_id=client_order_id,
        )
        self._close_position(position, float(price), qty)
        self._record_trade(
            symbol=symbol, side="SELL", quantity=qty,
            price=float(price), order_row=order_row, mode="shadow",
        )
        if position.pnl is not None and position.pnl < 0:
            self.cooldown.trigger(
                datetime.utcnow(),
                self.risk_config.cooldown_minutes_after_loss,
            )
        self._log_event(
            "INFO",
            "trade",
            f"SELL(SHADOW) {qty:.8f} {symbol} @ {price:.2f} orderId={oid} "
            f"clientOrderId={client_order_id}",
            symbol=symbol,
        )
        return TradeResult(
            success=True,
            executed=True,
            signal="SELL",
            reason="Phase-2A shadow execution (real balance, simulated fill)",
            order_id=oid,
            price=float(price),
            quantity=qty,
            position_id=position.id,
            exchange_status="FILLED",
            executed_qty=qty,
            cummulative_quote_qty=float(price) * qty,
        )
