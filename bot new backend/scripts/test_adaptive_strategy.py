"""
Test script for Adaptive Trading Strategy

This script tests the adaptive strategy components without executing actual trades.
Useful for validating the setup and seeing decision logic in action.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.config import get_settings
from src.exchange.binance_spot_client import BinanceSpotClient
from src.features.indicators import add_all_indicators
from src.live.adaptive_strategy import AdaptiveStrategy
import pandas as pd


def test_indicators():
    """Test indicator calculations"""
    print("=" * 60)
    print("TEST 1: Indicator Calculations")
    print("=" * 60)

    try:
        client = BinanceSpotClient()
        klines = client.klines(symbol="BTCUSDT", interval="5m", limit=500)

        # Convert to DataFrame
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
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)

        # Add all indicators
        df = add_all_indicators(df)

        print(f"✅ Successfully calculated indicators")
        print(f"   Rows after indicators: {len(df)}")
        print(f"   Columns: {list(df.columns)}")
        print(f"\nLast row indicators:")
        last = df.iloc[-1]
        print(f"   Close: ${last['close']:.2f}")
        print(f"   EMA20: ${last['ema_20']:.2f}")
        print(f"   EMA50: ${last['ema_50']:.2f}")
        print(f"   RSI14: {last['rsi_14']:.2f}")
        print(f"   ADX: {last['adx']:.2f}")
        print(f"   BB Upper: ${last['bb_upper']:.2f}")
        print(f"   BB Lower: ${last['bb_lower']:.2f}")
        print(f"   ATR: ${last['atr']:.2f}")
        print()
        return df

    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback

        traceback.print_exc()
        return None


def test_regime_detection(df):
    """Test regime detection"""
    print("=" * 60)
    print("TEST 2: Regime Detection")
    print("=" * 60)

    try:
        settings = get_settings()
        config = {
            "adx_threshold": settings.adx_threshold,
            "atr_vol_threshold": settings.atr_vol_threshold,
            "ema_fast": settings.ema_fast,
            "ema_slow": settings.ema_slow,
            "rsi_len": settings.rsi_len,
            "rsi_buy_min": settings.rsi_buy_min,
            "rsi_buy_max": settings.rsi_buy_max,
            "rsi_take_profit": settings.rsi_take_profit,
            "bb_len": settings.bb_len,
            "bb_std": settings.bb_std,
            "rsi_range_buy": settings.rsi_range_buy,
            "rsi_range_sell": settings.rsi_range_sell,
            "max_risk_per_trade": settings.max_risk_per_trade,
            "stop_loss_atr_mult": settings.stop_loss_atr_mult,
            "take_profit_rr": settings.take_profit_rr,
        }

        strategy = AdaptiveStrategy(config)
        regime = strategy.detect_regime(df)

        print(f"✅ Regime Detection Complete")
        print(f"   Regime: {regime.regime.value}")
        print(f"   ADX: {regime.adx:.2f} (threshold: {regime.adx_threshold})")
        print(f"   +DI: {regime.plus_di:.2f}")
        print(f"   -DI: {regime.minus_di:.2f}")
        print(f"   ATR%: {regime.atr_pct:.3f}%")
        print(f"   Confidence: {regime.confidence:.2f}")
        print(f"   Reason: {regime.reason}")
        print()
        return strategy

    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback

        traceback.print_exc()
        return None


def test_decision_generation(df, strategy):
    """Test decision generation"""
    print("=" * 60)
    print("TEST 3: Decision Generation")
    print("=" * 60)

    try:
        decision = strategy.generate_decision(df)

        print(f"✅ Decision Generated")
        print(f"\n📊 DECISION SUMMARY:")
        print(f"   Action: {decision.action.value}")
        print(f"   Confidence: {decision.confidence:.2%}")
        print(f"   Regime: {decision.regime.value}")
        print(f"   Price: ${decision.price:.2f}")

        print(f"\n📈 INDICATORS:")
        print(f"   ADX: {decision.adx:.2f}")
        print(f"   EMA{strategy.config['ema_fast']}: ${decision.ema_fast:.2f}")
        print(f"   EMA{strategy.config['ema_slow']}: ${decision.ema_slow:.2f}")
        print(f"   RSI: {decision.rsi:.2f}")
        if decision.bb_upper:
            print(f"   BB Upper: ${decision.bb_upper:.2f}")
            print(f"   BB Lower: ${decision.bb_lower:.2f}")
        print(f"   ATR: ${decision.atr:.2f} ({decision.atr_pct:.3f}%)")

        if decision.entry_price:
            print(f"\n💰 RISK MANAGEMENT:")
            print(f"   Entry: ${decision.entry_price:.2f}")
            print(f"   Stop Loss: ${decision.stop_loss:.2f}")
            print(f"   Take Profit: ${decision.take_profit:.2f}")
            print(f"   Risk:Reward: 1:{decision.risk_reward:.2f}")
            print(f"   Position Size: {decision.position_size_pct:.2f}% of balance")

        print(f"\n📝 REASONING:")
        print(f"   {decision.reason}")

        print(f"\n🔍 DETAILED SIGNALS:")
        for key, value in decision.signals.items():
            print(f"   {key}: {value}")

        print()

    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback

        traceback.print_exc()


def main():
    print("\n")
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 10 + "ADAPTIVE TRADING STRATEGY TEST" + " " * 17 + "║")
    print("╚" + "=" * 58 + "╝")
    print()

    # Test 1: Indicators
    df = test_indicators()
    if df is None:
        print("❌ Test 1 failed. Cannot continue.")
        return

    # Test 2: Regime Detection
    strategy = test_regime_detection(df)
    if strategy is None:
        print("❌ Test 2 failed. Cannot continue.")
        return

    # Test 3: Decision Generation
    test_decision_generation(df, strategy)

    print("=" * 60)
    print("✅ ALL TESTS COMPLETED")
    print("=" * 60)
    print()
    print("Next steps:")
    print("  1. Start the API server: python -m uvicorn src.main:app --reload")
    print("  2. Test via API: POST http://localhost:8000/exchange/auto-trade")
    print("  3. View decisions: GET http://localhost:8000/exchange/decisions/recent")
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
    except Exception as e:
        print(f"\n\n❌ FATAL ERROR: {e}")
        import traceback

        traceback.print_exc()
