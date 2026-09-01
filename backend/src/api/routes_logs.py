from fastapi import APIRouter, Query
from typing import Optional
from sqlalchemy import desc
from src.db.session import SessionLocal
from src.db.models import EventLog

router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("")
def list_logs(
    limit: int = Query(50, ge=1, le=500, description="Max number of logs to return"),
    offset: int = Query(0, ge=0, description="Number of logs to skip"),
    level: Optional[str] = Query(None, description="Filter by log level (DEBUG, INFO, WARNING, ERROR)"),
    category: Optional[str] = Query(None, description="Filter by category (signal, order, trade, risk, etc.)"),
    symbol: Optional[str] = Query(None, description="Filter by trading symbol"),
):
    """
    Get system activity logs with optional filtering
    
    Logs include:
    - Signal generation (buy/sell/hold)
    - Order placement and execution
    - Trade completions
    - Risk check triggers
    - Balance updates
    - Paper trading wallet changes
    - Binance Testnet API responses
    """
    db = SessionLocal()
    try:
        query = db.query(EventLog)
        
        if level:
            query = query.filter(EventLog.level == level.upper())
        if category:
            query = query.filter(EventLog.category == category)
        if symbol:
            query = query.filter(EventLog.symbol == symbol)
        
        total = query.count()
        items = (
            query
            .order_by(desc(EventLog.ts))
            .offset(offset)
            .limit(min(limit, 500))
            .all()
        )
        
        return {
            "ok": True,
            "total": total,
            "offset": offset,
            "limit": limit,
            "items": [
                {
                    "id": x.id,
                    "ts": x.ts.isoformat() if x.ts else None,
                    "level": x.level,
                    "category": x.category,
                    "message": x.message,
                    "symbol": x.symbol,
                    "timeframe": x.timeframe,
                }
                for x in items
            ],
        }
    finally:
        db.close()


@router.get("/summary")
def logs_summary():
    """Get summary of logs by category and level"""
    db = SessionLocal()
    try:
        all_logs = db.query(EventLog).all()
        
        by_level = {}
        by_category = {}
        
        for log in all_logs:
            by_level[log.level] = by_level.get(log.level, 0) + 1
            by_category[log.category] = by_category.get(log.category, 0) + 1
        
        return {
            "ok": True,
            "total_logs": len(all_logs),
            "by_level": by_level,
            "by_category": by_category,
        }
    finally:
        db.close()

