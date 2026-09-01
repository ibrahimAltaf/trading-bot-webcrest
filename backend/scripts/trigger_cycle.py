"""Trigger one auto-trade cycle for each symbol and print the result."""
import json
import urllib.request
import sys

BASE = "http://127.0.0.1:6000"

for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
    data = json.dumps({"symbol": sym, "timeframe": "5m"}).encode()
    req = urllib.request.Request(
        f"{BASE}/exchange/auto-trade",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        r = urllib.request.urlopen(req, timeout=120)
        d = json.loads(r.read())
        ok = d.get("ok")
        signal = d.get("signal")
        executed = d.get("executed")
        reason = (d.get("reason") or "")[:120]
        print(f"{sym}: ok={ok}, signal={signal}, executed={executed}, reason={reason}")
    except Exception as e:
        err_body = ""
        if hasattr(e, "read"):
            err_body = e.read().decode()[:300]
        print(f"{sym}: ERROR {e} {err_body}")
