"""
Multi-coin trading: canonical Binance spot symbols and display labels.

Display pairs map to Binance symbols. Model directories must match
``<BINANCE_SYMBOL>_<timeframe>`` (e.g. ``BTCUSDT_5m``) under ``ML_MODEL_DIR`` (often
``models``) — see ``src.ml.model_selector.resolve_model_selection``.
"""
from __future__ import annotations

import os
from typing import Final, List, Tuple

# Human-readable pairs (Step 1 spec)
SUPPORTED_SYMBOLS: Final[Tuple[str, ...]] = ("BTC/USDT", "ETH/USDT", "SOL/USDT")

_DEFAULT_BINANCE: Final[Tuple[str, ...]] = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


def normalize_binance_symbol(raw: str) -> str:
    """BTC/USDT, BTCUSDT, btc-usdt -> BTCUSDT."""
    s = raw.strip().upper().replace("/", "").replace("-", "")
    if not s.endswith("USDT"):
        raise ValueError(f"Unsupported quote; expected *USDT pair: {raw!r}")
    return s


def parse_supported_trading_symbols() -> Tuple[str, ...]:
    """
    Env SUPPORTED_TRADING_SYMBOLS: comma-separated, e.g.
    BTC/USDT,ETH/USDT,SOL/USDT or BTCUSDT,ETHUSDT,SOLUSDT
    """
    raw = os.getenv("SUPPORTED_TRADING_SYMBOLS", "").strip()
    if not raw:
        return _DEFAULT_BINANCE
    out: List[str] = []
    seen = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        sym = normalize_binance_symbol(part)
        if sym not in seen:
            seen.add(sym)
            out.append(sym)
    return tuple(out) if out else _DEFAULT_BINANCE


def display_for_binance(symbol: str) -> str:
    """BTCUSDT -> BTC/USDT"""
    s = symbol.upper().strip()
    if s.endswith("USDT") and len(s) > 4:
        base = s[:-4]
        return f"{base}/USDT"
    return s
