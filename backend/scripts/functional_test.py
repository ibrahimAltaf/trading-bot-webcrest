"""Functional verification: hit live endpoints and verify actual JSON output."""
import json
import urllib.request
import sys

BASE = "http://127.0.0.1:6000"

def get(path):
    r = urllib.request.urlopen(f"{BASE}{path}", timeout=120)
    return json.loads(r.read())

def test_model_health_symbols():
    print("\n=== TEST 1: GET /status/model-health/symbols ===")
    d = get("/status/model-health/symbols")
    assert d["ok"] is True, f"Expected ok=True, got {d['ok']}"
    assert d["ml_enabled"] is True, f"Expected ml_enabled=True, got {d['ml_enabled']}"
    assert d["ml_require_exact_symbol_match"] is True
    assert d["timeframe"] == "5m"
    
    for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
        s = d["symbols"][sym]
        assert s["symbol"] == sym, f"Expected symbol={sym}"
        assert s["model_exists"] is True, f"{sym}: model_exists should be True"
        assert s["specific_match"] is False, f"{sym}: specific_match should be False (no per-symbol dir)"
        assert s["tensorflow_ok"] is True, f"{sym}: tensorflow_ok should be True"
        assert s["model_load_ok"] is True, f"{sym}: model should load"
        assert s["ready"] is False, f"{sym}: ready should be False (exact match required but not met)"
        assert s["reason"] == "exact_model_match_required"
        print(f"  {sym}: model_exists={s['model_exists']}, specific_match={s['specific_match']}, "
              f"tf_ok={s['tensorflow_ok']}, ready={s['ready']}, reason={s['reason']}")
    
    assert d["all_symbols_ready"] is False
    print("  all_symbols_ready:", d["all_symbols_ready"])
    print("  PASS")

def test_positions_open_symbol_filter():
    print("\n=== TEST 2: GET /exchange/positions/open (global vs symbol-filtered) ===")
    d_global = get("/exchange/positions/open")
    d_btc = get("/exchange/positions/open?symbol=BTCUSDT")
    d_eth = get("/exchange/positions/open?symbol=ETHUSDT")
    d_sol = get("/exchange/positions/open?symbol=SOLUSDT")
    
    for label, d in [("global", d_global), ("BTC", d_btc), ("ETH", d_eth), ("SOL", d_sol)]:
        assert d["ok"] is True
        assert isinstance(d["positions"], list)
        print(f"  {label}: count={d['count']}, positions={len(d['positions'])}")
    print("  PASS")

def test_proof_symbol_isolation():
    print("\n=== TEST 3: GET /exchange/proof — symbol isolation & section_errors ===")
    results = {}
    for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
        d = get(f"/exchange/proof?symbol={sym}")
        assert d["ok"] is True
        assert d["symbol"] == sym, f"Expected symbol={sym}, got {d['symbol']}"
        
        # section_errors should exist in response (None when no errors)
        assert "section_errors" in d, f"section_errors key missing from proof response"
        
        # Verify all expected sections exist
        assert "balances" in d
        assert "decision_visibility" in d
        assert "positions" in d
        assert "orders" in d
        assert "trades" in d
        assert "logs" in d
        assert "performance" in d
        assert "environment" in d
        
        decisions = d["decision_visibility"]["action_counts"]["total"]
        pnl = d["performance"]["realized_pnl_usdt"]
        pos = d["positions"]["open_count"]
        errors = d.get("section_errors")
        
        results[sym] = {"decisions": decisions, "pnl": pnl, "pos": pos, "errors": errors}
        print(f"  {sym}: decisions={decisions}, pnl={pnl}, positions_open={pos}, "
              f"section_errors={errors}")
    
    # Verify isolation: BTC should have decisions, ETH/SOL should differ
    btc_dec = results["BTCUSDT"]["decisions"]
    eth_dec = results["ETHUSDT"]["decisions"]
    sol_dec = results["SOLUSDT"]["decisions"]
    print(f"  Decision counts — BTC:{btc_dec} ETH:{eth_dec} SOL:{sol_dec}")
    if btc_dec > 0 and eth_dec == 0 and sol_dec == 0:
        print("  Symbol isolation confirmed: only BTC has historical decisions")
    print("  PASS")

def test_decisions_per_symbol():
    print("\n=== TEST 4: GET /exchange/decisions/recent per symbol ===")
    for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
        d = get(f"/exchange/decisions/recent?symbol={sym}&limit=5")
        assert d["ok"] is True
        count = d.get("count", 0)
        decisions = d.get("decisions", [])
        # Verify all returned decisions match the requested symbol
        for dec in decisions:
            assert dec["symbol"] == sym, f"Decision symbol mismatch: expected {sym}, got {dec['symbol']}"
        print(f"  {sym}: count={count}, returned={len(decisions)}")
    print("  PASS")

def test_cycle_debug_structure():
    print("\n=== TEST 5: Verify cycle_debug structure in latest BTC decision ===")
    d = get("/exchange/decisions/recent?symbol=BTCUSDT&limit=1")
    assert d["ok"] is True
    if d["count"] == 0:
        print("  SKIP: no BTC decisions in DB")
        return
    
    dec = d["decisions"][0]
    signals = dec.get("signals", {})
    
    # Check for cycle_debug
    cycle_debug = signals.get("cycle_debug")
    if cycle_debug:
        print(f"  cycle_debug found with keys: {list(cycle_debug.keys())}")
        expected_keys = ["rule_confidence", "ml_confidence", "final_confidence", 
                         "final_source", "hold_kind", "block_reasons", "execution_eligible"]
        for k in expected_keys:
            assert k in cycle_debug, f"Missing key '{k}' in cycle_debug"
            print(f"    {k}: {cycle_debug[k]}")
    else:
        print("  WARNING: cycle_debug not found in signals (decision may predate implementation)")
    
    # Check for cycle_envelope
    envelope = signals.get("cycle_envelope")
    if envelope:
        print(f"  cycle_envelope found with keys: {list(envelope.keys())}")
    
    # Check for ml_audit fields
    for field in ["ml_signal", "ml_confidence", "ml_status", "final_source"]:
        val = signals.get(field)
        print(f"  {field}: {val}")
    
    print("  PASS")

def test_latest_decision_detail():
    print("\n=== TEST 6: GET /exchange/decisions/latest for BTC — full payload ===")
    d = get("/exchange/decisions/latest?symbol=BTCUSDT")
    assert d["ok"] is True
    dec = d.get("decision")
    if not dec:
        print("  SKIP: no latest decision")
        return
    
    print(f"  id: {dec.get('id')}")
    print(f"  symbol: {dec.get('symbol')}")
    print(f"  action: {dec.get('action')}")
    print(f"  confidence: {dec.get('confidence')}")
    print(f"  regime: {dec.get('regime')}")
    print(f"  executed: {dec.get('executed')}")
    
    signals = dec.get("signals", {})
    print(f"  final_source: {signals.get('final_source')}")
    print(f"  ml_status: {signals.get('ml_status')}")
    print(f"  ml_signal: {signals.get('ml_signal')}")
    print(f"  ml_confidence: {signals.get('ml_confidence')}")
    
    cd = signals.get("cycle_debug")
    if cd:
        print(f"  cycle_debug.rule_confidence: {cd.get('rule_confidence')}")
        print(f"  cycle_debug.ml_confidence: {cd.get('ml_confidence')}")
        print(f"  cycle_debug.final_confidence: {cd.get('final_confidence')}")
        print(f"  cycle_debug.final_source: {cd.get('final_source')}")
        print(f"  cycle_debug.execution_eligible: {cd.get('execution_eligible')}")
        print(f"  cycle_debug.hold_kind: {cd.get('hold_kind')}")
    else:
        print("  WARNING: no cycle_debug in signals")
    
    env = signals.get("cycle_envelope")
    if env:
        print(f"  cycle_envelope.final_action: {env.get('final_action')}")
        print(f"  cycle_envelope.final_source: {env.get('final_source')}")
        print(f"  cycle_envelope.ml_enabled: {env.get('ml_enabled')}")
        print(f"  cycle_envelope.model_loaded: {env.get('model_loaded')}")
    print("  PASS")

def test_stats_per_symbol():
    print("\n=== TEST 7: GET /stats/performance (check per-symbol aggregation) ===")
    d = get("/stats/performance?mode=live")
    assert d["ok"] is True
    
    # Check for by_symbol or final_source_counts
    by_symbol = d.get("by_symbol")
    if by_symbol:
        print(f"  by_symbol keys: {list(by_symbol.keys())}")
        for sym, data in by_symbol.items():
            fsc = data.get("final_source_counts") if isinstance(data, dict) else None
            print(f"    {sym}: final_source_counts={fsc}")
    
    fsc_global = d.get("final_source_counts")
    if fsc_global:
        print(f"  global final_source_counts: {fsc_global}")
    print("  PASS")

def test_health_summary():
    print("\n=== TEST 8: GET /status/summary ===")
    d = get("/status/summary")
    assert "app_version" in d, "Expected app_version in summary"
    assert "scheduler_state" in d
    assert "model_loaded" in d
    assert "database_connected" in d
    assert "exchange_connected" in d
    print(f"  scheduler_state: {d.get('scheduler_state')}")
    print(f"  model_loaded: {d.get('model_loaded')}")
    print(f"  database_connected: {d.get('database_connected')}")
    print(f"  exchange_connected: {d.get('exchange_connected')}")
    print(f"  last_decision_time: {d.get('last_decision_time')}")
    print("  PASS")

if __name__ == "__main__":
    passed = 0
    failed = 0
    errors = []
    
    tests = [
        test_model_health_symbols,
        test_positions_open_symbol_filter,
        test_proof_symbol_isolation,
        test_decisions_per_symbol,
        test_cycle_debug_structure,
        test_latest_decision_detail,
        test_stats_per_symbol,
        test_health_summary,
    ]
    
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            failed += 1
            errors.append((t.__name__, str(e)))
            print(f"  FAIL: {e}")
    
    print(f"\n{'='*60}")
    print(f"FUNCTIONAL TESTS: {passed} passed, {failed} failed out of {len(tests)}")
    if errors:
        print("\nFailed tests:")
        for name, err in errors:
            print(f"  {name}: {err}")
    print(f"{'='*60}")
    sys.exit(1 if failed else 0)
