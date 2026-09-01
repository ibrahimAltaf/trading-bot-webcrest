from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional


@dataclass
class RiskConfig:
    max_position_pct: float = 0.10      # max 10% of balance per trade
    stop_loss_pct: float = 0.02         # 2% SL (tighter on reversals)
    take_profit_pct: float = 0.06       # 6% TP (3:1 risk/reward - good for trends)
    fee_pct: float = 0.001              # 0.1% fee each side (spot approx)
    cooldown_minutes_after_loss: int = 60  # Increased: don't revenge trade


@dataclass
class CooldownState:
    until: Optional[datetime] = None

    def blocked(self, now: datetime) -> bool:
        return self.until is not None and now < self.until

    def trigger(self, now: datetime, minutes: int) -> None:
        self.until = now + timedelta(minutes=minutes)
