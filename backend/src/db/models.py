from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    String,
    Integer,
    Float,
    Boolean,
    DateTime,
    Text,
    ForeignKey,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base


def utcnow() -> datetime:
    return datetime.utcnow()


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Scope
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    timeframe: Mapped[str] = mapped_column(String(10), index=True)

    # When / what
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    status: Mapped[str] = mapped_column(
        String(20), default="running"
    )  # running/success/failed
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Results summary (filled after run)
    initial_balance: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    final_balance: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    total_return_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_drawdown_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    trades_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Relationships
    orders: Mapped[list["Order"]] = relationship(
        back_populates="backtest_run", cascade="all, delete-orphan"
    )
    trades: Mapped[list["Trade"]] = relationship(
        back_populates="backtest_run", cascade="all, delete-orphan"
    )


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    mode: Mapped[str] = mapped_column(
        String(10), default="backtest"
    )  # backtest/paper/live
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    side: Mapped[str] = mapped_column(String(4))  # BUY/SELL
    order_type: Mapped[str] = mapped_column(String(20), default="MARKET")
    quantity: Mapped[float] = mapped_column(Float)

    requested_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    executed_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    status: Mapped[str] = mapped_column(
        String(20), default="created"
    )  # created/filled/canceled/rejected
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    # External IDs (for paper/live)
    exchange_order_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # Client-supplied id (Phase 2A) — engine-stable, used for idempotency /
    # duplicate detection across retries and crash-recoveries.
    client_order_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )

    # Links (optional)
    backtest_run_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("backtest_runs.id"), nullable=True, index=True
    )
    backtest_run: Mapped[Optional["BacktestRun"]] = relationship(
        back_populates="orders"
    )

    # Phase 2A: authoritative trigger provenance — who/what caused this order,
    # independent of which signal pipeline (rule/ML) produced the decision.
    # scheduler = unattended APScheduler cycle (src/scheduler/runner.py);
    # api_manual = a human/script called /exchange/auto-trade directly;
    # proof_forced = force_signal audit call. Distinguishes genuine autonomous
    # execution from manual test calls (see docs/CLIENT-SAAD-* validation).
    triggered_by: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True, index=True
    )
    cycle_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)


Index("ix_orders_symbol_created_at", Order.symbol, Order.created_at)


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    mode: Mapped[str] = mapped_column(String(10), default="backtest")
    symbol: Mapped[str] = mapped_column(String(20), index=True)

    side: Mapped[str] = mapped_column(String(4))  # BUY/SELL
    quantity: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)

    fee: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fee_asset: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)

    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    # Links
    order_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("orders.id"), nullable=True, index=True
    )
    backtest_run_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("backtest_runs.id"), nullable=True, index=True
    )

    backtest_run: Mapped[Optional["BacktestRun"]] = relationship(
        back_populates="trades"
    )


Index("ix_trades_symbol_ts", Trade.symbol, Trade.ts)


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    mode: Mapped[str] = mapped_column(String(10), default="backtest")
    symbol: Mapped[str] = mapped_column(String(20), index=True)

    is_open: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    entry_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    entry_qty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    entry_ts: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    exit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    exit_qty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    exit_ts: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    pnl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pnl_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class EventLog(Base):
    __tablename__ = "event_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    level: Mapped[str] = mapped_column(
        String(10), default="INFO", index=True
    )  # INFO/WARN/ERROR
    category: Mapped[str] = mapped_column(
        String(30), default="system", index=True
    )  # db/exchange/backtest/paper/...
    message: Mapped[str] = mapped_column(Text)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    # Optional context
    symbol: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)
    timeframe: Mapped[Optional[str]] = mapped_column(
        String(10), nullable=True, index=True
    )


class TradingDecisionLog(Base):
    """
    Stores adaptive trading decisions with full transparency.
    Records why each BUY/SELL/HOLD decision was made.
    """

    __tablename__ = "trading_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Decision
    action: Mapped[str] = mapped_column(String(10), index=True)  # BUY/SELL/HOLD
    confidence: Mapped[float] = mapped_column(Float)

    # Context
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    timeframe: Mapped[str] = mapped_column(String(10))
    regime: Mapped[str] = mapped_column(
        String(20), index=True
    )  # TRENDING/RANGING/UNKNOWN
    price: Mapped[float] = mapped_column(Float)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    # Indicators (numeric evidence)
    adx: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ema_fast: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ema_slow: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rsi: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bb_upper: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bb_lower: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    atr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Risk levels
    entry_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    take_profit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    risk_reward: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Reasoning
    reason: Mapped[str] = mapped_column(Text)
    signals_json: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )  # JSON string of detailed signals

    # Execution link (if order was placed)
    order_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("orders.id"), nullable=True, index=True
    )
    executed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    # Phase 2A: same trigger provenance as Order (see Order.triggered_by) —
    # duplicated here so a decision that never resulted in an order (e.g. a
    # scheduler HOLD cycle) is still attributable.
    triggered_by: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True, index=True
    )
    cycle_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)


Index(
    "ix_trading_decisions_symbol_ts", TradingDecisionLog.symbol, TradingDecisionLog.ts
)
Index(
    "ix_trading_decisions_action_ts", TradingDecisionLog.action, TradingDecisionLog.ts
)


class User(Base):
    """User account for login and per-user exchange config."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    exchange_config: Mapped[Optional["ExchangeConfig"]] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


class ExchangeConfig(Base):
    """
    Per-user exchange connection (CCXT-style).
    Store exchange_id (binance, binanceus, etc.), testnet/live, API keys.
    """

    __tablename__ = "exchange_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)

    exchange_id: Mapped[str] = mapped_column(String(32), default="binance")  # ccxt exchange id
    testnet: Mapped[bool] = mapped_column(Boolean, default=True)
    api_key: Mapped[str] = mapped_column(String(512), default="")
    api_secret: Mapped[str] = mapped_column(String(512), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    user: Mapped["User"] = relationship(back_populates="exchange_config")


class AppSetting(Base):
    """
    Simple key/value settings table so the frontend can toggle
    runtime flags (e.g. LIVE_SCHEDULER_ENABLED) without restarting.
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )


class PortfolioSnapshot(Base):
    """
    Time-series snapshot of total portfolio value in USDT terms.
    Used by frontend portfolio line charts (profit/loss over time).
    """

    __tablename__ = "portfolio_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    source: Mapped[str] = mapped_column(String(20), default="manual", index=True)
    total_value_usdt: Mapped[float] = mapped_column(Float)
    usdt_cash: Mapped[float] = mapped_column(Float, default=0.0)
    assets_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


Index(
    "ix_portfolio_snapshots_source_ts", PortfolioSnapshot.source, PortfolioSnapshot.ts
)
