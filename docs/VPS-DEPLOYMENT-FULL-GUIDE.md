# Trading Bot — VPS deployment & architecture (full guide)

This document describes how the **dashboard**, **API**, and **nginx** work together on the VPS, and summarizes the fixes applied during setup (CORS, ports, two code folders, systemd, frontend API URL).

> **Copy-paste friendly:** You can paste this file into [Google Docs](https://docs.google.com) (File → Open → Upload, or paste sections) and apply headings / table styles there.

---

## 1. High-level architecture

### 1.1 What runs where

| Piece | Role | Typical URL / path on server |
|--------|------|------------------------------|
| **Browser** | User opens the dashboard | `http://147.93.96.42/` (port **80**, HTTP) |
| **Nginx** | Serves static React `dist/` and proxies API | Listens on **80** |
| **FastAPI** (uvicorn/gunicorn) | REST API, DB, Binance, scheduler | **127.0.0.1:8000** (localhost only) |
| **PostgreSQL** | App data | Local or remote per `.env` |

### 1.2 Why we use `/api` on port 80 (not `:8000` in the browser)

- The **dashboard** is served from **`http://147.93.96.42/`** (origin = scheme + host + port **80**).
- If the JavaScript called **`http://147.93.96.42:8000`**, that is a **different origin** (different port) → **CORS** rules apply, and many mobile networks / firewalls block or **time out** on a non-standard port.
- **Solution:** Nginx exposes **`http://147.93.96.42/api/...`** on port **80**. Nginx forwards to **`http://127.0.0.1:8000/...`** and strips the `/api` prefix so `/api/status` becomes FastAPI’s **`/status`**.

So: **browser → only port 80 + path `/api`**. **Backend never needs to be publicly reachable on 8000** for normal dashboard use.

---

## 2. Nginx (dashboard + API proxy)

### 2.1 `server_name` for the IP

For **`http://147.93.96.42`**, there is a `server { ... }` block with:

- `server_name 147.93.96.42;`
- `root` pointing to the Vite build output, e.g.  
  `/var/www/TRADING-BOT-WEBCREST/trading-bot-dashboard/dist`
- **`location ^~ /api/`** with  
  `proxy_pass http://127.0.0.1:8000/;`  
  **Important:** trailing slash on **`8000/`** so `/api/status` maps to backend **`/status`**.

### 2.2 SPA fallback

- **`location /`** uses `try_files` → **`index.html`** for the React app.
- If **`location /api/`** is missing, `/api/...` incorrectly falls through to the SPA and returns **HTML** instead of JSON — that was fixed by adding the **`^~ /api/`** block **above** `location /`.

### 2.3 Repo reference files

- `bot new backend/deploy/nginx/trading-dashboard-http-ip.conf` — full example (static + `/api`).
- `bot new backend/deploy/nginx/trading-dashboard-ip-147.conf` — same idea for IP-only server block.
- `bot new backend/deploy/nginx/merge-api-location.snippet.conf` — only the `/api` block (merge into existing multi-site).

---

## 3. Backend (FastAPI) — single source of truth

### 3.1 Two folders problem (resolved)

| Path | What it was |
|------|-------------|
| ` /var/www/TRADING-BOT/` | Older deploy; **incomplete** vs `main.py` — missing modules like `routes_settings` → crash. |
| **`/var/www/TRADING-BOT-WEBCREST/bot new backend/`** | **Git repo** — full code. |

**Proper approach:** run the API from the **WEBCREST** tree only.

### 3.2 Symlink `trading-backend`

To avoid spaces in systemd paths:

```text
/var/www/trading-backend  →  symlink to  …/TRADING-BOT-WEBCREST/bot new backend
```

Systemd **`WorkingDirectory=/var/www/trading-backend`**, **`EnvironmentFile=/var/www/trading-backend/.env`**.

### 3.3 systemd service (`tradingbot.service`)

- **ExecStart** (one of):
  - **Gunicorn + Uvicorn workers** (production-style):  
    `gunicorn -k uvicorn.workers.UvicornWorker -w 2 -b 127.0.0.1:8000 src.main:app`
  - **Or uvicorn** (simpler):  
    `uvicorn src.main:app --host 127.0.0.1 --port 8000`
- **Bind `127.0.0.1:8000`** so only nginx (and localhost) hit the API; **not** `0.0.0.0:8000` unless you explicitly need public access.

### 3.4 `gunicorn` and `203/EXEC`

- **`pip install -r requirements.txt`** did not install **gunicorn** initially → **`status=203/EXEC`** (executable missing).
- **Fix:** `gunicorn` added to **`requirements.txt`** and `pip install gunicorn` on the server.

### 3.5 CORS (FastAPI)

- **`main.py`** allows **`http://147.93.96.42`** (and optional **`CORS_ORIGINS`** in `.env`).
- With **same-origin `/api`** on port 80, **CORS is less critical** for the main dashboard, but still needed if you open the UI from **localhost:5173** or a different domain.

---

## 4. Frontend (Vite / React)

### 4.1 `VITE_*` is build-time

- **`VITE_API_BASE_URL`** is embedded at **`npm run build`** time.
- Changing `.env` on the server **without** rebuilding **does not** change the JS bundle.

### 4.2 Correct API base for production

- **Use:** `http://147.93.96.42/api` (or relative **`/api`** with same-origin).
- **Do not** embed **`http://147.93.96.42:8000`** in production builds for the public dashboard.

### 4.3 `src/lib/http.ts` behavior

- **Default:** `http://147.93.96.42/api`.
- **`normalizeApiBase`:** if an old build still has **`...:8000`**, it rewrites to **`.../api`** so nginx is used.

### 4.4 Deploy flow after code changes

```bash
cd /var/www/TRADING-BOT-WEBCREST/trading-bot-dashboard
git pull
npm ci   # or npm install
npm run build
# Nginx root must point to the new dist/
```

---

## 5. URLs cheat sheet

| Purpose | URL |
|--------|-----|
| Dashboard | `http://147.93.96.42/` |
| API status | `http://147.93.96.42/api/status` |
| Swagger | `http://147.93.96.42/api/docs` |
| **Direct (SSH only)** | `http://127.0.0.1:8000/status` |

---

## 6. Git / VPS notes

- **`git pull`** failed once because **`trading-bot-dashboard/.env.production`** existed locally as untracked; **rename** (e.g. `.backup`) then pull.
- **GitHub** push needs **PAT** or **SSH** (password auth disabled).

---

## 7. Troubleshooting quick list

| Symptom | Likely cause |
|--------|----------------|
| **CORS** on `:8000` | Browser calls wrong origin; use **`/api`** on port 80. |
| **ERR_CONNECTION_TIMED_OUT** to `:8000` | Firewall / network / nothing listening publicly; use **`/api`**. |
| **502** from nginx | Backend down or not on **127.0.0.1:8000** — `systemctl status tradingbot`, `journalctl -u tradingbot`. |
| **HTML** for `/api/status` | Nginx missing **`location ^~ /api/`** or wrong `server` block. |
| **`ModuleNotFoundError`** | Backend code path **out of sync** — use **WEBCREST** + symlink. |
| **`203/EXEC`** | **gunicorn** not installed in venv. |

---

## 8. Change log (summary)

1. **CORS:** `http://147.93.96.42` added to FastAPI allowed origins in `main.py`.
2. **Nginx:** `/api/` → `127.0.0.1:8000/` with correct **`proxy_pass`** trailing slash; IP-only config files in repo.
3. **Backend deploy:** Single tree via **`/var/www/trading-backend`** symlink; systemd points to it; **gunicorn** in `requirements.txt`.
4. **Frontend:** API base **`http://147.93.96.42/api`**; **`normalizeApiBase`** for legacy `:8000` builds.
5. **Docs / snippets:** `merge-api-location.snippet.conf`, `trading-dashboard-ip-147.conf`, etc.

---

*Last updated for deployment at `http://147.93.96.42/` — adjust host/IP if you change server or domain.*
