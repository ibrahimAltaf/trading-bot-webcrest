# Phase 2A — Operations Runbook

> Companion to `docs/PHASE-2A-SPEC.md`. Everything here is **production
> procedure** — deploy, rollback, alerting setup, drift handling, log rotation.

---

## 1. Alerting (`src/safety/alerts.py`)

### Configuration

All env vars are optional. The alerter is silent unless something is configured.

```
ALERT_WEBHOOK_URL=https://hooks.example.com/trading-bot     # generic JSON POST
ALERT_TELEGRAM_BOT_TOKEN=123456:ABC...                      # Telegram bot
ALERT_TELEGRAM_CHAT_ID=-1001234567890                        # destination chat
ALERT_MIN_LEVEL=WARN                                         # INFO | WARN | ERROR
ALERT_TIMEOUT_SECONDS=3
```

### What triggers an alert

| Event | Level | Category |
|---|---|---|
| Order blocked by `RiskEngine` | `WARN` | `risk_rejected` |
| Kill switch **engaged** | `ERROR` | `kill_switch_engaged` |
| Kill switch released | `WARN` | `kill_switch_released` |

Webhook payload shape (JSON POST body):

```json
{
  "level": "WARN",
  "category": "risk_rejected",
  "message": "BUY BTCUSDT blocked by risk gate",
  "extra": {
    "symbol": "BTCUSDT",
    "side": "BUY",
    "price": 100.0,
    "quantity": 0.5,
    "reason_codes": ["above_max_trade_notional"],
    "reasons": ["notional 50.0000 > max 5.0"],
    "mode": "paper"
  },
  "ts": 1748160000.0
}
```

Alerter is non-blocking (separate daemon thread + bounded queue). If the
webhook is down or the queue is full, alerts are **dropped silently** so the
trading hot-path is never affected.

---

## 2. Deploy procedure (VPS)

Assumes the deployment layout from Phase 1: code at `/var/www/trading-backend`,
service `tradingbot.service`, frontend served by Nginx behind `/api/`.

### 2.1 Pre-flight (60 seconds)

```bash
# 1. Confirm we are SAFE before touching anything live.
curl -sS "http://127.0.0.1:8000/safety/live-readiness" | jq .
# expect ready_for_live_capital: false  (unless this is the live-promotion deploy)

# 2. Confirm tests pass locally on the laptop / CI runner.
cd "bot new backend" && pytest -q src/tests
```

### 2.2 Engage safety brake

```bash
# Engage kill switch so any in-flight scheduler tick is refused.
curl -sS -X POST "http://127.0.0.1:8000/safety/kill-switch/engage" \
  -H "Content-Type: application/json" \
  -d '{"reason":"deploy lock","by":"deploy-script"}'

# Confirm:
curl -sS "http://127.0.0.1:8000/safety/kill-switch" | jq .kill_switch.engaged
# expect: true
```

### 2.3 Rsync new code

```bash
rsync -avz --delete \
  --exclude '.git' --exclude 'venv' --exclude 'data/' --exclude '.env' \
  ./ root@VPS:/var/www/trading-backend/
```

### 2.4 Restart service

```bash
ssh root@VPS '
  set -e
  cd /var/www/trading-backend
  source venv/bin/activate
  pip install -q -r requirements.txt
  systemctl restart tradingbot.service
  sleep 5
  systemctl status tradingbot.service --no-pager | head -20
'
```

### 2.5 Smoke check

```bash
# Service healthy?
curl -sS "https://YOUR_DOMAIN/api/status" | jq .ok
# expect: true

# Phase 2A surface reachable?
curl -sS "https://YOUR_DOMAIN/api/safety/status" | jq '{mode: .execution_mode.effective_mode, engaged: .kill_switch.engaged}'

# DB ↔ memory drift after restart?
curl -sS "https://YOUR_DOMAIN/api/safety/reconcile" | jq .drift
# expect: []   (recovery hydrated trackers from DB)
```

### 2.6 Release the brake

```bash
curl -sS -X POST "http://127.0.0.1:8000/safety/kill-switch/release" \
  -H "Content-Type: application/json" \
  -d '{"reason":"deploy done","by":"deploy-script"}'
```

### 2.7 First-trade observation

After release, watch the next 2 cycle outcomes:

```bash
curl -sS "http://127.0.0.1:8000/exchange/decisions/recent?limit=5" | jq '.[].action'
journalctl -u tradingbot.service -f | grep -E "trade|risk|kill"
```

---

## 3. Rollback (under 2 minutes)

If the new deploy misbehaves (rejection storm, repeated 500s, exception loop):

```bash
# 1. STOP everything immediately.
curl -sS -X POST "http://127.0.0.1:8000/safety/kill-switch/engage" \
  -H "Content-Type: application/json" \
  -d '{"reason":"rollback","by":"oncall"}'

# 2. Disable the scheduler so even paper cycles stop.
curl -sS -X POST "http://127.0.0.1:8000/admin/settings/LIVE_SCHEDULER_ENABLED" \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"value":"false"}'

# 3. Revert source on VPS.
ssh root@VPS '
  cd /var/www/trading-backend
  git fetch --all
  git reset --hard $PREVIOUS_COMMIT_SHA      # the last known-good SHA from main
  systemctl restart tradingbot.service
'

# 4. Re-run readiness gate and only release kill switch when green.
curl -sS "http://127.0.0.1:8000/safety/live-readiness" | jq .ready_for_live_capital
```

The persistent state files (`<data_dir>/safety/kill_switch.json`,
`execution_mode.json`, `runtime_keys.json`) **survive rollbacks** so the
kill-switch remains engaged across the restart.

---

## 4. Drift triage

When `/safety/reconcile` or `/safety/exchange-reconcile` reports drift:

| Drift kind | Likely cause | Action |
|---|---|---|
| `paper_tracker_empty_but_db_has_orders` | Process restarted before recovery ran | Restart service; recovery rehydrates trackers |
| `paper_open_positions_not_in_memory` | Same as above | Same as above |
| `only_in_db` (open orders) | Order cancelled exchange-side; DB still NEW | Manual SQL update: `UPDATE orders SET status='CANCELED' WHERE exchange_order_id=...` |
| `only_on_exchange` (open orders) | Order placed outside the bot | Investigate Binance UI access; never trade alongside the bot |
| `positions.drift` | Balance ≠ DB position qty (>1%) | Engage kill switch; reconcile by hand; check fee / partial-fill |

---

## 5. Log rotation

Backend logs are written by `systemd journald`. Rotation is handled by
`/etc/systemd/journald.conf` — defaults are fine for Phase 2A. If the disk
fills up, tighten the cap:

```
sudo sed -i 's/^#\?SystemMaxUse=.*/SystemMaxUse=2G/' /etc/systemd/journald.conf
sudo systemctl restart systemd-journald
```

Application-level files under `<data_dir>/safety/` are small (≤ 50 history
events each) and do not need rotation.

---

## 6. First-time promotion to micro-live (Phase 2A → 2B)

Gate checklist:

1. `/safety/live-readiness` returns `ready_for_live_capital: true` after
   manually clearing all blockers.
2. Shadow mode has run **continuously for ≥ 7 days** without unhandled
   exceptions (`journalctl -u tradingbot.service | grep -c ERROR` ≤ 0).
3. `/safety/reconcile` and `/safety/exchange-reconcile?mode=shadow` both
   report `drift_count: 0` under steady state.
4. Alerter tested with an artificial rejection — webhook + Telegram messages
   verified end-to-end.
5. Risk caps tightened for micro-live:

```
RISK_MAX_TRADE_NOTIONAL_USDT=10
RISK_MAX_OPEN_POSITIONS=1
RISK_MAX_DAILY_LOSS_USDT=5
RISK_MAX_DAILY_ORDERS=5
RISK_MAX_EXPOSURE_PCT=0.05
```

6. Switch mode **after** restart so the new caps load:

```bash
curl -sS -X POST "http://127.0.0.1:8000/execution/mode" \
  -H "Content-Type: application/json" \
  -d '{"mode":"live","reason":"phase2a micro-live opener","by":"ops"}'
```

7. Watch the first 3 live cycles closely (`journalctl -fu tradingbot.service`).
   Engage the kill switch at the first sign of trouble — no questions asked.
