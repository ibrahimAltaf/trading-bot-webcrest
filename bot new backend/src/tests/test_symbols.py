from src.core.symbols import (
    SUPPORTED_SYMBOLS,
    display_for_binance,
    normalize_binance_symbol,
    parse_supported_trading_symbols,
)


def test_normalize_binance_symbol():
    assert normalize_binance_symbol("BTC/USDT") == "BTCUSDT"
    assert normalize_binance_symbol("ethusdt") == "ETHUSDT"


def test_display_for_binance():
    assert display_for_binance("BTCUSDT") == "BTC/USDT"


def test_default_supported():
    assert "BTCUSDT" in parse_supported_trading_symbols()
    assert SUPPORTED_SYMBOLS[0] == "BTC/USDT"
