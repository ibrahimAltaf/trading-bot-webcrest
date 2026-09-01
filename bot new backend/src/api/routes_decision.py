"""Decision observability: latest cycle + recent logs (parsed envelope when present)."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from sqlalchemy import desc

from src.db.models import TradingDecisionLog
from src.db.session import SessionLocal

router = APIRouter(prefix="/decision", tags=["decision"])


def _parse_signals_json(raw: Optional[str]) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {"parse_error": True, "raw_preview": (raw or "")[:200]}


def _confidence_fields(sig: Dict[str, Any]) -> Dict[str, Any]:
    cycle_debug = (
        sig.get("cycle_debug") if isinstance(sig.get("cycle_debug"), dict) else {}
    )
    cycle_envelope = (
        sig.get("cycle_envelope") if isinstance(sig.get("cycle_envelope"), dict) else {}
    )
    return {
        "rule_confidence": sig.get(
            "rule_confidence",
            cycle_debug.get("rule_confidence", cycle_envelope.get("rule_confidence")),
        ),
        "ml_confidence": sig.get(
            "ml_confidence",
            cycle_debug.get("ml_confidence", cycle_envelope.get("ml_confidence")),
        ),
        "final_confidence": sig.get(
            "final_confidence",
            cycle_debug.get("final_confidence", cycle_envelope.get("final_confidence")),
        ),
        "confidence_source": sig.get(
            "confidence_source",
            cycle_debug.get(
                "confidence_source",
                cycle_envelope.get("confidence_source", sig.get("final_source")),
            ),
        ),
    }


@router.get("/latest")
def decision_latest() -> Dict[str, Any]:
    db = SessionLocal()
    try:
        row = db.query(TradingDecisionLog).order_by(desc(TradingDecisionLog.ts)).first()
        if not row:
            return {"ok": False, "error": "no_decisions"}
        sig = _parse_signals_json(getattr(row, "signals_json", None))
        conf = _confidence_fields(sig)
        return {
            "ok": True,
            "ts": row.ts.isoformat() if row.ts else None,
            "symbol": row.symbol,
            "timeframe": row.timeframe,
            "action": row.action,
            "confidence": row.confidence,
            "rule_confidence": conf.get("rule_confidence"),
            "ml_confidence": conf.get("ml_confidence"),
            "final_confidence": conf.get("final_confidence"),
            "confidence_source": conf.get("confidence_source"),
            "reason": row.reason,
            "executed": bool(row.executed),
            "cycle_envelope": sig.get("cycle_envelope"),
            "cycle_debug": sig.get("cycle_debug"),
        }
    finally:
        db.close()


@router.get("/logs")
def decision_logs(limit: int = 50) -> Dict[str, Any]:
    """Recent decision rows (newest first) with envelope + cycle_debug when present."""
    lim = max(1, min(200, int(limit)))
    db = SessionLocal()
    try:
        rows = (
            db.query(TradingDecisionLog)
            .order_by(desc(TradingDecisionLog.ts))
            .limit(lim)
            .all()
        )
        out: List[Dict[str, Any]] = []
        for row in rows:
            sig = _parse_signals_json(getattr(row, "signals_json", None))
            conf = _confidence_fields(sig)
            out.append(
                {
                    "ts": row.ts.isoformat() if row.ts else None,
                    "symbol": row.symbol,
                    "timeframe": row.timeframe,
                    "action": row.action,
                    "confidence": row.confidence,
                    "rule_confidence": conf.get("rule_confidence"),
                    "ml_confidence": conf.get("ml_confidence"),
                    "final_confidence": conf.get("final_confidence"),
                    "confidence_source": conf.get("confidence_source"),
                    "reason": (row.reason or "")[:2000],
                    "executed": bool(row.executed),
                    "cycle_envelope": sig.get("cycle_envelope"),
                    "cycle_debug": sig.get("cycle_debug"),
                }
            )
        return {"ok": True, "count": len(out), "items": out}
    finally:
        db.close()
