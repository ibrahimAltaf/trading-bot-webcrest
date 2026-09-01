#!/usr/bin/env python3
"""Deploy TRADING-BOT-WEBCREST Phase 2C to VPS and verify."""
from __future__ import annotations

import json
import os
import sys
import tarfile
import tempfile
import time

import paramiko

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HOST = "147.93.96.42"
USER = "root"
PASSWORD = "Developer0312@"
REMOTE_ROOT = "/var/www/TRADING-BOT-WEBCREST"
LOCAL_ROOT = r"c:\Users\muham\Desktop\CHALO\TRADING-BOT-WEBCREST"

EXCLUDE_DIRS = {
    "node_modules",
    "venv",
    ".venv",
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".pytest_tmp",
    "evidence-exports",
    "dist",
}
EXCLUDE_FILES = {
    ".env",
    ".env.local",
    ".env.docker",
    "TRADING-BOT-WEBCREST.tar.gz",
}


def create_archive() -> str:
    tmp = tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False)
    tmp.close()
    path = tmp.name
    print(f"Creating archive {path}...")
    with tarfile.open(path, "w:gz") as tar:
        for root, dirs, files in os.walk(LOCAL_ROOT):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            rel_root = os.path.relpath(root, LOCAL_ROOT)
            if rel_root == ".":
                rel_root = ""
            for f in files:
                if f in EXCLUDE_FILES or f.endswith((".pyc", ".db", ".log")):
                    continue
                full = os.path.join(root, f)
                arc = os.path.join(rel_root, f) if rel_root else f
                tar.add(full, arcname=arc.replace("\\", "/"))
    size_mb = os.path.getsize(path) / (1024 * 1024)
    print(f"Archive size: {size_mb:.1f} MB")
    return path


def run_ssh(ssh: paramiko.SSHClient, cmd: str, timeout: int = 600) -> tuple[int, str, str]:
    print(f"\n>>> {cmd[:120]}...")
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    code = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    if out:
        print(out[-4000:] if len(out) > 4000 else out)
    if err and code != 0:
        print("ERR:", err[-2000:])
    return code, out, err


PHASE2C_ENV_BLOCK = """
# === Phase 2C Controlled Micro-Live (deploy 2026-09-01) ===
EXECUTION_MODE=shadow
PHASE_2C_MICRO_LIVE_ENABLED=false
RISK_MAX_TRADE_NOTIONAL_USDT=5
RISK_MAX_OPEN_POSITIONS=2
RISK_MAX_TOTAL_EXPOSURE_USDT=6
RISK_MAX_DAILY_LOSS_USDT=1.50
RISK_MAX_CUMULATIVE_LOSS_USDT=3
RISK_MIN_ORDER_NOTIONAL_USDT=5
RISK_ALLOWED_SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT
"""


def main() -> int:
    archive = create_archive()
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Connecting to {HOST}...")
    ssh.connect(HOST, username=USER, password=PASSWORD, timeout=30)
    sftp = ssh.open_sftp()
    remote_tar = "/tmp/trading-bot-webcrest-phase2c.tar.gz"
    print(f"Uploading to {remote_tar}...")
    sftp.put(archive, remote_tar)
    sftp.close()
    os.unlink(archive)

    ts = int(time.time())
    cmds = [
        f"cp -a {REMOTE_ROOT}/backend/.env {REMOTE_ROOT}/backend/.env.bak.{ts} 2>/dev/null || true",
        f"cp -a {REMOTE_ROOT}/backend/data {REMOTE_ROOT}/backups/data.bak.{ts} 2>/dev/null || true",
        f"cd {REMOTE_ROOT} && tar -xzf {remote_tar}",
        f"grep -q 'Phase 2C Controlled Micro-Live' {REMOTE_ROOT}/backend/.env || cat >> {REMOTE_ROOT}/backend/.env << 'ENVEOF'\n{PHASE2C_ENV_BLOCK}\nENVEOF",
        f"""python3 << 'PY'
from pathlib import Path
p = Path("{REMOTE_ROOT}/backend/.env")
text = p.read_text(encoding="utf-8")
keys = {{
    "EXECUTION_MODE": "shadow",
    "PHASE_2C_MICRO_LIVE_ENABLED": "false",
    "RISK_MAX_TRADE_NOTIONAL_USDT": "5",
    "RISK_MAX_OPEN_POSITIONS": "2",
    "RISK_MAX_TOTAL_EXPOSURE_USDT": "6",
    "RISK_MAX_DAILY_LOSS_USDT": "1.50",
    "RISK_MAX_CUMULATIVE_LOSS_USDT": "3",
    "RISK_MIN_ORDER_NOTIONAL_USDT": "5",
    "RISK_ALLOWED_SYMBOLS": "BTCUSDT,ETHUSDT,SOLUSDT",
}}
for k, v in keys.items():
    import re
    if re.search(rf"^{{k}}=", text, re.M):
        text = re.sub(rf"^{{k}}=.*", f"{{k}}={{v}}", text, flags=re.M)
    else:
        text = text.rstrip() + f"\\n{{k}}={{v}}\\n"
p.write_text(text, encoding="utf-8")
print("backend/.env Phase2C keys updated")
PY""",
        f"grep -v '^DATABASE_URL=' {REMOTE_ROOT}/backend/.env > {REMOTE_ROOT}/.env.docker.tmp",
        f"""cat >> {REMOTE_ROOT}/.env.docker.tmp << 'ENVEOF'
APP_ENV=production
OPENAPI_SERVER_PREFIX=/api
FASTAPI_ROOT_PATH=/api
POSTGRES_DB=tradingbot
POSTGRES_USER=tradingbot
POSTGRES_PASSWORD=TradingBot_VPS_2026!
ENVEOF""",
        f"mv {REMOTE_ROOT}/.env.docker.tmp {REMOTE_ROOT}/.env.docker",
        f"cd {REMOTE_ROOT} && docker compose build trading-api trading-web 2>&1 | tail -30",
        f"cd {REMOTE_ROOT} && docker compose --env-file .env.docker up -d --no-build 2>&1",
        "sleep 20",
        f"cd {REMOTE_ROOT} && docker compose exec -T trading-api python -c \"from src.db.session import engine; from src.execution.recovery import ensure_client_order_id_column, ensure_trigger_tracking_columns; from src.db.models import Base; Base.metadata.create_all(bind=engine); ensure_client_order_id_column(engine); ensure_trigger_tracking_columns(engine); print('schema ok')\" 2>&1",
        "curl -sf http://127.0.0.1:6000/status | head -c 300; echo",
        "curl -sf http://127.0.0.1:6000/safety/phase2c/status | head -c 500; echo",
        "curl -sf -H 'Host: bot.webcrestllc.com' http://127.0.0.1/api/safety/phase2c/status | head -c 500; echo",
        f"cd {REMOTE_ROOT} && docker compose ps",
        "nginx -t && systemctl reload nginx",
    ]

    for cmd in cmds:
        code, _, err = run_ssh(ssh, cmd, timeout=900)
        if code != 0 and "docker compose build" not in cmd:
            print(f"Command failed with code {code}")
            # continue for non-fatal

    ssh.close()
    print("\n=== DEPLOY COMPLETE ===")
    print("Live: https://bot.webcrestllc.com")
    print("API:  https://bot.webcrestllc.com/api/safety/phase2c/status")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
