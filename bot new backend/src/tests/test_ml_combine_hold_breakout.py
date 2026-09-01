"""ML + rule fusion: HOLD + directional ML breakout."""
from datetime import datetime
from unittest.mock import MagicMock

from src.live.auto_trade_engine import AutoTradeEngine, SignalType, TradeSignal


def _ts():
    return datetime.utcnow()


def test_combine_hold_breakout_prefers_ml_when_confident():
    eng = AutoTradeEngine(db=MagicMock())
    eng._log_event = MagicMock()  # noqa: SLF001
    eng.settings = MagicMock()
    eng.settings.ml_hold_breakout_enabled = True
    eng.settings.ml_hold_breakout_min_confidence = 0.58
    eng.settings.ml_override_threshold = 0.95
    eng.settings.ml_prioritize_threshold = 0.99
    eng.settings.ml_agree_threshold = 0.70

    rule = TradeSignal(
        signal=SignalType.HOLD,
        confidence=0.55,
        price=100.0,
        timestamp=_ts(),
        source="rule_based",
    )
    ml = TradeSignal(
        signal=SignalType.BUY,
        confidence=0.65,
        price=100.0,
        timestamp=_ts(),
        source="ml",
        metadata={"up": 0.7},
    )
    out = eng._combine_signals(rule, ml)
    assert out.source == "ml_hold_breakout"
    assert out.signal == SignalType.BUY
    assert out.confidence > 0.5


def test_ml_prioritize_when_very_high_confidence():
    eng = AutoTradeEngine(db=MagicMock())
    eng._log_event = MagicMock()  # noqa: SLF001
    eng.settings = MagicMock()
    eng.settings.ml_hold_breakout_enabled = True
    eng.settings.ml_hold_breakout_min_confidence = 0.58
    eng.settings.ml_override_threshold = 0.70
    eng.settings.ml_prioritize_threshold = 0.80
    eng.settings.ml_agree_threshold = 0.70

    rule = TradeSignal(
        signal=SignalType.SELL,
        confidence=0.6,
        price=100.0,
        timestamp=_ts(),
        source="rule_based",
    )
    ml = TradeSignal(
        signal=SignalType.BUY,
        confidence=0.85,
        price=100.0,
        timestamp=_ts(),
        source="ml",
    )
    out = eng._combine_signals(rule, ml)
    assert out.source == "ml_prioritize"
    assert out.signal == SignalType.BUY


def test_ml_moderate_influence_on_directional_conflict():
    """SELL vs BUY with softmax in [floor, override): follow ML."""
    eng = AutoTradeEngine(db=MagicMock())
    eng._log_event = MagicMock()  # noqa: SLF001
    eng.settings = MagicMock()
    eng.settings.ml_absolute_min_confidence = 0.50
    eng.settings.ml_hold_breakout_enabled = True
    eng.settings.ml_hold_breakout_min_confidence = 0.52
    eng.settings.ml_override_threshold = 0.60
    eng.settings.ml_prioritize_threshold = 0.70
    eng.settings.ml_agree_threshold = 0.70

    rule = TradeSignal(
        signal=SignalType.SELL,
        confidence=0.55,
        price=100.0,
        timestamp=_ts(),
        source="rule_based",
    )
    ml = TradeSignal(
        signal=SignalType.BUY,
        confidence=0.55,
        price=100.0,
        timestamp=_ts(),
        source="ml",
    )
    out = eng._combine_signals(rule, ml)
    assert out.source == "ml_moderate_influence"
    assert out.signal == SignalType.BUY


def test_combine_conflict_falls_back_when_ml_too_weak():
    eng = AutoTradeEngine(db=MagicMock())
    eng._log_event = MagicMock()  # noqa: SLF001
    eng.settings = MagicMock()
    eng.settings.ml_hold_breakout_enabled = True
    eng.settings.ml_hold_breakout_min_confidence = 0.58
    eng.settings.ml_override_threshold = 0.95
    eng.settings.ml_prioritize_threshold = 0.99
    eng.settings.ml_agree_threshold = 0.70

    rule = TradeSignal(
        signal=SignalType.HOLD,
        confidence=0.55,
        price=100.0,
        timestamp=_ts(),
        source="rule_based",
    )
    ml = TradeSignal(
        signal=SignalType.BUY,
        confidence=0.40,
        price=100.0,
        timestamp=_ts(),
        source="ml",
    )
    out = eng._combine_signals(rule, ml)
    assert out.signal == SignalType.HOLD
    assert out.source == "rule_only"


def test_rule_directional_ml_neutral_executes_buy_when_ml_holds():
    """Production case: SOL 1h rule=BUY, ml=HOLD must not collapse to conflict HOLD."""
    eng = AutoTradeEngine(db=MagicMock())
    eng._log_event = MagicMock()  # noqa: SLF001
    eng.settings = MagicMock()
    eng.settings.rule_directional_ml_neutral_enabled = True
    eng.settings.rule_directional_min_confidence = 0.55
    eng.settings.ml_hold_breakout_enabled = True
    eng.settings.ml_hold_breakout_min_confidence = 0.58
    eng.settings.ml_override_threshold = 0.95
    eng.settings.ml_prioritize_threshold = 0.99
    eng.settings.ml_agree_threshold = 0.70

    rule = TradeSignal(
        signal=SignalType.BUY,
        confidence=0.65,
        price=100.0,
        timestamp=_ts(),
        source="rule_based",
    )
    ml = TradeSignal(
        signal=SignalType.HOLD,
        confidence=0.48,
        price=100.0,
        timestamp=_ts(),
        source="ml",
    )
    out = eng._combine_signals(rule, ml, strict_ai=True)
    assert out.source == "rule_directional_ml_neutral"
    assert out.signal == SignalType.BUY
    assert out.confidence >= 0.55


def test_strict_ai_opposing_buy_sell_still_holds():
    eng = AutoTradeEngine(db=MagicMock())
    eng._log_event = MagicMock()  # noqa: SLF001
    eng.settings = MagicMock()
    eng.settings.rule_directional_ml_neutral_enabled = True
    eng.settings.rule_directional_min_confidence = 0.55
    eng.settings.ml_hold_breakout_enabled = True
    eng.settings.ml_hold_breakout_min_confidence = 0.58
    eng.settings.ml_absolute_min_confidence = 0.50
    eng.settings.ml_override_threshold = 0.95
    eng.settings.ml_prioritize_threshold = 0.99
    eng.settings.ml_agree_threshold = 0.70

    rule = TradeSignal(
        signal=SignalType.BUY,
        confidence=0.65,
        price=100.0,
        timestamp=_ts(),
        source="rule_based",
    )
    ml = TradeSignal(
        signal=SignalType.SELL,
        confidence=0.45,
        price=100.0,
        timestamp=_ts(),
        source="ml",
    )
    out = eng._combine_signals(rule, ml, strict_ai=True)
    assert out.source == "ml_rule_conflict_hold"
    assert out.signal == SignalType.HOLD
