"""
Enhanced Exchange Routes with Auto-Trading
Replaces your existing routes_exchange.py

BTC-only optimization:
- /exchange/portfolio/history computes ONLY for BTCUSDT
- Skips open_orders(symbol=None)
- Skips all_orders() (was only used for counts)
- Skips pricing "other assets"
"""

import json

from fastapi import APIRouter, HTTPException, Depends, Query, Header, status
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Set
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func, case

from src.core.config import get_settings
from src.core.json_safe import iso_utc
from src.api.deps_auth import admin_required
from src.execution.mode import ExecutionMode, get_execution_mode
from src.exchange.binance_spot_client import BinanceSpotClient
from src.db.session import SessionLocal
from src.db.models import Order as OrderModel
from src.live.auto_trade_engine import AutoTradeEngine
from src.live.portfolio import capture_portfolio_snapshot
from src.risk.rules import RiskConfig

settings = get_settings()

router = APIRouter(prefix="/exchange", tags=["Exchange"])


# === Dependency for DB session ===
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


_VALID_QUERY_MODES = frozenset({"live", "paper", "shadow", "backtest"})


def _normalize_query_mode(mode: str) -> str:
    """Validate mode query param for exchange audit endpoints."""
    m = str(mode).strip().lower()
    if m not in _VALID_QUERY_MODES:
        raise HTTPException(
            status_code=400,
            detail="mode must be one of: live, paper, shadow, backtest",
        )
    return m


def _order_dict_from_db_row(row: OrderModel, *, mode: str) -> Dict[str, Any]:
    oid = row.exchange_order_id or str(row.id)
    cid = row.client_order_id
    return {
        "orderId": oid,
        "clientOrderId": cid,
        # Audit scripts often expect snake_case aliases:
        "order_id": oid,
        "client_order_id": cid,
        # DB primary key — the authoritative join target for
        # TradingDecisionLog.order_id (see /safety/shadow-soak-report's
        # shadow_orders[].db_id for the same value). `orderId`/`order_id`
        # above are the exchange/shadow string identifier, NOT this key.
        "id": row.id,
        "db_id": row.id,
        "triggered_by": row.triggered_by,
        "cycle_id": row.cycle_id,
        "symbol": row.symbol,
        "side": row.side,
        "price": row.executed_price or row.requested_price,
        "quantity": row.quantity,
        "status": (row.status or "FILLED").upper(),
        "type": row.order_type or "MARKET",
        "execution_mode": mode,
        "timestamp": iso_utc(row.created_at),
    }


def _db_orders_for_mode(
    db: Session, mode: str, symbol: Optional[str], limit: int
) -> List[Dict[str, Any]]:
    q = db.query(OrderModel).filter(OrderModel.mode == mode)
    if symbol and str(symbol).strip():
        q = q.filter(OrderModel.symbol == str(symbol).strip().upper())
    rows = q.order_by(OrderModel.created_at.desc()).limit(limit).all()
    return [_order_dict_from_db_row(r, mode=mode) for r in rows]


def _memory_orders_for_mode(
    mode: str, symbol: Optional[str], limit: int
) -> List[Dict[str, Any]]:
    if mode == "paper":
        from src.execution.execution_engine import ORDERS as _src
    elif mode == "shadow":
        from src.execution.execution_engine import SHADOW_ORDERS as _src
    else:
        return []
    sym_u = str(symbol).strip().upper() if symbol and str(symbol).strip() else None
    items = [
        o
        for o in (_src or [])
        if isinstance(o, dict)
        and (not sym_u or str(o.get("symbol", "")).upper() == sym_u)
    ]
    return list(items[-limit:])


def _merge_orders_by_id(*lists: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Later lists win on conflicting fields (existing behavior). The DB
    primary key / trigger provenance (id, db_id, triggered_by, cycle_id) is
    only ever populated by the DB-sourced list, so it's preserved separately
    and re-applied after the merge — otherwise an in-memory tracker entry for
    the same orderId silently drops these fields (they'd never be present in
    that source), breaking decision-order correlation for external audits.
    """
    merged: Dict[str, Dict[str, Any]] = {}
    db_fields: Dict[str, Dict[str, Any]] = {}
    for lst in lists:
        for o in lst:
            oid = str(o.get("orderId") or "").strip()
            if not oid:
                continue
            if "db_id" in o:
                db_fields[oid] = {
                    k: o[k]
                    for k in ("id", "db_id", "triggered_by", "cycle_id")
                    if k in o
                }
            merged[oid] = o
    for oid, extra in db_fields.items():
        if oid in merged:
            merged[oid].update(extra)
    return list(merged.values())


def _simulated_orders_response(
    db: Session,
    *,
    mode: str,
    symbol: str,
    limit: int,
) -> Dict[str, Any]:
    """Paper/shadow order history from DB + in-memory trackers (newest first)."""
    safe_limit = max(1, min(int(limit), 1000))
    db_items = _db_orders_for_mode(db, mode, symbol, safe_limit)
    mem_items = _memory_orders_for_mode(mode, symbol, safe_limit)
    items = _merge_orders_by_id(db_items, mem_items)
    items.sort(key=lambda x: str(x.get("timestamp") or ""), reverse=True)
    items = items[:safe_limit]
    return {
        "ok": True,
        "symbol": symbol,
        "mode": mode,
        "count": len(items),
        "orders": items,
        "sources": {
            "db_count": len(db_items),
            "memory_count": len(mem_items),
        },
    }


def _asset_to_usdt_symbol(asset: str) -> Optional[str]:
    a = (asset or "").upper().strip()
    if not a or a == "USDT":
        return None
    return f"{a}USDT"


def _confidence_fields(parsed_signals: Dict[str, Any]) -> Dict[str, Any]:
    cycle_debug = (
        parsed_signals.get("cycle_debug")
        if isinstance(parsed_signals.get("cycle_debug"), dict)
        else {}
    )
    cycle_envelope = (
        parsed_signals.get("cycle_envelope")
        if isinstance(parsed_signals.get("cycle_envelope"), dict)
        else {}
    )
    return {
        "rule_confidence": parsed_signals.get(
            "rule_confidence",
            cycle_debug.get("rule_confidence", cycle_envelope.get("rule_confidence")),
        ),
        "ml_confidence": parsed_signals.get(
            "ml_confidence",
            cycle_debug.get("ml_confidence", cycle_envelope.get("ml_confidence")),
        ),
        "final_confidence": parsed_signals.get(
            "final_confidence",
            cycle_debug.get("final_confidence", cycle_envelope.get("final_confidence")),
        ),
        "confidence_source": parsed_signals.get(
            "confidence_source",
            cycle_debug.get(
                "confidence_source",
                cycle_envelope.get(
                    "confidence_source", parsed_signals.get("final_source")
                ),
            ),
        ),
    }


# === Balance Endpoints ===


@router.get("/balances")
def get_balances():
    """
    Returns all assets with non-zero balance (free or locked).
    """
    try:
        client = BinanceSpotClient()
        data = client.account()

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
                        "total": str(free + locked),
                    }
                )

        return {"ok": True, "count": len(balances), "balances": balances}

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/balance/{asset}")
def get_asset_balance(asset: str):
    """Get balance for a specific asset (e.g., USDT, BTC)"""
    try:
        client = BinanceSpotClient()
        data = client.account()

        asset_balance = next(
            (b for b in data.get("balances", []) if b.get("asset") == asset.upper()),
            None,
        )

        if not asset_balance:
            return {
                "ok": True,
                "asset": asset.upper(),
                "free": "0",
                "locked": "0",
                "total": "0",
            }

        free = float(asset_balance.get("free", 0))
        locked = float(asset_balance.get("locked", 0))

        return {
            "ok": True,
            "asset": asset.upper(),
            "free": asset_balance["free"],
            "locked": asset_balance["locked"],
            "total": str(free + locked),
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/portfolio/snapshot")
def create_portfolio_snapshot(db: Session = Depends(get_db), source: str = "manual"):
    """
    Capture one portfolio snapshot now.
    Frontend can call this before/after actions, or on interval polling.
    """
    try:
        client = BinanceSpotClient()
        snap = capture_portfolio_snapshot(db=db, client=client, source=source)
        return {
            "ok": True,
            "snapshot": {
                "id": snap.id,
                "ts": snap.ts,
                "source": snap.source,
                "total_value_usdt": snap.total_value_usdt,
                "usdt_cash": snap.usdt_cash,
            },
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/portfolio/history")
def get_portfolio_history(
    db: Session = Depends(get_db),
    limit: int = 200,
    period: str = "overall",
    days: Optional[int] = None,
    symbol: Optional[str] = None,
    max_symbols: int = 4,
):
    """
    Return portfolio value history + P&L computed from Binance balances/trades.

    BTC-only (for now):
    - Always computes using BTCUSDT only (ignores symbol/max_symbols)
    - Skips open_orders(all), all_orders(), and "other assets" valuation
    """
    try:
        safe_limit = max(2, min(int(limit), 2000))

        normalized_period = (period or "overall").strip().lower()
        if normalized_period in ("all", "overall"):
            start_ts = None
            normalized_period = "overall"
        elif normalized_period == "today":
            now = datetime.utcnow()
            start_ts = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif normalized_period in ("7d", "7days", "week"):
            start_ts = datetime.utcnow() - timedelta(days=7)
            normalized_period = "7days"
        elif normalized_period in ("30d", "month"):
            start_ts = datetime.utcnow() - timedelta(days=30)
            normalized_period = "month"
        elif normalized_period == "days":
            safe_days = int(days or 0)
            if safe_days < 1 or safe_days > 365:
                raise HTTPException(
                    status_code=400,
                    detail="When period=days, query param days must be between 1 and 365",
                )
            start_ts = datetime.utcnow() - timedelta(days=safe_days)
        else:
            raise HTTPException(
                status_code=400,
                detail="Invalid period. Use today, 7days, month, overall, or days",
            )

        client = BinanceSpotClient()
        account = client.account()
        balances = account.get("balances", []) or []

        balance_qty: Dict[str, float] = {}
        for b in balances:
            asset = str(b.get("asset", "")).upper().strip()
            qty_total = _safe_float(b.get("free", 0)) + _safe_float(b.get("locked", 0))
            if asset and qty_total > 0:
                balance_qty[asset] = qty_total

        # === BTC-only: force single symbol ===
        symbols: List[str] = ["BTCUSDT"]

        now = datetime.utcnow()
        now_ms = int(now.timestamp() * 1000)
        start_ms = int(start_ts.timestamp() * 1000) if start_ts is not None else None

        price_now: Dict[str, float] = {}

        def get_price_cached(sym: str) -> float:
            s = sym.upper().strip()
            if s in price_now:
                return price_now[s]
            try:
                px = float(client.get_price(s))
            except Exception:
                px = 0.0
            price_now[s] = px
            return px

        # Prime price cache
        get_price_cached("BTCUSDT")

        all_events: List[Dict[str, Any]] = []

        # === BTC-only: skip all_orders() entirely (was just for counts) ===
        orders_count = 0

        # Fetch trades (fills)
        try:
            trades = client.my_trades(symbol="BTCUSDT", limit=250)
        except Exception:
            trades = []

        # Track Binance order IDs to avoid double-counting with DB orders
        binance_order_ids: set = set()

        for t in trades or []:
            ts_ms = int(t.get("time", 0) or 0)
            if ts_ms <= 0:
                continue
            if ts_ms > now_ms:
                continue
            side = "BUY" if bool(t.get("isBuyer", False)) else "SELL"
            qty = _safe_float(t.get("qty", 0))
            quote_qty = _safe_float(t.get("quoteQty", 0))
            commission = _safe_float(t.get("commission", 0))
            commission_asset = str(t.get("commissionAsset", "")).upper().strip()
            fee_usdt = commission if commission_asset == "USDT" else 0.0

            oid = str(t.get("orderId", "")).strip()
            if oid:
                binance_order_ids.add(oid)

            all_events.append(
                {
                    "ts_ms": ts_ms,
                    "ts": datetime.utcfromtimestamp(ts_ms / 1000.0),
                    "symbol": "BTCUSDT",
                    "side": side,
                    "qty": qty,
                    "quote_qty": quote_qty,
                    "fee_usdt": fee_usdt,
                }
            )

        # Supplement with local DB live orders not already returned by Binance.
        # This covers cases where Binance API returns stale/limited results.
        try:
            db_orders = (
                db.query(OrderModel)
                .filter(
                    OrderModel.mode == "live",
                    OrderModel.symbol == "BTCUSDT",
                    OrderModel.status == "FILLED",
                    OrderModel.executed_price.isnot(None),
                    OrderModel.quantity > 0,
                )
                .order_by(OrderModel.created_at.asc())
                .all()
            )
            for o in db_orders:
                oid = str(o.exchange_order_id or "").strip()
                if oid and oid in binance_order_ids:
                    continue  # already present from Binance trades
                ts_ms = int(o.created_at.timestamp() * 1000)
                if ts_ms <= 0 or ts_ms > now_ms:
                    continue
                quote_qty = float(o.quantity or 0) * float(o.executed_price or 0)
                all_events.append(
                    {
                        "ts_ms": ts_ms,
                        "ts": o.created_at,
                        "symbol": "BTCUSDT",
                        "side": str(o.side or "BUY").upper(),
                        "qty": float(o.quantity or 0),
                        "quote_qty": quote_qty,
                        "fee_usdt": 0.0,
                    }
                )
        except Exception:
            pass

        all_events.sort(key=lambda x: x["ts_ms"])

        def compute_deltas(
            events: List[Dict[str, Any]],
        ) -> tuple[Dict[str, float], float]:
            qty_delta: Dict[str, float] = {}
            usdt_delta = 0.0
            for e in events:
                sym = str(e["symbol"])
                qty = float(e["qty"])
                quote_qty = float(e["quote_qty"])
                fee_usdt = float(e["fee_usdt"])

                if sym not in qty_delta:
                    qty_delta[sym] = 0.0

                if e["side"] == "BUY":
                    qty_delta[sym] += qty
                    usdt_delta -= quote_qty + fee_usdt
                else:
                    qty_delta[sym] -= qty
                    usdt_delta += quote_qty - fee_usdt
            return qty_delta, usdt_delta

        def symbol_asset(sym: str) -> str:
            s = sym.upper().strip()
            if s.endswith("USDT"):
                return s[:-4]
            return s

        tracked_assets = {symbol_asset(s) for s in symbols}

        current_usdt = float(balance_qty.get("USDT", 0.0))
        current_qty_by_symbol: Dict[str, float] = {
            "BTCUSDT": float(balance_qty.get("BTC", 0.0))
        }

        # === BTC-only: skip valuing other assets ===
        other_assets_value = 0.0

        def equity_value(usdt_value: float, qty_by_symbol: Dict[str, float]) -> float:
            total = usdt_value + other_assets_value
            for sym, qty in qty_by_symbol.items():
                total += qty * get_price_cached(sym)
            return total

        # Overall baseline based on all events we fetched (limited by trade limit)
        delta_all_qty, delta_all_usdt = compute_deltas(all_events)
        baseline_overall_usdt = current_usdt - delta_all_usdt
        baseline_overall_qty = {
            "BTCUSDT": current_qty_by_symbol.get("BTCUSDT", 0.0)
            - delta_all_qty.get("BTCUSDT", 0.0)
        }
        baseline_overall = equity_value(baseline_overall_usdt, baseline_overall_qty)
        latest_overall = equity_value(current_usdt, current_qty_by_symbol)
        pnl_abs_overall = latest_overall - baseline_overall
        pnl_pct_overall = (
            ((pnl_abs_overall / baseline_overall) * 100.0)
            if baseline_overall > 0
            else 0.0
        )

        period_events = (
            [e for e in all_events if int(e["ts_ms"]) >= int(start_ms)]
            if start_ms is not None
            else list(all_events)
        )

        delta_period_qty, delta_period_usdt = compute_deltas(period_events)
        baseline_usdt = current_usdt - delta_period_usdt
        baseline_qty = {
            "BTCUSDT": current_qty_by_symbol.get("BTCUSDT", 0.0)
            - delta_period_qty.get("BTCUSDT", 0.0)
        }
        baseline = equity_value(baseline_usdt, baseline_qty)
        latest = latest_overall

        range_pnl_abs = latest - baseline
        range_pnl_pct = ((range_pnl_abs / baseline) * 100.0) if baseline > 0 else 0.0

        points: List[Dict[str, Any]] = []
        state_usdt = baseline_usdt
        state_qty = dict(baseline_qty)

        for e in period_events:
            sym = str(e["symbol"])
            qty = float(e["qty"])
            quote_qty = float(e["quote_qty"])
            fee_usdt = float(e["fee_usdt"])

            if sym not in state_qty:
                state_qty[sym] = 0.0

            if e["side"] == "BUY":
                state_qty[sym] += qty
                state_usdt -= quote_qty + fee_usdt
            else:
                state_qty[sym] -= qty
                state_usdt += quote_qty - fee_usdt

            value = equity_value(state_usdt, state_qty)
            point_pnl_abs = value - baseline
            point_pnl_pct = (
                ((point_pnl_abs / baseline) * 100.0) if baseline > 0 else 0.0
            )

            points.append(
                {
                    "ts": e["ts"],
                    "value_usdt": value,
                    "pnl_abs": point_pnl_abs,
                    "pnl_pct": point_pnl_pct,
                    "source": "binance_trades",
                    "symbol": sym,
                    "side": e["side"],
                }
            )

        if len(points) > safe_limit:
            points = points[-safe_limit:]

        # === BTC-only: we skipped open_orders(all), so set to 0 ===
        open_orders_count = 0

        return {
            "ok": True,
            "period": normalized_period,
            "days": days,
            "count": len(points),
            "baseline": baseline,
            "latest": latest,
            "baseline_overall": baseline_overall,
            "latest_overall": latest_overall,
            "pnl_abs": range_pnl_abs,
            "pnl_pct": range_pnl_pct,
            "range_pnl_abs": range_pnl_abs,
            "range_pnl_pct": range_pnl_pct,
            "overall_pnl_abs": pnl_abs_overall,
            "overall_pnl_pct": pnl_pct_overall,
            "symbols": symbols,
            "trades_count": len(period_events),
            "orders_count": orders_count,
            "open_orders_count": open_orders_count,
            "points": points,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/ticker/price")
def get_ticker_price(symbol: str = "BTCUSDT"):
    """Current price for a symbol (for charts and display)."""
    try:
        client = BinanceSpotClient()
        price = client.get_price(symbol)
        return {"ok": True, "symbol": symbol, "price": float(price)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/klines")
def get_klines(
    symbol: str = "BTCUSDT",
    interval: str = "1h",
    limit: int = 100,
):
    """OHLCV klines for price chart. interval: 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 1d."""
    try:
        limit = max(10, min(500, int(limit)))
        client = BinanceSpotClient()
        rows = client.klines(symbol=symbol, interval=interval, limit=limit)
        # Binance returns [open_time, open, high, low, close, volume, ...]
        klines = [
            {
                "time": r[0] // 1000,
                "open": float(r[1]),
                "high": float(r[2]),
                "low": float(r[3]),
                "close": float(r[4]),
                "volume": float(r[5]),
            }
            for r in rows
        ]
        return {"ok": True, "symbol": symbol, "interval": interval, "klines": klines}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# === Order Endpoints ===


class LimitBuyBody(BaseModel):
    symbol: str = Field(default="BTCUSDT", min_length=5)
    price: str = Field(..., description="Limit price as string, e.g. '92000.00'")
    quantity: str = Field(..., description="Quantity as string, e.g. '0.001'")


class LimitSellBody(BaseModel):
    symbol: str = Field(default="BTCUSDT", min_length=5)
    price: str = Field(..., description="Limit price as string, e.g. '92000.00'")
    quantity: str = Field(..., description="Quantity as string, e.g. '0.001'")


@router.post("/order/limit-buy", summary="DISABLED — use AutoTradeEngine path")
def place_limit_buy_disabled():
    """Legacy manual limit buy — disabled for Phase 2C (bypassed RiskEngine)."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=(
            "POST /exchange/order/limit-buy is disabled for Phase 2C. "
            "All live order placement must use the centralized AutoTradeEngine path "
            "(scheduler or authenticated POST /exchange/auto-trade)."
        ),
    )


@router.post("/order/limit-sell", summary="DISABLED — use AutoTradeEngine path")
def place_limit_sell_disabled():
    """Legacy manual limit sell — disabled for Phase 2C (bypassed RiskEngine)."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=(
            "POST /exchange/order/limit-sell is disabled for Phase 2C. "
            "All live order placement must use the centralized AutoTradeEngine path "
            "(scheduler or authenticated POST /exchange/auto-trade)."
        ),
    )


class CancelOrderBody(BaseModel):
    symbol: str = Field(..., description="Trading pair, e.g. BTCUSDT")
    order_id: int = Field(..., description="Order ID to cancel")


@router.post("/order/cancel", summary="DISABLED — use AutoTradeEngine path")
def cancel_order_disabled():
    """Legacy manual cancel — disabled for Phase 2C (bypassed RiskEngine)."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=(
            "POST /exchange/order/cancel is disabled for Phase 2C. "
            "Order lifecycle must go through the centralized AutoTradeEngine path."
        ),
    )


@router.get("/order")
def get_order(symbol: str, order_id: int):
    try:
        client = BinanceSpotClient()
        res = client.get_order(symbol=symbol, order_id=order_id)
        return {"ok": True, "order": res}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/orders/open")
def get_open_orders(symbol: Optional[str] = None):
    """
    Shows current open orders (unfilled/partially filled).
    If symbol is omitted, returns open orders for all symbols.
    """
    try:
        client = BinanceSpotClient()
        orders = client.open_orders(symbol=symbol)
        return {"ok": True, "count": len(orders), "orders": orders}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/orders/all")
def get_all_orders(
    symbol: Optional[str] = None,
    limit: int = 200,
    mode: str = "live",
    db: Session = Depends(get_db),
):
    """
    Shows order history (NEW/FILLED/CANCELED/EXPIRED) for a symbol.

    API contract:
    - symbol: optional; if omitted, uses TRADE_SYMBOL from .env (default BTCUSDT).
    - limit: max orders (capped to 1000).
    """
    try:
        if not symbol or not str(symbol).strip():
            symbol = settings.trade_symbol.strip().upper()
        else:
            symbol = str(symbol).strip().upper()

        safe_limit = max(1, min(int(limit), 1000))
        m = _normalize_query_mode(mode)

        # Paper / shadow: DB rows + in-memory trackers (never Binance order history).
        if m in ("paper", "shadow"):
            return _simulated_orders_response(
                db, mode=m, symbol=symbol, limit=safe_limit
            )

        client = BinanceSpotClient()
        orders = client.all_orders(symbol=symbol, limit=safe_limit)
        return {"ok": True, "symbol": symbol, "mode": "live", "count": len(orders), "orders": orders}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/trades")
def get_my_trades(symbol: Optional[str] = None, limit: int = 200):
    """
    Shows executed trades (fills) for a symbol.
    If symbol is omitted, uses TRADE_SYMBOL from .env (default BTCUSDT).
    IMPORTANT: A LIMIT order will appear here only after it gets FILLED (or PARTIALLY filled).
    """
    try:
        if not symbol or not str(symbol).strip():
            symbol = settings.trade_symbol.strip().upper()
        else:
            symbol = str(symbol).strip().upper()

        client = BinanceSpotClient()
        trades = client.my_trades(symbol=symbol, limit=limit)
        return {"ok": True, "count": len(trades), "trades": trades}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# === AUTO-TRADING ENDPOINTS ===


class AutoTradeBody(BaseModel):
    symbol: str = Field(default="BTCUSDT", description="Trading pair")
    timeframe: str = Field(default="1h", description="Candle interval (1h, 4h, 1d)")
    risk_pct: Optional[float] = Field(
        default=None,
        ge=0.001,
        le=0.5,
        description="Risk % of balance per trade (0.001-0.5). Use 0.001 for small shadow audit proofs.",
    )
    force_signal: Optional[str] = Field(
        default=None,
        description="Force signal for testing: 'BUY', 'SELL', or 'HOLD'. Same as query ?force_signal= for audits.",
    )


def _require_admin_if_live(
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> Optional[str]:
    """Live-mode manual API calls require admin auth; paper/shadow remain open for audits."""
    if get_execution_mode() != ExecutionMode.LIVE:
        return None
    return admin_required(
        x_admin_token=x_admin_token,
        authorization=authorization,
    )


@router.post("/auto-trade")
def auto_trade(
    body: AutoTradeBody,
    db: Session = Depends(get_db),
    _live_admin: Optional[str] = Depends(_require_admin_if_live),
    symbol_q: Optional[str] = Query(
        default=None,
        alias="symbol",
        description="Optional override of body.symbol (audits often use curl ?symbol=).",
    ),
    timeframe_q: Optional[str] = Query(
        default=None,
        alias="timeframe",
        description="Optional override of body.timeframe.",
    ),
    risk_pct_q: Optional[float] = Query(
        default=None,
        alias="risk_pct",
        ge=0.01,
        le=0.5,
        description="Optional override of body.risk_pct.",
    ),
    force_signal_q: Optional[str] = Query(
        default=None,
        alias="force_signal",
        description="Optional override of body.force_signal. Required for curl-only query URLs.",
    ),
):
    """
    Enhanced auto-trading endpoint with:
    - ML + rule-based signal combination
    - Position tracking
    - Risk management
    - Database logging
    - Cooldown after losses

    Returns execution result with details about what happened.
    """
    try:
        # Merge JSON body with query-string params (auditors often use ?force_signal=BUY only).
        eff_symbol = (
            symbol_q.strip().upper()
            if symbol_q and str(symbol_q).strip()
            else body.symbol
        )
        eff_timeframe = (
            timeframe_q.strip()
            if timeframe_q and str(timeframe_q).strip()
            else body.timeframe
        )
        eff_risk = risk_pct_q if risk_pct_q is not None else body.risk_pct
        eff_force = (
            (body.force_signal.strip() if body.force_signal else None)
            or (force_signal_q.strip() if force_signal_q else None)
        )

        if get_execution_mode() == ExecutionMode.LIVE and eff_force:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="force_signal is not permitted in LIVE mode; use autonomous pipeline only",
            )

        # Create risk config (use defaults or override)
        risk_config = RiskConfig()
        if eff_risk is not None:
            risk_config.max_position_pct = float(eff_risk)

        # Initialize engine
        engine = AutoTradeEngine(db=db, risk_config=risk_config)

        # Execute trade
        result = engine.execute_auto_trade(
            symbol=eff_symbol,
            timeframe=eff_timeframe,
            risk_pct=eff_risk,
            force_signal=eff_force,
        )

        # Return structured response
        return {
            "ok": result.success,
            "executed": result.executed,
            "signal": result.signal,
            # Alias for client audits that expect `action` to match executed side.
            "action": result.signal,
            "reason": result.reason,
            "order_id": result.order_id,
            "price": result.price,
            "quantity": result.quantity,
            "balance_before": result.balance_before,
            "balance_after": result.balance_after,
            "position_id": result.position_id,
        }

    except HTTPException:
        # Gate rejections (e.g. force_signal in LIVE) must keep their own status.
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class AutoTradeScheduleBody(BaseModel):
    symbol: str = Field(default="BTCUSDT")
    timeframe: str = Field(default="1h")
    risk_pct: Optional[float] = Field(default=None, ge=0.01, le=0.5)
    enabled: bool = Field(default=True, description="Enable/disable scheduled trading")
    interval_minutes: int = Field(
        default=60,
        ge=1,
        le=1440,
        description="How often to check (in minutes)",
    )


@router.post("/auto-trade/schedule")
def schedule_auto_trade(body: AutoTradeScheduleBody):
    """
    Schedule auto-trading to run periodically.

    NOTE: This endpoint sets up configuration but you'll need to implement
    the actual scheduler (e.g., using APScheduler, Celery, or cron).

    For now, this returns the configuration that should be saved.
    """
    return {
        "ok": True,
        "message": "Schedule configuration received",
        "config": {
            "symbol": body.symbol,
            "timeframe": body.timeframe,
            "risk_pct": body.risk_pct,
            "enabled": body.enabled,
            "interval_minutes": body.interval_minutes,
        },
        "note": "Implement actual scheduler using APScheduler or Celery",
    }


# === POSITION MANAGEMENT ===


@router.get("/positions/open")
def get_open_positions(
    symbol: Optional[str] = None, mode: str = "live", db: Session = Depends(get_db)
):
    """Get open positions, optionally filtered by symbol and mode (live/paper/backtest)."""
    from src.db.models import Position

    m = _normalize_query_mode(mode)

    query = db.query(Position).filter(Position.is_open == True, Position.mode == m)
    if symbol:
        query = query.filter(Position.symbol == symbol.upper().strip())
    positions = query.all()

    client = BinanceSpotClient()
    prices: Dict[str, float] = {}

    def px(symbol: str) -> float:
        s = (symbol or "").upper().strip()
        if s in prices:
            return prices[s]
        try:
            prices[s] = float(client.get_price(s))
        except Exception:
            prices[s] = 0.0
        return prices[s]

    return {
        "ok": True,
        "mode": m,
        "count": len(positions),
        "positions": [
            {
                "id": p.id,
                "mode": p.mode,
                "symbol": p.symbol,
                "entry_price": p.entry_price,
                "entry_qty": p.entry_qty,
                "entry_ts": iso_utc(p.entry_ts),
                "current_price": px(p.symbol),
                "unrealized_pnl": (
                    (px(p.symbol) - float(p.entry_price or 0)) * float(p.entry_qty or 0)
                ),
                "unrealized_pnl_pct": (
                    (
                        (
                            (px(p.symbol) - float(p.entry_price or 0))
                            / float(p.entry_price or 1)
                        )
                        * 100.0
                    )
                    if float(p.entry_price or 0) > 0
                    else 0.0
                ),
            }
            for p in positions
        ],
    }


@router.get("/positions/history")
def get_position_history(
    symbol: Optional[str] = None,
    limit: int = 50,
    mode: str = "live",
    db: Session = Depends(get_db),
):
    """Get closed position history (supports mode=live|paper|backtest)."""
    from src.db.models import Position

    m = _normalize_query_mode(mode)

    query = db.query(Position).filter(
        Position.is_open == False,
        Position.mode == m,
    )

    if symbol:
        query = query.filter(Position.symbol == symbol.strip().upper())

    positions = query.order_by(Position.exit_ts.desc()).limit(limit).all()

    return {
        "ok": True,
        "mode": m,
        "count": len(positions),
        "positions": [
            {
                "id": p.id,
                "symbol": p.symbol,
                "entry_price": p.entry_price,
                "entry_qty": p.entry_qty,
                "entry_ts": iso_utc(p.entry_ts),
                "exit_price": p.exit_price,
                "exit_qty": p.exit_qty,
                "exit_ts": iso_utc(p.exit_ts),
                "pnl": p.pnl,
                "pnl_pct": p.pnl_pct,
            }
            for p in positions
        ],
    }


# === EVENT LOGS ===


@router.get("/logs/recent")
def get_recent_logs(
    category: Optional[str] = None,
    level: Optional[str] = None,
    symbol: Optional[str] = None,
    all_symbols: bool = False,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """Get recent event logs (symbol-scoped by default to avoid mixing pairs).

    - ``symbol``: optional explicit Binance symbol (e.g. BTCUSDT).
    - If omitted and ``all_symbols`` is false, scopes to ``TRADE_SYMBOL`` from settings.
    - Set ``all_symbols=true`` only for admin views (mixed-symbol stream).
    """
    from src.db.models import EventLog
    from sqlalchemy import or_

    from src.core.config import get_settings as _gs

    _settings = _gs()
    query = db.query(EventLog)

    if category:
        query = query.filter(EventLog.category == category)
    if level:
        query = query.filter(EventLog.level == level)

    if not all_symbols:
        scope = (symbol or _settings.trade_symbol).strip().upper()
        query = query.filter(or_(EventLog.symbol == scope, EventLog.symbol.is_(None)))

    logs = query.order_by(EventLog.ts.desc()).limit(limit).all()

    return {
        "ok": True,
        "scope": (
            "all_symbols"
            if all_symbols
            else (symbol or _settings.trade_symbol).strip().upper()
        ),
        "count": len(logs),
        "logs": [
            {
                "id": l.id,
                "level": l.level,
                "category": l.category,
                "message": l.message,
                "symbol": l.symbol,
                "ts": iso_utc(l.ts),
            }
            for l in logs
        ],
    }


# === TRADING DECISIONS (Explainability Dashboard) ===


@router.get("/decisions/recent")
def get_recent_decisions(
    symbol: Optional[str] = None,
    action: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """
    Get recent trading decisions with full transparency.
    Shows WHY each BUY/SELL/HOLD decision was made with numeric evidence.

    Required transparency fields:
    - rule_signal
    - ml_signal
    - ml_confidence
    - combined_signal
    - override_reason
    - final_action
    """
    from src.db.models import TradingDecisionLog

    query = db.query(TradingDecisionLog)

    if symbol:
        sym = symbol.strip().upper()
        query = query.filter(TradingDecisionLog.symbol == sym)
    if action:
        query = query.filter(TradingDecisionLog.action == action.strip().upper())

    decisions = query.order_by(TradingDecisionLog.ts.desc()).limit(limit).all()

    items = []

    for d in decisions:
        parsed_signals = {}
        if d.signals_json:
            try:
                parsed_signals = json.loads(d.signals_json)
            except Exception:
                parsed_signals = {}
        confidence_fields = _confidence_fields(parsed_signals)

        rule_signal = getattr(d, "rule_signal", None) or parsed_signals.get(
            "rule_signal"
        )
        ml_signal = getattr(d, "ml_signal", None) or parsed_signals.get("ml_signal")
        ml_confidence = getattr(d, "ml_confidence", None)
        if ml_confidence is None:
            ml_confidence = confidence_fields.get("ml_confidence")

        combined_signal = getattr(d, "combined_signal", None) or parsed_signals.get(
            "combined_signal"
        )

        override_reason = getattr(d, "override_reason", None) or parsed_signals.get(
            "override_reason"
        )

        final_action = (
            getattr(d, "final_action", None)
            or parsed_signals.get("final_action")
            or parsed_signals.get("combined_signal")
            or d.action
        )
        ml_context = parsed_signals.get("ml_context") or {}

        items.append(
            {
                "id": d.id,
                "action": d.action,
                "confidence": (
                    round(d.confidence, 3) if d.confidence is not None else None
                ),
                "symbol": d.symbol,
                "timeframe": d.timeframe,
                "regime": d.regime,
                "price": round(d.price, 2) if d.price is not None else None,
                "timestamp": iso_utc(d.ts),
                "indicators": {
                    "adx": round(d.adx, 2) if d.adx is not None else None,
                    "ema_fast": (
                        round(d.ema_fast, 2) if d.ema_fast is not None else None
                    ),
                    "ema_slow": (
                        round(d.ema_slow, 2) if d.ema_slow is not None else None
                    ),
                    "rsi": round(d.rsi, 2) if d.rsi is not None else None,
                    "bb_upper": (
                        round(d.bb_upper, 2) if d.bb_upper is not None else None
                    ),
                    "bb_lower": (
                        round(d.bb_lower, 2) if d.bb_lower is not None else None
                    ),
                    "atr": round(d.atr, 2) if d.atr is not None else None,
                },
                "risk": {
                    "entry": (
                        round(d.entry_price, 2) if d.entry_price is not None else None
                    ),
                    "stop_loss": (
                        round(d.stop_loss, 2) if d.stop_loss is not None else None
                    ),
                    "take_profit": (
                        round(d.take_profit, 2) if d.take_profit is not None else None
                    ),
                    "risk_reward": (
                        round(d.risk_reward, 2) if d.risk_reward is not None else None
                    ),
                },
                "reason": d.reason,
                "signals": parsed_signals,
                "rule_signal": rule_signal,
                "ml_signal": ml_signal,
                "ml_confidence": (
                    round(ml_confidence, 3)
                    if isinstance(ml_confidence, (int, float))
                    else ml_confidence
                ),
                "rule_confidence": confidence_fields.get("rule_confidence"),
                "final_confidence": confidence_fields.get("final_confidence"),
                "confidence_source": confidence_fields.get("confidence_source"),
                "combined_signal": combined_signal,
                "override_reason": override_reason,
                "final_action": final_action,
                "model_name": ml_context.get("model_name"),
                "model_version": ml_context.get("model_version"),
                "model_symbol": ml_context.get("symbol"),
                "model_timeframe": ml_context.get("timeframe"),
                "prediction": ml_context.get("prediction"),
                "prediction_confidence": ml_context.get("confidence"),
                "ml_changed_final_action": ml_context.get("changed_final_action"),
                "exact_match_exists": ml_context.get("exact_match_exists"),
                "fallback_used": ml_context.get("fallback_used"),
                "artifact_exists": ml_context.get("artifact_exists"),
                "runtime_eligible": ml_context.get("runtime_eligible"),
                "executed": d.executed,
                "order_id": d.order_id,
                "cycle_debug": parsed_signals.get("cycle_debug"),
                "final_source": parsed_signals.get("final_source"),
                # Phase 2A / Saad validation: authoritative trigger provenance
                # (concern #1) and the actual per-cycle numeric thresholds used
                # to gate this decision — not just raw indicators (concern #3).
                "triggered_by": getattr(d, "triggered_by", None),
                "cycle_id": getattr(d, "cycle_id", None),
                "active_thresholds": parsed_signals.get("active_thresholds"),
                "adaptive_posture": (
                    parsed_signals.get("active_thresholds") or {}
                ).get("adaptive_posture"),
            }
        )

    return {
        "ok": True,
        "count": len(items),
        "decisions": items,
    }


@router.get("/decisions/latest")
def get_latest_decision(
    symbol: str = "BTCUSDT",
    db: Session = Depends(get_db),
):
    """
    Get the most recent decision for a symbol.
    Useful for dashboard real-time display.
    """
    from src.db.models import TradingDecisionLog

    sym = symbol.strip().upper()
    decision = (
        db.query(TradingDecisionLog)
        .filter(TradingDecisionLog.symbol == sym)
        .order_by(TradingDecisionLog.ts.desc())
        .first()
    )

    if not decision:
        return {
            "ok": False,
            "message": f"No decisions found for {sym}",
        }

    parsed_signals = json.loads(decision.signals_json) if decision.signals_json else {}
    confidence_fields = _confidence_fields(parsed_signals)

    return {
        "ok": True,
        "decision": {
            "id": decision.id,
            "action": decision.action,
            "confidence": (
                round(decision.confidence, 3)
                if decision.confidence is not None
                else None
            ),
            "symbol": decision.symbol,
            "timeframe": decision.timeframe,
            "regime": decision.regime,
            "price": (round(decision.price, 2) if decision.price is not None else None),
            "timestamp": iso_utc(decision.ts),
            "indicators": {
                "adx": round(decision.adx, 2) if decision.adx else None,
                "ema_fast": round(decision.ema_fast, 2) if decision.ema_fast else None,
                "ema_slow": round(decision.ema_slow, 2) if decision.ema_slow else None,
                "rsi": round(decision.rsi, 2) if decision.rsi else None,
                "bb_upper": round(decision.bb_upper, 2) if decision.bb_upper else None,
                "bb_lower": round(decision.bb_lower, 2) if decision.bb_lower else None,
                "atr": round(decision.atr, 2) if decision.atr else None,
            },
            "risk": {
                "entry": (
                    round(decision.entry_price, 2) if decision.entry_price else None
                ),
                "stop_loss": (
                    round(decision.stop_loss, 2) if decision.stop_loss else None
                ),
                "take_profit": (
                    round(decision.take_profit, 2) if decision.take_profit else None
                ),
                "risk_reward": (
                    round(decision.risk_reward, 2) if decision.risk_reward else None
                ),
            },
            "reason": decision.reason,
            "signals": parsed_signals,
            "ml_alignment": parsed_signals.get("ml_context", {}),
            "executed": decision.executed,
            "order_id": decision.order_id,
            "rule_confidence": confidence_fields.get("rule_confidence"),
            "ml_confidence": confidence_fields.get("ml_confidence"),
            "final_confidence": confidence_fields.get("final_confidence"),
            "confidence_source": confidence_fields.get("confidence_source"),
            "cycle_debug": parsed_signals.get("cycle_debug"),
            "final_source": parsed_signals.get("final_source"),
        },
    }


# === AI OBSERVABILITY ===

import src.ml.state as _ml_state
from src.core.ml_runtime_state import get_ml_state
from src.execution.execution_engine import ORDERS as _PAPER_ORDERS
from src.execution.positions import POSITIONS as _PAPER_POSITIONS


@router.get("/ai-observability")
def ai_observability():
    """
    Runtime ML observability snapshot (single source: ml_runtime_state).
    """
    state = get_ml_state()
    return {
        "ok": True,
        "model_loaded": bool(state.get("model_loaded")),
        "model_symbol": state.get("model_symbol"),
        "model_timeframe": state.get("model_timeframe"),
        "model_artifact_path": state.get("model_artifact_path"),
        "last_prediction": state.get("last_prediction"),
        "last_action": state.get("last_action"),
        "ml_confidence": state.get("last_confidence"),
        "inference_count": state.get("inference_count", 0),
        "last_used_at": state.get("last_used_at"),
        "last_error": state.get("last_error"),
        "symbols_active": _ml_state.ACTIVE_SYMBOLS,
    }


def _check_ml_cache_loaded() -> bool:
    try:
        import src.ml.inference as mlinf

        return bool(getattr(mlinf, "_cache", {}))
    except Exception:
        return False


# === DEBUG ===


@router.get("/_debug")
def debug_exchange():
    """Debug endpoint to check configuration"""
    s = get_settings()
    return {
        "binance_testnet": s.binance_testnet,
        "binance_spot_base_url": s.binance_spot_base_url,
        "api_key_present": bool(s.binance_api_key),
        "api_secret_present": bool(s.binance_api_secret),
        "ml_enabled": s.ml_enabled,
        "ml_model_dir": s.ml_model_dir if s.ml_enabled else None,
    }


@router.get("/proof")
def exchange_proof(
    symbol: Optional[str] = None, mode: str = "live", db: Session = Depends(get_db)
):
    """
    Unified verification snapshot for audit/monitoring.
    Includes decisions, balances, pnl, orders, positions, and recent logs.
    Each subsection is isolated — one failure does not invalidate the rest.
    """
    from src.db.models import Position, Trade, EventLog, TradingDecisionLog

    s = get_settings()
    selected_symbol = (symbol or s.trade_symbol or "BTCUSDT").upper().strip()
    m = _normalize_query_mode(mode)

    section_errors: Dict[str, str] = {}

    # --- balances ---
    balances_res: Dict[str, Any] = {}
    try:
        balances_res = get_balances()
    except Exception as e:
        section_errors["balances"] = str(e)[:300]

    # --- decisions ---
    recent_decisions_res: Dict[str, Any] = {}
    latest_decision_res: Dict[str, Any] = {}
    try:
        recent_decisions_res = get_recent_decisions(
            symbol=selected_symbol, action=None, limit=20, db=db
        )
        latest_decision_res = get_latest_decision(symbol=selected_symbol, db=db)
    except Exception as e:
        section_errors["decisions"] = str(e)[:300]

    # --- positions (symbol-scoped) ---
    open_positions_res: Dict[str, Any] = {}
    positions_history_res: Dict[str, Any] = {}
    try:
        open_positions_res = get_open_positions(symbol=selected_symbol, mode=m, db=db)
        positions_history_res = get_position_history(
            symbol=selected_symbol, limit=20, mode=m, db=db
        )
    except Exception as e:
        section_errors["positions"] = str(e)[:300]

    # --- orders ---
    open_orders_res: Dict[str, Any] = {}
    simulated_orders_res: Dict[str, Any] = {}
    try:
        if m in ("paper", "shadow"):
            simulated_orders_res = get_all_orders(
                symbol=selected_symbol, limit=50, mode=m, db=db
            )
            open_orders_res = {
                "ok": True,
                "count": int(simulated_orders_res.get("count", 0)),
                "orders": simulated_orders_res.get("orders", []),
                "note": f"{m} mode — simulated orders only; no Binance openOrders",
            }
        else:
            open_orders_res = get_open_orders(symbol=selected_symbol)
    except Exception as e:
        section_errors["orders"] = str(e)[:300]

    # --- trades ---
    trades_res: Dict[str, Any] = {}
    try:
        trades_res = get_my_trades(symbol=selected_symbol, limit=50)
    except Exception as e:
        section_errors["trades"] = str(e)[:300]

    # --- logs (symbol-scoped; do not mix pairs) ---
    recent_logs_res: Dict[str, Any] = {}
    try:
        recent_logs_res = get_recent_logs(symbol=selected_symbol, limit=50, db=db)
    except Exception as e:
        section_errors["logs"] = str(e)[:300]

    usdt_balance = next(
        (
            b
            for b in (balances_res.get("balances", []) or [])
            if str(b.get("asset", "")).upper() == "USDT"
        ),
        None,
    )

    closed_positions = (
        db.query(Position)
        .filter(
            Position.mode == m,
            Position.is_open == False,  # noqa: E712
            Position.symbol == selected_symbol,
        )
        .order_by(Position.exit_ts.desc())
        .limit(200)
        .all()
    )
    pnl_usdt = float(sum(float(p.pnl or 0) for p in closed_positions))

    decision_counts_row = (
        db.query(
            func.count(TradingDecisionLog.id).label("total"),
            func.sum(case((TradingDecisionLog.action == "BUY", 1), else_=0)).label(
                "buy"
            ),
            func.sum(case((TradingDecisionLog.action == "SELL", 1), else_=0)).label(
                "sell"
            ),
            func.sum(case((TradingDecisionLog.action == "HOLD", 1), else_=0)).label(
                "hold"
            ),
        )
        .filter(TradingDecisionLog.symbol == selected_symbol)
        .first()
    )

    last_trade = (
        db.query(Trade)
        .filter(Trade.mode == m, Trade.symbol == selected_symbol)
        .order_by(Trade.ts.desc())
        .first()
    )
    last_event = db.query(EventLog).order_by(EventLog.ts.desc()).first()

    return {
        "ok": True,
        "symbol": selected_symbol,
        "mode": m,
        "section_errors": section_errors if section_errors else None,
        "environment": {
            "binance_testnet": bool(s.binance_testnet),
            "binance_spot_base_url": s.binance_spot_base_url,
            "app_env": s.app_env,
        },
        "balances": {
            "count": int(balances_res.get("count", 0)),
            "usdt": usdt_balance,
            "all": balances_res.get("balances", []),
        },
        "decision_visibility": {
            "latest": (
                latest_decision_res.get("decision")
                if latest_decision_res.get("ok")
                else None
            ),
            "recent_count": int(recent_decisions_res.get("count", 0)),
            "recent": recent_decisions_res.get("decisions", []),
            "action_counts": {
                "total": int(getattr(decision_counts_row, "total", 0) or 0),
                "buy": int(getattr(decision_counts_row, "buy", 0) or 0),
                "sell": int(getattr(decision_counts_row, "sell", 0) or 0),
                "hold": int(getattr(decision_counts_row, "hold", 0) or 0),
            },
        },
        "positions": {
            "open_count": int(open_positions_res.get("count", 0)),
            "open": open_positions_res.get("positions", []),
            "history_count": int(positions_history_res.get("count", 0)),
            "history": positions_history_res.get("positions", []),
        },
        "orders": {
            "open_count": int(open_orders_res.get("count", 0)),
            "open": open_orders_res.get("orders", []),
        },
        "trades": {
            "count": int(trades_res.get("count", 0)),
            "recent": trades_res.get("trades", []),
            "last_trade_ts": (
                iso_utc(last_trade.ts) if last_trade else None
            ),
        },
        "performance": {
            "realized_pnl_usdt": pnl_usdt,
            "closed_positions_count": len(closed_positions),
        },
        "logs": {
            "recent_count": int(recent_logs_res.get("count", 0)),
            "recent": recent_logs_res.get("logs", []),
            "last_event_ts": (
                iso_utc(last_event.ts) if last_event else None
            ),
        },
        "paper_trading": {
            "orders_count": len(_PAPER_ORDERS),
            "positions_count": len(_PAPER_POSITIONS),
            "recent_orders": list(_PAPER_ORDERS)[-10:],
            "recent_positions": list(_PAPER_POSITIONS)[-10:],
            "ml_inference_count": get_ml_state().get("inference_count", 0),
            "model_loaded": get_ml_state().get("model_loaded"),
        },
        "shadow_trading": _shadow_proof_snapshot(m, db=db, symbol=selected_symbol),
        "simulated_orders": simulated_orders_res if m in ("paper", "shadow") else None,
    }


def _shadow_proof_snapshot(
    requested_mode: str,
    *,
    db: Optional[Session] = None,
    symbol: Optional[str] = None,
) -> Dict[str, Any]:
    """Shadow tracker + DB order IDs for /exchange/proof audits."""
    if requested_mode != "shadow":
        return {
            "active": False,
            "note": "Set ?mode=shadow to include shadow tracker snapshot",
        }
    try:
        from src.execution.execution_engine import SHADOW_ORDERS
    except Exception:
        SHADOW_ORDERS = []
    order_ids: List[str] = []
    client_ids: List[str] = []
    db_count = 0
    if db is not None:
        from src.db.models import Order as OrderModel

        q = db.query(OrderModel).filter(OrderModel.mode == "shadow")
        if symbol:
            q = q.filter(OrderModel.symbol == symbol.upper().strip())
        rows = q.order_by(OrderModel.created_at.desc()).limit(200).all()
        db_count = len(rows)
        for r in rows:
            oid = str(r.exchange_order_id or "").strip()
            cid = str(r.client_order_id or "").strip()
            if oid:
                order_ids.append(oid)
            if cid:
                client_ids.append(cid)
    mem_recent = list(SHADOW_ORDERS or [])[-10:]
    for o in mem_recent:
        if isinstance(o, dict):
            oid = str(o.get("orderId") or o.get("order_id") or "").strip()
            cid = str(o.get("clientOrderId") or o.get("client_order_id") or "").strip()
            if oid and oid not in order_ids:
                order_ids.append(oid)
            if cid and cid not in client_ids:
                client_ids.append(cid)
    return {
        "active": True,
        "orders_count_memory": len(SHADOW_ORDERS or []),
        "orders_count_db": db_count,
        "unique_shadow_order_ids": order_ids,
        "unique_client_order_ids": client_ids,
        "unique_shadow_order_ids_count": len(order_ids),
        "unique_client_order_ids_count": len(client_ids),
        "recent_orders": mem_recent,
        "note": "Shadow fills are simulated; orderId/clientOrderId use shadow-* prefixes",
    }
