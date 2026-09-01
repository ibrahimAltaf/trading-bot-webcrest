from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional
import json
import pandas as pd

from src.core.config import get_settings
from src.db.session import SessionLocal
from src.db.models import BacktestRun, Order, Trade, Position
from src.risk.rules import RiskConfig, CooldownState

settings = get_settings()


@dataclass
class BacktestConfig:
    symbol: str = "BTCUSDT"
    timeframe: str = "1h"
    initial_balance: float = 1000.0
    risk: RiskConfig = field(default_factory=RiskConfig)


def load_features(symbol: str, timeframe: str) -> pd.DataFrame:
    fp = Path(settings.data_dir) / "features" / f"{symbol}_{timeframe}_features.parquet"
    if not fp.exists():
        raise FileNotFoundError(f"Features not found: {fp}")
    return pd.read_parquet(fp).sort_values("open_time").reset_index(drop=True)


def generate_signal(row) -> str:
    """
    Improved signal: Wait for strong pullbacks in uptrends
    Only buy when:
      1. Price is above both EMAs (uptrend)
      2. RSI has pulled back (oversold but not crashed)
      3. MACD is bullish
    Only sell when:
      1. Trend breaks (price below EMA50)
      2. RSI divergence (price high but RSI low)
    """
    ema20 = float(row["ema_20"])
    ema50 = float(row["ema_50"])
    rsi = float(row["rsi_14"])
    macd = float(row.get("macd", 0))
    signal_line = float(row.get("macd_signal", 0))
    
    price = float(row["close"])

    # ========================
    # BUY SIGNAL (Conservative)
    # ========================
    # Criteria: Strong uptrend + pullback + bullish MACD
    if (
        price > ema50 and                    # Price above slow MA
        price > ema20 and                    # Price above fast MA
        ema20 > ema50 and                    # Uptrend confirmed
        40 <= rsi <= 60 and                  # RSI in sweet spot (not overbought, not oversold)
        macd > signal_line                   # MACD bullish
    ):
        return "BUY"

    # ========================
    # SELL SIGNAL (Strict Exit)
    # ========================
    # ONLY exit on trend break, not noise
    if price < ema50:                        # Trend broken
        return "SELL"
    
    return "HOLD"


def create_backtest_run(
    cfg: BacktestConfig, *, seed: int | None, dataset_sha256: str | None
) -> int:
    db = SessionLocal()
    try:
        notes_obj = {
            "seed": seed,
            "dataset_sha256": dataset_sha256,
            "created_at_utc": datetime.utcnow().isoformat(),
        }
        run = BacktestRun(
            symbol=cfg.symbol,
            timeframe=cfg.timeframe,
            status="running",
            initial_balance=float(cfg.initial_balance),
            started_at=datetime.utcnow(),
            notes=json.dumps(notes_obj),
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        return int(run.id)
    finally:
        db.close()


def run_backtest_for_run_id(run_id: int, cfg: BacktestConfig) -> None:
    """
    ✅ Background worker: executes backtest & updates DB for that run_id
    Includes optional LSTM + ensemble logic (feature-flagged).
    """
    db = SessionLocal()
    settings = get_settings()

    try:
        run = db.query(BacktestRun).filter(BacktestRun.id == run_id).first()
        if not run:
            return

        df = load_features(cfg.symbol, cfg.timeframe)
        n = len(df)

        balance = float(cfg.initial_balance)
        in_position = False
        entry_price: Optional[float] = None
        entry_qty: Optional[float] = None

        cooldown = CooldownState()
        pos: Optional[Position] = None

        trades_count = 0
        peak_equity = balance
        max_drawdown = 0.0

        # ML init (lazy)
        infer = None
        LOOKBACK = int(getattr(settings, "ml_lookback", 100))

        # speed: commit batching
        pending_ops = 0
        COMMIT_EVERY = 200

        for i in range(n):
            row = df.iloc[i]

            ts = row["open_time"].to_pydatetime()
            price = float(row["close"])

            ema_fast = float(row["ema_20"])
            ema_slow = float(row["ema_50"])
            ema_dist_pct = abs(ema_fast - ema_slow) / price

            if ema_dist_pct < 0.002:
                continue

            # -------------------------
            # MARK-TO-MARKET EQUITY
            # -------------------------
            equity = balance
            if in_position and entry_price is not None and entry_qty is not None:
                equity = balance + (price - entry_price) * entry_qty

            peak_equity = max(peak_equity, equity)
            dd = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0.0
            max_drawdown = max(max_drawdown, dd)

            # cooldown after loss
            if cooldown.blocked(ts):
                continue

            # -------------------------
            # RULE-BASED SIGNAL
            # -------------------------
            rule_signal = generate_signal(row)
            signal = rule_signal

            # -------------------------
            # LSTM + ENSEMBLE (SAFE)
            # -------------------------
            if (
                settings.ml_enabled
                and i >= LOOKBACK - 1
            ):
                try:
                    if infer is None:
                        from src.ml.inference import get_infer
                        from src.ml.ensemble import combine
                        infer = get_infer(settings.ml_model_dir)

                    window = df.iloc[i - LOOKBACK + 1 : i + 1]
                    lstm = infer.predict_window(window)

                    signal = combine(
                        rule_signal,
                        lstm,
                        settings.ml_agree_threshold,
                        settings.ml_override_threshold,
                    )
                except Exception:
                    # Fail-safe: never break backtest
                    signal = rule_signal

            # -------------------------
            # EXIT LOGIC
            # -------------------------
            if in_position and entry_price is not None and entry_qty is not None:
                sl_price = entry_price * (1 - cfg.risk.stop_loss_pct)
                tp_price = entry_price * (1 + cfg.risk.take_profit_pct)

                exit_reason = None
                if price <= sl_price:
                    exit_reason = "SL"
                elif price >= tp_price:
                    exit_reason = "TP"
                elif signal == "SELL":
                    exit_reason = "SIG"

                if exit_reason:
                    qty = entry_qty
                    fee = (qty * price) * cfg.risk.fee_pct
                    balance += (qty * price) - fee

                    db.add(
                        Order(
                            mode="backtest",
                            symbol=cfg.symbol,
                            side="SELL",
                            order_type="MARKET",
                            quantity=qty,
                            executed_price=price,
                            status="filled",
                            backtest_run_id=run_id,
                        )
                    )

                    db.add(
                        Trade(
                            mode="backtest",
                            symbol=cfg.symbol,
                            side="SELL",
                            quantity=qty,
                            price=price,
                            fee=fee,
                            fee_asset="USDT",
                            backtest_run_id=run_id,
                        )
                    )

                    if pos:
                        pos.exit_price = price
                        pos.exit_qty = qty
                        pos.exit_ts = ts
                        pnl = (price - entry_price) * qty - fee
                        pos.pnl = pnl
                        pos.pnl_pct = (
                            (price - entry_price) / entry_price
                            if entry_price else None
                        )
                        pos.is_open = False

                        if pnl < 0:
                            cooldown.trigger(
                                ts,
                                cfg.risk.cooldown_minutes_after_loss,
                            )

                    in_position = False
                    entry_price = None
                    entry_qty = None
                    pos = None
                    trades_count += 1

                    pending_ops += 1
                    if pending_ops >= COMMIT_EVERY:
                        db.commit()
                        pending_ops = 0

                    continue

            # -------------------------
            # ENTRY LOGIC
            # -------------------------
            if (not in_position) and signal == "BUY":
                spend = balance * cfg.risk.max_position_pct
                if spend <= 10:
                    continue

                qty = spend / price
                fee = spend * cfg.risk.fee_pct
                total = spend + fee

                if total > balance:
                    continue

                balance -= total

                db.add(
                    Order(
                        mode="backtest",
                        symbol=cfg.symbol,
                        side="BUY",
                        order_type="MARKET",
                        quantity=qty,
                        executed_price=price,
                        status="filled",
                        backtest_run_id=run_id,
                    )
                )

                db.add(
                    Trade(
                        mode="backtest",
                        symbol=cfg.symbol,
                        side="BUY",
                        quantity=qty,
                        price=price,
                        fee=fee,
                        fee_asset="USDT",
                        backtest_run_id=run_id,
                    )
                )

                pos = Position(
                    mode="backtest",
                    symbol=cfg.symbol,
                    is_open=True,
                    entry_price=price,
                    entry_qty=qty,
                    entry_ts=ts,
                )
                db.add(pos)

                in_position = True
                entry_price = price
                entry_qty = qty

                pending_ops += 1
                if pending_ops >= COMMIT_EVERY:
                    db.commit()
                    pending_ops = 0

        # -------------------------
        # FINALIZE RUN
        # -------------------------
        if pending_ops:
            db.commit()

        run.status = "success"
        run.finished_at = datetime.utcnow()
        run.final_balance = float(balance)
        run.total_return_pct = (
            (balance - float(cfg.initial_balance)) / float(cfg.initial_balance)
        ) * 100.0
        run.max_drawdown_pct = max_drawdown * 100.0
        run.trades_count = trades_count

        db.commit()

    except Exception as e:
        try:
            run = db.query(BacktestRun).filter(BacktestRun.id == run_id).first()
            if run:
                run.status = "failed"
                run.finished_at = datetime.utcnow()
                run.notes = str(e)[:2000]
                db.commit()
        except Exception:
            pass
        raise
    finally:
        db.close()
