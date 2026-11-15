"""Manual triggers for the background jobs (for admins, demos and troubleshooting)."""
from dataclasses import asdict
from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.timeutil import utcnow
from app.db.session import get_db
from app.models import User
from app.schemas.complaint import JobRunResult
from app.services.assignment import sweep_unassigned
from app.services.escalation import run_sla_check
from app.services.notification_service import dispatch_pending

router = APIRouter(prefix="/admin/jobs", tags=["admin-jobs"])


@router.post("/sla-check", response_model=JobRunResult)
def sla_check(hours_ahead: float = Query(0, ge=0, le=24 * 30, description="Pretend this many hours have passed"),
              _: User = Depends(require_admin), db: Session = Depends(get_db)):
    return JobRunResult(result=asdict(run_sla_check(db, utcnow() + timedelta(hours=hours_ahead))))


@router.post("/dispatch", response_model=JobRunResult)
def dispatch(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return JobRunResult(result=asdict(dispatch_pending(db)))


@router.post("/auto-assign", response_model=JobRunResult)
def auto_assign_sweep(minutes_ahead: float = Query(0, ge=0, le=60 * 24 * 7, description="Pretend this many minutes have passed"),
                      grace_minutes: float = Query(10, ge=0, le=60 * 24),
                      _: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Assign open jobs that nobody took within the grace period."""
    return JobRunResult(result=sweep_unassigned(db, utcnow() + timedelta(minutes=minutes_ahead), grace_minutes))
