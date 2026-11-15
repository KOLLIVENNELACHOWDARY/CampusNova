"""Scheduled-job endpoints for hosts that cannot run a background scheduler (Vercel).

A scheduler (Vercel Cron, GitHub Actions, cron-job.org...) calls `GET/POST /cron/{job}` with
`Authorization: Bearer <CRON_SECRET>`. Jobs: sla-check, auto-assign, dispatch, all.
"""
import hmac
from dataclasses import asdict

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.timeutil import utcnow
from app.db.session import get_db
from app.services.assignment import auto_assign_enabled, sweep_unassigned
from app.services.escalation import run_sla_check
from app.services.notification_service import dispatch_pending

router = APIRouter(prefix="/cron", tags=["cron"])


def require_cron_secret(authorization: str = Header(default="", alias="Authorization")) -> None:
    secret = settings.cron_secret
    if not secret:
        raise HTTPException(status_code=503, detail="CRON_SECRET is not configured on the server")
    given = authorization.removeprefix("Bearer ").strip() if authorization.startswith("Bearer ") else ""
    if not hmac.compare_digest(given.encode(), secret.encode()):
        raise HTTPException(status_code=401, detail="Invalid cron credentials", headers={"WWW-Authenticate": "Bearer"})


def _run(job: str, db: Session) -> dict:
    now = utcnow()
    if job == "sla-check":
        return asdict(run_sla_check(db, now))
    if job == "auto-assign":
        return sweep_unassigned(db, now) if auto_assign_enabled() else {"skipped": "auto-assign is switched off"}
    if job == "dispatch":
        return asdict(dispatch_pending(db))
    raise HTTPException(status_code=404, detail="Unknown job")


@router.api_route("/{job}", methods=["GET", "POST"], dependencies=[Depends(require_cron_secret)])
def run_job(job: str, db: Session = Depends(get_db)):
    if job == "all":  # order matters: assign first so the new assignments are notified in the same run
        return {name: _run(name, db) for name in ("sla-check", "auto-assign", "dispatch")}
    return {job: _run(job, db)}
