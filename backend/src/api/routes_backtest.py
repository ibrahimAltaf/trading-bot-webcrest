# from fastapi import APIRouter, HTTPException, BackgroundTasks, Query
# from pydantic import BaseModel, Field
# from sqlalchemy.orm import Session
# from sqlalchemy import desc

# from src.backtest.engine import (
#     BacktestConfig,
#     create_backtest_run,
#     run_backtest_for_run_id,
# )
# from src.db.session import SessionLocal
# from src.db.models import BacktestRun, Order, Trade, Position

# router = APIRouter(prefix="/backtest", tags=["backtest"])


# # =========================
# # INPUT SCHEMAS
# # =========================
# class RiskIn(BaseModel):
#     max_position_pct: float = 0.1
#     stop_loss_pct: float = 0.02
#     take_profit_pct: float = 0.04
#     fee_pct: float = 0.001
#     cooldown_minutes_after_loss: int = 60


# class BacktestIn(BaseModel):
#     symbol: str = "BTCUSDT"
#     timeframe: str = "1h"
#     initial_balance: float = 1000.0
#     risk: RiskIn = Field(default_factory=RiskIn)


# def _build_cfg(body: BacktestIn) -> BacktestConfig:
#     cfg = BacktestConfig(
#         symbol=body.symbol,
#         timeframe=body.timeframe,
#         initial_balance=float(body.initial_balance),
#     )
#     cfg.risk.max_position_pct = body.risk.max_position_pct
#     cfg.risk.stop_loss_pct = body.risk.stop_loss_pct
#     cfg.risk.take_profit_pct = body.risk.take_profit_pct
#     cfg.risk.fee_pct = body.risk.fee_pct
#     cfg.risk.cooldown_minutes_after_loss = body.risk.cooldown_minutes_after_loss
#     return cfg


# # =========================
# # RUN BACKTEST (ASYNC STYLE)
# # =========================
# @router.post("/run")
# def run_bt(body: BacktestIn, background: BackgroundTasks):
#     cfg = _build_cfg(body)

#     run_id = create_backtest_run(cfg)
#     background.add_task(run_backtest_for_run_id, run_id, cfg)

#     return {
#         "ok": True,
#         "run_id": run_id,
#         "status": "running",
#     }


# # =========================
# # GET SINGLE RUN
# # =========================
# @router.get("/{run_id}")
# def get_run(run_id: int):
#     db: Session = SessionLocal()
#     try:
#         run = db.query(BacktestRun).filter_by(id=run_id).first()
#         if not run:
#             raise HTTPException(status_code=404, detail="run not found")

#         return {
#             "ok": True,
#             "run": {
#                 "id": run.id,
#                 "symbol": run.symbol,
#                 "timeframe": run.timeframe,
#                 "status": run.status,
#                 "started_at": run.started_at,
#                 "finished_at": run.finished_at,
#                 "initial_balance": run.initial_balance,
#                 "final_balance": run.final_balance,
#                 "total_return_pct": run.total_return_pct,
#                 "max_drawdown_pct": run.max_drawdown_pct,
#                 "trades_count": run.trades_count,
#                 "notes": run.notes,
#             },
#         }
#     finally:
#         db.close()


# # =========================
# # RUN HISTORY (LIST)
# # =========================
# @router.get("/runs")
# def list_runs(
#     limit: int = Query(20, ge=1, le=100),
#     offset: int = Query(0, ge=0),
# ):
#     db = SessionLocal()
#     try:
#         q = (
#             db.query(BacktestRun)
#             .order_by(desc(BacktestRun.started_at))
#             .offset(offset)
#             .limit(limit)
#         )

#         runs = q.all()
#         total = db.query(BacktestRun).count()

#         return {
#             "ok": True,
#             "total": total,
#             "items": [
#                 {
#                     "id": r.id,
#                     "symbol": r.symbol,
#                     "timeframe": r.timeframe,
#                     "status": r.status,
#                     "started_at": r.started_at,
#                     "final_balance": r.final_balance,
#                     "total_return_pct": r.total_return_pct,
#                 }
#                 for r in runs
#             ],
#         }
#     finally:
#         db.close()


# # =========================
# # ORDERS / TRADES / POSITIONS
# # =========================
# @router.get("/{run_id}/orders")
# def run_orders(run_id: int):
#     db = SessionLocal()
#     try:
#         items = (
#             db.query(Order)
#             .filter(Order.backtest_run_id == run_id)
#             .order_by(Order.created_at)
#             .all()
#         )
#         return {"ok": True, "items": items}
#     finally:
#         db.close()


# @router.get("/{run_id}/trades")
# def run_trades(run_id: int):
#     db = SessionLocal()
#     try:
#         items = (
#             db.query(Trade)
#             .filter(Trade.backtest_run_id == run_id)
#             .order_by(Trade.ts)
#             .all()
#         )
#         return {"ok": True, "items": items}
#     finally:
#         db.close()


# @router.get("/{run_id}/positions")
# def run_positions(run_id: int):
#     db = SessionLocal()
#     try:
#         items = db.query(Position).filter_by(symbol=None).all()
#         items = (
#             db.query(Position)
#             .filter(Position.mode == "backtest")
#             .all()
#         )
#         return {"ok": True, "items": items}
#     finally:
#         db.close()


# # =========================
# # SUMMARY / KPIs
# # =========================
# @router.get("/{run_id}/summary")
# def run_summary(run_id: int):
#     db = SessionLocal()
#     try:
#         run = db.query(BacktestRun).filter_by(id=run_id).first()
#         if not run:
#             raise HTTPException(status_code=404, detail="run not found")

#         trades = db.query(Trade).filter_by(backtest_run_id=run_id).all()

#         wins = [t for t in trades if t.side == "SELL" and t.fee is not None]
#         total_trades = len(wins)

#         return {
#             "ok": True,
#             "summary": {
#                 "initial_balance": run.initial_balance,
#                 "final_balance": run.final_balance,
#                 "return_pct": run.total_return_pct,
#                 "max_drawdown_pct": run.max_drawdown_pct,
#                 "trades_count": run.trades_count,
#                 "status": run.status,
#             },
#         }
#     finally:
#         db.close()

from __future__ import annotations

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
import hashlib
import json
import random
from pathlib import Path
from uuid import uuid4
from sqlalchemy.orm import Session
from datetime import datetime

from src.core.config import get_settings
from src.db.session import SessionLocal
from src.backtest.engine import generate_signal
from src.db.models import BacktestRun
from src.backtest.engine import (
    BacktestConfig,
    create_backtest_run,
    run_backtest_for_run_id,
)
import pandas as pd


settings = get_settings()
router = APIRouter(prefix="/backtest", tags=["Backtest"])


# ---------------------------
# DTOs (Data Transfer Objects)
# ---------------------------


class RiskIn(BaseModel):
    """Risk management parameters"""

    max_position_pct: float = Field(
        default=0.1, ge=0.0, le=1.0, description="Max position size as % of balance"
    )
    stop_loss_pct: float = Field(
        default=0.02, ge=0.0, le=1.0, description="Stop loss percentage"
    )
    take_profit_pct: float = Field(
        default=0.04, ge=0.0, le=1.0, description="Take profit percentage"
    )
    fee_pct: float = Field(
        default=0.001, ge=0.0, le=0.1, description="Trading fee percentage"
    )
    cooldown_minutes_after_loss: int = Field(
        default=60, ge=0, description="Cooldown period after loss"
    )


class BacktestIn(BaseModel):
    """Main backtest configuration"""

    symbol: str = Field(default="BTCUSDT", description="Trading pair symbol")
    timeframe: str = Field(
        default="1h", description="Candle timeframe (1m, 5m, 15m, 1h, 4h, 1d)"
    )
    initial_balance: float = Field(
        default=1000.0, gt=0, description="Starting balance in quote currency"
    )
    risk: RiskIn = Field(default_factory=RiskIn)
    seed: Optional[int] = Field(
        default=None, description="Random seed for reproducibility"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "symbol": "BTCUSDT",
                "timeframe": "1h",
                "initial_balance": 10000.0,
                "risk": {
                    "max_position_pct": 0.1,
                    "stop_loss_pct": 0.02,
                    "take_profit_pct": 0.04,
                    "fee_pct": 0.001,
                    "cooldown_minutes_after_loss": 60,
                },
                "seed": 42,
            }
        }


class ValidateIn(BacktestIn):
    """Validation run configuration for multiple backtests"""

    runs: int = Field(default=5, ge=2, le=50, description="Number of validation runs")
    vary_seed: bool = Field(
        default=False, description="Vary seed across runs to test determinism"
    )


class CompareIn(BaseModel):
    """Request to compare multiple backtest runs"""

    run_ids: List[int] = Field(
        ..., min_length=2, description="List of run IDs to compare"
    )


class StrategyParams(BaseModel):
    """Strategy-specific parameters"""

    ema_fast: int = Field(default=12, ge=1, description="Fast EMA period")
    ema_slow: int = Field(default=26, ge=2, description="Slow EMA period")
    rsi_period: int = Field(default=14, ge=1, description="RSI calculation period")
    rsi_overbought: float = Field(
        default=70.0, ge=0, le=100, description="RSI overbought threshold"
    )
    rsi_oversold: float = Field(
        default=30.0, ge=0, le=100, description="RSI oversold threshold"
    )


# ---------------------------
# Helper Functions
# ---------------------------


def _build_cfg(body: BacktestIn) -> BacktestConfig:
    """Convert API request body to BacktestConfig"""
    cfg = BacktestConfig(
        symbol=body.symbol,
        timeframe=body.timeframe,
        initial_balance=float(body.initial_balance),
    )

    cfg.risk.max_position_pct = float(body.risk.max_position_pct)
    cfg.risk.stop_loss_pct = float(body.risk.stop_loss_pct)
    cfg.risk.take_profit_pct = float(body.risk.take_profit_pct)
    cfg.risk.fee_pct = float(body.risk.fee_pct)
    cfg.risk.cooldown_minutes_after_loss = int(body.risk.cooldown_minutes_after_loss)

    return cfg


def _sha256_file(fp: Path) -> str:
    """Calculate SHA256 hash of a file"""
    h = hashlib.sha256()
    with fp.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _klines_to_ohlcv_df(klines: list) -> pd.DataFrame:
    """Build OHLCV DataFrame from Binance klines (list of lists)."""
    if not klines:
        return pd.DataFrame()
    df = pd.DataFrame(
        klines,
        columns=[
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "qav",
            "num_trades",
            "taker_base",
            "taker_quote",
            "ignore",
        ],
    )
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _ensure_features_file(symbol: str, timeframe: str) -> None:
    """
    If features parquet does not exist, fetch klines from Binance, build features,
    and save. This allows backtest to run without a separate data pipeline step.
    """
    fp = Path(settings.data_dir) / "features" / f"{symbol}_{timeframe}_features.parquet"
    if fp.exists():
        return
    try:
        from src.exchange.binance_spot_client import BinanceSpotClient
        from src.features.build_features import build_features
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Cannot build features (missing deps?): {e!s}",
        ) from e
    try:
        client = BinanceSpotClient()
        raw = client.klines(symbol=symbol, interval=timeframe, limit=1000)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch klines from exchange: {e!s}",
        ) from e
    if not raw or len(raw) < 60:
        raise HTTPException(
            status_code=400,
            detail=f"Not enough candles from exchange (got {len(raw) if raw else 0}, need at least 60).",
        )
    df = _klines_to_ohlcv_df(raw)
    df = build_features(df)
    fp.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(fp, index=False)


def _dataset_sha256_for(symbol: str, timeframe: str) -> str:
    """Get SHA256 hash of dataset file for versioning"""
    fp = Path(settings.data_dir) / "features" / f"{symbol}_{timeframe}_features.parquet"
    if not fp.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Features file not found: {fp}. Run data pipeline first.",
        )
    return _sha256_file(fp)


def _apply_seed(seed: Optional[int]) -> None:
    """Apply random seed for reproducibility"""
    if seed is None:
        return
    random.seed(seed)
    try:
        import numpy as np

        np.random.seed(seed)
    except ImportError:
        pass


def _hash_dict(d: Dict[str, Any]) -> str:
    """Create deterministic hash of dictionary"""
    s = json.dumps(d, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# ---------------------------
# API Endpoints
# ---------------------------


@router.get("/health")
def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "backtest-api",
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/strategy/info")
def strategy_info():
    """Get information about the trading strategy"""
    return {
        "name": "EMA Crossover + RSI Thresholds",
        "description": "Combines EMA crossover signals with RSI overbought/oversold conditions",
        "ai_driven": False,
        "signal_generation": "deterministic",
        "parameters": {
            "ema_fast": {
                "default": 12,
                "type": "int",
                "description": "Period for fast exponential moving average",
            },
            "ema_slow": {
                "default": 26,
                "type": "int",
                "description": "Period for slow exponential moving average",
            },
            "rsi_period": {
                "default": 14,
                "type": "int",
                "description": "Period for RSI calculation",
            },
            "rsi_overbought": {
                "default": 70.0,
                "type": "float",
                "description": "RSI threshold for overbought condition",
            },
            "rsi_oversold": {
                "default": 30.0,
                "type": "float",
                "description": "RSI threshold for oversold condition",
            },
        },
    }


@router.get("/signal")
def get_live_signal(symbol: str = "BTCUSDT", timeframe: str = "1h"):
    try:
        # Load latest features
        fp = (
            Path(settings.data_dir)
            / "features"
            / f"{symbol}_{timeframe}_features.parquet"
        )
        if not fp.exists():
            raise HTTPException(status_code=404, detail="Feature dataset not found")

        df = pd.read_parquet(fp).sort_values("open_time")
        last_row = df.iloc[-1]

        signal = generate_signal(last_row)

        return {
            "ok": True,
            "symbol": symbol,
            "timeframe": timeframe,
            "price": float(last_row["close"]),
            "signal": signal,
            "ema_fast": float(last_row["ema_20"]),
            "ema_slow": float(last_row["ema_50"]),
            "rsi": float(last_row["rsi_14"]),
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/dataset/fingerprint")
def dataset_fingerprint(symbol: str = "BTCUSDT", timeframe: str = "1h"):
    """Get dataset fingerprint for version tracking"""
    fp = Path(settings.data_dir) / "features" / f"{symbol}_{timeframe}_features.parquet"

    if not fp.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Features not found: {fp}. Available datasets can be listed via data pipeline.",
        )

    digest = _sha256_file(fp)
    stat = fp.stat()
    
    # Make path relative to project root
    try:
        rel_path = fp.relative_to(Path.cwd())
    except ValueError:
        rel_path = fp

    return {
        "ok": True,
        "symbol": symbol,
        "timeframe": timeframe,
        "path": str(rel_path),
        "sha256": digest,
        "bytes": stat.st_size,
        "mtime_utc": stat.st_mtime,
        "note": "Use sha256 as dataset_version for reproducibility controls.",
    }


@router.post("/run")
def run_backtest(body: BacktestIn, background: BackgroundTasks):
    """
    Start a new backtest run

    The backtest will run in the background. Poll GET /backtest/{run_id} to check status.
    If the features file is missing, it is built automatically from exchange klines.
    """
    try:
        cfg = _build_cfg(body)
        _ensure_features_file(body.symbol, body.timeframe)
        dataset_sha = _dataset_sha256_for(body.symbol, body.timeframe)

        # Apply seed if provided
        if body.seed is not None:
            _apply_seed(body.seed)

        # Create backtest run record in DB
        run_id = create_backtest_run(cfg, seed=body.seed, dataset_sha256=dataset_sha)

        # Schedule backtest execution in background
        background.add_task(run_backtest_for_run_id, run_id, cfg)

        return {
            "ok": True,
            "run_id": run_id,
            "status": "running",
            "seed": body.seed,
            "dataset_sha256": dataset_sha,
            "message": f"Backtest started. Poll GET /backtest/{run_id} for status.",
        }

    except HTTPException:
        raise
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to start backtest: {str(e)}"
        )


@router.get("/{run_id}")
def get_backtest_run(run_id: int):
    """
    Get details of a specific backtest run

    Poll this endpoint until status becomes 'success' or 'failed'.
    """
    db: Session = SessionLocal()
    try:
        run = db.query(BacktestRun).filter(BacktestRun.id == run_id).first()

        if not run:
            raise HTTPException(
                status_code=404, detail=f"Backtest run {run_id} not found"
            )

        return {
            "ok": True,
            "run": {
                "id": int(run.id),
                "symbol": run.symbol,
                "timeframe": run.timeframe,
                "status": run.status,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "initial_balance": (
                    float(run.initial_balance)
                    if run.initial_balance is not None
                    else None
                ),
                "final_balance": (
                    float(run.final_balance) if run.final_balance is not None else None
                ),
                "total_return_pct": (
                    float(run.total_return_pct)
                    if run.total_return_pct is not None
                    else None
                ),
                "max_drawdown_pct": (
                    float(run.max_drawdown_pct)
                    if run.max_drawdown_pct is not None
                    else None
                ),
                "trades_count": (
                    int(run.trades_count) if run.trades_count is not None else 0
                ),
                "win_rate": (
                    float(run.win_rate)
                    if hasattr(run, "win_rate") and run.win_rate is not None
                    else None
                ),
                "sharpe_ratio": (
                    float(run.sharpe_ratio)
                    if hasattr(run, "sharpe_ratio") and run.sharpe_ratio is not None
                    else None
                ),
                "notes": run.notes,
                "dataset_sha256": (
                    run.dataset_sha256 if hasattr(run, "dataset_sha256") else None
                ),
                "seed": run.seed if hasattr(run, "seed") else None,
            },
        }
    finally:
        db.close()


@router.get("/runs/list")
def list_backtest_runs(
    skip: int = 0,
    limit: int = 10,
    status: Optional[str] = None,
    symbol: Optional[str] = None,
):
    """List all backtest runs with optional filtering"""
    db: Session = SessionLocal()
    try:
        query = db.query(BacktestRun)

        if status:
            query = query.filter(BacktestRun.status == status)
        if symbol:
            query = query.filter(BacktestRun.symbol == symbol)

        total = query.count()
        runs = query.order_by(BacktestRun.id.desc()).offset(skip).limit(limit).all()

        return {
            "ok": True,
            "total": total,
            "skip": skip,
            "limit": limit,
            "runs": [
                {
                    "id": r.id,
                    "symbol": r.symbol,
                    "timeframe": r.timeframe,
                    "status": r.status,
                    "started_at": r.started_at.isoformat() if r.started_at else None,
                    "final_balance": (
                        float(r.final_balance) if r.final_balance is not None else None
                    ),
                    "total_return_pct": (
                        float(r.total_return_pct)
                        if r.total_return_pct is not None
                        else None
                    ),
                }
                for r in runs
            ],
        }
    finally:
        db.close()


@router.post("/validate")
def validate_backtest(body: ValidateIn, background: BackgroundTasks):
    """
    Run multiple backtests for validation and reproducibility testing

    This endpoint runs the same backtest configuration multiple times to verify:
    - Reproducibility (same seed should give same results)
    - Determinism (strategy should be consistent)
    """
    try:
        cfg = _build_cfg(body)
        dataset_sha = _dataset_sha256_for(body.symbol, body.timeframe)

        batch_id = str(uuid4())
        run_ids: List[int] = []
        base_seed = body.seed if body.seed is not None else 0

        for i in range(body.runs):
            # Vary seed if requested, otherwise use same seed
            seed_i = (base_seed + i) if body.vary_seed else base_seed

            if seed_i is not None:
                _apply_seed(seed_i)

            run_id = create_backtest_run(cfg, seed=seed_i, dataset_sha256=dataset_sha)
            run_ids.append(run_id)
            background.add_task(run_backtest_for_run_id, run_id, cfg)

        return {
            "ok": True,
            "batch_id": batch_id,
            "dataset_sha256": dataset_sha,
            "vary_seed": body.vary_seed,
            "runs_count": body.runs,
            "run_ids": run_ids,
            "message": "Validation runs started. Poll GET /backtest/{run_id} for each run, then use POST /backtest/validate/compare to compare results.",
        }

    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to start validation: {str(e)}"
        )


@router.post("/validate/compare")
def compare_backtest_runs(body: CompareIn):
    """
    Compare results across multiple backtest runs

    Use this to verify reproducibility and analyze variance across runs.
    """
    db: Session = SessionLocal()
    try:
        runs = db.query(BacktestRun).filter(BacktestRun.id.in_(body.run_ids)).all()

        if len(runs) != len(body.run_ids):
            missing = set(body.run_ids) - {r.id for r in runs}
            raise HTTPException(status_code=404, detail=f"Run IDs not found: {missing}")

        # Check if all runs are complete
        incomplete = [r for r in runs if r.status not in ("success", "failed")]
        if incomplete:
            return {
                "ok": True,
                "ready": False,
                "message": f"{len(incomplete)} runs still in progress",
                "runs": [
                    {
                        "id": r.id,
                        "status": r.status,
                        "started_at": (
                            r.started_at.isoformat() if r.started_at else None
                        ),
                    }
                    for r in incomplete
                ],
            }

        # Build comparison data
        items = []
        for r in sorted(runs, key=lambda x: x.id):
            items.append(
                {
                    "run_id": r.id,
                    "status": r.status,
                    "seed": r.seed if hasattr(r, "seed") else None,
                    "final_balance": (
                        float(r.final_balance) if r.final_balance is not None else None
                    ),
                    "total_return_pct": (
                        float(r.total_return_pct)
                        if r.total_return_pct is not None
                        else None
                    ),
                    "max_drawdown_pct": (
                        float(r.max_drawdown_pct)
                        if r.max_drawdown_pct is not None
                        else None
                    ),
                    "trades_count": (
                        int(r.trades_count) if r.trades_count is not None else 0
                    ),
                    "win_rate": (
                        float(r.win_rate)
                        if hasattr(r, "win_rate") and r.win_rate is not None
                        else None
                    ),
                    "notes": r.notes,
                }
            )

        # Check reproducibility (all successful runs should have identical results)
        successful_items = [x for x in items if x["status"] == "success"]

        if len(successful_items) < 2:
            reproducible = None
            message = "Need at least 2 successful runs to check reproducibility"
        else:
            first = successful_items[0]
            # Combine with `and` — `all((a,b,c))` per item wrongly treated a tuple as one truthy value.
            def _matches(x: dict) -> bool:
                fb_ok = (
                    abs(x["final_balance"] - first["final_balance"]) < 0.01
                    if x["final_balance"] and first["final_balance"]
                    else x["final_balance"] == first["final_balance"]
                )
                ret_ok = (
                    abs(x["total_return_pct"] - first["total_return_pct"]) < 0.01
                    if x["total_return_pct"] and first["total_return_pct"]
                    else x["total_return_pct"] == first["total_return_pct"]
                )
                tc_ok = x["trades_count"] == first["trades_count"]
                return bool(fb_ok and ret_ok and tc_ok)

            reproducible = all(_matches(x) for x in successful_items[1:])
            message = (
                "All runs match - strategy is reproducible"
                if reproducible
                else "Variance detected across runs"
            )

        # Calculate statistics
        stats = None
        if successful_items:
            returns = [
                x["total_return_pct"]
                for x in successful_items
                if x["total_return_pct"] is not None
            ]
            if returns:
                stats = {
                    "mean_return_pct": sum(returns) / len(returns),
                    "min_return_pct": min(returns),
                    "max_return_pct": max(returns),
                    "std_return_pct": (
                        (
                            sum((x - sum(returns) / len(returns)) ** 2 for x in returns)
                            / len(returns)
                        )
                        ** 0.5
                        if len(returns) > 1
                        else 0
                    ),
                }

        return {
            "ok": True,
            "ready": True,
            "reproducible": reproducible,
            "message": message,
            "total_runs": len(items),
            "successful_runs": len(successful_items),
            "failed_runs": len([x for x in items if x["status"] == "failed"]),
            "statistics": stats,
            "items": items,
        }

    finally:
        db.close()


@router.delete("/{run_id}")
def delete_backtest_run(run_id: int):
    """Delete a backtest run"""
    db: Session = SessionLocal()
    try:
        run = db.query(BacktestRun).filter(BacktestRun.id == run_id).first()

        if not run:
            raise HTTPException(
                status_code=404, detail=f"Backtest run {run_id} not found"
            )

        db.delete(run)
        db.commit()

        return {"ok": True, "message": f"Backtest run {run_id} deleted"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete run: {str(e)}")
    finally:
        db.close()
