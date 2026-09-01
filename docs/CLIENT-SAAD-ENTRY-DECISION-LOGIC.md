# TRADING BOT — Updated Entry Decision Logic (Post-Fix)

**Prepared for:** Saad Salim  
**Prepared by:** Webcrest Team  
**Date:** 3 July 2026  
**Applies to:** Production VPS (`4ba38b9`+) — Shadow Mode validation  
**Purpose:** Explain the complete decision flow from market data to shadow order creation after the Phase 2A execution-logic fixes.

---

## 1. Executive Summary

After the recent fixes, the system uses a **two-stage pipeline**:

1. **Decision stage** — Rule Engine + ML model are fused into a final action (BUY / SELL / HOLD / BLOCKED).
2. **Execution stage** — Additional guards (confidence, market filters, risk engine, position rules) may block an otherwise valid signal.

A **shadow order is created only when** the final action is BUY or SELL, all execution guards pass, and position rules allow it (e.g. BUY requires no open position).

The system **does adapt to market conditions** at the rule layer (trending vs ranging regime). ML thresholds and risk limits are **static configuration values** (`.env`), not self-tuning in production today.

---

## 2. Complete Decision Flow (Ordered)

```
Market Data (Binance OHLCV klines)
        ↓
Indicator Calculation (EMA, RSI, ADX, ATR, Bollinger Bands, volume ratios for ML)
        ↓
Regime Detection (TRENDING vs RANGING via ADX)
        ↓
Rule Engine → rule_signal + rule_confidence + reason
        ↓
ML Model Load Check (exact symbol+timeframe model required when ML_STRICT=true)
        ↓
ML Inference → ml_signal + ml_confidence (BUY / SELL / HOLD softmax)
        ↓
Decision Fusion (_combine_signals) → final_source + final action
        ↓
Entry Gate Evaluation (diagnostic; blocks only if STRICT_ENTRY_GATES=true)
        ↓
Position Rule Check (BUY if flat / SELL if open position exists)
        ↓
ML Execution Confidence Gate (BUY only, ML-driven sources)
        ↓
Optional Market Filters (ADX min, ATR% min — if configured)
        ↓
Portfolio Weight Cap (skipped in shadow/paper mode; active only if RL hybrid enabled)
        ↓
Position Sizing (risk % × balance, stop-loss distance, min notional)
        ↓
Risk Engine (kill switch, limits, cooldown, duplicate, exposure)
        ↓
Shadow Order Creation (simulated fill, mode='shadow', persisted to DB)
        ↓
Decision Log (executed=true, order_id, full audit chain)
```

Every cycle writes to **`GET /api/exchange/decisions/recent`** even when `executed=false`.

---

## 3. Market Conditions Evaluated

### 3.1 Data Input

| Input | Source | Default lookback |
|-------|--------|------------------|
| OHLCV candles | Binance Spot (testnet in production) | 500 bars (`TRADE_LOOKBACK`) |
| Symbol | Scheduler / API (BTCUSDT, ETHUSDT, SOLUSDT) | — |
| Timeframe | Per cycle (e.g. 5m, 1h) | Must match ML model folder |

### 3.2 Indicators Calculated

| Category | Indicators | Used by |
|----------|-----------|---------|
| **Trend** | EMA fast (20), EMA slow (50), ADX, +DI / −DI | Rule Engine |
| **Momentum** | RSI (14) | Rule Engine |
| **Volatility** | ATR, ATR% | Rule Engine + optional execution filter |
| **Mean reversion** | Bollinger Bands (20, 2σ) | Rule Engine (ranging regime) |
| **Volume** | vol_sma_20, vol_ratio | ML model features (not direct rule entry) |

### 3.3 Regime Detection (Adaptive)

| Regime | Condition | Rule set used |
|--------|-----------|---------------|
| **TRENDING** | ADX ≥ 25 (default) | EMA crossover + RSI bands |
| **RANGING** | ADX < 25 | Bollinger Band mean-reversion + RSI |
| **UNKNOWN** | Insufficient ADX data | HOLD |

This is **dynamic per cycle** — the same symbol can switch regimes as ADX changes.

---

## 4. Rule Engine — How It Contributes

The Rule Engine runs **before** ML fusion and produces:

- `rule_signal`: BUY | SELL | HOLD  
- `rule_confidence`: typically 0.65–0.80  
- `reason`: human-readable evidence string  
- Indicator snapshot: ADX, RSI, EMA fast/slow, ATR%, BB levels  

### 4.1 TRENDING Regime Rules

| Signal | Conditions (simplified) |
|--------|-------------------------|
| **BUY** | EMA20 > EMA50 AND RSI in [45, 70] (defaults) |
| **BUY** (alt) | Fresh bullish EMA crossover + RSI pullback below min |
| **SELL** | RSI > 75 (take-profit / overbought) |
| **SELL** | EMA20 < EMA50 with bearish crossover |
| **HOLD** | Otherwise (e.g. bearish trend, no position to sell) |

### 4.2 RANGING Regime Rules

| Signal | Conditions (simplified) |
|--------|-------------------------|
| **BUY** | Price near lower Bollinger Band + RSI < 35 |
| **SELL** | Price near upper Bollinger Band + RSI > 65 |
| **HOLD** | Price mid-range |

### 4.3 Rule Engine Output

The rule output is **never silently discarded**. It is always logged as `rule_signal` in the decision audit, even when ML changes the final action.

---

## 5. ML Model — How It Contributes

### 5.1 Model Selection

- Requires **exact symbol + timeframe** match (e.g. `models/BTCUSDT_5m/model.keras`).
- If no model exists and `ML_STRICT=true` → cycle returns **BLOCKED** (`ml_runtime_failure`), not HOLD.
- Inference uses the last ~50 bars with production feature columns.

### 5.2 ML Output

| Field | Description |
|-------|-------------|
| `ml_signal` | BUY, SELL, or HOLD (3-class softmax) |
| `ml_confidence` | Probability of predicted class (0.0–1.0) |
| `ml_prediction` | Full breakdown: up / hold / down probabilities |

ML runs **every cycle** when a model is available. It does not directly place orders — fusion + execution gates decide.

---

## 6. Decision Fusion (Post-Fix Logic)

Fusion happens in `_combine_signals()` in priority order below. The result is stored as `final_source`.

### 6.1 Priority Order (First Match Wins)

| Priority | Condition | Final source | Winner |
|----------|-----------|--------------|--------|
| 1 | ML confidence ≥ **0.70** (`ML_PRIORITIZE_THRESHOLD`) | `ml_prioritize` | **ML** |
| 2 | ML confidence ≥ **0.60** (`ML_OVERRIDE_THRESHOLD`) | `ml_override` | **ML** |
| 3 | Rule and ML **agree** on BUY or SELL | `combined` | **Both** (blended confidence) |
| 4 | Rule and ML **agree** on HOLD (ML conf ≥ 0.70) | `combined` | HOLD |
| 5 | Rule BUY/SELL **opposes** ML BUY/SELL, ML conf 0.50–0.60 | `ml_moderate_influence` | **ML** (blended) |
| 6 | Rule **HOLD**, ML directional (BUY/SELL), ML conf ≥ **0.52** | `ml_hold_breakout` | **ML** |
| 7 | Rule **BUY/SELL**, ML **HOLD**, rule conf ≥ **0.55** | `rule_directional_ml_neutral` | **Rule** *(NEW FIX)* |
| 8 | Rule BUY **opposes** ML SELL (or vice versa), ML_STRICT=true | `ml_rule_conflict_hold` | **HOLD** |
| 9 | All other conflicts | `rule_only` | **Rule** |

### 6.2 When They Agree

| Agreement | Result |
|-----------|--------|
| Both BUY | Final = BUY, source = `combined`, confidence = average |
| Both SELL | Final = SELL, source = `combined` |
| Both HOLD | Final = HOLD, source = `combined` |

### 6.3 When They Disagree (Post-Fix Behaviour)

| Rule | ML | Result (after fix) |
|------|-----|-------------------|
| BUY | HOLD | **BUY** if rule confidence ≥ 0.55 (`rule_directional_ml_neutral`) |
| HOLD | BUY | **BUY** if ML confidence ≥ 0.52 (`ml_hold_breakout`) |
| BUY | SELL | **HOLD** if ML_STRICT=true (`ml_rule_conflict_hold`) |
| BUY | SELL | ML may win if ML conf ≥ 0.60 (`ml_override`) or 0.50–0.60 (`ml_moderate_influence`) |
| SELL | HOLD | **SELL** if rule confidence ≥ 0.55 (symmetric to BUY case) |

### 6.4 When Can Rule Override ML?

- ML confidence **below 0.60** and not in special breakout/neutral paths → **Rule wins** (`rule_only`).
- Rule directional + ML neutral path → **Rule wins** explicitly.
- ML says HOLD, rule says BUY with high confidence → **Rule wins** (fix #7 above).

### 6.5 When Can ML Override Rule?

- ML confidence ≥ **0.60** → ML direction always wins (`ml_override`).
- ML confidence ≥ **0.70** → ML wins with highest priority (`ml_prioritize`).
- Rule HOLD + ML directional ≥ 0.52 → ML wins (`ml_hold_breakout`).
- Rule/ML oppose + ML conf 0.50–0.60 → ML wins (`ml_moderate_influence`).

---

## 7. Exact Conditions to Create a Shadow Order

All of the following must be true:

| # | Requirement |
|---|-------------|
| 1 | Kill switch **released** |
| 2 | Execution mode = **shadow** |
| 3 | ML runtime eligible (model exists for symbol+TF) OR cycle not ML_STRICT-blocked |
| 4 | Final fused action = **BUY** (no open position) or **SELL** (open position exists) |
| 5 | ML execution confidence gate passed (for ML-driven BUY sources) |
| 6 | Optional ADX/ATR filters passed (only if env > 0) |
| 7 | Portfolio weight cap passed (skipped in shadow mode) |
| 8 | Sufficient USDT balance for min notional (real testnet balance used for sizing) |
| 9 | **Risk Engine approved** (notional, exposure, daily limits, cooldown, duplicate) |
| 10 | Shadow fill simulated and persisted with `order_id` prefix `shadow-` |

**Order origin classification:**

| final_source | order_origin in audit |
|--------------|----------------------|
| `forced_signal` | `proof_forced` |
| `combined`, `ml_*`, `rule_directional_ml_neutral` | `ai_ml` |
| `rule_only` | `ai_rule` |

---

## 8. Execution Guards That Can Block a Valid Signal

Even when fusion produces BUY/SELL, execution may still fail:

### 8.1 Pre-Execution (Decision Layer)

| Guard | When it blocks | Production default |
|-------|----------------|-------------------|
| **ML_STRICT runtime failure** | No model for symbol+TF | Active (`ML_STRICT=true`) |
| **ml_rule_conflict_hold** | Rule BUY vs ML SELL (true opposition) | Active |
| **ML confidence gate** | ML-driven BUY, confidence < 0.50 | Active (VPS: 0.50) |
| **Rule directional gate** | `rule_directional_ml_neutral` but rule conf < 0.55 | Active |
| **STRICT_ENTRY_GATES** | Any entry gate failed | **Off** (`false`) |
| **Open position rule** | BUY while position open, or SELL while flat | Always active |
| **Portfolio weight cap** | RL hybrid + live cap exceeded | **Skipped in shadow** *(fix)* |
| **ADX / ATR filters** | Below configured minimum | Off (min = 0) |

### 8.2 Execution Layer (Risk Engine)

| Check | Default limit |
|-------|---------------|
| Kill switch engaged | Block |
| Min order notional | 5 USDT |
| Max trade notional | 100 USDT |
| Max open positions | 3 |
| Max daily orders | 50 |
| Max daily loss | 50 USDT |
| Max exposure % of balance | 30% |
| Cooldown after loss | 60 seconds |
| Duplicate order window | 10 seconds |
| ML confidence (live only) | 0.55 minimum |

### 8.3 Sizing Layer

| Block reason | Cause |
|--------------|-------|
| Insufficient USDT | Real testnet balance < min notional |
| Position sizing | Risk calculation yields spend ≤ 0 |
| Symbol filters | Binance minNotional / stepSize not met |

---

## 9. Fixed vs Dynamic Thresholds

### 9.1 Fixed (Static — `.env` / Settings)

These do **not** auto-adjust unless you change configuration:

| Parameter | Production default | Purpose |
|-----------|-------------------|---------|
| `ML_PRIORITIZE_THRESHOLD` | 0.70 | ML takes full control |
| `ML_OVERRIDE_THRESHOLD` | 0.60 | ML overrides rule |
| `ML_AGREE_THRESHOLD` | 0.70 | Agree-on-HOLD threshold |
| `ML_MIN_TRADE_CONFIDENCE` | **0.50** (VPS patched) | Min confidence to execute BUY |
| `ML_ABSOLUTE_MIN_CONFIDENCE` | 0.50 | Safety floor |
| `RULE_DIRECTIONAL_MIN_CONFIDENCE` | 0.55 | Rule wins when ML=HOLD |
| `ML_HOLD_BREAKOUT_MIN_CONFIDENCE` | 0.52 | ML wins when rule=HOLD |
| `ADX_THRESHOLD` | 25.0 | Trend vs range |
| `RSI_BUY_MIN` / `RSI_BUY_MAX` | 45 / 70 | Trending entry band |
| `RSI_TAKE_PROFIT` | 75 | Trending exit |
| Risk limits | see §8.2 | Hard caps |

### 9.2 Dynamic (Changes Every Cycle)

| Element | How it adapts |
|---------|---------------|
| **Regime** | ADX-driven TRENDING vs RANGING switches rule set |
| **Rule confidence** | Higher on fresh crossovers (0.70–0.80 vs 0.65) |
| **Fused confidence** | Blended from rule + ML per fusion path |
| **Position size** | Based on live USDT balance + ATR stop distance |
| **ML softmax** | Changes with each candle window |

There is **no online learning** or threshold self-tuning in production today. The `FullyAdaptiveStrategy` engine exists but is off by default (`FULLY_ADAPTIVE_ENGINE=false`).

---

## 10. Expected Behaviour in Post-Fix Validation

When you run the validation test, you should observe:

| Scenario | Expected outcome |
|----------|------------------|
| Rule BUY + ML HOLD (SOL 1h case) | Final **BUY**, source = `rule_directional_ml_neutral` |
| Rule BUY + ML BUY (BTC 5m case) | Final **BUY**, source = `combined` → shadow order if confidence ≥ 0.50 |
| Rule BUY + ML SELL | Final **HOLD**, source = `ml_rule_conflict_hold` |
| Rule HOLD + ML BUY (high conf) | Final **BUY**, source = `ml_hold_breakout` |
| No model for timeframe | **BLOCKED**, not HOLD |
| Valid BUY but low balance | Decision logged, `executed=false`, sizing reason |
| Valid BUY, all gates pass | `executed=true`, `order_id=shadow-...`, origin ≠ `proof_forced` |

**Important:** HOLD-dominant cycles are **expected and intentional** — the strategy avoids over-trading. Validation success = observing at least **one full autonomous chain** when market conditions produce an actionable fused BUY/SELL.

---

## 11. API Fields to Monitor During Validation

```http
GET /api/exchange/decisions/recent?limit=20
GET /api/safety/shadow-soak-report?days=7
GET /api/exchange/ai-observability
GET /api/safety/shadow-audit?symbol=BTCUSDT
```

Key fields per decision:

- `rule_signal`, `ml_signal`, `ml_confidence`
- `final_source`, `combined_signal`
- `executed`, `order_id`
- `override_reason`

---

## 12. Summary Answer to Your Core Question

> *Does the system automatically adapt entry criteria to changing market conditions?*

**Partially:**

- **Yes** at the **rule layer** — regime detection (ADX) switches between trending and ranging logic every cycle.
- **Yes** at the **ML layer** — predictions change with each new candle window.
- **No** at the **threshold layer** — fusion cutoffs, confidence floors, and risk limits are **static config** unless manually changed in `.env`.

The post-fix validation should demonstrate that when rule and ML produce an actionable aligned signal, the system no longer blocks execution at the fusion or portfolio-cap stages, and proceeds through risk validation to create a genuine shadow order.

---

**Webcrest Team**

*Formatted for Google Docs — copy from `docs/CLIENT-SAAD-ENTRY-DECISION-LOGIC.md`*
