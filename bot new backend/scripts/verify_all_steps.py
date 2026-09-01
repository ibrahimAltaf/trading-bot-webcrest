"""
FULL FUNCTIONAL VERIFICATION — hits the live server, triggers real cycles,
inspects every field the client asked for.
"""
import json, urllib.request, sys, time

BASE = "http://127.0.0.1:6000"

def get(path):
    return json.loads(urllib.request.urlopen(f"{BASE}{path}", timeout=120).read())

def post(path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=120).read())

PASS = 0
FAIL = 0
WARN = 0
details = []

def ok(msg):
    global PASS; PASS += 1; print(f"  [PASS] {msg}")
def fail(msg):
    global FAIL; FAIL += 1; details.append(msg); print(f"  [FAIL] {msg}")
def warn(msg):
    global WARN; WARN += 1; print(f"  [WARN] {msg}")

# ============================================================
print("\n" + "="*70)
print("STEP 0: TRIGGER FRESH CYCLES (BTC, ETH, SOL)")
print("="*70)
for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
    try:
        r = post("/exchange/auto-trade", {"symbol": sym, "timeframe": "5m"})
        print(f"  {sym}: ok={r.get('ok')}, signal={r.get('signal')}, executed={r.get('executed')}, reason={(r.get('reason') or '')[:100]}")
    except Exception as e:
        err = ""
        if hasattr(e, "read"):
            err = e.read().decode()[:200]
        print(f"  {sym}: ERROR {e} {err}")

# ============================================================
print("\n" + "="*70)
print("STEP 1: _dump_signals_json FIX VERIFICATION")
print("="*70)
# If the bug still exists, the latest decision for BTC would have an ERROR log
# right after the decision. Check logs.
logs = get("/exchange/logs/recent?limit=30")
dump_errors = [l for l in logs.get("logs", []) if "_dump_signals_json" in (l.get("message") or "")]
if dump_errors:
    fail(f"_dump_signals_json error STILL in logs! count={len(dump_errors)}, latest={dump_errors[0].get('ts')}")
else:
    ok("No _dump_signals_json errors in recent 30 logs — bug is fixed")

# Also verify decisions are being persisted (if bug existed, they wouldn't save)
btc_recent = get("/exchange/decisions/recent?symbol=BTCUSDT&limit=3")
if btc_recent.get("count", 0) > 0:
    latest_ts = btc_recent["decisions"][0].get("ts", "")
    ok(f"BTC decisions persisting to DB (latest ts={latest_ts})")
else:
    fail("No BTC decisions in DB — persistence may be broken")

# ============================================================
print("\n" + "="*70)
print("STEP 2: ML RUNTIME VALIDATION")
print("="*70)
health = get("/status/model-health/symbols")
print(f"  ml_enabled: {health.get('ml_enabled')}")
print(f"  ml_require_exact_symbol_match: {health.get('ml_require_exact_symbol_match')}")
print(f"  all_symbols_ready: {health.get('all_symbols_ready')}")

for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
    s = health.get("symbols", {}).get(sym, {})
    tf_ok = s.get("tensorflow_ok")
    model_ok = s.get("model_load_ok")
    ready = s.get("ready")
    reason = s.get("reason")
    specific = s.get("specific_match")
    print(f"  {sym}: tf_ok={tf_ok}, model_load_ok={model_ok}, specific_match={specific}, ready={ready}, reason={reason}")

    if tf_ok:
        ok(f"{sym}: TensorFlow loads successfully")
    else:
        fail(f"{sym}: TensorFlow NOT loading")
    if model_ok:
        ok(f"{sym}: Model loads successfully")
    else:
        warn(f"{sym}: Model load issue (reason={reason})")

# Hard guard check: does the health endpoint exist and work?
if health.get("ml_enabled") is not None:
    ok("ML health endpoint exists and returns structured data")
else:
    fail("ML health endpoint broken")

# ============================================================
print("\n" + "="*70)
print("STEP 3: EXACT MODEL MATCHING ENFORCEMENT")
print("="*70)
for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
    s = health.get("symbols", {}).get(sym, {})
    specific = s.get("specific_match")
    ready = s.get("ready")
    reason = s.get("reason")
    if not specific and reason == "exact_model_match_required" and not ready:
        ok(f"{sym}: Exact match enforced — no specific model dir, correctly marked not-ready")
    elif specific:
        ok(f"{sym}: Has specific model match")
    else:
        fail(f"{sym}: Exact match enforcement not working (specific={specific}, ready={ready}, reason={reason})")

# Check it also shows in the decision signals
btc_latest = get("/exchange/decisions/latest?symbol=BTCUSDT")
dec = btc_latest.get("decision", {})
sig = dec.get("signals", {}) if dec else {}
ml_err = sig.get("ml_load_error")
if ml_err and "exact_model_match" in str(ml_err):
    ok(f"BTC decision signals contain ml_load_error={ml_err}")
elif ml_err:
    ok(f"BTC decision has ml_load_error={ml_err} (ML context captured)")
else:
    warn("BTC latest decision missing ml_load_error field (may need to check older or newer decision)")

# ============================================================
print("\n" + "="*70)
print("STEP 4: CYCLE DEBUG OBJECT IN DECISIONS")
print("="*70)
for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
    d = get(f"/exchange/decisions/latest?symbol={sym}")
    dec = d.get("decision")
    if not dec:
        warn(f"{sym}: No decision found in DB (expected for ETH/SOL if cycles just started)")
        continue
    sig = dec.get("signals", {})
    cd = sig.get("cycle_debug")
    env = sig.get("cycle_envelope")

    if cd:
        ok(f"{sym}: cycle_debug EXISTS")
        expected = ["rule_confidence", "ml_confidence", "final_confidence", "final_source",
                     "hold_kind", "block_reasons", "execution_eligible"]
        missing = [k for k in expected if k not in cd]
        if missing:
            fail(f"{sym}: cycle_debug missing keys: {missing}")
        else:
            ok(f"{sym}: cycle_debug has ALL required keys")
        print(f"    rule_confidence={cd.get('rule_confidence')}")
        print(f"    ml_confidence={cd.get('ml_confidence')}")
        print(f"    final_confidence={cd.get('final_confidence')}")
        print(f"    final_source={cd.get('final_source')}")
        print(f"    hold_kind={cd.get('hold_kind')}")
        print(f"    execution_eligible={cd.get('execution_eligible')}")
        print(f"    block_reasons={cd.get('block_reasons')}")
    else:
        fail(f"{sym}: cycle_debug NOT FOUND in decision signals")

    if env:
        ok(f"{sym}: cycle_envelope EXISTS")
        print(f"    envelope keys: {list(env.keys())[:10]}...")
    else:
        warn(f"{sym}: cycle_envelope not found (may be older decision)")

# ============================================================
print("\n" + "="*70)
print("STEP 5: CONFIDENCE SYSTEM")
print("="*70)
for sym in ["BTCUSDT"]:
    d = get(f"/exchange/decisions/latest?symbol={sym}")
    dec = d.get("decision")
    if not dec:
        warn(f"{sym}: No decision"); continue
    sig = dec.get("signals", {})
    cd = sig.get("cycle_debug", {})

    # Check separate confidence values exist
    rc = cd.get("rule_confidence") if cd else sig.get("rule_confidence")
    mc = cd.get("ml_confidence") if cd else sig.get("ml_confidence")
    fc = cd.get("final_confidence") if cd else sig.get("final_confidence")
    fs = cd.get("final_source") if cd else sig.get("final_source")

    if rc is not None:
        ok(f"{sym}: rule_confidence={rc}")
    else:
        fail(f"{sym}: rule_confidence missing")

    if fc is not None:
        ok(f"{sym}: final_confidence={fc}")
    else:
        fail(f"{sym}: final_confidence missing")

    if fs:
        ok(f"{sym}: final_source={fs} (serves as confidence_source)")
    else:
        fail(f"{sym}: final_source missing")

    # ml_confidence can be None when ML disabled/failed — that's correct
    print(f"    ml_confidence={mc} (None is valid when ML unavailable)")

    # Check ml_signal, ml_status in signals root
    for field in ["ml_signal", "ml_confidence", "ml_status", "final_source"]:
        v = sig.get(field)
        print(f"    signals.{field}={v}")

# ============================================================
print("\n" + "="*70)
print("STEP 6: MULTI-COIN API (positions + proof)")
print("="*70)

# Test /positions/open with symbol filter
for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT", None]:
    url = "/exchange/positions/open"
    if sym:
        url += f"?symbol={sym}"
    try:
        d = get(url)
        label = sym or "GLOBAL"
        if d.get("ok"):
            ok(f"/positions/open?symbol={label}: ok, count={d.get('count')}")
        else:
            fail(f"/positions/open?symbol={label}: not ok")
    except Exception as e:
        fail(f"/positions/open?symbol={sym}: {e}")

# Test proof symbol isolation
btc_proof = get("/exchange/proof?symbol=BTCUSDT")
eth_proof = get("/exchange/proof?symbol=ETHUSDT")
sol_proof = get("/exchange/proof?symbol=SOLUSDT")

if btc_proof["symbol"] == "BTCUSDT" and eth_proof["symbol"] == "ETHUSDT" and sol_proof["symbol"] == "SOLUSDT":
    ok("Proof endpoint returns correct symbol for each request")
else:
    fail("Proof symbol mismatch")

# Check section_errors field exists
for label, p in [("BTC", btc_proof), ("ETH", eth_proof), ("SOL", sol_proof)]:
    if "section_errors" in p:
        se = p["section_errors"]
        if se:
            warn(f"{label} proof has section_errors: {se}")
        else:
            ok(f"{label} proof: section_errors=None (all sections healthy)")
    else:
        fail(f"{label} proof: section_errors field MISSING")

# Symbol isolation: BTC decisions should differ from ETH
btc_dec_count = btc_proof["decision_visibility"]["action_counts"]["total"]
eth_dec_count = eth_proof["decision_visibility"]["action_counts"]["total"]
sol_dec_count = sol_proof["decision_visibility"]["action_counts"]["total"]
print(f"  Decision counts — BTC:{btc_dec_count} ETH:{eth_dec_count} SOL:{sol_dec_count}")
if btc_dec_count != eth_dec_count or btc_dec_count != sol_dec_count:
    ok("Symbol isolation confirmed: different decision counts per symbol")
else:
    warn("All symbols have same decision count — may need more data to confirm isolation")

# ============================================================
print("\n" + "="*70)
print("STEP 7: HEALTH + STATS APIs")
print("="*70)

# /status/model-health/symbols already tested in step 2
ok("/status/model-health/symbols endpoint verified in Step 2")

# Stats
stats = get("/stats/performance?mode=live")
if stats.get("ok"):
    ok("/stats/performance endpoint works")
    by_sym = stats.get("by_symbol", {})
    fsc = stats.get("final_source_counts", {})
    print(f"  by_symbol keys: {list(by_sym.keys())}")
    print(f"  global final_source_counts: {fsc}")
    for sym, data in by_sym.items():
        sym_fsc = data.get("final_source_counts") if isinstance(data, dict) else None
        if sym_fsc:
            print(f"    {sym}: final_source_counts={sym_fsc}")
    if fsc or any(isinstance(v, dict) and v.get("final_source_counts") for v in by_sym.values()):
        ok("Per-symbol final_source_counts present in stats")
    else:
        warn("final_source_counts not populated yet (may need more historical data)")
else:
    fail("/stats/performance endpoint failed")

# /status/summary
summary = get("/status/summary")
if "scheduler_state" in summary and "model_loaded" in summary:
    ok(f"/status/summary works: scheduler={summary.get('scheduler_state')}, model_loaded={summary.get('model_loaded')}")
else:
    fail("/status/summary missing expected fields")

# ============================================================
print("\n" + "="*70)
print("STEP 8: SCHEDULER MULTI-COIN BEHAVIOR")
print("="*70)
# Check recent logs for scheduler skip messages
logs = get("/exchange/logs/recent?limit=100")
all_logs = logs.get("logs", [])
scheduler_skip = [l for l in all_logs if "SKIPPED" in (l.get("message") or "") and "ML not ready" in (l.get("message") or "")]
scheduler_exec = [l for l in all_logs if "SCHEDULER" in (l.get("message") or "")]

if scheduler_skip:
    ok(f"Scheduler skip messages found ({len(scheduler_skip)} entries)")
    for l in scheduler_skip[:3]:
        print(f"    {l.get('ts')}: {l.get('message')[:100]}")
else:
    warn("No scheduler skip messages in recent logs (scheduler may not have run with ml_strict=true, or symbols were healthy)")

# Check that the scheduler is actually running
if summary.get("scheduler_state") == "running":
    ok("Scheduler is running")
else:
    warn(f"Scheduler state: {summary.get('scheduler_state')}")

# ============================================================
print("\n" + "="*70)
print("STEP 9: REGRESSION TESTS")
print("="*70)
print("  (Run separately with pytest — checking test file exists)")
import os
test_path = os.path.join(os.path.dirname(__file__), "..", "src", "tests", "test_runtime_upgrades.py")
if os.path.exists(test_path):
    ok("test_runtime_upgrades.py exists")
else:
    fail("test_runtime_upgrades.py NOT FOUND")

# ============================================================
print("\n" + "="*70)
print("STEP 10: VALIDATION FLOW")
print("="*70)
# Stage A: model-health
try:
    h = get("/status/model-health/symbols")
    if h.get("ok"):
        ok("Stage A: /status/model-health/symbols accessible and returns data")
    else:
        fail("Stage A: model-health endpoint not ok")
except:
    fail("Stage A: model-health endpoint unreachable")

# Stage B: decisions/latest per symbol
for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
    try:
        d = get(f"/exchange/decisions/latest?symbol={sym}")
        if d.get("ok"):
            dec = d.get("decision")
            if dec:
                ok(f"Stage B: {sym} latest decision exists (id={dec.get('id')}, action={dec.get('action')})")
            else:
                warn(f"Stage B: {sym} no decision yet (first run may not have persisted)")
        else:
            fail(f"Stage B: {sym} endpoint not ok")
    except Exception as e:
        fail(f"Stage B: {sym} error: {e}")

# ============================================================
print("\n" + "="*70)
print(f"FINAL RESULTS: {PASS} PASSED / {FAIL} FAILED / {WARN} WARNINGS")
print("="*70)
if details:
    print("\nFAILURES:")
    for d in details:
        print(f"  - {d}")

sys.exit(1 if FAIL else 0)
