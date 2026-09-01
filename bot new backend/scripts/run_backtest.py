from pathlib import Path
import pandas as pd

from src.backtest.engine import BacktestConfig, run_backtest
from src.db.session import SessionLocal
from src.db.models import BacktestRun, Trade


def main():
    cfg = BacktestConfig()
    run_id = run_backtest(cfg)
    print(f"✅ Backtest done. Run ID: {run_id}")

    # export trades to CSV
    db = SessionLocal()
    trades = db.query(Trade).filter(Trade.backtest_run_id == run_id).all()
    run = db.query(BacktestRun).filter(BacktestRun.id == run_id).first()

    rows = []
    for t in trades:
        rows.append({
            "id": t.id,
            "ts": t.ts,
            "side": t.side,
            "qty": t.quantity,
            "price": t.price,
            "fee": t.fee,
        })

    out_dir = Path("data/reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_csv = out_dir / f"backtest_trades_run_{run_id}.csv"

    pd.DataFrame(rows).to_csv(out_csv, index=False)
    print(f"📄 Trades CSV saved: {out_csv}")

    print("📊 Summary:")
    print({
        "symbol": run.symbol,
        "timeframe": run.timeframe,
        "initial_balance": run.initial_balance,
        "final_balance": run.final_balance,
        "return_pct": run.total_return_pct,
        "max_drawdown_pct": run.max_drawdown_pct,
        "trades_count": run.trades_count,
    })

    db.close()


if __name__ == "__main__":
    main()
