import os
import subprocess
import sys
import threading
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from src.core.config import get_settings
from src.db.session import engine
from src.api.routes_exchange import router as exchange_router
from src.api.routes_backtest import router as backtest_router
from src.api.routes_logs import router as logs_router
from src.api.routes_paper import router as paper_router
from src.api.routes_live import router as live_router
from src.scheduler.runner import start_scheduler
from src.api.routes_settings import router as settings_router
from src.api.routes_demo import router as demo_router
from src.api.routes_status import router as status_router
from src.api.routes_health import router as health_router
from src.api.routes_health import status_summary as status_summary_handler
from src.api.routes_strategy import router as strategy_router
from src.api.routes_decision import router as decision_router
from src.api.routes_system import router as system_router
from src.api.routes_stats import router as stats_router
from src.api.routes_safety import router as safety_router
from src.api.routes_admin import router as admin_router

try:
    from src.api.routes_auth import router as auth_router

    _auth_available = True
except Exception:
    auth_router = None
    _auth_available = False

# OpenAPI / Swagger: all routers are included; tags below add descriptions in /docs and /redoc.
PHASE1_OPENAPI_TAGS = [
    {
        "name": "Exchange",
        "description": (
            "Trading, portfolio, decisions, proof, ML snapshot. "
            "**Audit:** `GET /exchange/ai-observability`, `GET /exchange/decisions/latest`, "
            "`GET /exchange/orders/all`, `GET /exchange/proof`."
        ),
    },
    {
        "name": "performance",
        "description": "Historical performance / observability under `/exchange/performance/*`.",
    },
    {
        "name": "status",
        "description": (
            "Health and ML readiness. **Audit:** `GET /status/model-health`, "
            "`GET /status/model-health/symbols`, `GET /status/summary`, `GET /status/startup-check`."
        ),
    },
    {
        "name": "stats",
        "description": "Aggregated stats: `GET /stats/performance`, `GET /stats/live-proof`.",
    },
    {"name": "Backtest", "description": "Backtest runs and results."},
    {"name": "logs", "description": "Application logs API."},
    {"name": "paper", "description": "Paper trading."},
    {"name": "live", "description": "Live trading helpers."},
    {"name": "Settings", "description": "App and runtime settings."},
    {"name": "Demo Trading", "description": "Demo / sandbox flows."},
    {"name": "decision", "description": "Decision introspection routes."},
    {"name": "system", "description": "System metadata and controls."},
    {"name": "strategy", "description": "Strategy configuration (`/strategy/*`)."},
    {"name": "auth", "description": "Authentication (if enabled)."},
    {
        "name": "safety",
        "description": (
            "Phase 2A safety layer. **Kill switch:** `GET /safety/kill-switch`, "
            "`POST /safety/kill-switch/engage`, `POST /safety/kill-switch/release`. "
            "**Risk limits:** `GET /safety/limits`. **Reconciliation:** "
            "`GET /safety/reconcile`. **Execution mode:** `GET /execution/mode`, "
            "`POST /execution/mode` (paper | shadow | live). "
            "**Live readiness:** `GET /safety/live-readiness` for a single "
            "go/no-go answer with per-check reasoning."
        ),
    },
    {
        "name": "admin",
        "description": (
            "Phase 2A admin controls. **Binance key rotation from frontend:** "
            "`GET /admin/binance-keys` (masked snapshot), `PUT /admin/binance-keys` "
            "(save runtime overlay), `POST /admin/binance-keys/verify` (test against "
            "Binance), `DELETE /admin/binance-keys/override` (fall back to .env). "
            "Auth: `X-Admin-Token` header (matching `ADMIN_TOKEN` env) **or** any "
            "valid `Authorization: Bearer <jwt>`."
        ),
    },
]

OPENAPI_DESCRIPTION = """### Phase 1 — WebCrest trading API

**Interactive documentation**
- **Swagger UI:** [`/docs`](/docs)
- **ReDoc:** [`/redoc`](/redoc)
- **OpenAPI JSON:** [`/openapi.json`](/openapi.json)

All route modules registered on this app appear in the schema above (no `include_in_schema=False` on public audit routes).

**Typical external validation URLs** (behind nginx use **`/api/...`**, e.g. `GET /api/exchange/ai-observability`):
- `GET /exchange/ai-observability` — runtime ML: `model_loaded`, `inference_count`, `ml_confidence`
- `GET /status/model-health` — optional `load_model`, `smoke` query params
- `GET /status/model-health/symbols` — per-symbol ML readiness
- `GET /status/ml` — config flags + `runtime_model_loaded`, `runtime_inference_count`
- `GET /exchange/decisions/latest?symbol=BTCUSDT`
- `GET /exchange/orders/all?symbol=BTCUSDT`
- `GET /exchange/proof?symbol=BTCUSDT`

**Reverse proxy:** Nginx `location /api/` → this app sees paths **without** `/api`. Set **`OPENAPI_SERVER_PREFIX=/api`** (or **`FASTAPI_ROOT_PATH=/api`**) in `.env` so Swagger **Try it out** builds `http://host/api/exchange/...` instead of `http://host/exchange/...` (which would return the SPA HTML). Relative `openapi.json` still loads the schema under `/api/docs` without extra config.
"""

_fastapi_kw: dict = {
    "title": "AI Trading System - Phase 1",
    "description": OPENAPI_DESCRIPTION,
    "version": os.getenv("APP_VERSION", "1.0").strip(),
    "openapi_tags": PHASE1_OPENAPI_TAGS,
    "openapi_url": "/openapi.json",
    # Always custom /docs + /redoc: default FastAPI uses absolute "/openapi.json", which
    # breaks behind nginx+SPA (browser requests host root → HTML, not OpenAPI JSON).
    "docs_url": None,
    "redoc_url": None,
}
# OpenAPI "servers": Swagger "Try it out" uses this as the request base URL. Without it,
# URLs become http://host/exchange/... and nginx serves the React index.html instead of JSON.
_root_path = os.getenv("FASTAPI_ROOT_PATH", "").strip().rstrip("/")
_swagger_browser_prefix = os.getenv("SWAGGER_BROWSER_OPENAPI_PREFIX", "").strip().rstrip("/")
_openapi_server_prefix = os.getenv("OPENAPI_SERVER_PREFIX", "").strip().rstrip("/")
_effective_public_prefix = _root_path or _swagger_browser_prefix
_server_url = _effective_public_prefix or _openapi_server_prefix
if _effective_public_prefix:
    _fastapi_kw["root_path"] = _effective_public_prefix
if _server_url:
    _fastapi_kw["servers"] = [
        {
            "url": _server_url,
            "description": "Public URL (include nginx /api prefix when applicable)",
        },
    ]

app = FastAPI(**_fastapi_kw)

# Relative to the docs page: .../api/docs → .../api/openapi.json; .../docs → .../openapi.json
_RELATIVE_OPENAPI_SPEC = "openapi.json"


@app.get("/docs", include_in_schema=False)
def _swagger_ui_html():
    return get_swagger_ui_html(
        openapi_url=_RELATIVE_OPENAPI_SPEC,
        title=f"{app.title} - Swagger UI",
    )


@app.get("/redoc", include_in_schema=False)
def _redoc_html():
    return get_redoc_html(
        openapi_url=_RELATIVE_OPENAPI_SPEC,
        title=f"{app.title} - ReDoc",
    )


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _maybe_auto_train_background() -> None:
    """If ML_AUTO_TRAIN_ON_START=true and artifacts missing, run training in a daemon thread."""
    if os.getenv("ML_AUTO_TRAIN_ON_START", "").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        return
    s = get_settings()
    from src.ml.model_verify import check_model_artifacts

    art = check_model_artifacts(Path(s.ml_model_dir))
    if art.get("all_present"):
        print("[STARTUP][ML] artifacts present — skip auto-train")
        return

    root = _repo_root()
    script = root / "scripts" / "train_btc_production.py"
    if not script.is_file():
        print(f"[STARTUP][ML][WARN] auto-train script missing: {script}")
        return

    def _run() -> None:
        env = {**os.environ, "PYTHONPATH": str(root)}
        try:
            subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--limit",
                    "8000",
                    "--epochs",
                    "28",
                ],
                cwd=str(root),
                env=env,
                timeout=7200,
            )
            print("[STARTUP][ML] background training finished")
        except Exception as ex:
            print(f"[STARTUP][ML][ERROR] auto-train failed: {ex}")

    threading.Thread(target=_run, daemon=True).start()
    print(
        "[STARTUP][ML] ML_AUTO_TRAIN_ON_START: background training started "
        "(see logs; inference activates after model files appear)"
    )


def _startup_ml_diagnostics_and_prewarm() -> None:
    """Print resolved paths and load inferencers so model_loaded + artifact_path are real at runtime."""
    import os
    from pathlib import Path

    s = get_settings()
    if not getattr(s, "ml_enabled", False):
        return

    try:
        from src.ml.model_loader import MODELS_ROOT, PROJECT_ROOT, resolve_model_artifact
        from src.ml.model_selector import resolve_model_selection
        from src.ml.model_verify import check_model_artifacts
        from src.ml.inference import get_infer
        from src.core.ml_runtime_state import set_model_loaded, set_model_error

        print("[DIAGNOSTICS] cwd=", os.getcwd())
        print("[DIAGNOSTICS] project_root=", PROJECT_ROOT)
        print("[DIAGNOSTICS] models_root=", MODELS_ROOT)

        symbols = list(getattr(s, "supported_trading_symbols", (s.trade_symbol,)))
        tf = s.trade_timeframe
        version = os.getenv("ML_MODEL_VERSION", "").strip() or None
        loaded_any = False
        last_err = None
        smoke_done = False
        smoke_env = os.getenv("ML_STARTUP_INFERENCE_SMOKE", "true").strip().lower()

        for sym in symbols:
            flat = resolve_model_artifact(sym, tf)
            print("[DIAGNOSTICS][MODEL_FLAT]", sym, flat)

            ctx = resolve_model_selection(
                base_model_dir=s.ml_model_dir,
                symbol=sym,
                timeframe=tf,
                version=version,
            )
            print(
                "[DIAGNOSTICS][MODEL_SEL]",
                sym,
                "dir=",
                ctx.get("model_dir"),
                "exists=",
                ctx.get("model_exists"),
                "artifact=",
                ctx.get("artifact_path"),
            )

            if not ctx.get("model_exists"):
                continue
            art_check = check_model_artifacts(Path(ctx["model_dir"]))
            if not art_check.get("all_present"):
                last_err = f"{sym}: incomplete artifacts {art_check}"
                print("[STARTUP][ML][WARN]", last_err)
                continue
            try:
                _ = get_infer(str(ctx["model_dir"]))
                ap = ctx.get("artifact_path") or art_check.get("model_artifact_path")
                set_model_loaded(sym, tf, str(ap or ctx["model_dir"]))
                loaded_any = True
                print(
                    "[STARTUP][ML] inferencer ready:",
                    sym,
                    ap or ctx["model_dir"],
                )
                if (
                    not smoke_done
                    and smoke_env in ("1", "true", "yes")
                ):
                    from src.ml.startup_ml_smoke import run_public_klines_smoke

                    sm = run_public_klines_smoke(
                        model_dir=str(ctx["model_dir"]),
                        symbol=sym,
                        timeframe=tf,
                        settings=s,
                    )
                    smoke_done = True
                    print("[STARTUP][ML] inference_smoke", sym, sm)
                    if not sm.get("ok"):
                        print(
                            "[STARTUP][ML][WARN] inference_smoke failed (model still loaded):",
                            sm.get("error"),
                        )
            except Exception as exc:
                last_err = str(exc)
                print(f"[STARTUP][ML][ERROR] load {sym}: {exc}")

        if not loaded_any:
            set_model_error(last_err or "no_model_loaded_for_any_symbol")
    except Exception as exc:
        print(f"[STARTUP][ML][ERROR] diagnostics/prewarm: {exc}")


def _startup_ml_model_check() -> None:
    """Log explicit ML resolution at boot (no silent misconfiguration)."""
    s = get_settings()
    if not getattr(s, "ml_enabled", False):
        print("[STARTUP][ML] ML_ENABLED=false — inference disabled")
        return
    if not getattr(s, "ml_strict", True):
        print(
            "[STARTUP][ML][WARN] ML_STRICT=false — ML failures may fall back to rules; "
            "set ML_STRICT=true for production"
        )
    try:
        from src.ml.model_selector import resolve_model_selection
        from src.ml.model_verify import check_model_artifacts

        sym_list = list(getattr(s, "supported_trading_symbols", (s.trade_symbol,)))
        all_ok = True
        for sym in sym_list:
            ctx = resolve_model_selection(
                base_model_dir=s.ml_model_dir,
                symbol=sym,
                timeframe=s.trade_timeframe,
                version=os.getenv("ML_MODEL_VERSION", "").strip() or None,
            )
            re_ok = bool(ctx.get("runtime_eligible"))
            art = check_model_artifacts(Path(ctx.get("model_dir", s.ml_model_dir)))
            print(
                f"[STARTUP][ML] symbol={sym} resolved_dir={ctx.get('model_dir')} "
                f"runtime_eligible={re_ok} exact_match_exists={ctx.get('exact_match_exists')} "
                f"artifact_exists={ctx.get('artifact_exists')}"
            )
            print(
                f"[STARTUP][ML] symbol={sym} artifacts model_keras={art['model_keras']} "
                f"scaler_json={art['scaler_json']} meta_json={art['meta_json']}"
            )
            if not re_ok or not art.get("all_present"):
                all_ok = False
                print(
                    f"[STARTUP][ML][ERROR] symbol={sym} missing model artifacts — "
                    "run: PYTHONPATH=. python scripts/train_multi_coin.py "
                    "or train_btc_production.py / set ML_AUTO_TRAIN_ON_START=true"
                )
        if not all_ok:
            _maybe_auto_train_background()
        else:
            print("[STARTUP][ML] all configured symbols: model artifacts OK")
    except Exception as exc:
        print(f"[STARTUP][ML][ERROR] model resolution failed: {exc}")

# Local dev + Vercel preview; VPS HTTP dashboard (port 80) calling API on another port is cross-origin — list origins.
# Vite dev default port 7000 (see trading-bot-dashboard/vite.config.ts).
# Append CORS_ORIGINS (comma-separated) in .env for extra domains (HTTPS, staging, etc.).
_origins = [
    "http://localhost:7000",
    "http://127.0.0.1:7000",
    "http://147.93.96.42:7000",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
    "https://trading-bot-dashboard-delta.vercel.app",
    "http://147.93.96.42",
]
_extra = os.getenv("CORS_ORIGINS", "").strip()
if _extra:
    _origins = _origins + [o.strip() for o in _extra.split(",") if o.strip()]
origins = _origins

# Dev / LAN: phone testing via http://192.168.x.x:7000 — match without listing every IP.
_cors_regex = None
if os.getenv("APP_ENV", "dev").strip().lower() in ("dev", "development"):
    _cors_regex = r"https?://(localhost|127\.0\.0\.1|192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3})(:\d+)?"

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=_cors_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(backtest_router)
app.include_router(logs_router)
app.include_router(paper_router)
app.include_router(exchange_router)
app.include_router(live_router)
app.include_router(settings_router)
app.include_router(demo_router)
app.include_router(status_router)
app.include_router(health_router)
app.include_router(decision_router)
app.include_router(system_router)
app.include_router(stats_router)
app.include_router(safety_router)
app.include_router(admin_router)
app.include_router(strategy_router, prefix="/strategy")

if _auth_available and auth_router is not None:
    app.include_router(auth_router)


@app.on_event("startup")
def startup():
    # Re-read proxy prefix after full env load; refresh OpenAPI so Swagger "Try it out"
    # uses http://host/api/... (otherwise defaults to /exchange/... → SPA HTML).
    _p = (
        os.getenv("FASTAPI_ROOT_PATH", "").strip().rstrip("/")
        or os.getenv("SWAGGER_BROWSER_OPENAPI_PREFIX", "").strip().rstrip("/")
        or os.getenv("OPENAPI_SERVER_PREFIX", "").strip().rstrip("/")
    )
    if _p:
        app.servers = [
            {
                "url": _p,
                "description": "Behind nginx /api/ (use this in Try it out)",
            },
        ]
        app.openapi_schema = None

    try:
        from src.db.base import Base
        from src.db.models import AppSetting, User, ExchangeConfig  # noqa: F401

        Base.metadata.create_all(bind=engine)

        # Phase 2A: shim Order.client_order_id column on legacy DBs.
        try:
            from src.execution.recovery import ensure_client_order_id_column

            if ensure_client_order_id_column(engine):
                print("[STARTUP] migrated orders.client_order_id column")
        except Exception as e:
            print(f"[STARTUP] client_order_id column shim skipped: {e}")

        # Phase 2A: shim triggered_by/cycle_id columns on legacy DBs.
        try:
            from src.execution.recovery import ensure_trigger_tracking_columns

            if ensure_trigger_tracking_columns(engine):
                print("[STARTUP] migrated triggered_by/cycle_id columns")
        except Exception as e:
            print(f"[STARTUP] trigger tracking column shim skipped: {e}")

        from src.db.session import SessionLocal

        db = SessionLocal()
        try:
            row = db.query(AppSetting).filter_by(key="LIVE_SCHEDULER_ENABLED").first()
            if row is None:
                env_val = os.getenv("LIVE_SCHEDULER_ENABLED", "false").lower()
                db.add(AppSetting(key="LIVE_SCHEDULER_ENABLED", value=env_val))
                db.commit()

            # Phase 2A: hydrate paper / shadow trackers from DB so audits and
            # the reconciler do not see false drift after a process restart.
            try:
                from src.execution.recovery import bootstrap_runtime_state

                summary = bootstrap_runtime_state(db)
                if any(v > 0 for v in summary.values()):
                    print(f"[STARTUP] runtime trackers restored: {summary}")
            except Exception as e:
                print(f"[STARTUP] runtime tracker recovery skipped: {e}")
        finally:
            db.close()
    except Exception as e:
        print(f"[STARTUP] settings seed error: {e}")

    try:
        from src.ml.bootstrap_stub_models import bootstrap_if_enabled

        bootstrap_if_enabled()
    except Exception as e:
        print(f"[STARTUP] ML stub bootstrap: {e}")

    try:
        _startup_ml_model_check()
    except Exception as e:
        print(f"[STARTUP] ML model check: {e}")

    try:
        _startup_ml_diagnostics_and_prewarm()
    except Exception as e:
        print(f"[STARTUP] ML prewarm: {e}")

    try:
        start_scheduler()
    except Exception as e:
        print(f"[SCHEDULER] not started: {e}")


@app.get("/status", tags=["status"])
def status():
    s = get_settings()
    return {
        "ok": True,
        "phase": 1,
        "env": s.app_env,
        "binance_testnet": s.binance_testnet,
        "binance_spot_base_url": s.binance_spot_base_url,
        "trade_symbol": s.trade_symbol,
        "trade_timeframe": s.trade_timeframe,
        "supported_trading_symbols": list(s.supported_trading_symbols),
        "ml_enabled": bool(s.ml_enabled),
        "ml_strict": bool(s.ml_strict),
        "ml_override_threshold": s.ml_override_threshold,
        "ml_prioritize_threshold": s.ml_prioritize_threshold,
        "rl_hybrid_enabled": bool(s.rl_hybrid_enabled),
    }


@app.get("/status/ml", tags=["status"])
def status_ml():
    """Runtime ML flags (verify process actually has ML_ENABLED=true)."""
    from src.core.ml_runtime_state import get_ml_state

    s = get_settings()
    rs = get_ml_state()
    return {
        "ok": True,
        "ml_enabled": bool(s.ml_enabled),
        "ml_strict": bool(s.ml_strict),
        "ml_override_threshold": s.ml_override_threshold,
        "ml_prioritize_threshold": s.ml_prioritize_threshold,
        "ml_agree_threshold": s.ml_agree_threshold,
        "ml_min_trade_confidence": s.ml_min_trade_confidence,
        "ml_absolute_min_confidence": s.ml_absolute_min_confidence,
        "ml_model_dir": s.ml_model_dir,
        "supported_trading_symbols": list(s.supported_trading_symbols),
        "rl_hybrid_enabled": s.rl_hybrid_enabled,
        "rl_ppo_model_path": s.rl_ppo_model_path or None,
        "runtime_model_loaded": bool(rs.get("model_loaded")),
        "runtime_inference_count": int(rs.get("inference_count") or 0),
        "runtime_last_error": rs.get("last_error"),
        "ml_bootstrap_stub_env": os.getenv("ML_BOOTSTRAP_STUB", "true"),
        "hint_if_model_missing": (
            "No weights on disk + no TensorFlow means ML cannot run. "
            "Install deps (Python 3.11/3.12): pip install -r requirements.txt; "
            "restart backend with ML_BOOTSTRAP_STUB=true; "
            "or train: PYTHONPATH=. python scripts/train_multi_coin.py --interval 5m"
        )
        if not rs.get("model_loaded") and bool(s.ml_enabled)
        else None,
    }


@app.get("/status/ml-runtime", tags=["status"])
def status_ml_runtime():
    """Per-symbol ML readiness: exact path, artifacts, inferencer cache (no heavy smoke)."""
    import os

    from src.ml.model_selector import resolve_model_selection
    from src.ml.inference import runtime_health

    s = get_settings()
    ver = os.getenv("ML_MODEL_VERSION", "").strip() or None
    tf = s.trade_timeframe
    out: list[dict] = []
    all_ok = True
    for sym in s.supported_trading_symbols:
        ctx = resolve_model_selection(
            base_model_dir=s.ml_model_dir,
            symbol=sym,
            timeframe=tf,
            version=ver,
        )
        re_ok = bool(ctx.get("runtime_eligible"))
        if re_ok:
            rh = runtime_health(str(ctx["model_dir"]))
            ml_ready = bool(rh.get("ready"))
            if not ml_ready:
                all_ok = False
        else:
            rh = {"ready": False, "error": str(ctx.get("reason"))}
            all_ok = False
            ml_ready = False
        out.append(
            {
                "symbol": sym,
                "timeframe": tf,
                "model_exists": bool(ctx.get("exact_match_exists")),
                "specific_match": bool(ctx.get("exact_match_exists")),
                "runtime_eligible": re_ok,
                "ml_ready": ml_ready,
                "model_dir": ctx.get("model_dir"),
                "detail": rh,
            }
        )
    return {
        "ok": all_ok,
        "trade_timeframe": tf,
        "symbols": out,
    }


@app.get("/status-summary", tags=["status"])
def status_summary_alias():
    """Same payload as GET /status/summary — for audits/tools that expect kebab-case."""
    return status_summary_handler()


@app.get("/health/db", tags=["status"])
def db_health():
    try:
        with engine.connect() as c:
            one = c.execute(text("select 1")).scalar()
        return {"db": "ok", "select_1": one}
    except OperationalError as e:
        return {"db": "error", "detail": str(e.orig)}
