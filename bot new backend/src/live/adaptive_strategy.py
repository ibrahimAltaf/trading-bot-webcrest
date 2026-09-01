"""
Adaptive Trading Strategy - Regime Detection & Decision Engine

Implements two-regime adaptive strategy:
- Regime A (Trending): EMA crossover + RSI momentum
- Regime B (Ranging): Bollinger Bands mean-reversion

Full transparency: every decision includes numeric evidence.
"""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Any, Optional
import pandas as pd


class MarketRegime(Enum):
    """Market regime classification"""

    TRENDING = "TRENDING"
    RANGING = "RANGING"
    UNKNOWN = "UNKNOWN"


class SignalAction(Enum):
    """Trading signal actions"""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    # System blocked cycle: ML/runtime failure under ML_STRICT — not a market HOLD
    BLOCKED = "BLOCKED"


@dataclass
class RegimeDetection:
    """Results of market regime detection"""

    regime: MarketRegime
    adx: float
    adx_threshold: float
    plus_di: float
    minus_di: float
    atr_pct: float
    confidence: float
    reason: str


@dataclass
class TradingDecision:
    """
    Complete trading decision with full transparency.
    Contains all numeric evidence for dashboard display.
    """

    # Decision
    action: SignalAction
    confidence: float

    # Market State
    regime: MarketRegime
    price: float
    timestamp: str

    # Indicators (numeric evidence)
    adx: float
    ema_fast: float
    ema_slow: float
    rsi: float
    bb_upper: Optional[float]
    bb_middle: Optional[float]
    bb_lower: Optional[float]
    atr: float
    atr_pct: float

    # Risk Levels
    entry_price: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    risk_reward: Optional[float]
    position_size_pct: float

    # Reasoning
    reason: str
    signals: Dict[str, Any]  # Detailed signal breakdown

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            "action": self.action.value,
            "confidence": round(self.confidence, 3),
            "regime": self.regime.value,
            "price": round(self.price, 2),
            "timestamp": self.timestamp,
            "indicators": {
                "adx": round(self.adx, 2),
                "ema_fast": round(self.ema_fast, 2),
                "ema_slow": round(self.ema_slow, 2),
                "rsi": round(self.rsi, 2),
                "bb_upper": round(self.bb_upper, 2) if self.bb_upper else None,
                "bb_middle": round(self.bb_middle, 2) if self.bb_middle else None,
                "bb_lower": round(self.bb_lower, 2) if self.bb_lower else None,
                "atr": round(self.atr, 2),
                "atr_pct": round(self.atr_pct, 3),
            },
            "risk": {
                "entry": round(self.entry_price, 2) if self.entry_price else None,
                "stop_loss": round(self.stop_loss, 2) if self.stop_loss else None,
                "take_profit": round(self.take_profit, 2) if self.take_profit else None,
                "risk_reward": round(self.risk_reward, 2) if self.risk_reward else None,
                "position_size_pct": round(self.position_size_pct, 2),
            },
            "reason": self.reason,
            "signals": self.signals,
        }


class AdaptiveStrategy:
    """
    Adaptive trading strategy that switches between trending and ranging logic
    based on market regime detection.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize with configuration parameters.

        Args:
            config: Dictionary with all strategy parameters from Settings
        """
        self.config = config

    def detect_regime(self, df: pd.DataFrame) -> RegimeDetection:
        """
        Detect market regime using ADX and trend indicators.

        Args:
            df: DataFrame with all indicators calculated

        Returns:
            RegimeDetection with regime classification and evidence
        """
        last = df.iloc[-1]

        adx = float(last["adx"])
        adx_threshold = float(self.config.get("adx_threshold", 25.0))
        plus_di = float(last.get("plus_di", 0))
        minus_di = float(last.get("minus_di", 0))
        atr_pct = float(last.get("atr_pct", 0))

        if pd.isna(adx):
            return RegimeDetection(
                regime=MarketRegime.UNKNOWN,
                adx=0,
                adx_threshold=adx_threshold,
                plus_di=0,
                minus_di=0,
                atr_pct=0,
                confidence=0.0,
                reason="Insufficient data for ADX calculation",
            )

        # Determine regime
        if adx >= adx_threshold:
            regime = MarketRegime.TRENDING
            # Confidence based on how strong the trend is
            confidence = min(1.0, (adx - adx_threshold) / adx_threshold + 0.5)
            reason = f"ADX {adx:.1f} >= {adx_threshold:.1f} indicates trending market"
        else:
            regime = MarketRegime.RANGING
            # Confidence based on how much below threshold
            confidence = min(1.0, (adx_threshold - adx) / adx_threshold + 0.5)
            reason = f"ADX {adx:.1f} < {adx_threshold:.1f} indicates ranging market"

        return RegimeDetection(
            regime=regime,
            adx=adx,
            adx_threshold=adx_threshold,
            plus_di=plus_di,
            minus_di=minus_di,
            atr_pct=atr_pct,
            confidence=confidence,
            reason=reason,
        )

    def _calculate_risk_levels(
        self, entry_price: float, atr: float, action: SignalAction
    ) -> tuple[float, float]:
        """
        Calculate stop loss and take profit levels.

        Returns:
            (stop_loss, take_profit)
        """
        atr_mult = float(self.config.get("stop_loss_atr_mult", 2.0))
        rr_ratio = float(self.config.get("take_profit_rr", 2.0))

        if action == SignalAction.BUY:
            stop_loss = entry_price - (atr * atr_mult)
            risk_amount = entry_price - stop_loss
            take_profit = entry_price + (risk_amount * rr_ratio)
        elif action == SignalAction.SELL:
            stop_loss = entry_price + (atr * atr_mult)
            risk_amount = stop_loss - entry_price
            take_profit = entry_price - (risk_amount * rr_ratio)
        else:
            return (0, 0)

        return (stop_loss, take_profit)

    def decide_trending(
        self, df: pd.DataFrame, regime_info: RegimeDetection
    ) -> TradingDecision:
        """
        Generate trading decision for TRENDING market regime.

        Strategy:
        - BUY: EMA_fast > EMA_slow AND RSI in healthy range (45-70)
        - SELL: EMA_fast < EMA_slow OR RSI > 75 (take profit)
        """
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else last

        # Extract indicators
        ema_fast_col = f"ema_{self.config.get('ema_fast', 20)}"
        ema_slow_col = f"ema_{self.config.get('ema_slow', 50)}"
        rsi_col = f"rsi_{self.config.get('rsi_len', 14)}"

        price = float(last["close"])
        ema_fast = float(last[ema_fast_col])
        ema_slow = float(last[ema_slow_col])
        rsi = float(last[rsi_col])
        atr = float(last["atr"])
        atr_pct = float(last["atr_pct"])

        # Previous values for crossover detection
        prev_ema_fast = float(prev[ema_fast_col])
        prev_ema_slow = float(prev[ema_slow_col])

        # Signal detection
        bullish_crossover = (ema_fast > ema_slow) and (prev_ema_fast <= prev_ema_slow)
        bearish_crossover = (ema_fast < ema_slow) and (prev_ema_fast >= prev_ema_slow)

        # Optional: relax RSI bands for validation/testing (RELAXED_ENTRY_FOR_TESTING=true)
        relaxed = bool(self.config.get("relaxed_entry_for_testing", False))
        rsi_buy_min = float(self.config.get("rsi_buy_min", 45.0))
        rsi_buy_max = float(self.config.get("rsi_buy_max", 70.0))
        rsi_tp = float(self.config.get("rsi_take_profit", 75.0))
        if relaxed:
            rsi_buy_min = min(rsi_buy_min, 40.0)
            rsi_buy_max = max(rsi_buy_max, 75.0)
            rsi_tp = max(rsi_tp, 78.0)

        signals = {
            "ema_trend": "BULLISH" if ema_fast > ema_slow else "BEARISH",
            "bullish_crossover": bullish_crossover,
            "bearish_crossover": bearish_crossover,
            "rsi_level": "HEALTHY" if rsi_buy_min <= rsi <= rsi_buy_max else "EXTREME",
        }

        # Decision logic
        action = SignalAction.HOLD
        reason = ""
        confidence = 0.5

        # BUY conditions — relaxed: RSI range widened and lower bound removed in strong trends
        # Primary: bullish EMA cross + RSI not overbought
        if ema_fast > ema_slow and rsi < rsi_tp:
            if rsi_buy_min <= rsi <= rsi_buy_max:
                action = SignalAction.BUY
                confidence = 0.75 if bullish_crossover else 0.65
                reason = f"TRENDING BUY: EMA{self.config.get('ema_fast')}>EMA{self.config.get('ema_slow')}, RSI={rsi:.1f} in [{rsi_buy_min:.0f}-{rsi_buy_max:.0f}]"
            elif rsi < rsi_buy_min and bullish_crossover:
                # Fresh crossover even on RSI pullback — good entry
                action = SignalAction.BUY
                confidence = 0.70
                reason = f"TRENDING BUY (crossover pullback): fresh EMA cross, RSI={rsi:.1f} (below min={rsi_buy_min:.0f})"

        # SELL conditions
        elif rsi > rsi_tp:
            action = SignalAction.SELL
            confidence = 0.75
            reason = (
                f"TRENDING SELL: RSI={rsi:.1f} > {rsi_tp} (take profit - overbought)"
            )

        elif ema_fast < ema_slow:
            if bearish_crossover:
                action = SignalAction.SELL
                confidence = 0.80
                reason = f"TRENDING SELL: EMA{self.config.get('ema_fast')} crossed below EMA{self.config.get('ema_slow')} (trend reversal)"
            else:
                reason = f"HOLD: Bearish trend (EMA{self.config.get('ema_fast')} < EMA{self.config.get('ema_slow')}), no position"

        else:
            reason = f"HOLD: Waiting for clearer signal (RSI={rsi:.1f}, EMAs={'bullish' if ema_fast > ema_slow else 'bearish'})"

        if action == SignalAction.HOLD:
            dist = abs(rsi - 50.0) / 50.0
            confidence = round(
                0.36 + (1.0 - dist) * 0.30 + min(0.12, atr_pct / 30.0), 4
            )

        # Calculate risk levels
        entry_price = price
        stop_loss, take_profit = self._calculate_risk_levels(entry_price, atr, action)
        risk_reward = None
        if action != SignalAction.HOLD and stop_loss > 0:
            risk = abs(entry_price - stop_loss)
            reward = abs(take_profit - entry_price)
            risk_reward = reward / risk if risk > 0 else 0

        return TradingDecision(
            action=action,
            confidence=confidence,
            regime=regime_info.regime,
            price=price,
            timestamp=pd.Timestamp.now().isoformat(),
            adx=regime_info.adx,
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            rsi=rsi,
            bb_upper=None,
            bb_middle=None,
            bb_lower=None,
            atr=atr,
            atr_pct=atr_pct,
            entry_price=entry_price if action != SignalAction.HOLD else None,
            stop_loss=stop_loss if action != SignalAction.HOLD else None,
            take_profit=take_profit if action != SignalAction.HOLD else None,
            risk_reward=risk_reward,
            position_size_pct=float(self.config.get("max_risk_per_trade", 0.01)) * 100,
            reason=reason,
            signals=signals,
        )

    def decide_ranging(
        self, df: pd.DataFrame, regime_info: RegimeDetection
    ) -> TradingDecision:
        """
        Generate trading decision for RANGING market regime.

        Strategy:
        - BUY: Price touches lower BB AND RSI < 35 (oversold mean-reversion)
        - SELL: Price touches upper BB AND RSI > 65 (overbought mean-reversion)
        """
        last = df.iloc[-1]

        # Extract indicators
        rsi_col = f"rsi_{self.config.get('rsi_len', 14)}"

        price = float(last["close"])
        bb_upper = float(last["bb_upper"])
        bb_middle = float(last["bb_middle"])
        bb_lower = float(last["bb_lower"])
        rsi = float(last[rsi_col])
        atr = float(last["atr"])
        atr_pct = float(last["atr_pct"])

        # EMA values for display (not used in ranging logic)
        ema_fast_col = f"ema_{self.config.get('ema_fast', 20)}"
        ema_slow_col = f"ema_{self.config.get('ema_slow', 50)}"
        ema_fast = float(last[ema_fast_col])
        ema_slow = float(last[ema_slow_col])

        # Distance from bands (as % of price)
        dist_lower = ((price - bb_lower) / price) * 100
        dist_upper = ((bb_upper - price) / price) * 100

        relaxed = bool(self.config.get("relaxed_entry_for_testing", False))
        rsi_buy_threshold = float(self.config.get("rsi_range_buy", 35.0))
        rsi_sell_threshold = float(self.config.get("rsi_range_sell", 65.0))
        if relaxed:
            rsi_buy_threshold = min(rsi_buy_threshold, 40.0)
            rsi_sell_threshold = max(rsi_sell_threshold, 70.0)

        signals = {
            "bb_position": (
                "LOWER"
                if dist_lower < 1.0
                else "UPPER" if dist_upper < 1.0 else "MIDDLE"
            ),
            "rsi_level": (
                "OVERSOLD"
                if rsi < rsi_buy_threshold
                else "OVERBOUGHT" if rsi > rsi_sell_threshold else "NEUTRAL"
            ),
            "dist_lower_pct": round(dist_lower, 2),
            "dist_upper_pct": round(dist_upper, 2),
        }

        # Decision logic
        action = SignalAction.HOLD
        reason = ""
        confidence = 0.5

        # When relaxed, allow 5% from band; else 3%
        dist_threshold_lower = 5.0 if relaxed else 3.0
        dist_threshold_upper = 5.0 if relaxed else 3.0

        if dist_lower < dist_threshold_lower and rsi < rsi_buy_threshold:
            action = SignalAction.BUY
            confidence = 0.80 - (
                dist_lower * 0.05
            )  # Closer to band = higher confidence
            reason = f"RANGING BUY: Price near lower BB ({dist_lower:.1f}% away), RSI={rsi:.1f} < {rsi_buy_threshold} (oversold mean-reversion)"

        elif dist_upper < dist_threshold_upper and rsi > rsi_sell_threshold:
            action = SignalAction.SELL
            confidence = 0.80 - (dist_upper * 0.05)
            reason = f"RANGING SELL: Price near upper BB ({dist_upper:.1f}% away), RSI={rsi:.1f} > {rsi_sell_threshold} (overbought mean-reversion)"

        else:
            reason = f"HOLD: Price in middle of range (lower={dist_lower:.1f}%, upper={dist_upper:.1f}%), RSI={rsi:.1f} neutral"

        if action == SignalAction.HOLD:
            mid = (dist_lower + dist_upper) / 2.0
            confidence = round(
                0.40 + max(0.0, 1.0 - min(50.0, mid) / 50.0) * 0.35, 4
            )

        # Calculate risk levels
        entry_price = price
        stop_loss, take_profit = self._calculate_risk_levels(entry_price, atr, action)
        risk_reward = None
        if action != SignalAction.HOLD and stop_loss > 0:
            risk = abs(entry_price - stop_loss)
            reward = abs(take_profit - entry_price)
            risk_reward = reward / risk if risk > 0 else 0

        return TradingDecision(
            action=action,
            confidence=confidence,
            regime=regime_info.regime,
            price=price,
            timestamp=pd.Timestamp.now().isoformat(),
            adx=regime_info.adx,
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            rsi=rsi,
            bb_upper=bb_upper,
            bb_middle=bb_middle,
            bb_lower=bb_lower,
            atr=atr,
            atr_pct=atr_pct,
            entry_price=entry_price if action != SignalAction.HOLD else None,
            stop_loss=stop_loss if action != SignalAction.HOLD else None,
            take_profit=take_profit if action != SignalAction.HOLD else None,
            risk_reward=risk_reward,
            position_size_pct=float(self.config.get("max_risk_per_trade", 0.01)) * 100,
            reason=reason,
            signals=signals,
        )

    def generate_decision(self, df: pd.DataFrame) -> TradingDecision:
        """
        Main entry point: detect regime and generate appropriate decision.

        Args:
            df: DataFrame with all indicators calculated

        Returns:
            TradingDecision with full transparency
        """
        # Step 1: Detect market regime
        regime_info = self.detect_regime(df)

        # Step 2: Apply appropriate strategy
        if regime_info.regime == MarketRegime.TRENDING:
            return self.decide_trending(df, regime_info)
        elif regime_info.regime == MarketRegime.RANGING:
            return self.decide_ranging(df, regime_info)
        else:
            # Insufficient data
            last = df.iloc[-1]
            return TradingDecision(
                action=SignalAction.HOLD,
                confidence=0.0,
                regime=MarketRegime.UNKNOWN,
                price=float(last["close"]),
                timestamp=pd.Timestamp.now().isoformat(),
                adx=0,
                ema_fast=0,
                ema_slow=0,
                rsi=0,
                bb_upper=None,
                bb_middle=None,
                bb_lower=None,
                atr=0,
                atr_pct=0,
                entry_price=None,
                stop_loss=None,
                take_profit=None,
                risk_reward=None,
                position_size_pct=0,
                reason="Insufficient data for analysis",
                signals={},
            )
