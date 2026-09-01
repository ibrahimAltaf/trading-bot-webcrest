import json
import math

from src.core.json_safe import finite_float, sanitize_for_json


def test_finite_float_nan():
    assert finite_float(float("nan"), 0.5) == 0.5
    assert finite_float(float("inf"), 1.0) == 1.0


def test_sanitize_for_json_nan():
    d = {"a": float("nan"), "b": [1.0, float("inf")], "c": {"x": 1}}
    out = sanitize_for_json(d)
    assert out["a"] is None
    assert out["b"] == [1.0, None]
    json.dumps(out, allow_nan=False)


def test_sanitize_roundtrip():
    assert sanitize_for_json({"ok": True}) == {"ok": True}
