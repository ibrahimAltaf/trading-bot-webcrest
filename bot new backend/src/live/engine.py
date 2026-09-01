from datetime import datetime

from src.live.binance_client import get_price, place_market_order
from src.db.session import SessionLocal
from src.db.models import Order, Trade
from src.risk.rules import RiskConfig


def run_live_trade(symbol: str, usdt_amount: float, risk: RiskConfig):
    db = SessionLocal()

    price = get_price(symbol)
    qty = usdt_amount / price

    order_resp = place_market_order(
        symbol=symbol,
        side="BUY",
        quantity=qty,
    )

    db.add(
        Order(
            mode="live",
            symbol=symbol,
            side="BUY",
            order_type="MARKET",
            quantity=qty,
            executed_price=price,
            status="filled",
            exchange_order_id=str(order_resp["orderId"]),
        )
    )

    db.add(
        Trade(
            mode="live",
            symbol=symbol,
            side="BUY",
            quantity=qty,
            price=price,
            fee=0,
            fee_asset="USDT",
            ts=datetime.utcnow(),
        )
    )

    db.commit()
    db.close()

    return {
        "symbol": symbol,
        "price": price,
        "qty": qty,
        "order_id": order_resp["orderId"],
    }
