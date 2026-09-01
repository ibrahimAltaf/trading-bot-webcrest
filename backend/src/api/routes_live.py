"""
Legacy live trading routes — DISABLED for Phase 2C.

The POST /live/run path bypassed RiskEngine and Phase 2C gates.
All live execution must go through AutoTradeEngine.execute_auto_trade().
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

router = APIRouter(prefix="/live", tags=["live"])


class LiveIn(BaseModel):
    symbol: str = "BTCUSDT"
    usdt_amount: float = 20


@router.post("/run", summary="DISABLED — use /exchange/auto-trade (authenticated)")
def run_live_disabled(body: LiveIn):
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=(
            "POST /live/run is disabled for Phase 2C. "
            "All live execution must use the centralized AutoTradeEngine path "
            "(scheduler or authenticated POST /exchange/auto-trade) which enforces "
            "Phase 2C gate, RiskEngine, kill switch, and audit logging."
        ),
    )
