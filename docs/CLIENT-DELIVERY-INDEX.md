# Client Delivery Index

**Repo:** https://github.com/ibrahimAltaf/TRADING-BOT-WEBCREST-CLIENT-CON  
**Production:** http://147.93.96.42/ · **API:** http://147.93.96.42/api/docs

---

## Start here (Saad)

| Document | Purpose |
|----------|---------|
| [CLIENT-SAAD-PHASE2A-FINAL-REPORT.md](./CLIENT-SAAD-PHASE2A-FINAL-REPORT.md) | **Final client report (Google Docs ready)** — deploy status, fixes, sign-off |
| [CLIENT-SAAD-ENTRY-DECISION-LOGIC.md](./CLIENT-SAAD-ENTRY-DECISION-LOGIC.md) | **Entry decision logic (post-fix)** — full flow for validation |
| [CLIENT-SAAD-ORDER-ORIGIN-VS-DECISIONS.md](./CLIENT-SAAD-ORDER-ORIGIN-VS-DECISIONS.md) | **Round 2 clarification** — `ai_scheduler_count` vs decision-record counts, with raw DB numbers |
| [CLIENT-SAAD-PHASE2A-EXECUTION-FIX-RESPONSE.md](./CLIENT-SAAD-PHASE2A-EXECUTION-FIX-RESPONSE.md) | Technical fix details |
| [CLIENT-SETUP-AND-ENV-GUIDE.md](./CLIENT-SETUP-AND-ENV-GUIDE.md) | Local `.env`, API audit without prod DB |
| [VPS-DEPLOYMENT-FULL-GUIDE.md](./VPS-DEPLOYMENT-FULL-GUIDE.md) | Deploy backend + dashboard on VPS |

---

## Specs & ops

| Document | Purpose |
|----------|---------|
| [PHASE-2A-SPEC.md](./PHASE-2A-SPEC.md) | Phase 2A requirements |
| [PHASE-2A-OPS.md](./PHASE-2A-OPS.md) | Operations runbook |

---

## Live verification (VPS)

```http
GET /api/safety/shadow-soak-report?days=7
GET /api/safety/shadow-audit?symbol=SOLUSDT
GET /api/exchange/decisions/recent?limit=20
GET /api/execution/mode
GET /api/safety/phase2b-health   # scheduler heartbeat, decision-order integrity, adaptive status, duplicate check
```

**Autonomous proof script:** `bot new backend/scripts/ai_shadow_autonomous_proof.sh`

---

## Phase 2A sign-off

- ≥1 shadow order with `order_origin` ≠ `proof_forced`
- Full chain in `decisions/recent`: rule_signal, ml_signal, final_source, executed=true
- See execution fix doc for deploy + verify commands
