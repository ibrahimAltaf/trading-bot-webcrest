# src/api/routes_demo.py
"""
Binance Demo Mode API Routes
Base URL targeted: https://demo-api.binance.com/api

Endpoints:
  GET  /demo/balances               - All non-zero balances
  GET  /demo/balance/{asset}        - Single asset balance
  GET  /demo/orders/open            - All open orders (optionally filtered by symbol)
  GET  /demo/orders/{symbol}        - All orders for a symbol
  GET  /demo/order/{symbol}/{order_id} - Single order status
  POST /demo/order                  - Place a new order (market/limit, buy/sell)
  DELETE /demo/order/{symbol}/{order_id} - Cancel an open order
  GET  /demo/trades/{symbol}        - My trade history for a symbol
"""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.exchange.binance_demo_client import BinanceDemoClient

router = APIRouter(prefix="/demo", tags=["Demo Trading"])


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _client() -> BinanceDemoClient:
    try:
        return BinanceDemoClient()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


# ---------------------------------------------------------------------------
# Balance
# ---------------------------------------------------------------------------


@router.get("/balances", summary="Demo – All non-zero balances")
def demo_balances():
    """
    Returns every asset with a non-zero free or locked balance in the
    Binance Demo account.
    """
    try:
        data = _client().account()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    balances = []
    for b in data.get("balances", []):
        free = float(b.get("free", 0))
        locked = float(b.get("locked", 0))
        if free > 0 or locked > 0:
            balances.append(
                {
                    "asset": b["asset"],
                    "free": b["free"],
                    "locked": b["locked"],
                    "total": str(round(free + locked, 8)),
                }
            )

    return {"ok": True, "count": len(balances), "balances": balances}


@router.get("/balance/{asset}", summary="Demo – Single asset balance")
def demo_balance_asset(asset: str):
    """Get free / locked / total balance for a specific asset (e.g. USDT, BTC)."""
    try:
        data = _client().account()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    asset_upper = asset.upper().strip()
    for b in data.get("balances", []):
        if b.get("asset") == asset_upper:
            free = float(b.get("free", 0))
            locked = float(b.get("locked", 0))
            return {
                "ok": True,
                "asset": asset_upper,
                "free": b["free"],
                "locked": b["locked"],
                "total": str(round(free + locked, 8)),
            }

    raise HTTPException(
        status_code=404, detail=f"Asset '{asset_upper}' not found in demo account"
    )


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


@router.get("/orders/open", summary="Demo – Open orders")
def demo_open_orders(
    symbol: Optional[str] = Query(default=None, description="e.g. BTCUSDT")
):
    """
    Returns all open (active) orders.  Pass ?symbol=BTCUSDT to filter by pair.
    """
    try:
        data = _client().open_orders(symbol.upper().strip() if symbol else None)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"ok": True, "count": len(data), "orders": data}


@router.get("/orders/{symbol}", summary="Demo – All orders for a symbol")
def demo_all_orders(
    symbol: str,
    limit: int = Query(default=100, ge=1, le=500),
):
    """Get all orders (any status) for a trading pair. Max 500."""
    try:
        data = _client().all_orders(symbol.upper().strip(), limit=limit)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"ok": True, "count": len(data), "orders": data}


@router.get("/order/{symbol}/{order_id}", summary="Demo – Single order status")
def demo_get_order(symbol: str, order_id: int):
    """Query status of a specific order by orderId."""
    try:
        data = _client().get_order(symbol.upper().strip(), order_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"ok": True, "order": data}


# ---------------------------------------------------------------------------
# Place order
# ---------------------------------------------------------------------------


class DemoOrderIn(BaseModel):
    symbol: str = Field(..., min_length=5, description="e.g. BTCUSDT")
    side: Literal["BUY", "SELL"]
    order_type: Literal["MARKET", "LIMIT"] = Field(default="MARKET", alias="type")
    # MARKET BUY → quote_order_qty (USDT amount), or quantity (base qty)
    quote_order_qty: Optional[str] = Field(
        default=None,
        description="Quote asset amount for MARKET BUY (e.g. '100' = 100 USDT)",
    )
    quantity: Optional[str] = Field(
        default=None,
        description="Base asset quantity for LIMIT orders or MARKET SELL",
    )
    # LIMIT order fields
    price: Optional[str] = Field(
        default=None,
        description="Limit price (required for LIMIT orders)",
    )

    model_config = {"populate_by_name": True}


@router.post("/order", summary="Demo – Place a new order")
def demo_place_order(body: DemoOrderIn):
    """
    Place a market or limit order in the Binance Demo account.

    | type   | side | Required fields                    |
    |--------|------|------------------------------------|
    | MARKET | BUY  | quote_order_qty  (e.g. 100 USDT)   |
    | MARKET | SELL | quantity (base qty, e.g. 0.001 BTC) |
    | LIMIT  | BUY  | price + quantity                   |
    | LIMIT  | SELL | price + quantity                   |
    """
    client = _client()
    symbol = body.symbol.upper().strip()

    try:
        if body.order_type == "MARKET":
            if body.side == "BUY":
                if not body.quote_order_qty:
                    raise HTTPException(
                        status_code=422,
                        detail="quote_order_qty is required for MARKET BUY",
                    )
                result = client.create_order_market_buy(symbol, body.quote_order_qty)
            else:
                if not body.quantity:
                    raise HTTPException(
                        status_code=422,
                        detail="quantity is required for MARKET SELL",
                    )
                result = client.create_order_market_sell(symbol, body.quantity)

        else:  # LIMIT
            if not body.price or not body.quantity:
                raise HTTPException(
                    status_code=422,
                    detail="price and quantity are required for LIMIT orders",
                )
            if body.side == "BUY":
                result = client.create_order_limit_buy(
                    symbol, body.price, body.quantity
                )
            else:
                result = client._request(
                    "POST",
                    "/api/v3/order",
                    params={
                        "symbol": symbol,
                        "side": "SELL",
                        "type": "LIMIT",
                        "timeInForce": "GTC",
                        "price": body.price,
                        "quantity": body.quantity,
                    },
                    signed=True,
                )

    except HTTPException:
        raise
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return {"ok": True, "order": result}


# ---------------------------------------------------------------------------
# Cancel order
# ---------------------------------------------------------------------------


@router.delete("/order/{symbol}/{order_id}", summary="Demo – Cancel an open order")
def demo_cancel_order(symbol: str, order_id: int):
    """Cancel an open order in the Demo account."""
    try:
        result = _client().cancel_order(symbol.upper().strip(), order_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"ok": True, "cancelled": result}


# ---------------------------------------------------------------------------
# Trades
# ---------------------------------------------------------------------------


@router.get("/trades/{symbol}", summary="Demo – My trade history")
def demo_my_trades(
    symbol: str,
    limit: int = Query(default=100, ge=1, le=500),
):
    """
    Returns trade history for the given symbol from the Binance Demo account.
    Max 500 trades per request.
    """
    try:
        data = _client().my_trades(symbol.upper().strip(), limit=limit)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "ok": True,
        "symbol": symbol.upper().strip(),
        "count": len(data),
        "trades": data,
    }
