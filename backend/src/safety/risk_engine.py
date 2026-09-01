"""
Centralized pre-trade risk & safety engine (Phase 2A).

Single chokepoint for every order — paper / shadow / live — so live trading later
inherits exactly the same guard rails that the paper audit already passes.

Design goals
------------
* Pure validation: no side effects, no DB writes, no exchange calls.
* Deterministic + introspectable: every rejection carries machine-readable reason
  codes for dashboards/alerts.
* Composable: each check is an independent method returning `(ok, reason_code, detail)`
  so future checks (volatility filter, correlation, etc.) plug in without churn.

Caller workflow
---------------
    decision = RiskEngine(limits, kill_switch, current_state).validate(order_request)
    if not decision.approved:
        # log + alert + skip execution
        ...
    else:
        # proceed to mode-specific executor (paper / shadow / live)
        ...
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.execution.mode import ExecutionMode
from src.safety import kill_switch as _ks


# ----------------------------- typed contracts -------------------------------


@dataclass
class OrderRequest:
    """Incoming candidate order for validation."""

    symbol: str
    side: str  # "BUY" | "SELL"
    price: float
    quantity: float
    notional_usdt: Optional[float] = None  # if None, computed as price * qty
    mode: ExecutionMode = ExecutionMode.PAPER
    client_order_id: Optional[str] = None  # idempotency / duplicate detection
    source: str = "engine"  # e.g. "engine", "manual", "scheduler"
    ml_confidence: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def effective_notional(self) -> float:
        if self.notional_usdt is not None:
            return float(self.notional_usdt)
        return float(self.price or 0.0) * float(self.quantity or 0.0)


@dataclass
class RiskLimits:
    """All Phase 2A/2C configurable risk caps. Defaults are conservative."""

    max_trade_notional_usdt: float = 100.0
    max_open_positions: int = 3
    max_daily_loss_usdt: float = 50.0
    max_daily_orders: int = 50
    max_exposure_pct_of_balance: float = 0.30  # 30%
    min_order_notional_usdt: float = 5.0
    cooldown_seconds_after_loss: int = 60
    duplicate_window_seconds: int = 10  # reject same client_order_id within window
    require_kill_switch_release: bool = True
    # Optional: if set and order.ml_confidence < this, reject (live only by default).
    min_ml_confidence_for_live: Optional[float] = 0.55
    # Phase 2C — absolute caps (independent of adaptive AI thresholds)
    max_total_exposure_usdt: Optional[float] = None
    max_cumulative_loss_usdt: Optional[float] = None
    allowed_symbols: Optional[tuple] = None


@dataclass
class RiskDecision:
    """Outcome of `RiskEngine.validate()`."""

    approved: bool
    reasons: List[str] = field(default_factory=list)
    reason_codes: List[str] = field(default_factory=list)
    checks: List[Dict[str, Any]] = field(default_factory=list)
    adjustments: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "approved": self.approved,
            "reasons": list(self.reasons),
            "reason_codes": list(self.reason_codes),
            "checks": list(self.checks),
            "adjustments": dict(self.adjustments),
        }


# ----------------------------- engine ----------------------------------------


@dataclass
class _State:
    """Runtime snapshot the engine uses; provided by the caller."""

    open_positions_count: int = 0
    daily_realized_pnl_usdt: float = 0.0
    daily_orders_count: int = 0
    account_balance_usdt: float = 0.0
    last_loss_at: Optional[datetime] = None
    recent_client_order_ids: Dict[str, datetime] = field(default_factory=dict)
    current_total_exposure_usdt: float = 0.0
    cumulative_realized_pnl_usdt: float = 0.0


class RiskEngine:
    """
    Stateless validator — caller supplies a live snapshot of engine state.

    `now_fn` is injectable for deterministic tests.
    """

    def __init__(
        self,
        limits: Optional[RiskLimits] = None,
        *,
        state: Optional[_State] = None,
        now_fn: Callable[[], datetime] = datetime.utcnow,
        kill_switch_is_engaged: Optional[Callable[[], bool]] = None,
    ) -> None:
        self.limits = limits or RiskLimits()
        self.state = state or _State()
        self._now = now_fn
        self._ks_check = kill_switch_is_engaged or _ks.is_engaged

    # public ---------------------------------------------------------------

    def validate(self, req: OrderRequest) -> RiskDecision:
        checks: List[Dict[str, Any]] = []
        approved = True
        reasons: List[str] = []
        codes: List[str] = []

        for check in (
            self._check_kill_switch,
            self._check_side,
            self._check_symbol,
            self._check_symbol_whitelist,
            self._check_quantity,
            self._check_notional_min,
            self._check_notional_max,
            self._check_exposure_pct,
            self._check_total_exposure,
            self._check_open_positions,
            self._check_daily_orders,
            self._check_daily_loss,
            self._check_cumulative_loss,
            self._check_cooldown,
            self._check_duplicate,
            self._check_ml_confidence,
        ):
            ok, code, detail = check(req)
            checks.append(
                {
                    "name": check.__name__.lstrip("_"),
                    "ok": ok,
                    "code": code,
                    "detail": detail,
                }
            )
            if not ok:
                approved = False
                if code:
                    codes.append(code)
                if detail:
                    reasons.append(detail)

        return RiskDecision(
            approved=approved,
            reasons=reasons,
            reason_codes=codes,
            checks=checks,
        )

    # individual checks ----------------------------------------------------

    def _check_kill_switch(
        self, req: OrderRequest
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        if not self.limits.require_kill_switch_release:
            return True, None, None
        if self._ks_check():
            return False, "kill_switch_engaged", "kill switch is engaged"
        return True, None, None

    def _check_side(
        self, req: OrderRequest
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        side = (req.side or "").upper()
        if side not in ("BUY", "SELL"):
            return False, "invalid_side", f"side must be BUY or SELL, got {req.side!r}"
        return True, None, None

    def _check_symbol(
        self, req: OrderRequest
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        sym = (req.symbol or "").upper().strip()
        if not sym:
            return False, "missing_symbol", "symbol is required"
        return True, None, None

    def _check_symbol_whitelist(
        self, req: OrderRequest
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        allowed = self.limits.allowed_symbols
        if not allowed or req.mode != ExecutionMode.LIVE:
            return True, None, None
        sym = (req.symbol or "").upper().strip()
        if sym not in {s.upper() for s in allowed}:
            return (
                False,
                "symbol_not_allowed",
                f"symbol {sym!r} not in allowed list {list(allowed)}",
            )
        return True, None, None

    def _check_quantity(
        self, req: OrderRequest
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        if req.quantity is None or float(req.quantity) <= 0:
            return False, "invalid_quantity", f"quantity must be > 0, got {req.quantity!r}"
        return True, None, None

    def _check_notional_min(
        self, req: OrderRequest
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        n = req.effective_notional
        if n < self.limits.min_order_notional_usdt:
            return (
                False,
                "below_min_notional",
                f"notional {n:.4f} < min {self.limits.min_order_notional_usdt}",
            )
        return True, None, None

    def _check_notional_max(
        self, req: OrderRequest
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        # SELL is exit logic — never block closing an existing position by entry caps.
        if (req.side or "").upper() == "SELL":
            return True, None, None
        n = req.effective_notional
        if n > self.limits.max_trade_notional_usdt:
            return (
                False,
                "above_max_trade_notional",
                f"notional {n:.4f} > max {self.limits.max_trade_notional_usdt}",
            )
        return True, None, None

    def _check_exposure_pct(
        self, req: OrderRequest
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        # SELL reduces exposure — never block on exposure caps.
        if (req.side or "").upper() == "SELL":
            return True, None, None
        bal = float(self.state.account_balance_usdt or 0.0)
        if bal <= 0:
            return True, None, None  # cannot evaluate; skip rather than block
        pct = req.effective_notional / bal
        if pct > self.limits.max_exposure_pct_of_balance:
            return (
                False,
                "exposure_pct_exceeded",
                f"exposure {pct:.2%} > cap {self.limits.max_exposure_pct_of_balance:.2%}",
            )
        return True, None, None

    def _check_total_exposure(
        self, req: OrderRequest
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        cap = self.limits.max_total_exposure_usdt
        if cap is None or (req.side or "").upper() == "SELL":
            return True, None, None
        if req.mode != ExecutionMode.LIVE:
            return True, None, None
        projected = float(self.state.current_total_exposure_usdt or 0.0) + req.effective_notional
        if projected > float(cap):
            return (
                False,
                "max_total_exposure",
                f"total exposure {projected:.4f} > max {cap:.4f} USDT",
            )
        return True, None, None

    def _check_open_positions(
        self, req: OrderRequest
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        # Only BUY opens a new slot; SELL is closing flow.
        if (req.side or "").upper() != "BUY":
            return True, None, None
        if self.state.open_positions_count >= self.limits.max_open_positions:
            return (
                False,
                "max_open_positions",
                f"open_positions {self.state.open_positions_count} >= "
                f"max {self.limits.max_open_positions}",
            )
        return True, None, None

    def _check_daily_orders(
        self, req: OrderRequest
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        if self.state.daily_orders_count >= self.limits.max_daily_orders:
            return (
                False,
                "max_daily_orders",
                f"daily_orders {self.state.daily_orders_count} >= "
                f"max {self.limits.max_daily_orders}",
            )
        return True, None, None

    def _check_daily_loss(
        self, req: OrderRequest
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        loss = -float(self.state.daily_realized_pnl_usdt or 0.0)
        if loss > self.limits.max_daily_loss_usdt:
            return (
                False,
                "max_daily_loss",
                f"daily_loss {loss:.2f} > max {self.limits.max_daily_loss_usdt:.2f}",
            )
        return True, None, None

    def _check_cumulative_loss(
        self, req: OrderRequest
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        cap = self.limits.max_cumulative_loss_usdt
        if cap is None or (req.side or "").upper() == "SELL":
            return True, None, None
        if req.mode != ExecutionMode.LIVE:
            return True, None, None
        loss = -float(self.state.cumulative_realized_pnl_usdt or 0.0)
        if loss >= float(cap):
            return (
                False,
                "max_cumulative_loss",
                f"cumulative loss {loss:.2f} >= max {cap:.2f} USDT (Phase 2C)",
            )
        return True, None, None

    def _check_cooldown(
        self, req: OrderRequest
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        # SELL must always be allowed to close losing positions — only gate BUY entries.
        if (req.side or "").upper() == "SELL":
            return True, None, None
        last_loss = self.state.last_loss_at
        if last_loss is None:
            return True, None, None
        elapsed = (self._now() - last_loss).total_seconds()
        if elapsed < self.limits.cooldown_seconds_after_loss:
            return (
                False,
                "cooldown_after_loss",
                f"cooldown active ({elapsed:.0f}s elapsed of "
                f"{self.limits.cooldown_seconds_after_loss}s)",
            )
        return True, None, None

    def _check_duplicate(
        self, req: OrderRequest
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        if not req.client_order_id:
            return True, None, None
        seen = self.state.recent_client_order_ids.get(req.client_order_id)
        if seen is None:
            return True, None, None
        if (self._now() - seen).total_seconds() < self.limits.duplicate_window_seconds:
            return (
                False,
                "duplicate_client_order_id",
                f"client_order_id {req.client_order_id!r} replayed within "
                f"{self.limits.duplicate_window_seconds}s",
            )
        return True, None, None

    def _check_ml_confidence(
        self, req: OrderRequest
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        # SELL is exit logic; min-confidence gate is for opening live BUY entries only.
        if (req.side or "").upper() == "SELL":
            return True, None, None
        min_conf = self.limits.min_ml_confidence_for_live
        if (
            min_conf is None
            or req.mode != ExecutionMode.LIVE
            or req.ml_confidence is None
        ):
            return True, None, None
        if float(req.ml_confidence) < float(min_conf):
            return (
                False,
                "ml_confidence_below_min_for_live",
                f"ml_confidence {req.ml_confidence:.3f} < min {min_conf:.3f} for live",
            )
        return True, None, None


# ----------------------------- convenience -----------------------------------


def default_limits_from_env() -> RiskLimits:
    """Build RiskLimits from RISK_* env vars (all optional; defaults applied)."""
    import os as _os

    def _f(name: str, default: float) -> float:
        try:
            return float(_os.getenv(name, str(default)))
        except (TypeError, ValueError):
            return default

    def _i(name: str, default: int) -> int:
        try:
            return int(_os.getenv(name, str(default)))
        except (TypeError, ValueError):
            return default

    def _optf(name: str) -> Optional[float]:
        raw = _os.getenv(name, "").strip()
        if not raw:
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    allowed_raw = _os.getenv("RISK_ALLOWED_SYMBOLS", "").strip()
    allowed_symbols = None
    if allowed_raw:
        allowed_symbols = tuple(
            s.strip().upper() for s in allowed_raw.split(",") if s.strip()
        )

    return RiskLimits(
        max_trade_notional_usdt=_f("RISK_MAX_TRADE_NOTIONAL_USDT", 100.0),
        max_open_positions=_i("RISK_MAX_OPEN_POSITIONS", 3),
        max_daily_loss_usdt=_f("RISK_MAX_DAILY_LOSS_USDT", 50.0),
        max_daily_orders=_i("RISK_MAX_DAILY_ORDERS", 50),
        max_exposure_pct_of_balance=_f("RISK_MAX_EXPOSURE_PCT", 0.30),
        min_order_notional_usdt=_f("RISK_MIN_ORDER_NOTIONAL_USDT", 5.0),
        cooldown_seconds_after_loss=_i("RISK_COOLDOWN_SECONDS_AFTER_LOSS", 60),
        duplicate_window_seconds=_i("RISK_DUPLICATE_WINDOW_SECONDS", 10),
        require_kill_switch_release=(
            _os.getenv("RISK_REQUIRE_KILL_SWITCH_RELEASE", "true").strip().lower()
            in ("1", "true", "yes", "y")
        ),
        min_ml_confidence_for_live=_optf("RISK_MIN_ML_CONFIDENCE_FOR_LIVE") or 0.55,
        max_total_exposure_usdt=_optf("RISK_MAX_TOTAL_EXPOSURE_USDT"),
        max_cumulative_loss_usdt=_optf("RISK_MAX_CUMULATIVE_LOSS_USDT"),
        allowed_symbols=allowed_symbols,
    )
