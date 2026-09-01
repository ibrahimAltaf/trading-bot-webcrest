"""
/settings  –  runtime configuration that the frontend can toggle.
Backed by the `app_settings` table so changes survive restarts.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.db.session import SessionLocal
from src.db.models import AppSetting
from src.scheduler.runner import start_scheduler, stop_scheduler

router = APIRouter(prefix="/settings", tags=["Settings"])


# ── Dependency ────────────────────────────────────────────────
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Schemas ───────────────────────────────────────────────────
class SchedulerToggleBody(BaseModel):
    enabled: bool


class SchedulerToggleResponse(BaseModel):
    enabled: bool
    message: str


# ── Helpers ───────────────────────────────────────────────────
SCHEDULER_KEY = "LIVE_SCHEDULER_ENABLED"


def get_scheduler_enabled(db: Session) -> bool:
    """Read the scheduler flag from the DB."""
    row = db.query(AppSetting).filter_by(key=SCHEDULER_KEY).first()
    if row is None:
        return False
    return row.value.lower() == "true"


# ── Endpoints ─────────────────────────────────────────────────
@router.get("/scheduler", response_model=SchedulerToggleResponse)
def get_scheduler_status(db: Session = Depends(get_db)):
    """Return the current scheduler enabled/disabled state."""
    enabled = get_scheduler_enabled(db)
    return SchedulerToggleResponse(
        enabled=enabled,
        message="scheduler is running" if enabled else "scheduler is stopped",
    )


@router.put("/scheduler", response_model=SchedulerToggleResponse)
def toggle_scheduler(body: SchedulerToggleBody, db: Session = Depends(get_db)):
    """
    Enable or disable the live scheduler at runtime.
    The change is persisted in the DB for next restart too.
    """
    row = db.query(AppSetting).filter_by(key=SCHEDULER_KEY).first()
    if row is None:
        row = AppSetting(key=SCHEDULER_KEY, value=str(body.enabled).lower())
        db.add(row)
    else:
        row.value = str(body.enabled).lower()

    db.commit()

    # Actually start / stop the background scheduler
    if body.enabled:
        start_scheduler()
        msg = "scheduler enabled and started"
    else:
        stop_scheduler()
        msg = "scheduler disabled and stopped"

    return SchedulerToggleResponse(enabled=body.enabled, message=msg)
