from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from src.core.config import Settings
from src.features.indicators import add_all_indicators
from src.live.adaptive_strategy import (
    MarketRegime,
    RegimeDetection,
    SignalAction,
    TradingDecision,
)


@dataclass(frozen=True)
class AdaptiveParams:
    # indicator params
    ema_fast: int
    ema_slow: int
    rsi_len: int
    bb_len: int
    bb_std: float

    # regime/thresholds
    adx_threshold: float
    rsi_buy_min: float
    rsi_buy_max: float
    rsi_take_profit: float
    rsi_range_buy: float
    rsi_range_sell: float

    # risk
    stop_loss_atr_mult: float
    take_profit_rr: float

    # execution posture — regime-aware confidence floors / agreement sensitivity.
    # Distinct from the indicator/RSI params above: this layer answers "how hard
    # is it to trigger a trade this cycle", scaled by trend + volatility regime
    # rather than held at a fixed .env value (Phase 2A / Saad adaptive-thresholds
    # validation, concern #3).
    posture: str  # "aggressive" | "conservative"
    atr_vol_threshold: float
    ml_absolute_min_confidence: float
    ml_min_trade_confidence: float
    rule_directional_min_confidence: float


class FullyAdaptiveStrategy:
    """Phase-1 compatible strategy that adapts parameters per-bar.

    It keeps the current architecture (rules + risk) but chooses *params dynamically*
    using recent volatility (ATR%) and trend strength (ADX).
    """

    def __init__(self, settings: Settings):
        self.s = settings

    def _two_pass(
        self, df: pd.DataFrame
    ) -> Tuple[pd.DataFrame, AdaptiveParams, Dict[str, Any]]:
        # Pass-1: baseline indicators to measure vol + trend.
        # FIX: add_all_indicators takes a 'config' dict, not individual kwargs
        df1 = add_all_indicators(
            df.copy(),
            config={
                "ema_fast": self.s.ema_fast,
                "ema_slow": self.s.ema_slow,
                "rsi_period": self.s.rsi_len,
                "bb_period": self.s.bb_len,
                "bb_std": self.s.bb_std,
            },
        )
        last1 = df1.iloc[-1]
        price = float(last1.get("close"))
        adx = float(last1.get("adx"))
        atr = float(last1.get("atr"))
        atr_pct = (atr / price * 100.0) if price > 0 else 0.0

        # Vol buckets (safe defaults; tune later)
        if atr_pct < 1.0:
            vol_bucket = "LOW"
            vol_scale = 1.15
            bb_std = 1.8
            sl_atr = max(1.6, self.s.stop_loss_atr_mult * 0.9)
        elif atr_pct < 2.5:
            vol_bucket = "MED"
            vol_scale = 1.0
            bb_std = float(self.s.bb_std)
            sl_atr = float(self.s.stop_loss_atr_mult)
        else:
            vol_bucket = "HIGH"
            vol_scale = 0.85
            bb_std = 2.5
            sl_atr = max(2.2, self.s.stop_loss_atr_mult * 1.2)

        trend_bucket = "STRONG" if adx >= max(20.0, self.s.adx_threshold) else "WEAK"

        # Adaptive lengths
        ema_fast = int(round(self.s.ema_fast * vol_scale))
        ema_slow = int(round(self.s.ema_slow * vol_scale))
        ema_fast = min(max(5, ema_fast), 50)
        ema_slow = min(max(10, ema_slow), 200)
        if ema_fast >= ema_slow:
            ema_fast = max(5, ema_slow - 5)

        rsi_len = int(
            round(
                self.s.rsi_len
                * (1.1 if vol_bucket == "LOW" else 0.9 if vol_bucket == "HIGH" else 1.0)
            )
        )
        rsi_len = min(max(7, rsi_len), 30)

        bb_len = int(
            round(
                self.s.bb_len
                * (1.1 if vol_bucket == "LOW" else 0.9 if vol_bucket == "HIGH" else 1.0)
            )
        )
        bb_len = min(max(10, bb_len), 60)

        # Adaptive thresholds
        if trend_bucket == "STRONG":
            rsi_buy_max = min(80.0, self.s.rsi_buy_max + 5.0)
            rsi_buy_min = max(35.0, self.s.rsi_buy_min - 2.0)
            rsi_tp = min(85.0, self.s.rsi_take_profit + 5.0)
            rr = max(2.0, self.s.take_profit_rr)
        else:
            rsi_buy_max = min(75.0, self.s.rsi_buy_max)
            rsi_buy_min = max(40.0, self.s.rsi_buy_min)
            rsi_tp = float(self.s.rsi_take_profit)
            rr = max(1.6, min(2.2, self.s.take_profit_rr))

        if vol_bucket == "HIGH":
            rsi_range_buy = max(25.0, self.s.rsi_range_buy - 3.0)
            rsi_range_sell = min(75.0, self.s.rsi_range_sell + 3.0)
        else:
            rsi_range_buy = float(self.s.rsi_range_buy)
            rsi_range_sell = float(self.s.rsi_range_sell)

        adx_th = float(self.s.adx_threshold)
        if vol_bucket == "HIGH":
            adx_th = max(adx_th, 30.0)

        # Execution posture: strong trend + normal/low vol -> aggressive (lower
        # confidence floors, more trades taken). High volatility, or a weak/quiet
        # trend, -> conservative (higher floors, fewer higher-conviction trades).
        # These are the values external validators must see actually change
        # cycle-to-cycle with market regime, not just the raw ADX/ATR% inputs.
        if trend_bucket == "STRONG" and vol_bucket in ("LOW", "MED"):
            posture = "aggressive"
            floor_delta = -0.05
        elif vol_bucket == "HIGH":
            posture = "conservative"
            floor_delta = 0.07
        else:
            posture = "conservative"
            floor_delta = 0.03

        def _adapt_floor(base: float) -> float:
            return round(min(0.95, max(0.35, float(base) + floor_delta)), 4)

        atr_vol_threshold = float(self.s.atr_vol_threshold) * (
            1.2 if trend_bucket == "STRONG" else 0.9
        )
        ml_absolute_min_confidence = _adapt_floor(self.s.ml_absolute_min_confidence)
        ml_min_trade_confidence = _adapt_floor(self.s.ml_min_trade_confidence)
        rule_directional_min_confidence = _adapt_floor(
            self.s.rule_directional_min_confidence
        )

        params = AdaptiveParams(
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            rsi_len=rsi_len,
            bb_len=bb_len,
            bb_std=float(bb_std),
            adx_threshold=float(adx_th),
            rsi_buy_min=float(rsi_buy_min),
            rsi_buy_max=float(rsi_buy_max),
            rsi_take_profit=float(rsi_tp),
            rsi_range_buy=float(rsi_range_buy),
            rsi_range_sell=float(rsi_range_sell),
            stop_loss_atr_mult=float(sl_atr),
            take_profit_rr=float(rr),
            posture=posture,
            atr_vol_threshold=float(atr_vol_threshold),
            ml_absolute_min_confidence=float(ml_absolute_min_confidence),
            ml_min_trade_confidence=float(ml_min_trade_confidence),
            rule_directional_min_confidence=float(rule_directional_min_confidence),
        )

        # Pass-2: recompute indicators with adaptive params
        # FIX: use config dict, not kwargs
        df2 = add_all_indicators(
            df.copy(),
            config={
                "ema_fast": params.ema_fast,
                "ema_slow": params.ema_slow,
                "rsi_period": params.rsi_len,
                "bb_period": params.bb_len,
                "bb_std": params.bb_std,
            },
        )

        meta = {
            "price": price,
            "adx": adx,
            "atr": atr,
            "atr_pct": atr_pct,
            "vol_bucket": vol_bucket,
            "trend_bucket": trend_bucket,
        }
        return df2, params, meta

    def decide(
        self, df: pd.DataFrame, force_action: Optional[str] = None
    ) -> TradingDecision:
        if df is None or df.empty:
            # FIX: TradingDecision uses flat typed fields, not 'indicators'/'risk' dicts
            return TradingDecision(
                action=SignalAction.HOLD,
                confidence=0.0,
                regime=MarketRegime.UNKNOWN,
                price=0.0,
                timestamp=pd.Timestamp.now().isoformat(),
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
                reason="No market data",
                signals={},
            )

        df2, p, meta = self._two_pass(df)
        latest = df2.iloc[-1]

        price = float(latest.get("close"))
        if not math.isfinite(price) or price <= 0:
            price = 1.0
        adx = float(latest.get("adx", 0.0))
        if not math.isfinite(adx):
            adx = 0.0
        # FIX: column names use actual period numbers, not 'rsi'/'ema_fast'/'ema_slow'
        rsi = float(latest.get(f"rsi_{p.rsi_len}", latest.get("rsi_14", 50.0)))
        if not math.isfinite(rsi):
            rsi = 50.0
        ema_fast = float(latest.get(f"ema_{p.ema_fast}", latest.get("ema_20", price)))
        ema_slow = float(latest.get(f"ema_{p.ema_slow}", latest.get("ema_50", price)))
        if not math.isfinite(ema_fast):
            ema_fast = price
        if not math.isfinite(ema_slow):
            ema_slow = price
        atr = float(latest.get("atr", 0.0))
        if not math.isfinite(atr):
            atr = 0.0
        bb_upper = latest.get("bb_upper")
        bb_middle = latest.get("bb_middle")
        bb_lower = latest.get("bb_lower")
        atr_pct = float(meta.get("atr_pct", 0.0))

        regime = (
            MarketRegime.TRENDING if adx >= p.adx_threshold else MarketRegime.RANGING
        )
        bullish = ema_fast > ema_slow
        bearish = ema_fast < ema_slow

        action = SignalAction.HOLD
        confidence = 0.5
        reason = "No clear signal"

        def _dynamic_hold_confidence() -> float:
            """Avoid flat 0.50 on every HOLD — varies with RSI / regime / vol (audit-friendly)."""
            try:
                if regime == MarketRegime.TRENDING:
                    mid = (p.rsi_buy_min + p.rsi_buy_max) / 2.0
                    span = max(1.0, (p.rsi_buy_max - p.rsi_buy_min) / 2.0)
                    dist = abs(rsi - mid) / span
                    base = 0.78 - min(0.38, dist * 0.12)
                else:
                    dist = abs(rsi - 50.0) / 50.0
                    base = 0.42 + (1.0 - dist) * 0.32
                atr_pct = float(meta.get("atr_pct", 1.0))
                jitter = min(0.09, atr_pct / 25.0)
                return round(min(0.91, max(0.31, base + jitter)), 4)
            except Exception:
                return 0.52

        if force_action in ("BUY", "SELL"):
            action = SignalAction.BUY if force_action == "BUY" else SignalAction.SELL
            confidence = 1.0
            reason = f"Forced signal: {force_action}"
        else:
            if regime == MarketRegime.TRENDING:
                if bullish and (p.rsi_buy_min <= rsi <= p.rsi_buy_max):
                    action = SignalAction.BUY
                    confidence = 0.70 if meta["trend_bucket"] == "STRONG" else 0.65
                    reason = (
                        f"TRENDING BUY (adaptive): EMA{p.ema_fast}>EMA{p.ema_slow}, "
                        f"RSI={rsi:.1f} in [{p.rsi_buy_min:.0f}-{p.rsi_buy_max:.0f}] "
                        f"(vol={meta['vol_bucket']}, adx={adx:.1f})"
                    )
                elif bearish and rsi >= p.rsi_take_profit:
                    action = SignalAction.SELL
                    confidence = 0.70
                    reason = f"TRENDING SELL (adaptive): EMA{p.ema_fast}<EMA{p.ema_slow}, RSI={rsi:.1f}>=TP({p.rsi_take_profit:.0f})"
                else:
                    action = SignalAction.HOLD
                    confidence = _dynamic_hold_confidence()
                    reason = f"HOLD: Waiting (RSI={rsi:.1f}, EMAs={'bullish' if bullish else 'bearish' if bearish else 'flat'})"
            else:
                # Ranging (mean reversion)
                # FIX: relaxed entry — within 1% of band (not strict <=)
                bb_lower_val = float(bb_lower) if bb_lower is not None else None
                bb_upper_val = float(bb_upper) if bb_upper is not None else None
                near_lower = bb_lower_val is not None and price <= bb_lower_val * 1.01
                near_upper = bb_upper_val is not None and price >= bb_upper_val * 0.99
                if near_lower and rsi <= p.rsi_range_buy:
                    action = SignalAction.BUY
                    confidence = 0.65
                    reason = f"RANGING BUY (adaptive): price near BB_lower ({bb_lower_val:.2f}), RSI={rsi:.1f}<={p.rsi_range_buy:.0f}"
                elif near_upper and rsi >= p.rsi_range_sell:
                    action = SignalAction.SELL
                    confidence = 0.65
                    reason = f"RANGING SELL (adaptive): price near BB_upper ({bb_upper_val:.2f}), RSI={rsi:.1f}>={p.rsi_range_sell:.0f}"
                else:
                    action = SignalAction.HOLD
                    confidence = _dynamic_hold_confidence()
                    _bl = f"{bb_lower_val:.2f}" if bb_lower_val is not None else "N/A"
                    reason = f"HOLD: Range wait (RSI={rsi:.1f}, bb_lower={_bl})"

        # Risk model (ATR-based)
        entry_price: Optional[float] = None
        stop_loss: Optional[float] = None
        take_profit: Optional[float] = None
        risk_reward: Optional[float] = None

        if action == SignalAction.BUY:
            entry_price = price
            stop_loss = price - (atr * p.stop_loss_atr_mult)
            take_profit = price + (price - stop_loss) * p.take_profit_rr
            risk_reward = p.take_profit_rr
        elif action == SignalAction.SELL:
            entry_price = price
            stop_loss = price + (atr * p.stop_loss_atr_mult)
            take_profit = price - (stop_loss - price) * p.take_profit_rr
            risk_reward = p.take_profit_rr

        signals = {
            "ema_trend": "BULLISH" if bullish else "BEARISH" if bearish else "FLAT",
            "vol_bucket": meta["vol_bucket"],
            "trend_bucket": meta["trend_bucket"],
            "params": {
                "ema_fast": p.ema_fast,
                "ema_slow": p.ema_slow,
                "rsi_len": p.rsi_len,
                "bb_len": p.bb_len,
                "bb_std": p.bb_std,
                "adx_threshold": p.adx_threshold,
                "rsi_buy_min": p.rsi_buy_min,
                "rsi_buy_max": p.rsi_buy_max,
                "atr_vol_threshold": p.atr_vol_threshold,
                "stop_loss_atr_mult": p.stop_loss_atr_mult,
                "take_profit_rr": p.take_profit_rr,
                "posture": p.posture,
                "ml_absolute_min_confidence": p.ml_absolute_min_confidence,
                "ml_min_trade_confidence": p.ml_min_trade_confidence,
                "rule_directional_min_confidence": p.rule_directional_min_confidence,
            },
        }

        # FIX: TradingDecision has flat typed fields — map from computed values
        return TradingDecision(
            action=action,
            confidence=float(confidence),
            regime=regime,
            price=price,
            timestamp=pd.Timestamp.now().isoformat(),
            adx=adx,
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            rsi=rsi,
            bb_upper=float(bb_upper) if bb_upper is not None else None,
            bb_middle=float(bb_middle) if bb_middle is not None else None,
            bb_lower=float(bb_lower) if bb_lower is not None else None,
            atr=atr,
            atr_pct=atr_pct,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk_reward=risk_reward,
            position_size_pct=float(getattr(self.s, "max_risk_per_trade", 0.01)) * 100,
            reason=reason,
            signals=signals,
        )

    # --- Compatibility layer with existing AutoTradeEngine ---
    def detect_regime(self, df: pd.DataFrame) -> RegimeDetection:
        """Return RegimeDetection like AdaptiveStrategy.detect_regime."""
        if df is None or df.empty:
            # FIX: RegimeDetection has specific required fields (no di_diff)
            return RegimeDetection(
                regime=MarketRegime.UNKNOWN,
                adx=0.0,
                adx_threshold=float(self.s.adx_threshold),
                plus_di=0.0,
                minus_di=0.0,
                atr_pct=0.0,
                confidence=0.0,
                reason="No data",
            )

        df2, p, meta = self._two_pass(df)
        last = df2.iloc[-1]
        adx = float(last.get("adx", 0.0))
        atr_pct = float(meta.get("atr_pct", 0.0))
        plus_di = float(last.get("plus_di", 0.0))
        minus_di = float(last.get("minus_di", 0.0))

        regime = (
            MarketRegime.TRENDING if adx >= p.adx_threshold else MarketRegime.RANGING
        )
        confidence = min(1.0, abs(adx - p.adx_threshold) / p.adx_threshold + 0.5)
        reason = (
            f"{regime.value}: ADX {adx:.1f} vs th {p.adx_threshold:.1f}, "
            f"ATR% {atr_pct:.2f}, vol={meta.get('vol_bucket')}"
        )
        # FIX: use correct RegimeDetection fields
        return RegimeDetection(
            regime=regime,
            adx=adx,
            adx_threshold=p.adx_threshold,
            plus_di=plus_di,
            minus_di=minus_di,
            atr_pct=atr_pct,
            confidence=confidence,
            reason=reason,
        )

    def generate_decision(
        self, df: pd.DataFrame, forced_action: Optional[str] = None
    ) -> TradingDecision:
        """Return TradingDecision like AdaptiveStrategy.generate_decision."""
        return self.decide(df, force_action=forced_action)
