"""Complaint workflow (Sadhvika): routing to a department, the status state machine, assignment, remarks, sign-off.

Every function is one transaction (commits at the end) and writes both the status history (`complaint_history`,
the team table) and the detailed audit event (`complaint_events`).

State machine (anything else is rejected with BusinessRuleError):
    registered -> assigned -> in_progress -> resolved -> closed
    resolved -> in_progress              (reopen: the reporter/admin says it is not fixed)
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import Category, ComplaintStatus, NotificationType, UserRole
from app.core.permissions import has_permission
from app.core.timeutil import ensure_utc, utcnow
from app.models import Assignment, Complaint, ComplaintHistory, RoutingRule, User
from app.services.common import (OPEN_STATUSES, BusinessRuleError, NotFoundError, admin_ids, get_complaint, get_user,
                                 log_event)
from app.services.notification_service import notify

S = ComplaintStatus
ALLOWED = {
    S.REGISTERED: {S.ASSIGNED},
    S.ASSIGNED: {S.IN_PROGRESS},
    S.IN_PROGRESS: {S.RESOLVED},
    S.RESOLVED: {S.CLOSED, S.IN_PROGRESS},
    S.CLOSED: set(),
}
MAX_REMARK = 1000


# ------------------------------------------------------------------------------------------------ routing
def resolve_department(db: Session, category: Category, reporter_department_id: int) -> int:
    """Department responsible for `category`: the active routing rule, or the reporter's own department."""
    rule = db.scalar(select(RoutingRule).where(RoutingRule.category == category, RoutingRule.is_active.is_(True)))
    return rule.department_id if rule and rule.department_id else reporter_department_id


def list_rules(db: Session) -> list[RoutingRule]:
    return list(db.scalars(select(RoutingRule).order_by(RoutingRule.id)))


def set_rule(db: Session, category: Category, department_id: Optional[int], actor_id: int, is_active: bool = True) -> RoutingRule:
    from app.models import Department

    if department_id is not None and db.get(Department, department_id) is None:
        raise NotFoundError(f"department {department_id} not found")
    rule = db.scalar(select(RoutingRule).where(RoutingRule.category == category))
    if rule is None:
        rule = RoutingRule(category=category)
        db.add(rule)
    rule.department_id, rule.is_active, rule.updated_by = department_id, is_active, actor_id
    db.commit()
    return rule


# ------------------------------------------------------------------------------------------------ history
def _history(db: Session, c: Complaint, old, new, actor_id, remarks, now) -> None:
    db.add(ComplaintHistory(complaint_id=c.id, changed_by=actor_id, old_status=old, new_status=new,
                            remarks=remarks or None, created_at=now))


# ------------------------------------------------------------------------------------------------ assignment
def assign_complaint(db: Session, complaint_id: int, assignee_id: int, actor_id: Optional[int] = None,
                     now: Optional[datetime] = None, note: Optional[str] = None, assignment_type: Optional[str] = None) -> Complaint:
    now = now or utcnow()
    c = get_complaint(db, complaint_id)
    assignee = db.get(User, assignee_id)
    if assignee is None or assignee.role != UserRole.MAINTENANCE or not assignee.is_active:
        raise BusinessRuleError("Complaints can only be assigned to an active maintenance staff member.")
    if c.status not in OPEN_STATUSES:
        raise BusinessRuleError(f"A {c.status.value} complaint cannot be (re)assigned.")
    kind = assignment_type or ("auto" if actor_id is None else "claimed" if actor_id == assignee_id else "manual")
    previous, old_status = c.assigned_to, c.status
    c.assigned_to, c.assigned_at = assignee_id, now
    if c.status == ComplaintStatus.REGISTERED:
        c.status = ComplaintStatus.ASSIGNED
        _history(db, c, old_status, c.status, actor_id, note, now)
    db.add(Assignment(complaint_id=c.id, assigned_to=assignee_id, assigned_by=None if kind == "auto" else actor_id,
                      assignment_type=kind, assigned_at=now, notes=note))
    log_event(db, c.id, "assigned", str(previous) if previous else None, str(assignee_id), actor_id, note, now)
    notify(db, [assignee_id], NotificationType.ASSIGNMENT, f"New task {c.complaint_number}: {c.label}",
           f"Priority {c.priority.value.upper()}, due {ensure_utc(c.sla_due_at):%d %b %H:%M} UTC. Location: {c.location}",
           complaint_id=c.id, now=now)
    notify(db, [c.reported_by], NotificationType.STATUS_UPDATE, f"{c.complaint_number} assigned",
           f"Your complaint was assigned to {assignee.name}.", complaint_id=c.id, now=now)
    db.commit()
    return c


# ------------------------------------------------------------------------------------------------ status
def can_change(actor: User, c: Complaint, new_status: ComplaintStatus) -> bool:
    """Who may make which move (admins may make any legal move)."""
    if actor.role == UserRole.ADMIN:
        return True
    if new_status in (S.IN_PROGRESS, S.RESOLVED) and c.status != S.RESOLVED:
        return actor.role == UserRole.MAINTENANCE and c.assigned_to == actor.id
    if c.status == S.RESOLVED and new_status in (S.CLOSED, S.IN_PROGRESS):
        return actor.id == c.reported_by  # sign-off / reopen by the person who reported it
    return False


def change_status(db: Session, complaint_id: int, new_status: ComplaintStatus, actor_id: Optional[int] = None,
                  note: str = "", now: Optional[datetime] = None, enforce_actor: bool = True) -> Complaint:
    now = now or utcnow()
    c = get_complaint(db, complaint_id)
    if new_status not in ALLOWED[c.status]:
        raise BusinessRuleError(f"Cannot move a complaint from {c.status.value} to {new_status.value}.")
    if new_status == S.ASSIGNED and c.assigned_to is None:
        raise BusinessRuleError("Assign the complaint to a staff member first.")
    if new_status == S.ASSIGNED:  # assigning is done through assign_complaint so a worker and an Assignment row exist
        raise BusinessRuleError("Use the assign action to move a complaint to assigned.")
    if actor_id is not None and enforce_actor:
        actor = get_user(db, actor_id)
        if not can_change(actor, c, new_status):
            raise PermissionError("You are not allowed to make this status change on this complaint.")
    if new_status == S.RESOLVED and not (note or "").strip():
        raise BusinessRuleError("Add a short note describing what was done before marking it resolved.")
    old = c.status
    c.status = new_status
    if new_status == S.RESOLVED:
        c.resolved_at = now
    elif new_status == S.CLOSED:
        c.closed_at = now
    elif old == S.RESOLVED and new_status == S.IN_PROGRESS:
        c.resolved_at = None  # reopened
    _history(db, c, old, new_status, actor_id, note, now)
    log_event(db, c.id, "status_changed", old.value, new_status.value, actor_id, note or None, now)
    text = {S.IN_PROGRESS: "Work has started." if old != S.RESOLVED else "The complaint was reopened.",
            S.RESOLVED: "The issue was marked as resolved. Please confirm it is fixed (sign off) or reopen it.",
            S.CLOSED: "The complaint was closed."}[new_status]
    targets = [c.reported_by] + ([c.assigned_to] if new_status in (S.CLOSED,) or old == S.RESOLVED else [])
    notify(db, targets, NotificationType.STATUS_UPDATE,
           f"{c.complaint_number} is now {new_status.value.replace('_', ' ')}", f"{text} {note}".strip(),
           complaint_id=c.id, now=now)
    if new_status == S.RESOLVED:
        notify(db, admin_ids(db), NotificationType.STATUS_UPDATE, f"{c.complaint_number} resolved",
               f"Waiting for sign-off from the reporter. {note}".strip(), complaint_id=c.id,
               dedupe_key=f"resolved:{c.id}:{now.isoformat()}", now=now)
    db.commit()
    return c


# ------------------------------------------------------------------------------------------------ remarks
def add_remark(db: Session, complaint_id: int, actor_id: int, text: str, now: Optional[datetime] = None) -> ComplaintHistory:
    """A comment on the complaint's timeline (no status change)."""
    now = now or utcnow()
    text = (text or "").strip()
    if not text:
        raise BusinessRuleError("A remark cannot be empty.")
    if len(text) > MAX_REMARK:
        raise BusinessRuleError(f"A remark can be at most {MAX_REMARK} characters.")
    c = get_complaint(db, complaint_id)
    actor = get_user(db, actor_id)
    involved = actor.role == UserRole.ADMIN or actor_id in (c.reported_by, c.assigned_to)
    if not involved or not has_permission(actor.role, "workflow:remark"):
        raise PermissionError("Only people involved in this complaint can comment on it.")
    h = ComplaintHistory(complaint_id=c.id, changed_by=actor_id, old_status=c.status, new_status=c.status,
                         remarks=text, created_at=now)
    db.add(h)
    log_event(db, c.id, "remark", None, None, actor_id, text, now)
    others = {c.reported_by, c.assigned_to} - {actor_id, None}
    notify(db, list(others), NotificationType.STATUS_UPDATE, f"New remark on {c.complaint_number}", text[:200],
           complaint_id=c.id, now=now)
    db.commit()
    return h


def timeline(db: Session, complaint_id: int) -> list[ComplaintHistory]:
    return list(db.scalars(select(ComplaintHistory).where(ComplaintHistory.complaint_id == complaint_id)
                           .order_by(ComplaintHistory.id)))
