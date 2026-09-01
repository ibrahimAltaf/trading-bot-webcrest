"""Pre-deploy smoke test for Phase 2C API endpoints."""
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx

BASE = "http://127.0.0.1:6000"
ENDPOINTS = [
    ("GET", "/status"),
    ("GET", "/health/db"),
    ("GET", "/safety/status"),
    ("GET", "/safety/limits"),
    ("GET", "/safety/phase2c/status"),
    ("GET", "/safety/phase2c/evidence"),
    ("GET", "/safety/live-readiness"),
    ("GET", "/execution/mode"),
    ("GET", "/safety/kill-switch"),
    ("GET", "/exchange/decisions/recent?limit=5"),
    ("GET", "/exchange/ai-observability"),
]

def main():
    ok = 0
    fail = 0
    with httpx.Client(base_url=BASE, timeout=30.0) as client:
        for method, path in ENDPOINTS:
            try:
                r = client.request(method, path)
                status = r.status_code
                if status == 200:
                    print(f"OK  {method} {path}")
                    ok += 1
                else:
                    print(f"FAIL {method} {path} -> {status}")
                    fail += 1
            except Exception as exc:
                print(f"ERR {method} {path} -> {exc}")
                fail += 1
    print(f"\nResult: {ok} ok, {fail} failed")
    return 0 if fail == 0 else 1

if __name__ == "__main__":
    raise SystemExit(main())
