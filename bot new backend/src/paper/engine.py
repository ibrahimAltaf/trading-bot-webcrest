from datetime import datetime
from typing import Optional

from src.paper.market import get_latest_price
from src.paper.wallet import PaperWallet
from src.risk.rules import RiskConfig
from src.db.session import SessionLocal
from src.db.models import Order, Trade, Position


def run_paper_trade(
    symbol: str,
    wallet: PaperWallet,
    risk: RiskConfig,
):
    db = SessionLocal()

    price = get_latest_price(symbol)

    spend = wallet.balance * risk.max_position_pct
    fee = spend * risk.fee_pct
    qty = spend / price

    if not wallet.can_spend(spend + fee):
        return {"status": "skipped", "reason": "low balance"}

    # BUY
    wallet.debit(spend + fee)

    order = Order(
        mode="paper",
        symbol=symbol,
        side="BUY",
        order_type="MARKET",
        quantity=qty,
        executed_price=price,
        status="filled",
    )
    db.add(order)

    trade = Trade(
        mode="paper",
        symbol=symbol,
        side="BUY",
        quantity=qty,
        price=price,
        fee=fee,
        fee_asset="USDT",
    )
    db.add(trade)

    pos = Position(
        mode="paper",
        symbol=symbol,
        is_open=True,
        entry_price=price,
        entry_qty=qty,
        entry_ts=datetime.utcnow(),
    )
    db.add(pos)

    db.commit()
    db.close()

    return {
        "status": "filled",
        "price": price,
        "qty": qty,
        "balance": wallet.balance,
    }
