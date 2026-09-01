from __future__ import annotations

import json
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from src.db.models import PortfolioSnapshot
from src.exchange.binance_spot_client import BinanceSpotClient


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _asset_usdt_value(client: BinanceSpotClient, asset: str, qty: float) -> float:
    if qty <= 0:
        return 0.0

    if asset == "USDT":
        return qty

    symbol = f"{asset}USDT"
    try:
        price = client.get_price(symbol)
        return qty * float(price)
    except Exception:
        return 0.0


def capture_portfolio_snapshot(
    db: Session,
    client: BinanceSpotClient,
    source: str = "manual",
) -> PortfolioSnapshot:
    """
    Capture current account balances and convert to total USDT value.
    Unknown assets without a direct <ASSET>USDT ticker are ignored in total.
    """
    account = client.account()

    assets: List[Dict[str, Any]] = []
    total_value_usdt = 0.0
    usdt_cash = 0.0

    for bal in account.get("balances", []) or []:
        asset = str(bal.get("asset", "")).upper().strip()
        free = _safe_float(bal.get("free", 0))
        locked = _safe_float(bal.get("locked", 0))
        qty_total = free + locked

        if not asset or qty_total <= 0:
            continue

        value_usdt = _asset_usdt_value(client, asset, qty_total)

        if asset == "USDT":
            usdt_cash = qty_total

        assets.append(
            {
                "asset": asset,
                "free": free,
                "locked": locked,
                "qty_total": qty_total,
                "value_usdt": value_usdt,
            }
        )
        total_value_usdt += value_usdt

    snapshot = PortfolioSnapshot(
        source=source,
        total_value_usdt=total_value_usdt,
        usdt_cash=usdt_cash,
        assets_json=json.dumps(assets),
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot
