"""Background jobs (APScheduler).

    sla_check  every 5 min : find overdue complaints, send SLA warnings, escalate           (app.services.escalation)
    auto_assign every 5 min: hand open jobs nobody took to the best worker (skipped if CAMPUSNOVA_AUTO_ASSIGN=0)
    dispatch   every 60 s  : deliver queued notifications (in-app / SMTP email / FCM push)  (notification_service)

Enable inside the API process with CAMPUSNOVA_SCHEDULER=1, or run the jobs once from a cron / task scheduler:
    python -m app.jobs.run_once
Intervals: CAMPUSNOVA_SLA_CHECK_MINUTES, CAMPUSNOVA_DISPATCH_SECONDS.
"""
import logging
import os
from datetime import datetime, timezone
from typing import Callable, Optional

from apscheduler.schedulers.background import BackgroundScheduler

from app.db.session import SessionLocal
from app.services.assignment import auto_assign_enabled, sweep_unassigned
from app.services.escalation import SlaCheckResult, run_sla_check
from app.services.notification_service import DispatchResult, build_senders, dispatch_pending

logger = logging.getLogger("campusnova.jobs")


def sla_check_job(session_factory: Callable = SessionLocal, now: Optional[datetime] = None) -> SlaCheckResult:
    with session_factory() as db:
        result = run_sla_check(db, now)
    if result.warned or result.escalated:
        logger.info("SLA check: warned=%s escalated=%s overdue=%s", result.warned, result.escalated, result.overdue)
    return result


def auto_assign_job(session_factory: Callable = SessionLocal, now: Optional[datetime] = None) -> dict:
    with session_factory() as db:
        result = sweep_unassigned(db, now)
    if result["assigned"]:
        logger.info("Auto-assign sweep: %s", result["assigned"])
    return result


def dispatch_job(session_factory: Callable = SessionLocal, senders=None, now: Optional[datetime] = None) -> DispatchResult:
    with session_factory() as db:
        result = dispatch_pending(db, senders, now=now)
    if result.sent or result.failed:
        logger.info("Dispatch: sent=%s failed=%s gave_up=%s", result.sent, result.failed, result.gave_up)
    return result


def _safe(fn: Callable, name: str, **kwargs):
    """A crash in one run must never kill the schedule."""
    try:
        return fn(**kwargs)
    except Exception:
        logger.exception("background job %s failed", name)


def build_scheduler(session_factory: Callable = SessionLocal, senders=None, *, sla_check_minutes: Optional[int] = None,
                    dispatch_seconds: Optional[int] = None) -> BackgroundScheduler:
    sla_check_minutes = sla_check_minutes or int(os.getenv("CAMPUSNOVA_SLA_CHECK_MINUTES", "5"))
    dispatch_seconds = dispatch_seconds or int(os.getenv("CAMPUSNOVA_DISPATCH_SECONDS", "60"))
    senders = senders if senders is not None else build_senders()
    start = datetime.now(timezone.utc)
    sched = BackgroundScheduler(timezone="UTC")
    common = dict(max_instances=1, coalesce=True, misfire_grace_time=60, next_run_time=start)
    sched.add_job(_safe, "interval", minutes=sla_check_minutes, id="sla_check", name="Overdue detection and escalation",
                  args=[sla_check_job, "sla_check"], kwargs={"session_factory": session_factory}, **common)
    if auto_assign_enabled():
        sched.add_job(_safe, "interval", minutes=sla_check_minutes, id="auto_assign", name="Assign jobs nobody took",
                      args=[auto_assign_job, "auto_assign"], kwargs={"session_factory": session_factory}, **common)
    sched.add_job(_safe, "interval", seconds=dispatch_seconds, id="dispatch", name="Email / FCM / in-app dispatch",
                  args=[dispatch_job, "dispatch"], kwargs={"session_factory": session_factory, "senders": senders}, **common)
    return sched
