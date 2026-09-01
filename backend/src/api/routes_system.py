"""System-level health alias for monitoring tools."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

from src.api.routes_health import status_summary

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/health")
def system_health() -> Dict[str, Any]:
    """Same core signals as /status/summary (scheduler, DB, exchange, last decision)."""
    return status_summary()
