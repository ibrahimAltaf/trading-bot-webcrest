import os
from pathlib import Path
from dataclasses import dataclass
from typing import Tuple

from dotenv import load_dotenv

from src.core.symbols import parse_supported_trading_symbols


def _project_root() -> Path:
    """Backend package root (folder that contains `src/` and `models/`)."""
    return Path(__file__).resolve().parents[2]


# Load env from project root (not process cwd).
# Order: .env.production (VPS / deploy) → .env (local overrides) → .env.local (developer).
# override=False on production so Docker/systemd-injected vars and pytest's DATABASE_URL are not stomped.
_root = _project_root()
_env_prod = _root / ".env.production"
_env_base = _root / ".env"
_env_local = _root / ".env.local"
if _env_prod.is_file():
    load_dotenv(_env_prod, override=False)

# `.env` uses override=True; an empty line can wipe systemd-injected values.
_fastapi_root_before_dotenv_overrides = os.getenv("FASTAPI_ROOT_PATH", "").strip()
_openapi_server_before_dotenv_overrides = os.getenv("OPENAPI_SERVER_PREFIX", "").strip()

if _env_base.is_file():
    load_dotenv(_env_base, override=True)
if _env_local.is_file():
    load_dotenv(_env_local, override=True)

if _fastapi_root_before_dotenv_overrides and not os.getenv("FASTAPI_ROOT_PATH", "").strip():
    os.environ["FASTAPI_ROOT_PATH"] = _fastapi_root_before_dotenv_overrides
if _openapi_server_before_dotenv_overrides and not os.getenv(
    "OPENAPI_SERVER_PREFIX", ""
).strip():
    os.environ["OPENAPI_SERVER_PREFIX"] = _openapi_server_before_dotenv_overrides


@dataclass(frozen=True)
class Settings:
    app_env: str
    database_url: str
    data_dir: str
    log_level: str
    binance_testnet: bool
    binance_api_key: str
    binance_api_secret: str
    binance_spot_base_url: str
    # ML settings
    ml_enabled: bool
    ml_model_dir: str
    ml_lookback: int
    ml_agree_threshold: float
    ml_override_threshold: float
    ml_prioritize_threshold: float
    # When rules say HOLD but ML is directional (BUY/SELL), adopt ML if confidence >= min
    ml_hold_breakout_enabled: bool
    ml_hold_breakout_min_confidence: float
    # When ML says HOLD but rules are directional (BUY/SELL), allow rule if confidence >= min
    rule_directional_ml_neutral_enabled: bool
    rule_directional_min_confidence: float
    # If ML_ENABLED: fail cycle loudly when model missing or inference fails (no silent rule-only fallback)
    ml_strict: bool
    # When true, require exact symbol/timeframe model match for live trading (no fallback to generic model)
    ml_require_exact_symbol_match: bool
    # When true, block BUY when any entry gate fails (observability-first default: false)
    strict_entry_gates: bool
    # Fernet key (urlsafe base64) for encrypting persisted exchange secrets; empty = store plaintext (dev only)
    secrets_encryption_key: str
    # Minimum ML softmax confidence to execute when trade is ML-driven (0–1)
    ml_min_trade_confidence: float
    # Never execute ML-driven trades below this (safety floor, default 0.5)
    ml_absolute_min_confidence: float
    # If > 0: block trades when ADX below this (sideways filter); 0 disables
    ml_min_adx_for_trade: float
    # If > 0: block when ATR%% below this (dead market); 0 disables
    ml_min_atr_pct_for_trade: float
    # Adaptive Trading Strategy Parameters
    # General
    trade_symbol: str
    trade_timeframe: str
    trade_lookback: int
    # Multi-coin: Binance symbols (e.g. BTCUSDT,ETHUSDT,SOLUSDT); scheduler runs each
    supported_trading_symbols: Tuple[str, ...]
    # RL portfolio (optional; requires requirements-rl.txt)
    rl_hybrid_enabled: bool
    rl_ppo_model_path: str
    rl_max_weight_per_asset: float
    portfolio_rebalance_cycles: int
    portfolio_max_drawdown_pct: float
    portfolio_loss_reduce_factor: float
    # Regime Detection
    adx_threshold: float
    atr_vol_threshold: float
    # Trending Rules
    ema_fast: int
    ema_slow: int
    rsi_len: int
    rsi_buy_min: float
    rsi_buy_max: float
    rsi_take_profit: float
    # Ranging Rules
    bb_len: int
    bb_std: float
    rsi_range_buy: float
    rsi_range_sell: float
    # Risk Management
    max_risk_per_trade: float
    stop_loss_atr_mult: float
    take_profit_rr: float
    max_open_trades: int
    cooldown_seconds: int
    # Order Execution Mode
    demo_open_only: bool
    demo_fill_mode: bool
    # When true, BUY uses in-process paper fills (orderId paper-*) for Phase-1 audit proof without exchange fills
    phase1_paper_execution: bool
    # Engine selection
    fully_adaptive_engine: bool
    # Binance Demo Mode
    binance_demo_api_key: str
    binance_demo_api_secret: str
    binance_demo_base_url: str
    # Testing: relax entry conditions to allow more BUY/SELL signals (for validation only)
    relaxed_entry_for_testing: bool
    # Auth (JWT) for login / exchange config
    jwt_secret: str
    jwt_algorithm: str
    jwt_expire_minutes: int


def _env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "y")


def _env_int(name: str, default: str) -> int:
    v = os.getenv(name, default).strip()
    try:
        return int(v)
    except ValueError:
        raise RuntimeError(f"{name} must be an integer. Got: {v!r}")


def _env_float(name: str, default: str) -> float:
    v = os.getenv(name, default).strip()
    try:
        return float(v)
    except ValueError:
        raise RuntimeError(f"{name} must be a float. Got: {v!r}")


def get_settings() -> Settings:
    # Required
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is missing in .env")

    # Optional / defaulted
    app_env = os.getenv("APP_ENV", "dev").strip()

    # Paths relative to project root (not process cwd)
    data_dir = os.getenv("DATA_DIR", "./data").strip()
    _dp = Path(data_dir)
    data_path = _dp.resolve() if _dp.is_absolute() else (_project_root() / _dp).resolve()
    data_path.mkdir(parents=True, exist_ok=True)

    log_level = os.getenv("LOG_LEVEL", "INFO").strip()
    binance_testnet = _env_bool("BINANCE_TESTNET", "true")
    binance_api_key = os.getenv("BINANCE_API_KEY", "").strip()
    binance_api_secret = os.getenv("BINANCE_API_SECRET", "").strip()

    # default base URLs
    spot_mainnet = os.getenv(
        "BINANCE_SPOT_MAINNET_URL", "https://api.binance.com"
    ).strip()
    spot_testnet = os.getenv(
        "BINANCE_SPOT_TESTNET_URL", "https://testnet.binance.vision"
    ).strip()
    binance_spot_base_url = spot_testnet if binance_testnet else spot_mainnet

    # ===== ML (Phase-1 included, feature-flagged) =====
    # Default true: ML is part of the product pipeline; disable explicitly for dev/CI without a model.
    ml_enabled = _env_bool("ML_ENABLED", "true")
    ml_model_dir = os.getenv("ML_MODEL_DIR", "models").strip()
    ml_lookback = _env_int("ML_LOOKBACK", "50")
    ml_agree_threshold = _env_float("ML_AGREE_THRESHOLD", "0.70")
    # When ML confidence >= this, follow ML even if directional rules disagree.
    ml_override_threshold = _env_float("ML_OVERRIDE_THRESHOLD", "0.60")
    ml_prioritize_threshold = _env_float("ML_PRIORITIZE_THRESHOLD", "0.70")
    ml_hold_breakout_enabled = _env_bool("ML_HOLD_BREAKOUT_ENABLED", "true")
    ml_hold_breakout_min_confidence = _env_float(
        "ML_HOLD_BREAKOUT_MIN_CONFIDENCE", "0.52"
    )
    rule_directional_ml_neutral_enabled = _env_bool(
        "RULE_DIRECTIONAL_ML_NEUTRAL_ENABLED", "true"
    )
    rule_directional_min_confidence = _env_float(
        "RULE_DIRECTIONAL_MIN_CONFIDENCE", "0.55"
    )
    # When ML is enabled and a model is expected, do not silently fall back to rules on load/infer failure.
    ml_strict = _env_bool("ML_STRICT", "true")
    ml_require_exact_symbol_match = _env_bool("ML_REQUIRE_EXACT_SYMBOL_MATCH", "true")
    strict_entry_gates = _env_bool("STRICT_ENTRY_GATES", "false")
    secrets_encryption_key = os.getenv("SECRETS_ENCRYPTION_KEY", "").strip()
    ml_min_trade_confidence = _env_float("ML_MIN_TRADE_CONFIDENCE", "0.50")
    ml_absolute_min_confidence = _env_float("ML_ABSOLUTE_MIN_CONFIDENCE", "0.50")
    ml_min_adx_for_trade = _env_float("ML_MIN_ADX_FOR_TRADE", "0")
    ml_min_atr_pct_for_trade = _env_float("ML_MIN_ATR_PCT_FOR_TRADE", "0")

    _mp = Path(ml_model_dir)
    ml_model_path = _mp.resolve() if _mp.is_absolute() else (_project_root() / _mp).resolve()

    # ===== Adaptive Trading Strategy Parameters =====
    # General
    trade_symbol = os.getenv("TRADE_SYMBOL", "BTCUSDT").strip()
    trade_timeframe = os.getenv("TRADE_TIMEFRAME", "5m").strip()
    trade_lookback = _env_int("TRADE_LOOKBACK", "500")
    supported_trading_symbols = parse_supported_trading_symbols()
    rl_hybrid_enabled = _env_bool("RL_HYBRID_ENABLED", "false")
    rl_ppo_model_path = os.getenv("RL_PPO_MODEL_PATH", "").strip()
    rl_max_weight_per_asset = _env_float("RL_MAX_WEIGHT_PER_ASSET", "0.40")
    portfolio_rebalance_cycles = _env_int("PORTFOLIO_REBALANCE_CYCLES", "20")
    portfolio_max_drawdown_pct = _env_float("PORTFOLIO_MAX_DRAWDOWN_PCT", "0.15")
    portfolio_loss_reduce_factor = _env_float("PORTFOLIO_LOSS_REDUCE_FACTOR", "0.65")

    # Regime Detection
    adx_threshold = _env_float("ADX_THRESHOLD", "25.0")
    atr_vol_threshold = _env_float("ATR_VOL_THRESHOLD", "2.0")

    # Trending Rules
    ema_fast = _env_int("EMA_FAST", "20")
    ema_slow = _env_int("EMA_SLOW", "50")
    rsi_len = _env_int("RSI_LEN", "14")
    rsi_buy_min = _env_float("RSI_BUY_MIN", "45.0")
    rsi_buy_max = _env_float("RSI_BUY_MAX", "70.0")
    rsi_take_profit = _env_float("RSI_TAKE_PROFIT", "75.0")

    # Ranging Rules
    bb_len = _env_int("BB_LEN", "20")
    bb_std = _env_float("BB_STD", "2.0")
    rsi_range_buy = _env_float("RSI_RANGE_BUY", "35.0")
    rsi_range_sell = _env_float("RSI_RANGE_SELL", "65.0")

    # Risk Management
    max_risk_per_trade = _env_float("MAX_RISK_PER_TRADE", "0.01")  # 1%
    stop_loss_atr_mult = _env_float("STOP_LOSS_ATR_MULT", "2.0")
    take_profit_rr = _env_float("TAKE_PROFIT_RR", "2.0")  # Risk:Reward 1:2
    max_open_trades = _env_int("MAX_OPEN_TRADES", "1")
    cooldown_seconds = _env_int("COOLDOWN_SECONDS", "60")

    # Order Execution Mode
    demo_open_only = _env_bool("DEMO_OPEN_ONLY", "false")
    demo_fill_mode = _env_bool("DEMO_FILL_MODE", "true")
    phase1_paper_execution = _env_bool("PHASE1_PAPER_EXECUTION", "false")
    # Engine selection
    fully_adaptive_engine = _env_bool("FULLY_ADAPTIVE_ENGINE", "false")

    # Binance Demo Mode credentials / base URL
    binance_demo_api_key = os.getenv("BINANCE_DEMO_API_KEY", "").strip()
    binance_demo_api_secret = os.getenv("BINANCE_DEMO_API_SECRET", "").strip()
    binance_demo_base_url = os.getenv(
        "BINANCE_DEMO_BASE_URL", "https://demo-api.binance.com"
    ).strip()

    relaxed_entry_for_testing = _env_bool("RELAXED_ENTRY_FOR_TESTING", "false")

    jwt_secret = os.getenv("JWT_SECRET", "change-me-in-production").strip()
    jwt_algorithm = os.getenv("JWT_ALGORITHM", "HS256").strip()
    jwt_expire_minutes = int(os.getenv("JWT_EXPIRE_MINUTES", "10080"))  # 7 days default

    return Settings(
        app_env=app_env,
        database_url=database_url,
        data_dir=str(data_path),
        log_level=log_level,
        binance_testnet=binance_testnet,
        binance_api_key=binance_api_key,
        binance_api_secret=binance_api_secret,
        binance_spot_base_url=binance_spot_base_url,
        # ML
        ml_enabled=ml_enabled,
        ml_model_dir=str(ml_model_path),
        ml_lookback=ml_lookback,
        ml_agree_threshold=ml_agree_threshold,
        ml_override_threshold=ml_override_threshold,
        ml_prioritize_threshold=ml_prioritize_threshold,
        ml_hold_breakout_enabled=ml_hold_breakout_enabled,
        ml_hold_breakout_min_confidence=ml_hold_breakout_min_confidence,
        rule_directional_ml_neutral_enabled=rule_directional_ml_neutral_enabled,
        rule_directional_min_confidence=rule_directional_min_confidence,
        ml_strict=ml_strict,
        ml_require_exact_symbol_match=ml_require_exact_symbol_match,
        strict_entry_gates=strict_entry_gates,
        secrets_encryption_key=secrets_encryption_key,
        ml_min_trade_confidence=ml_min_trade_confidence,
        ml_absolute_min_confidence=ml_absolute_min_confidence,
        ml_min_adx_for_trade=ml_min_adx_for_trade,
        ml_min_atr_pct_for_trade=ml_min_atr_pct_for_trade,
        # Adaptive Trading
        trade_symbol=trade_symbol,
        trade_timeframe=trade_timeframe,
        trade_lookback=trade_lookback,
        supported_trading_symbols=supported_trading_symbols,
        rl_hybrid_enabled=rl_hybrid_enabled,
        rl_ppo_model_path=rl_ppo_model_path,
        rl_max_weight_per_asset=rl_max_weight_per_asset,
        portfolio_rebalance_cycles=portfolio_rebalance_cycles,
        portfolio_max_drawdown_pct=portfolio_max_drawdown_pct,
        portfolio_loss_reduce_factor=portfolio_loss_reduce_factor,
        adx_threshold=adx_threshold,
        atr_vol_threshold=atr_vol_threshold,
        ema_fast=ema_fast,
        ema_slow=ema_slow,
        rsi_len=rsi_len,
        rsi_buy_min=rsi_buy_min,
        rsi_buy_max=rsi_buy_max,
        rsi_take_profit=rsi_take_profit,
        bb_len=bb_len,
        bb_std=bb_std,
        rsi_range_buy=rsi_range_buy,
        rsi_range_sell=rsi_range_sell,
        max_risk_per_trade=max_risk_per_trade,
        stop_loss_atr_mult=stop_loss_atr_mult,
        take_profit_rr=take_profit_rr,
        max_open_trades=max_open_trades,
        cooldown_seconds=cooldown_seconds,
        demo_open_only=demo_open_only,
        demo_fill_mode=demo_fill_mode,
        phase1_paper_execution=phase1_paper_execution,
        fully_adaptive_engine=fully_adaptive_engine,
        binance_demo_api_key=binance_demo_api_key,
        binance_demo_api_secret=binance_demo_api_secret,
        binance_demo_base_url=binance_demo_base_url,
        relaxed_entry_for_testing=relaxed_entry_for_testing,
        jwt_secret=jwt_secret,
        jwt_algorithm=jwt_algorithm,
        jwt_expire_minutes=jwt_expire_minutes,
    )
