from fastapi import APIRouter
from pydantic import BaseModel

from src.live.engine import run_live_trade
from src.risk.rules import RiskConfig

router = APIRouter(prefix="/live", tags=["live"])


class LiveIn(BaseModel):
    symbol: str = "BTCUSDT"
    usdt_amount: float = 20


@router.post("/run")
def run_live(body: LiveIn):
    risk = RiskConfig()

    result = run_live_trade(
        symbol=body.symbol,
        usdt_amount=body.usdt_amount,
        risk=risk,
    )

    return {"ok": True, "result": result}
