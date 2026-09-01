from src.risk.position_sizing import compute_position_size


def test_risk_and_notional_cap():
    out = compute_position_size(
        equity=1000.0,
        entry_price=100.0,
        stop_loss=98.0,
        max_position_pct=0.1,
        risk_per_trade_pct=0.01,
    )
    assert out["ok"] is True
    # risk budget 10 / risk_per_unit 2 = 5 units; notional cap 100/100 = 1 unit
    assert abs(out["qty"] - 1.0) < 1e-9


def test_invalid_stop_rejected():
    out = compute_position_size(
        equity=1000.0,
        entry_price=100.0,
        stop_loss=101.0,
        max_position_pct=0.1,
        risk_per_trade_pct=0.01,
    )
    assert out["ok"] is False
