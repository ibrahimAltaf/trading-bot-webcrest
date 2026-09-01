# Order Origin vs. Decision Records — Clarification for Saad (Phase 2A round 2)

**Context:** After the July 13 deploy (trigger provenance + adaptive thresholds),
Saad's second validation confirmed decision extraction, decision→order
correlation, and adaptive behaviour are all working. One open question
remained: his validator reports **"AI-origin Orders: 1294"** while our
`/safety/shadow-soak-report` reports **`ai_scheduler_count: 0–2`**. This doc
is the full explanation, with the raw numbers pulled directly from the
production database.

---

## The short answer

**"AI-origin Orders" and `ai_scheduler_count` are counting two different things.**

| Metric | What it counts | Source |
|---|---|---|
| `ai_scheduler_count` (`/safety/shadow-soak-report`) | **Orders** — actual placed trades — confirmed to originate from an unattended scheduler cycle | `Order` table, `mode="shadow"` rows only |
| Validator's "AI-origin Orders" (likely) | **Decision records** — every cycle the engine evaluates a symbol (rule + ML pipeline runs, a HOLD/BUY/SELL decision is logged) whether or not it becomes a trade | `TradingDecisionLog` table, all rows |

A decision is logged on **every** scheduler tick for **every** symbol. Only a
small fraction of decisions ever become an `Order` — most cycles end in HOLD,
or a directional signal gets gated (open position exists, portfolio cap,
confidence floor) before it reaches execution.

---

## Raw numbers (pulled from the production DB, 2026-07-16)

| | Count |
|---|---|
| Total decision records logged, all-time | 11,947 |
| Decisions before trigger-tracking existed (untagged, June 15 – July 10) | 8,762 |
| Decisions since the fix went live (July 13, tagged `scheduler`) | 3,173 — `cycle_id` 1 → 748, ticking every ~5 min exactly as configured |
| Of those 3,173: BUY / SELL / HOLD | 587 / 224 / 2,367 |
| **Total Orders ever placed, all modes, all-time** | **53** |
| Of those, shadow-mode orders | 5 |
| Shadow orders by origin | `ai_scheduler`: 2, `proof_forced`: 2, `api_manual_unforced`: 1 |

The engine is genuinely generating 587 autonomous BUY signals since the fix
went live — the scheduler is ticking reliably and unattended (748 cycles over
~60 hours). The large majority of those signals never convert into a placed
order because of deliberate execution gates (open-position rules, portfolio
cap, confidence floor). Only 2 have converted into an actual autonomous
shadow order so far in this early soak window.

---

## Answers to Saad's three questions

1. **Which `order_origin` values should be considered genuine autonomous AI execution?**
   Only `ai_scheduler`. `api_manual_unforced` means the rule/ML pipeline ran
   for real, but the call came from a human/script hitting the endpoint
   directly (no `force_signal`) — not the unattended engine — so it's
   excluded by design. `proof_forced` is an explicit test call
   (`force_signal=BUY|SELL`).

2. **Is the validator interpreting the new order classification correctly?**
   Likely not fully. If "AI-origin Orders: 1294" is counting decision log
   rows (or including the pre-July-13 untagged history, where trigger
   provenance genuinely cannot be recovered), it is measuring *"the AI
   evaluated the market,"* not *"the AI placed a trade."* We'd like to
   confirm whether the 1294 figure comes from the decisions endpoint or the
   orders endpoint, and what time window was used, so the exact number can be
   reconciled rather than just the concept.

3. **Should AI-origin orders always correspond to an increase in `ai_scheduler_count`?**
   No — they represent different concepts by design. A decision can be
   genuinely `ai_scheduler`-triggered and still never become an order (HOLD,
   or gated). `ai_scheduler_count` only increases when the unattended engine
   actually executes a trade — a deliberately higher, stricter bar.

---

## Recommended check going forward

For an apples-to-apples "did autonomous execution happen" check, use:

```http
GET /api/safety/shadow-soak-report?days=7
```
→ look at `shadow_orders_origin_summary` (Orders only).

For "is the AI actively evaluating the market" (much larger, includes every
cycle regardless of execution), use:

```http
GET /api/exchange/decisions/recent?limit=50
```
→ each item now carries `triggered_by`, `cycle_id`, `active_thresholds`, and
`adaptive_posture`.

---

## Message you can send to Saad (copy-paste)

> Hi Saad,
>
> Good question — this is a metric-definition mismatch, not a bug.
> `ai_scheduler_count` counts actual placed **Orders** confirmed to come from
> an unattended scheduler cycle. Your "AI-origin Orders: 1294" is almost
> certainly counting **decision records** — every cycle the engine evaluates
> a symbol, whether or not that decision becomes a trade. Since the July 13
> fix, the scheduler has logged 3,173 genuine unattended decisions (587 BUY,
> 224 SELL, 2,367 HOLD) across 748 cycles — but only 53 orders have ever been
> placed in this project's entire history, 5 of them in shadow mode, 2
> confirmed `ai_scheduler` origin. Full breakdown and answers to your three
> questions: `docs/CLIENT-SAAD-ORDER-ORIGIN-VS-DECISIONS.md` in the repo.
> Could you confirm whether your 1294 figure comes from the decisions
> endpoint or the orders endpoint, and the time window used, so we can
> reconcile the exact number?
>
> Best,
> Ibrahim
