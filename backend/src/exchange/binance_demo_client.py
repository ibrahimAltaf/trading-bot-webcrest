# src/exchange/binance_demo_client.py
"""
Binance Demo Mode client.

Uses the same signed REST API as BinanceSpotClient but targets
  https://demo-api.binance.com/api
and uses separate BINANCE_DEMO_API_KEY / BINANCE_DEMO_API_SECRET
credentials obtained from https://demo.binance.com

Per the official docs:
  https://developers.binance.com/docs/binance-spot-api-docs/demo-mode/general-info
the Demo REST base URL is https://demo-api.binance.com/api and supports
the same endpoints as the live Spot API.
"""

from __future__ import annotations

import os
from src.exchange.binance_spot_client import BinanceSpotClient
from src.core.config import get_settings


class BinanceDemoClient(BinanceSpotClient):
    """
    Drop-in replacement for BinanceSpotClient that targets the Binance Demo
    trading environment (https://demo-api.binance.com/api).

    Credential resolution order:
      1. BINANCE_DEMO_API_KEY / BINANCE_DEMO_API_SECRET env vars (preferred).
      2. Falls back to BINANCE_API_KEY / BINANCE_API_SECRET when demo-specific
         keys are not set (e.g. the demo key is the active key in .env).
    """

    def __init__(self) -> None:
        s = get_settings()

        demo_key = s.binance_demo_api_key or os.getenv("BINANCE_API_KEY", "").strip()
        demo_secret = (
            s.binance_demo_api_secret or os.getenv("BINANCE_API_SECRET", "").strip()
        )

        if not demo_key or not demo_secret:
            raise RuntimeError(
                "Demo credentials missing. "
                "Set BINANCE_DEMO_API_KEY / BINANCE_DEMO_API_SECRET in .env "
                "(get keys from https://demo.binance.com)"
            )

        # Set required attributes directly — bypasses BinanceSpotClient.__init__
        # so we don't accidentally validate or use non-demo credentials.
        self.api_key = demo_key
        self.api_secret = demo_secret
        self.base_url = s.binance_demo_base_url
        # Single base URL; no testnet/mainnet failover needed for demo
        self._base_urls = [self.base_url]
        # _exchange_info_cache is a class-level dict, inherited automatically
