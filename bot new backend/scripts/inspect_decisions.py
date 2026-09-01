"""Inspect the latest decision for each symbol — check cycle_debug, envelope, ml fields."""
import json
import urllib.request

BASE = "http://127.0.0.1:6000"

def get(path):
    r = urllib.request.urlopen(f"{BASE}{path}", timeout=60)
    return json.loads(r.read())

for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
    print(f"\n{'='*60}")
    print(f"LATEST DECISION FOR {sym}")
    print(f"{'='*60}")
    d = get(f"/exchange/decisions/latest?symbol={sym}")
    dec = d.get("decision")
    if not dec:
        print("  NO DECISION FOUND")
        continue
    
    print(f"  id: {dec.get('id')}")
    print(f"  action: {dec.get('action')}")
    print(f"  confidence: {dec.get('confidence')}")
    print(f"  regime: {dec.get('regime')}")
    print(f"  executed: {dec.get('executed')}")
    print(f"  ts: {dec.get('ts')}")
    
    signals = dec.get("signals", {})
    print(f"\n  --- ML Audit Fields ---")
    print(f"  final_source: {signals.get('final_source')}")
    print(f"  ml_status: {signals.get('ml_status')}")
    print(f"  ml_signal: {signals.get('ml_signal')}")
    print(f"  ml_confidence: {signals.get('ml_confidence')}")
    print(f"  ml_load_error: {signals.get('ml_load_error')}")
    
    print(f"\n  --- cycle_debug ---")
    cd = signals.get("cycle_debug")
    if cd:
        for k, v in cd.items():
            print(f"  {k}: {v}")
    else:
        print("  NOT PRESENT")
    
    print(f"\n  --- cycle_envelope ---")
    env = signals.get("cycle_envelope")
    if env:
        for k in ["final_action", "final_source", "final_confidence", "rule_signal",
                   "rule_confidence", "ml_signal", "ml_confidence", "ml_enabled",
                   "model_loaded", "execution_eligible", "hold_kind", "ml_error"]:
            print(f"  {k}: {env.get(k)}")
    else:
        print("  NOT PRESENT")
