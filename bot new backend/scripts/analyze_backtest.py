#!/usr/bin/env python3
"""
Backtest Analysis Tool
Analyzes a specific backtest run to understand performance, trade quality, and signals
"""

import sys
from pathlib import Path
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.db.session import SessionLocal
from src.db.models import BacktestRun, Trade, Position


def analyze_backtest_run(run_id: int):
    """Detailed analysis of a backtest run"""
    db = SessionLocal()
    
    try:
        # Get run
        run = db.query(BacktestRun).filter(BacktestRun.id == run_id).first()
        if not run:
            print(f"❌ Run {run_id} not found")
            return
        
        print(f"\n{'='*70}")
        print(f"BACKTEST RUN #{run_id} ANALYSIS")
        print(f"{'='*70}\n")
        
        # Summary stats
        print("📊 RUN SUMMARY")
        print("-" * 70)
        print(f"Symbol:           {run.symbol}")
        print(f"Timeframe:        {run.timeframe}")
        print(f"Status:           {run.status}")
        print(f"Started:          {run.started_at}")
        print(f"Finished:         {run.finished_at}")
        print(f"Duration:         {(run.finished_at - run.started_at).total_seconds()/3600:.1f} hours" if run.finished_at else "N/A")
        print()
        
        # Performance metrics
        print("💰 PERFORMANCE METRICS")
        print("-" * 70)
        initial = float(run.initial_balance or 0)
        final = float(run.final_balance or 0)
        pnl_dollars = final - initial
        pnl_pct = float(run.total_return_pct or 0)
        max_dd = float(run.max_drawdown_pct or 0)
        
        print(f"Initial Balance:  ${initial:>15,.2f}")
        print(f"Final Balance:    ${final:>15,.2f}")
        print(f"Net PnL ($):      ${pnl_dollars:>15,.2f}")
        print(f"Net Return (%):   {pnl_pct:>15.2f}%")
        print(f"Max Drawdown (%): {max_dd:>15.2f}%")
        print(f"Total Trades:     {run.trades_count:>15}")
        print()
        
        # Get all trades
        trades = db.query(Trade).filter(Trade.backtest_run_id == run_id).order_by(Trade.ts).all()
        
        # Get all positions
        positions = db.query(Position).filter(
            Position.mode == "backtest",
            Position.symbol == run.symbol,
            Position.entry_ts >= run.started_at
        ).order_by(Position.entry_ts).all()
        
        print(f"📈 TRADE ANALYSIS ({len(trades)} trades total)")
        print("-" * 70)
        
        # Count buy vs sell
        buys = [t for t in trades if t.side == "BUY"]
        sells = [t for t in trades if t.side == "SELL"]
        
        print(f"Buy Orders:       {len(buys)}")
        print(f"Sell Orders:      {len(sells)}")
        print()
        
        # Analyze positions
        closed_positions = [p for p in positions if not p.is_open and p.pnl is not None]
        open_positions = [p for p in positions if p.is_open]
        
        print(f"📍 POSITION ANALYSIS ({len(positions)} total positions)")
        print("-" * 70)
        print(f"Closed Positions: {len(closed_positions)}")
        print(f"Open Positions:   {len(open_positions)}")
        print()
        
        if closed_positions:
            pnls = [float(p.pnl) for p in closed_positions]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p < 0]
            breakeven = [p for p in pnls if p == 0]
            
            print(f"Winning Trades:   {len(wins)} ({len(wins)/len(pnls)*100:.1f}%)")
            print(f"Losing Trades:    {len(losses)} ({len(losses)/len(pnls)*100:.1f}%)")
            print(f"Breakeven Trades: {len(breakeven)}")
            print()
            
            if wins:
                avg_win = sum(wins) / len(wins)
                max_win = max(wins)
                print(f"Avg Win:          ${avg_win:>15,.2f}")
                print(f"Max Win:          ${max_win:>15,.2f}")
            
            if losses:
                avg_loss = sum(losses) / len(losses)
                max_loss = min(losses)
                print(f"Avg Loss:         ${avg_loss:>15,.2f}")
                print(f"Max Loss:         ${max_loss:>15,.2f}")
            
            print()
            gross_profit = sum(wins) if wins else 0
            gross_loss = abs(sum(losses)) if losses else 0
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
            
            print(f"Gross Profit:     ${gross_profit:>15,.2f}")
            print(f"Gross Loss:       ${gross_loss:>15,.2f}")
            print(f"Profit Factor:    {profit_factor:>15.2f}x")
            print()
        
        # Show detailed trade list
        print(f"\n📋 TRADE-BY-TRADE DETAIL")
        print("-" * 70)
        
        trade_data = []
        for i, t in enumerate(trades, 1):
            trade_data.append({
                "#": i,
                "Type": t.side,
                "Qty": f"{t.quantity:.4f}",
                "Price": f"${t.price:.2f}",
                "Fee": f"${t.fee:.2f}" if t.fee else "N/A",
                "Time": t.ts.strftime("%Y-%m-%d %H:%M")
            })
        
        print(tabulate(trade_data, headers="keys", tablefmt="grid"))
        print()
        
        # Show position details
        if closed_positions:
            print(f"\n📊 CLOSED POSITION DETAILS")
            print("-" * 70)
            
            position_data = []
            for i, p in enumerate(closed_positions, 1):
                pnl_pct = (p.pnl_pct * 100) if p.pnl_pct else 0
                position_data.append({
                    "#": i,
                    "Entry Price": f"${p.entry_price:.2f}",
                    "Exit Price": f"${p.exit_price:.2f}",
                    "Qty": f"{p.entry_qty:.4f}",
                    "PnL ($)": f"${p.pnl:.2f}",
                    "PnL (%)": f"{pnl_pct:.2f}%",
                    "Duration": f"{(p.exit_ts - p.entry_ts).total_seconds()/3600:.1f}h"
                })
            
            print(tabulate(position_data, headers="keys", tablefmt="grid"))
            print()
        
        # Analysis and recommendations
        print(f"\n🔍 DIAGNOSTIC ANALYSIS")
        print("-" * 70)
        
        if pnl_pct < 0:
            print("❌ NEGATIVE PnL - System is losing money. Potential issues:")
            print()
            
            if closed_positions:
                loss_ratio = len(losses) / len(closed_positions) if losses else 0
                if loss_ratio > 0.5:
                    print("   1. ⚠️  HIGH LOSS RATIO: {:.0f}% of trades are losers".format(loss_ratio*100))
                    print("      → Strategy generates too many losing trades")
                    print("      → Consider: stricter entry signals, better stop loss rules")
                    print()
                
                if len(wins) > 0 and len(losses) > 0:
                    avg_win_amt = sum(wins) / len(wins)
                    avg_loss_amt = sum(losses) / len(losses)
                    win_loss_ratio = abs(avg_win_amt / avg_loss_amt)
                    print("   2. ⚠️  WIN/LOSS RATIO: {:.2f}x".format(win_loss_ratio))
                    if win_loss_ratio < 1:
                        print("      → Average losses are BIGGER than average wins")
                        print("      → Consider: larger take-profit targets, smaller stop losses")
                    print()
            
            # Fee analysis
            total_fees = sum([t.fee or 0 for t in trades])
            print("   3. 💸 TRADING COSTS: ${:,.2f} total fees paid".format(total_fees))
            print("      → Fees = {:.2f}% of initial balance".format(total_fees/initial*100))
            if total_fees > initial * 0.02:  # More than 2% in fees
                print("      → HIGH FEES: Consider reducing trade frequency")
            print()
        
        else:
            print("✅ POSITIVE PnL - System is profitable. Good job!")
            print()
        
        # Signal quality check
        if len(trades) < 5:
            print("⚠️  SIGNAL QUALITY: Very few trades ({})".format(len(trades)))
            print("   → Strategy is too conservative or market doesn't match signals")
            print("   → Consider: relaxing entry conditions, reviewing market data")
            print()
        
        elif len(trades) > 100:
            print("⚠️  TRADE FREQUENCY: Very high trade count ({})".format(len(trades)))
            print("   → Strategy is overtrading, accumulating high fees")
            print("   → Consider: adding cooldown periods, higher timeframes")
            print()
        
        print("\n" + "="*70)
        print("END ANALYSIS")
        print("="*70 + "\n")
        
    finally:
        db.close()


if __name__ == "__main__":
    run_id = int(sys.argv[1]) if len(sys.argv) > 1 else 128
    analyze_backtest_run(run_id)
