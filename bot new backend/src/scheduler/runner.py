from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime
import os
import threading
from typing import Any, Dict

from src.exchange.binance_spot_client import BinanceSpotClient
from src.risk.rules import RiskConfig
from src.live.auto_trade_engine import AutoTradeEngine
from src.live.portfolio import capture_portfolio_snapshot
from src.db.session import SessionLocal
from src.core.config import get_settings

scheduler = BackgroundScheduler(timezone="UTC")

# Lazy client: importing this module must not require Binance credentials so API workers
# can boot (health, Swagger, DB) even if keys are misconfigured; the scheduler job
# fails loudly on first use instead of killing Gunicorn at import time.
_client: BinanceSpotClient | None = None


def _get_client() -> BinanceSpotClient:
    global _client
    if _client is None:
        _client = BinanceSpotClient()
    return _client

# Prevent overlapping runs: if previous job still running, skip this cycle instead of
# letting APScheduler log "maximum number of running instances reached".
_job_lock = threading.Lock()

# Last successful cycle start per symbol (for observability / audits).
_symbol_last_run: Dict[str, datetime] = {}
# Last skip reason when a symbol was not executed (runtime / plan).
_symbol_last_skip: Dict[str, str] = {}

# Traceability counter — incremented on every scheduler cycle that actually runs.
CYCLE_COUNT: int = 0


def run_cycle() -> dict:
    """
    Increment the cycle counter and return a traceable snapshot.
    Called at the start of each live_job execution for audit traceability.
    """
    global CYCLE_COUNT
    CYCLE_COUNT += 1
    return {
        "cycle_id": CYCLE_COUNT,
        "timestamp": datetime.utcnow().isoformat(),
    }


def _runtime_plan_for_symbol(symbol: str, timeframe: str, settings: Any) -> Dict[str, Any]:
    """Per-symbol ML + execution gate before calling the engine (cheap path check)."""
    import os

    from src.ml.model_selector import resolve_model_selection

    ctx = resolve_model_selection(
        base_model_dir=settings.ml_model_dir,
        symbol=symbol,
        timeframe=timeframe,
        version=os.getenv("ML_MODEL_VERSION", "").strip() or None,
    )
    ml_on = bool(getattr(settings, "ml_enabled", False))
    re_ok = bool(ctx.get("runtime_eligible"))
    risk_ok = True
    execution_allowed = (not ml_on) or re_ok
    return {
        "symbol": symbol,
        "enabled": True,
        "exact_match_exists": bool(ctx.get("exact_match_exists")),
        "runtime_eligible": re_ok,
        "risk_ok": risk_ok,
        "execution_allowed": execution_allowed,
        "reason": ctx.get("reason"),
        "fallback_used": bool(ctx.get("fallback_used")),
    }

# Interval in minutes (env SCHEDULER_INTERVAL_MINUTES, default 5). Increase to 10–15
# if each cycle often takes longer than the interval.
def _scheduler_interval_minutes() -> int:
    try:
        v = int(os.getenv("SCHEDULER_INTERVAL_MINUTES", "5").strip())
        return max(1, min(60, v))
    except ValueError:
        return 5


def _is_scheduler_enabled() -> bool:
    """
    Read the live-scheduler flag from the DB (app_settings table).
    Falls back to the LIVE_SCHEDULER_ENABLED env var if the row
    doesn't exist yet (first boot before DB seed).
    """
    try:
        from src.db.models import AppSetting

        db = SessionLocal()
        try:
            row = db.query(AppSetting).filter_by(key="LIVE_SCHEDULER_ENABLED").first()
            if row is not None:
                return row.value.lower() == "true"
        finally:
            db.close()
    except Exception:
        pass  # table may not exist yet
    return os.getenv("LIVE_SCHEDULER_ENABLED", "false").lower() == "true"


def _active_symbols_from_config() -> list[str]:
    """Multi-symbol list from SUPPORTED_TRADING_SYMBOLS (see src.core.symbols)."""
    settings = get_settings()
    return list(settings.supported_trading_symbols)


def live_job():
    """
    Execute auto-trade using AutoTradeEngine.
    Uses a non-blocking lock so only one instance runs at a time; if the previous
    run is still active, this cycle is skipped (no APScheduler 'max instances' skip).
    """
    if not _job_lock.acquire(blocking=False):
        print(
            f"[SCHEDULER][{datetime.utcnow()}] Skipping cycle: previous run still in progress. "
            "Consider increasing SCHEDULER_INTERVAL_MINUTES if this appears often."
        )
        return
    try:
        cycle = run_cycle()
        print(f"[SCHEDULER] cycle_id={cycle['cycle_id']} ts={cycle['timestamp']}")
        _run_live_job(cycle_id=cycle["cycle_id"])
    finally:
        _job_lock.release()


def _run_live_job(cycle_id: int | None = None):
    """Inner live job: one cycle per configured symbol; failures are isolated."""
    db = SessionLocal()
    try:
        settings = get_settings()
        symbols = _active_symbols_from_config()
        timeframe = settings.trade_timeframe

        risk = RiskConfig(
            max_position_pct=0.1,
            stop_loss_pct=0.02,
            take_profit_pct=0.04,
            fee_pct=0.001,
        )

        c = _get_client()
        engine = AutoTradeEngine(db=db, client=c, risk_config=risk)

        b1 = c.balances_map()
        usdt_before = float(b1.get("USDT", "0"))

        any_executed = False
        ml_strict = bool(getattr(settings, "ml_strict", False))
        ml_on = bool(getattr(settings, "ml_enabled", False))
        for symbol in symbols:
            ts = datetime.utcnow()
            plan = _runtime_plan_for_symbol(symbol, timeframe, settings)
            if ml_on and ml_strict and not plan.get("runtime_eligible"):
                print(
                    f"[SCHEDULER][{ts}] {symbol} SKIP: ML_STRICT and model not runtime_eligible "
                    f"(reason={plan.get('reason')}) — no engine call"
                )
                _symbol_last_skip[symbol] = (
                    f"ml_strict_skip:{plan.get('reason', '')}"[:500]
                )
                continue

            if not plan["execution_allowed"]:
                print(
                    f"[SCHEDULER][{ts}] {symbol} runtime_not_eligible (plan) — "
                    f"running engine to persist degraded cycle in DB plan={plan}"
                )

            try:
                result = engine.execute_auto_trade(
                    symbol=symbol,
                    timeframe=timeframe,
                    risk_pct=risk.max_position_pct,
                    triggered_by="scheduler",
                    cycle_id=cycle_id,
                )
                _symbol_last_run[symbol] = ts
                rsn = result.reason or ""
                if "AI runtime degraded" in rsn or "ml_strict" in rsn.lower():
                    _symbol_last_skip[symbol] = rsn[:500]
                else:
                    _symbol_last_skip.pop(symbol, None)
                if result.executed:
                    any_executed = True
                    print(
                        f"[SCHEDULER][{ts}] {symbol} orderId={result.order_id} "
                        f"status={result.exchange_status} price={result.price:.4f}"
                    )
                else:
                    print(
                        f"[SCHEDULER][{ts}] {symbol} signal={result.signal} "
                        f"reason={result.reason}"
                    )
            except Exception as sym_err:
                skip_reason = str(sym_err)[:500]
                print(
                    f"[SCHEDULER][{datetime.utcnow()}] {symbol} SKIP "
                    f"reason={skip_reason}"
                )
                continue

        b2 = c.balances_map()
        usdt_after = float(b2.get("USDT", "0"))
        if any_executed:
            print(
                f"[SCHEDULER][{datetime.utcnow()}] portfolio USDT {usdt_before:.2f}->{usdt_after:.2f}"
            )

        try:
            capture_portfolio_snapshot(db=db, client=c, source="scheduler")
        except Exception as snap_err:
            print(f"[SCHEDULER][{datetime.utcnow()}] snapshot error: {snap_err}")

    except Exception as e:
        print(f"[SCHEDULER][{datetime.utcnow()}] ERROR: {e}")
    finally:
        db.close()


def start_scheduler():
    if not _is_scheduler_enabled():
        print("[SCHEDULER] live disabled (LIVE_SCHEDULER_ENABLED=false)")
        return

    interval_min = _scheduler_interval_minutes()
    # After process restart, run soon so heartbeat recovers automatically
    # (do not wait a full interval before the first post-boot cycle).
    try:
        delay_s = int(os.getenv("SCHEDULER_RESTART_FIRST_RUN_SECONDS", "20").strip())
        delay_s = max(5, min(120, delay_s))
    except ValueError:
        delay_s = 20
    from datetime import timedelta

    first_run = datetime.utcnow() + timedelta(seconds=delay_s)

    scheduler.add_job(
        live_job,
        trigger=IntervalTrigger(minutes=interval_min),
        id="live_trading_job",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=120,  # allow late start so we don't drop cycles when busy
        next_run_time=first_run,
    )
    if not scheduler.running:
        scheduler.start()
    print(
        f"[SCHEDULER] live started (interval={interval_min} min, "
        f"first_run_in≈{delay_s}s)"
    )


def stop_scheduler():
    if scheduler.get_job("live_trading_job"):
        scheduler.remove_job("live_trading_job")

    if scheduler.running:
        scheduler.shutdown(wait=False)

    print("[SCHEDULER] live stopped")
