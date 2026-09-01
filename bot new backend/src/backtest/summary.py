from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from src.db.models import BacktestRun, Position, Trade


def _safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


def compute_backtest_summary(db: Session, run_id: int) -> Dict[str, Any]:
    run: Optional[BacktestRun] = db.query(BacktestRun).filter(BacktestRun.id == run_id).first()
    if not run:
        return {"ok": False, "detail": "run not found"}

    # best-effort filter by time window
    start = run.started_at
    end = run.finished_at or run.started_at

    # Trades are linked by run_id ✅
    trades = (
        db.query(Trade)
        .filter(Trade.backtest_run_id == run_id)
        .order_by(Trade.ts.asc())
        .all()
    )

    # Positions currently don't have run_id in your model,
    # so we filter by: mode + symbol + entry_ts between run start/end (best effort)
    positions = (
        db.query(Position)
        .filter(Position.mode == "backtest", Position.symbol == run.symbol)
        .filter(Position.entry_ts >= start)
        .order_by(Position.entry_ts.asc())
        .all()
    )

    closed = [p for p in positions if (p.is_open is False and p.pnl is not None)]
    pnl_list = [float(p.pnl) for p in closed]

    wins = [p for p in pnl_list if p > 0]
    losses = [p for p in pnl_list if p < 0]

    gross_profit = float(sum(wins))
    gross_loss = float(abs(sum(losses)))
    win_rate = (_safe_div(len(wins), len(pnl_list)) * 100.0) if pnl_list else 0.0
    profit_factor = _safe_div(gross_profit, gross_loss) if gross_loss else (gross_profit if gross_profit else 0.0)

    avg_pnl = (sum(pnl_list) / len(pnl_list)) if pnl_list else 0.0

    # equity curve based on CLOSED positions
    equity_curve: List[Dict[str, Any]] = []
    equity = float(run.initial_balance or 0.0)
    equity_curve.append({"i": 0, "ts": run.started_at, "equity": equity})

    i = 1
    for p in closed:
        equity += float(p.pnl or 0.0)
        equity_curve.append({"i": i, "ts": p.exit_ts, "equity": equity})
        i += 1

    metrics = {
        "symbol": run.symbol,
        "timeframe": run.timeframe,
        "status": run.status,
        "initial_balance": run.initial_balance,
        "final_balance": run.final_balance,
        "total_return_pct": run.total_return_pct,
        "max_drawdown_pct": run.max_drawdown_pct,
        "trades_count": run.trades_count,

        "positions_closed": len(closed),
        "win_rate_pct": win_rate,
        "profit_factor": profit_factor,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "avg_pnl": avg_pnl,

        "db_items": {
            "trades_rows": len(trades),
            "positions_rows_in_window": len(positions),
        },
    }

    return {
        "ok": True,
        "run_id": run_id,
        "status": run.status,
        "metrics": metrics,
        "equity_curve": equity_curve,
    }
