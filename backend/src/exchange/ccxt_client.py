"""
CCXT-based exchange client from user's stored config.
Use when exchange routes are called with auth: load user's exchange_id, testnet, api_key, api_secret.
"""
from __future__ import annotations

from typing import Any, Optional

from src.db.session import SessionLocal
from src.db.models import ExchangeConfig


def get_ccxt_client_for_user(user_id: int) -> Optional[Any]:
    """
    Build a CCXT exchange instance from the user's ExchangeConfig.
    Returns None if no config or missing keys.
    """
    try:
        import ccxt
    except ImportError:
        return None

    db = SessionLocal()
    try:
        config = db.query(ExchangeConfig).filter(ExchangeConfig.user_id == user_id).first()
        if not config or not config.api_key or not config.api_secret:
            return None
        from src.core.config import get_settings as _gs
        from src.core.secrets_crypto import decrypt_optional

        secret = decrypt_optional(
            config.api_secret, _gs().secrets_encryption_key
        )
        exchange_id = (config.exchange_id or "binance").strip().lower()
        if exchange_id not in ccxt.exchanges:
            exchange_id = "binance"
        klass = getattr(ccxt, exchange_id)
        options = {}
        if config.testnet and exchange_id == "binance":
            options["defaultType"] = "spot"
            # Binance testnet
            options["sandbox"] = True
        client = klass(
            {
                "apiKey": config.api_key,
                "secret": secret,
                "enableRateLimit": True,
                "options": options,
            }
        )
        if config.testnet and exchange_id == "binance":
            client.set_sandbox_mode(True)
        return client
    finally:
        db.close()
