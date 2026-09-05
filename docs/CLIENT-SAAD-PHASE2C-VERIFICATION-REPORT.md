# TRADING BOT — Phase 2C Pre-Activation Verification Report

**Prepared for:** Saad Salim
**Prepared by:** Webcrest Team (Mubeen)
**Date:** 5 September 2026
**Production:** https://bot.webcrestllc.com
**API base:** https://bot.webcrestllc.com/api
**Repository:** https://github.com/ibrahimAltaf/trading-bot-webcrest
**Verified commit:** `3052463b56371276e6c53d783ae7983048334ed2`

---

## 1. Purpose

This report answers the final pre-activation confirmation checklist. Every item was verified twice:

1. In the source tree at commit `3052463` (and on `origin/main`).
2. Against the running production container on the VPS.

The review comments referencing `run_live_trade(...)` in `routes_live.py` and direct
`BinanceSpotClient` calls in `routes_exchange.py` describe an **earlier source package**.
Those code paths no longer exist at commit `3052463`.

---

## 2. Confirmation Checklist

| # | Requirement | Status | Evidence |
|---|-------------|--------|----------|
| 1 | `POST /live/run` returns 410 Gone | Confirmed | Handler `run_live_disabled` raises `HTTP_410_GONE`; production returns `410` |
| 2 | `POST /exchange/order/limit-buy` returns 410 Gone | Confirmed | Handler `place_limit_buy_disabled`; production returns `410` |
| 3 | `POST /exchange/order/limit-sell` returns 410 Gone | Confirmed | Handler `place_limit_sell_disabled`; production returns `410` |
| 4 | `POST /exchange/order/cancel` returns 410 Gone | Confirmed | Handler `cancel_order_disabled`; production returns `410` |
| 5 | Daily loss uses `>= 1.50 USDT` | Confirmed | `risk_engine.py:329` uses `loss >= self.limits.max_daily_loss_usdt` |
| 6 | MIN_NOTIONAL can never raise an order above the 5 USDT cap | Confirmed | Live BUY rejects instead of increasing spend |
| 7 | Adaptive AI thresholds independent of risk/position sizing | Confirmed | Caps applied only in RiskEngine / position sizing |
| 8 | Micro-Live remains disabled | Confirmed | `micro_live_enabled: false` |
| 9 | Execution mode remains Shadow | Confirmed | `effective_mode: "shadow"` |
| 10 | No real trades executed | Confirmed | No live order placement performed during corrections |

---

## 3. Item Detail

### 3.1 `POST /live/run` — Disabled

`backend/src/api/routes_live.py` no longer imports `run_live_trade` or `RiskConfig`.
The route exists only to return an explicit 410 so callers receive a clear error
instead of a misleading 404:

```python
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
```

`app.include_router(live_router)` is intentionally retained in `main.py`. Removing the
router would return 404 and leave no explicit record that the path is deliberately
retired. The router contains no executable order path.

### 3.2 Legacy direct-order endpoints — Disabled

All three legacy handlers in `backend/src/api/routes_exchange.py` were replaced with
410 responses. None of them instantiate `BinanceSpotClient` or call any order function:

| Route | Handler | Line |
|-------|---------|------|
| `POST /exchange/order/limit-buy` | `place_limit_buy_disabled` | 679 |
| `POST /exchange/order/limit-sell` | `place_limit_sell_disabled` | 692 |
| `POST /exchange/order/cancel` | `cancel_order_disabled` | 710 |

Read-only routes (`GET /exchange/order`, `GET /exchange/orders/open`,
`GET /exchange/orders/all`) remain available for monitoring and audit.

### 3.3 Daily loss boundary — `>=`

`backend/src/safety/risk_engine.py`:

```python
loss = -float(self.state.daily_realized_pnl_usdt or 0.0)
if loss >= self.limits.max_daily_loss_usdt:
    return (
        False,
        "max_daily_loss",
        f"daily_loss {loss:.2f} >= max {self.limits.max_daily_loss_usdt:.2f}",
    )
```

Reaching exactly 1.50 USDT of daily realized loss blocks new entries. Cumulative loss
uses the same `>=` boundary at 3.00 USDT.

### 3.4 MIN_NOTIONAL — order rejected, never increased

The live BUY path previously used `max(spend, min_notional)`, which could raise the
order size. That behaviour was removed. The current logic rejects instead:

```python
spend_f = float(spend)
if min_notional > 0 and spend_f < min_notional:
    return TradeResult(
        success=True,
        executed=False,
        signal="BUY",
        reason=(
            f"exchange minNotional ({min_notional:.2f}) exceeds "
            f"requested spend ({spend_f:.2f}); order not increased"
        ),
        balance_before=balance,
    )

target_spend = spend_f
if max_cap > 0 and target_spend > max_cap:
    return TradeResult(
        success=True,
        executed=False,
        signal="BUY",
        reason=(
            f"requested spend ({target_spend:.2f}) exceeds "
            f"max_trade_notional ({max_cap:.2f})"
        ),
        balance_before=balance,
    )
```

The 5 USDT `RISK_MAX_TRADE_NOTIONAL_USDT` value is an absolute ceiling. No exchange
filter, rounding step, or retry can push an order above it.

Live exchange filters can be inspected without placing an order:

```
GET /api/safety/binance-exchange-filters?symbols=BTCUSDT,ETHUSDT,SOLUSDT
```

### 3.5 Adaptive AI separation

Phase 2C notional caps are enforced in three places only:

- `src/safety/risk_engine.py` — pre-trade validation gate
- `src/risk/position_sizing.py` — `max_notional_usdt` ceiling on computed quantity
- `src/live/auto_trade_engine.py` — execution sizing and rejection

The Adaptive AI layer continues to compute its own regime-dependent values.
`active_thresholds`, `adaptive_posture`, ML inference, and the `AdaptiveStrategy` /
`FullyAdaptiveStrategy` decision logic are not modified, frozen, or overwritten by the
risk cap. Thresholds are still published unchanged through
`GET /exchange/decisions/recent`, and `GET /api/safety/phase2c/status` restates this
separation in its `adaptive_ai_note` field.

---

## 4. Centralized Execution Architecture

After these changes there is exactly one code path that can place a real Binance order:

```
Scheduler  or  authenticated POST /exchange/auto-trade
        |
        v
AutoTradeEngine.execute_auto_trade()
        |
        +-- Phase 2C gate            (micro-live must be activated)
        +-- Kill switch check
        +-- RiskEngine.validate()    (notional, positions, exposure, loss caps, whitelist)
        +-- Exchange filter check    (MIN_NOTIONAL / LOT_SIZE / stepSize)
        +-- Audit persistence        (orders, positions, decision log)
        |
        v
   Binance Spot order
```

### Authenticated control endpoints

The following require `X-Admin-Token` (matching `ADMIN_TOKEN`) or a valid JWT:

- `POST /safety/phase2c/activate`
- `POST /safety/phase2c/deactivate`
- `POST /safety/kill-switch/engage`
- `POST /safety/kill-switch/release`
- `POST /execution/mode`
- `DELETE /execution/mode/override`
- `POST /exchange/auto-trade` when execution mode is LIVE

`force_signal` is rejected with 403 in LIVE mode, so no manual or forced trade can be
injected during the validation window.

---

## 5. Active Phase 2C Limits

| Limit | Value |
|-------|-------|
| Max trade notional | 5.00 USDT |
| Max open positions | 2 |
| Max total exposure | 6.00 USDT |
| Daily loss cap | 1.50 USDT (blocks at `>=`) |
| Cumulative loss cap | 3.00 USDT (blocks at `>=`) |
| Min order notional | 5.00 USDT |
| Allowed symbols | BTCUSDT, ETHUSDT, SOLUSDT |

---

## 6. Verification Output

### Production container (VPS localhost, behind nginx)

```
live_run=410
limit_buy=410
limit_sell=410
cancel=410
micro_live=False
daily_loss=1.5
mode=shadow
```

### Source verification at commit `3052463`

```
risk_engine.py:329:        if loss >= self.limits.max_daily_loss_usdt:
risk_engine.py:346:        if loss >= float(cap):
routes_live.py:21:def run_live_disabled(body: LiveIn):
routes_live.py:23:        status_code=status.HTTP_410_GONE,
routes_exchange.py:680:def place_limit_buy_disabled(body: LimitBuyBody):
routes_exchange.py:683:        status_code=status.HTTP_410_GONE,
routes_exchange.py:696:        status_code=status.HTTP_410_GONE,
routes_exchange.py:714:        status_code=status.HTTP_410_GONE,
```

### Public API

`GET https://bot.webcrestllc.com/api/safety/phase2c/status`

```json
{
  "ok": true,
  "phase": "2C",
  "micro_live_enabled": false,
  "status_label": "READY FOR ACTIVATION / MICRO-LIVE DISABLED",
  "can_place_live_orders": false,
  "limits": {
    "max_trade_notional_usdt": 5.0,
    "max_open_positions": 2,
    "max_daily_loss_usdt": 1.5,
    "max_total_exposure_usdt": 6.0,
    "max_cumulative_loss_usdt": 3.0,
    "min_order_notional_usdt": 5.0,
    "allowed_symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
  }
}
```

`GET https://bot.webcrestllc.com/api/execution/mode`

```json
{ "ok": true, "effective_mode": "shadow", "is_simulated": true }
```

### Test suite

```
206 passed in 25.15s
```

Relevant coverage:

- `test_live_run_endpoint_disabled` — asserts 410
- `test_legacy_order_endpoints_disabled` — asserts 410 on all three routes
- `test_daily_loss_triggers_at_exact_boundary` — asserts block at exactly 1.50 USDT
- `test_live_buy_rejects_when_spend_below_min_notional` — asserts no order placed
- `test_activate_requires_admin_auth`, `test_kill_switch_mutations_require_auth` — assert 401

---

## 7. Activation Procedure (Client-Controlled)

Micro-Live has not been activated and no real trade has been executed. When you are
ready:

1. Settings — enter mainnet Binance API keys, then Verify (confirm `can_withdraw=false`).
2. Confirm `SECRETS_ENCRYPTION_KEY` is present in the production environment.
   Mainnet activation is rejected with 409 if it is missing.
3. Release the kill switch (authenticated).
4. Set execution mode to Live (authenticated).
5. Activate Micro-Live with a reason (authenticated).
6. Begin the independent 72-hour validation. No forced or manual trades are possible.

### Monitoring endpoints (read-only)

```
GET /api/safety/phase2c/status
GET /api/safety/phase2c/evidence
GET /api/safety/binance-exchange-filters
GET /api/safety/live-readiness
GET /api/safety/kill-switch
GET /api/execution/mode
GET /api/exchange/decisions/recent
```

---

## 8. Change History

| Commit | Description |
|--------|-------------|
| `29bfbac` | Phase 2C controlled micro-live with 5 USDT caps and activation gate |
| `7eff8be` | Admin auth on critical controls, `/live/run` disabled, daily loss `>=`, encryption gate |
| `3052463` | Legacy direct-order endpoints disabled, MIN_NOTIONAL bump removed |
