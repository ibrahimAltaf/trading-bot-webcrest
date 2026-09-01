"""GET /status/ml-runtime shape (uses live settings; no heavy smoke)."""

from fastapi.testclient import TestClient

from src.main import app


def test_ml_runtime_returns_symbols_array():
    client = TestClient(app)
    r = client.get("/status/ml-runtime")
    assert r.status_code == 200
    data = r.json()
    assert "ok" in data
    assert "trade_timeframe" in data
    assert isinstance(data.get("symbols"), list)
    for row in data["symbols"]:
        assert "symbol" in row
        assert "runtime_eligible" in row
        assert "ml_ready" in row
