"""
Phase 2A safety layer.

Public surface:
    - KillSwitch (state, engage, release)
    - RiskEngine (centralized pre-trade validation)
    - OrderRequest / RiskDecision (typed contracts)
"""
from src.safety.kill_switch import (  # noqa: F401
    engage as engage_kill_switch,
    get_state as get_kill_switch_state,
    is_engaged as kill_switch_is_engaged,
    release as release_kill_switch,
)
from src.safety.risk_engine import (  # noqa: F401
    OrderRequest,
    RiskDecision,
    RiskEngine,
    RiskLimits,
)
