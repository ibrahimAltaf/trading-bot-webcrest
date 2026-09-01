# Phase 2A — AI Execution Logic Fix (Response to Saad)

**Date:** 2 Jul 2026  
**Status:** Code fix implemented + tested locally

---

## Summary

You were correct: infrastructure was validated, but **autonomous AI → shadow order** never completed because of **over-restrictive signal fusion logic**, not because monitoring was insufficient.

We have **reviewed and corrected** the AI decision/execution pipeline.

---

## Root cause (confirmed)

When **Rule Engine = BUY** and **ML = HOLD** (the most common near-miss in production, e.g. SOLUSDT 1h):

| Before fix | After fix |
|---|---|
| `ml_rule_conflict_hold` → final action **HOLD** | `rule_directional_ml_neutral` → final action **BUY** |
| No shadow order | Shadow order created when position rules allow |

Under `ML_STRICT=true`, **any** rule/ML disagreement collapsed to HOLD — including benign cases where ML was neutral (HOLD), not opposing (SELL).

---

## Code changes

1. **`rule_directional_ml_neutral` fusion** — symmetric to existing `ml_hold_breakout`:
   - Rule BUY/SELL + ML HOLD + rule confidence ≥ `RULE_DIRECTIONAL_MIN_CONFIDENCE` (default 0.55) → execute rule direction
2. **`ML_STRICT` conflict refinement** — only **BUY vs SELL** opposition forces `ml_rule_conflict_hold`; rule vs ML-HOLD no longer blocked
3. **Execution gate** — `rule_directional_ml_neutral` uses rule confidence (not ML min-trade threshold, since ML said HOLD)
4. **Audit classification** — `order_origin` = `ai_ml` (not `proof_forced`)

**Files:** `auto_trade_engine.py`, `config.py`, `routes_safety.py`

**New env (optional):**
```env
RULE_DIRECTIONAL_ML_NEUTRAL_ENABLED=true
RULE_DIRECTIONAL_MIN_CONFIDENCE=0.55
```

---

## Test evidence

Automated test proves full chain **without `force_signal`**:

- `test_rule_directional_ml_neutral_executes_buy_when_ml_holds`
- `test_autonomous_shadow_buy_without_force_signal` → shadow order + `final_source=rule_directional_ml_neutral`

---

## Validation run (post-deploy)

On VPS after deploy + restart:

```bash
# 1. Deploy
cd /var/www/TRADING-BOT-WEBCREST && git pull origin main
rsync -av --delete --exclude venv --exclude data --exclude .env \
  "bot new backend/" backend/
systemctl restart tradingbot.service

# 2. Autonomous proof (no force_signal)
backend/scripts/ai_shadow_autonomous_proof.sh

# 3. Verify
curl -sS http://127.0.0.1:8001/api/safety/shadow-soak-report?days=1 | \
  python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('shadow_orders_origin_summary'))"
```

**Pass criteria:**
- `ai_scheduler_count >= 1`
- `proof_forced_count` unchanged or only prior audit trades
- At least one order with `order_origin` ≠ `proof_forced`
- `GET /exchange/decisions/recent` shows `executed=true`, `final_source=rule_directional_ml_neutral` (or `combined` / `ml_hold_breakout`)

---

## Phase 2A sign-off

Once the post-deploy validation run shows **≥1 genuine autonomous shadow order**, Phase 2A is complete and we can proceed to Phase 2B micro-live per your criteria.

Best regards,  
Webcrest Team
