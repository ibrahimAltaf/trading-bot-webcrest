# Phase 2C Deploy Guide — Controlled Micro-Live

**Live dashboard:** https://bot.webcrestllc.com  
**API base:** https://bot.webcrestllc.com/api  
**Phase 2C status:** `GET /api/safety/phase2c/status`

## Default state after deploy

- `EXECUTION_MODE=shadow` — no real Binance orders
- `PHASE_2C_MICRO_LIVE_ENABLED=false` — **READY FOR ACTIVATION**
- Risk limits: 5 USDT/trade, 2 positions, 6 USDT exposure, 1.50 daily loss, 3 USDT cumulative

## Client activation (Saad)

1. **Settings → Binance API Keys** — paste mainnet keys, uncheck testnet, Verify
2. Release **Kill Switch**
3. Set **Execution mode → Live**
4. **Phase 2C → Activate Micro-Live** (reason required)
5. Run 72-hour independent validation

## Server paths

| Item | Path |
|------|------|
| Project | `/var/www/TRADING-BOT-WEBCREST` |
| Backend env | `backend/.env` |
| Docker env | `.env.docker` |
| Phase 2C state | `backend/data/safety/phase2c.json` |

## Deploy commands (VPS)

```bash
cd /var/www/TRADING-BOT-WEBCREST
docker compose --env-file .env.docker build trading-api trading-web
docker compose --env-file .env.docker up -d --no-build
docker compose exec trading-api python -c "from src.db.session import engine; from src.db.models import Base; Base.metadata.create_all(bind=engine)"
curl -s http://127.0.0.1:6000/safety/phase2c/status | jq .
```

## Read-only validation endpoints

- `/api/safety/phase2c/status`
- `/api/safety/phase2c/evidence`
- `/api/safety/live-readiness`
- `/api/exchange/proof?mode=shadow`
- `/api/exchange/ai-observability`
- `/api/safety/exchange-reconcile?mode=live`

## Important

- Binance Spot **minimum notional is 5 USDT** (not 3) for BTC/ETH/SOL
- Adaptive AI thresholds are **not** modified by Phase 2C caps
- Never commit `.env` — use `.env.example` as template
