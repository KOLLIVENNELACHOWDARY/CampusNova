"""Automatic assignment: the right tradesperson, with the lightest workload, without an admin in the loop.

How a complaint finds its worker
    1. The AI category is routed (routing_rules) to a responsible department, e.g. electrical -> EEE.
       A maintenance worker's `department_id` says which department's jobs they handle.
    2. Among active workers of that department, the one with the lowest open workload gets it
       (workload = sum of weights of their open jobs: critical 4, high 3, medium 2, low 1; ties -> fewer jobs, then id).
    3. No worker in that department? Fall back to the least busy active maintenance worker.

Workers can also help themselves: `claim_complaint` takes an unassigned job from the open pool, and
`release_complaint` hands a job back (before work starts). `sweep_unassigned` is the safety net the scheduler runs for
anything nobody claimed. An admin can still assign by hand; nothing here removes that.

Complaints the AI was unsure about wait for an admin to confirm the category first (a wrong category means the wrong
trade), unless they are a safety risk: those are assigned immediately and corrected after review if needed.
"""
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import Category, ComplaintStatus, NotificationType, Priority, UserRole
from app.core.timeutil import ensure_utc, utcnow
from app.models import Complaint, ComplaintEvent, User
from app.services import common as cs
from app.services import workflow
from app.services.notification_service import notify

LOAD_WEIGHT = {Priority.CRITICAL: 4, Priority.HIGH: 3, Priority.MEDIUM: 2, Priority.LOW: 1}
DEFAULT_GRACE_MINUTES = 10  # how long a released/unclaimed job waits in the pool before the sweep assigns it
_WORKING = (ComplaintStatus.ASSIGNED, ComplaintStatus.IN_PROGRESS)


def auto_assign_enabled() -> bool:
    return os.getenv("CAMPUSNOVA_AUTO_ASSIGN", "1") != "0"


def same_dept(worker: User, complaint: Complaint) -> bool:
    """A worker belongs to the department that is responsible for the complaint (routing decides the department)."""
    return worker.department_id is not None and worker.department_id == complaint.responsible_department_id


def active_workers(db: Session) -> list[User]:
    return list(db.scalars(select(User).where(User.role == UserRole.MAINTENANCE, User.is_active.is_(True)).order_by(User.id)))


def worker_load(db: Session, worker_id: int) -> tuple[int, int]:
    """(weighted load, number of open jobs) for one worker."""
    jobs = db.scalars(select(Complaint).where(Complaint.assigned_to == worker_id, Complaint.status.in_(_WORKING))).all()
    return sum(LOAD_WEIGHT.get(j.priority, 2) for j in jobs), len(jobs)


@dataclass
class Choice:
    worker: User
    reason: str


def choose_worker(db: Session, complaint: Complaint, exclude: frozenset = frozenset()) -> Optional[Choice]:
    workers = [w for w in active_workers(db) if w.id not in exclude]
    if not workers:
        return None
    same = [w for w in workers if same_dept(w, complaint)]
    pool, how = (same, "responsible department") if same else (workers, "no one in that department, least busy worker")
    loads = {w.id: worker_load(db, w.id) for w in pool}
    best = min(pool, key=lambda w: (loads[w.id], w.id))
    load, jobs = loads[best.id]
    return Choice(best, f"{how}; workload {load} ({jobs} open job{'s' if jobs != 1 else ''})")


def released_by(db: Session, complaint_id: int) -> frozenset:
    """Workers who handed this job back: they should not be given it again automatically."""
    return frozenset(db.scalars(select(ComplaintEvent.actor_id).where(
        ComplaintEvent.complaint_id == complaint_id, ComplaintEvent.event_type == "released",
        ComplaintEvent.actor_id.is_not(None))))


def is_claimable(c: Complaint) -> bool:
    """In the open pool: not taken, not finished, and not waiting for an admin to confirm the AI (unless a safety risk)."""
    return (c.status == ComplaintStatus.REGISTERED and c.assigned_to is None
            and (not c.needs_manual_review or c.safety_risk))


def auto_assign(db: Session, complaint_id: int, now: Optional[datetime] = None, allow_reassign: bool = False) -> Optional[User]:
    """Give a complaint to the best worker. Returns the worker, or None if it was not (re)assigned."""
    now = now or utcnow()
    c = cs.get_complaint(db, complaint_id)
    if c.status not in (ComplaintStatus.REGISTERED, ComplaintStatus.ASSIGNED):
        return None
    if c.assigned_to is not None:
        current = db.get(User, c.assigned_to)
        # only move a job that has not started, and only if the current worker is no longer in the right trade
        if not allow_reassign or c.status != ComplaintStatus.ASSIGNED or (
                current and same_dept(current, c)):
            return None
    elif not is_claimable(c):
        return None
    choice = choose_worker(db, c, exclude=released_by(db, c.id))
    if choice is None:
        return None
    workflow.assign_complaint(db, c.id, choice.worker.id, actor_id=None, now=now, note=f"Auto-assigned by AI: {choice.reason}")
    return choice.worker


def claim_complaint(db: Session, complaint_id: int, worker_id: int, now: Optional[datetime] = None) -> Complaint:
    """A worker takes an open job themselves."""
    now = now or utcnow()
    worker = db.get(User, worker_id)
    if worker is None or worker.role != UserRole.MAINTENANCE or not worker.is_active:
        raise PermissionError("Only an active maintenance worker can take a job.")
    c = cs.get_complaint(db, complaint_id)
    if c.assigned_to is not None:
        owner = db.get(User, c.assigned_to)
        raise cs.BusinessRuleError(f"This job was already taken by {owner.name if owner else 'someone else'}.")
    if not is_claimable(c):
        if c.status != ComplaintStatus.REGISTERED:
            raise cs.BusinessRuleError(f"A {c.status.value} complaint cannot be taken.")
        raise cs.BusinessRuleError("This complaint is waiting for an admin to confirm the AI result before it can be taken.")
    return workflow.assign_complaint(db, complaint_id, worker_id, actor_id=worker_id, now=now,
                               note=f"Taken by {worker.name} ")


def release_complaint(db: Session, complaint_id: int, worker_id: int, reason: str = "",
                      now: Optional[datetime] = None) -> Complaint:
    """A worker hands back a job they have not started, so it returns to the open pool."""
    now = now or utcnow()
    c = cs.get_complaint(db, complaint_id)
    worker = db.get(User, worker_id)
    if c.assigned_to != worker_id or worker is None:
        raise PermissionError("You can only hand back your own jobs.")
    if c.status != ComplaintStatus.ASSIGNED:
        raise cs.BusinessRuleError("Only a job you have not started can be handed back. Ask an admin for help.")
    c.assigned_to, c.assigned_at, c.status = None, None, ComplaintStatus.REGISTERED
    from app.models import ComplaintHistory
    db.add(ComplaintHistory(complaint_id=c.id, changed_by=worker_id, old_status=ComplaintStatus.ASSIGNED, new_status=ComplaintStatus.REGISTERED, remarks=reason or 'Handed back to the pool', created_at=now))
    cs.log_event(db, c.id, "released", str(worker_id), None, worker_id, reason or None, now)
    code = c.complaint_number
    mates = [w.id for w in active_workers(db) if w.id != worker_id and same_dept(w, c)]
    notify(db, mates or cs.admin_ids(db), NotificationType.ASSIGNMENT, f"Job back in the pool: {code} {c.label}",
           f"{worker.name} handed this job back{': ' + reason if reason else ''}. Take it from the Open jobs page.",
           complaint_id=c.id, dedupe_key=f"released:{c.id}:{now.isoformat()}", now=now)
    db.commit()
    return c


def open_pool(db: Session, worker: Optional[User] = None) -> list[Complaint]:
    """Unassigned open jobs, the worker's own trade first, then most urgent."""
    rows = [c for c in db.scalars(select(Complaint).order_by(Complaint.id)) if is_claimable(c)]
    mine = worker.department_id if worker else None
    rank = cs.PRIORITY_RANK
    rows.sort(key=lambda c: (c.responsible_department_id != mine, rank.get(c.priority, 9), ensure_utc(c.created_at)))
    return rows


def sweep_unassigned(db: Session, now: Optional[datetime] = None, grace_minutes: float = DEFAULT_GRACE_MINUTES) -> dict:
    """Safety net: assign any open-pool job that nobody took within the grace period."""
    now = now or utcnow()
    assigned: dict[int, int] = {}
    for c in open_pool(db):
        last = db.scalar(select(ComplaintEvent.created_at).where(
            ComplaintEvent.complaint_id == c.id, ComplaintEvent.event_type == "released").order_by(ComplaintEvent.id.desc()))
        waiting_since = ensure_utc(last or c.created_at)
        if now - waiting_since < timedelta(minutes=grace_minutes):
            continue
        worker = auto_assign(db, c.id, now=now)
        if worker:
            assigned[c.id] = worker.id
    return {"assigned": assigned, "still_waiting": len(open_pool(db))}
