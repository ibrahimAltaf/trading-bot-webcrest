from __future__ import annotations

from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Any, Dict, Literal, Optional

from src.core.config import get_settings
from src.paper.engine import run_paper_trade
from src.paper.wallet import PaperWallet
from src.risk.rules import RiskConfig

# Live/Testnet price (your existing helper)
from src.live.binance_client import get_price

# Use your signed Spot client (configure base_url to testnet in settings)
from src.exchange.binance_spot_client import BinanceSpotClient

# Database models
from src.db.models import Position, Trade, Order

router = APIRouter(prefix="/paper", tags=["paper"])
settings = get_settings()


class PaperIn(BaseModel):
    symbol: str = Field(default="BTCUSDT", min_length=5)
    timeframe: str = Field(default="1h")  # kept for future parity (signals/indicators)
    mode: Literal["simulate", "testnet"] = Field(
        default="simulate",
        description="simulate = internal paper wallet only; testnet = place real orders on Binance Spot Testnet",
    )

    # Paper wallet starting balance (only used in simulate mode)
    balance: float = Field(default=1000.0, gt=0)

    # Risk controls
    max_position_pct: float = Field(default=0.1, ge=0.0, le=1.0)
    stop_loss_pct: float = Field(default=0.02, ge=0.0, le=1.0)
    take_profit_pct: float = Field(default=0.04, ge=0.0, le=1.0)
    fee_pct: float = Field(default=0.001, ge=0.0, le=0.1)

    # Execution controls for testnet mode
    entry_offset_pct: float = Field(
        default=0.001,
        ge=0.0,
        le=0.02,
        description="Limit entry offset below current price (e.g. 0.001 = 0.1% below)",
    )

    # Optional: explicitly override quote balance in testnet mode (normally we read from account)
    override_usdt_balance: Optional[float] = Field(default=None, gt=0)


def _extract_usdt_balance(account: Dict[str, Any]) -> float:
    balances = account.get("balances", []) or []
    for b in balances:
        if b.get("asset") == "USDT":
            try:
                return float(b.get("free", "0") or 0)
            except Exception:
                return 0.0
    return 0.0


@router.post("/run")
def run_paper(body: PaperIn):
    """
    - simulate mode: internal wallet simulation
    - testnet mode: places a real LIMIT BUY on Binance Spot Testnet and returns orderId
    - always returns SL/TP plan and sizing details for transparency
    """
    try:
        symbol = body.symbol.upper().strip()

        # 1) Build risk config (enforced consistently)
        risk = RiskConfig(
            max_position_pct=body.max_position_pct,
            stop_loss_pct=body.stop_loss_pct,
            take_profit_pct=body.take_profit_pct,
            fee_pct=body.fee_pct,
        )

        # 2) Fetch live price (for both modes)
        px = float(get_price(symbol))
        if px <= 0:
            raise HTTPException(status_code=400, detail="Invalid market price returned")

        # 3) Compute sizing
        # In testnet mode, use actual testnet USDT free balance unless overridden
        testnet_snapshot: Optional[Dict[str, Any]] = None
        usdt_balance_used: float

        if body.mode == "testnet":
            client = BinanceSpotClient()
            account = client.account()
            usdt_free = _extract_usdt_balance(account)

            if body.override_usdt_balance is not None:
                usdt_balance_used = float(body.override_usdt_balance)
            else:
                usdt_balance_used = float(usdt_free)

            testnet_snapshot = {
                "source": (
                    "binance_testnet"
                    if getattr(settings, "binance_testnet", False)
                    else "binance"
                ),
                "usdt_free": usdt_free,
                "balances_nonzero": [
                    {
                        "asset": b.get("asset"),
                        "free": b.get("free"),
                        "locked": b.get("locked"),
                    }
                    for b in (account.get("balances", []) or [])
                    if float(b.get("free", 0) or 0) > 0
                    or float(b.get("locked", 0) or 0) > 0
                ],
            }
        else:
            usdt_balance_used = float(body.balance)

        spend = usdt_balance_used * float(risk.max_position_pct)
        if spend <= 0:
            raise HTTPException(
                status_code=400,
                detail="Computed spend is zero (check balance / max_position_pct)",
            )

        # 4) Entry price plan
        limit_entry_price = px * (1.0 - float(body.entry_offset_pct))

        # 5) SL/TP plan (for transparency)
        stop_loss_price = limit_entry_price * (1.0 - float(risk.stop_loss_pct))
        take_profit_price = limit_entry_price * (1.0 + float(risk.take_profit_pct))

        # 6) Quantity from spend/entry (client will normalize for LOT_SIZE in testnet mode)
        raw_qty = spend / limit_entry_price

        # 7) Execute per mode
        if body.mode == "simulate":
            wallet = PaperWallet(balance=usdt_balance_used)

            result = run_paper_trade(
                symbol=symbol,
                wallet=wallet,
                risk=risk,
            )

            return {
                "ok": True,
                "mode": "simulate",
                "symbol": symbol,
                "market_price": px,
                "plan": {
                    "balance_used": usdt_balance_used,
                    "max_position_pct": risk.max_position_pct,
                    "spend": spend,
                    "limit_entry_price": limit_entry_price,
                    "raw_qty": raw_qty,
                    "stop_loss_price": stop_loss_price,
                    "take_profit_price": take_profit_price,
                    "fee_pct": risk.fee_pct,
                },
                "result": result,
            }

        # testnet mode: place a real LIMIT BUY and return verifiable orderId
        client = BinanceSpotClient()

        # Let the client normalize price/qty (LOT_SIZE / PRICE_FILTER / MIN_NOTIONAL)
        norm = client.normalize_limit(
            symbol=symbol,
            price=str(limit_entry_price),
            quantity=str(raw_qty),
        )

        order = client.create_order_limit_buy(
            symbol=symbol,
            price=norm["price"],
            quantity=norm["quantity"],
        )

        return {
            "ok": True,
            "mode": "testnet",
            "symbol": symbol,
            "market_price": px,
            "plan": {
                "balance_used": usdt_balance_used,
                "max_position_pct": risk.max_position_pct,
                "spend": spend,
                "limit_entry_price_requested": limit_entry_price,
                "raw_qty": raw_qty,
                "normalized": norm,
                "stop_loss_price": stop_loss_price,
                "take_profit_price": take_profit_price,
                "fee_pct": risk.fee_pct,
            },
            "testnet": testnet_snapshot,
            "order": order,  # contains orderId, status, executedQty, etc.
            "note": "SL/TP are planned values. To auto-place SL/TP on testnet, add OCO support (see below).",
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/price/{symbol}")
def paper_price(symbol: str):
    """
    Price endpoint used by paper trading.
    """
    sym = symbol.upper().strip()
    px = float(get_price(sym))
    return {
        "ok": True,
        "symbol": sym,
        "price": px,
        "source": (
            "binance_testnet"
            if getattr(settings, "binance_testnet", False)
            else "binance"
        ),
    }


@router.get("/positions")
def get_paper_positions(symbol: Optional[str] = None, is_open: Optional[bool] = None):
    """
    Get paper trading positions (open and/or closed).
    
    Query params:
    - symbol: Filter by symbol (e.g., BTCUSDT)
    - is_open: Filter by open status (true=open only, false=closed only, null=all)
    """
    try:
        from src.db.session import SessionLocal
        
        db = SessionLocal()
        
        # Start with paper mode positions
        query = db.query(Position).filter(Position.mode == "paper")
        
        # Filter by symbol if provided
        if symbol:
            query = query.filter(Position.symbol == symbol.upper().strip())
        
        # Filter by open status if provided
        if is_open is not None:
            query = query.filter(Position.is_open == is_open)
        
        positions = query.order_by(Position.entry_ts.desc()).all()
        db.close()
        
        result = []
        for pos in positions:
            result.append({
                "id": pos.id,
                "symbol": pos.symbol,
                "is_open": pos.is_open,
                "entry_price": pos.entry_price,
                "entry_qty": pos.entry_qty,
                "entry_ts": pos.entry_ts.isoformat() if pos.entry_ts else None,
                "exit_price": pos.exit_price,
                "exit_qty": pos.exit_qty,
                "exit_ts": pos.exit_ts.isoformat() if pos.exit_ts else None,
                "pnl": pos.pnl,
                "pnl_pct": pos.pnl_pct,
            })
        
        return {
            "ok": True,
            "count": len(result),
            "positions": result,
        }
    
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/wallet")
def get_paper_wallet():
    """
    Get current paper trading wallet balance and summary.
    
    Returns the current USDT balance and summary of open positions.
    """
    try:
        from src.db.session import SessionLocal
        
        db = SessionLocal()
        
        # Get all open paper positions
        open_positions = db.query(Position).filter(
            Position.mode == "paper",
            Position.is_open == True,
        ).all()
        
        # Calculate total value of open positions (at entry price for now)
        position_value = sum(
            (pos.entry_price or 0) * (pos.entry_qty or 0)
            for pos in open_positions
        )
        
        # Get sum of all paper trades to infer spent balance
        # (This is a simplification; in production, track wallet state separately)
        trades = db.query(Trade).filter(Trade.mode == "paper").all()
        total_spent = sum(
            t.price * t.quantity + (t.fee or 0)
            for t in trades
            if t.side == "BUY"
        )
        
        total_received = sum(
            t.price * t.quantity - (t.fee or 0)
            for t in trades
            if t.side == "SELL"
        )
        
        # Infer current cash (rough estimate)
        cash_balance = 1000.0 - total_spent + total_received  # Assume 1000 initial
        
        db.close()
        
        return {
            "ok": True,
            "mode": "paper",
            "cash_balance": max(0, cash_balance),  # Clamp to 0 minimum
            "position_value": position_value,
            "total_balance": max(0, cash_balance) + position_value,
            "open_positions_count": len(open_positions),
            "total_trades": len(trades),
        }
    
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


class ResetWalletBody(BaseModel):
    initial_balance: float = Field(default=1000.0, gt=0)


@router.post("/reset-wallet")
def reset_paper_wallet(body: ResetWalletBody):
    """
    Reset paper trading wallet (clear all positions and trades, start fresh).
    
    ⚠️ This is a destructive operation. Use with caution.
    """
    try:
        from src.db.session import SessionLocal
        
        db = SessionLocal()
        
        # Delete all paper mode records
        db.query(Trade).filter(Trade.mode == "paper").delete()
        db.query(Position).filter(Position.mode == "paper").delete()
        db.query(Order).filter(Order.mode == "paper").delete()
        
        db.commit()
        db.close()
        
        return {
            "ok": True,
            "message": "Paper wallet reset successfully",
            "initial_balance": body.initial_balance,
            "note": "All paper trades, positions, and orders have been deleted",
        }
    
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


class ClosePositionBody(BaseModel):
    position_id: int = Field(..., gt=0)
    exit_price: Optional[float] = Field(default=None, gt=0, description="If not provided, uses current market price")


@router.post("/close")
def close_paper_position(body: ClosePositionBody):
    """
    Close an open paper trading position and calculate PnL.
    
    - position_id: ID of the position to close
    - exit_price: Exit price (optional; if not provided, uses current market price)
    
    Returns the closed position with PnL details.
    """
    try:
        from src.db.session import SessionLocal
        
        db = SessionLocal()
        
        # Get the position
        position = db.query(Position).filter(Position.id == body.position_id).first()
        
        if not position:
            raise HTTPException(status_code=404, detail=f"Position {body.position_id} not found")
        
        if not position.is_open:
            raise HTTPException(status_code=400, detail=f"Position {body.position_id} is already closed")
        
        if position.mode != "paper":
            raise HTTPException(status_code=400, detail=f"Position {body.position_id} is not a paper trade")
        
        # Determine exit price
        exit_price = body.exit_price
        if exit_price is None:
            # Fetch current market price
            exit_price = float(get_price(position.symbol))
            if exit_price <= 0:
                raise HTTPException(status_code=400, detail="Invalid market price returned")
        
        # Calculate PnL
        entry_cost = (position.entry_price or 0) * (position.entry_qty or 0)
        exit_value = exit_price * (position.entry_qty or 0)
        pnl = exit_value - entry_cost
        pnl_pct = (pnl / entry_cost * 100) if entry_cost > 0 else 0.0
        
        # Update position (mark as closed)
        position.is_open = False
        position.exit_price = exit_price
        position.exit_qty = position.entry_qty  # Full exit
        position.exit_ts = datetime.utcnow()
        position.pnl = pnl
        position.pnl_pct = pnl_pct
        
        db.add(position)
        
        # Create corresponding SELL trade record for audit trail
        sell_trade = Trade(
            symbol=position.symbol,
            side="SELL",
            price=exit_price,
            quantity=position.entry_qty or 0,
            fee=((exit_price * (position.entry_qty or 0)) * (position.mode == "paper" and 0.001 or 0.0)),  # Default fee_pct
            mode="paper",
            ts=datetime.utcnow(),
        )
        db.add(sell_trade)
        
        db.commit()
        
        result = {
            "ok": True,
            "position_id": position.id,
            "symbol": position.symbol,
            "entry_price": position.entry_price,
            "entry_qty": position.entry_qty,
            "entry_ts": position.entry_ts.isoformat() if position.entry_ts else None,
            "exit_price": exit_price,
            "exit_qty": position.entry_qty,
            "exit_ts": position.exit_ts.isoformat() if position.exit_ts else None,
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "entry_cost": round(entry_cost, 2),
            "exit_value": round(exit_value, 2),
        }
        
        db.close()
        return result
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
