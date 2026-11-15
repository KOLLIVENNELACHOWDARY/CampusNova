"""Overdue detection, SLA warnings and escalation.

Every open complaint has `sla_due_at` (filed-at + the SLA hours of its priority).

    before the deadline : when <= 25% of the SLA window is left, warn the assignee (or admins if unassigned)
    level 1             : deadline passed                -> assignee + admins
    level 2             : overdue by >= 50% of the window -> admins (+ assignee)
    level 3             : overdue by >= 100% of the window -> admins, and the reporter is told it was escalated

Levels only go up, and each (complaint, level, deadline) notifies once: notifications carry a dedupe key, so
running the check every few minutes (or twice at the same moment) never sends duplicates.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import NotificationType
from app.core.timeutil import ensure_utc, utcnow
from app.models import Complaint, ComplaintEvent
from app.services.common import OPEN_STATUSES, admin_ids, log_event
from app.services.notification_service import notify

WARN_FRACTION = 0.25
LEVEL_2_AT = 0.5  # fraction of the SLA window past the deadline
LEVEL_3_AT = 1.0


@dataclass
class SlaCheckResult:
    checked: int = 0
    overdue: int = 0
    warned: list[int] = field(default_factory=list)
    escalated: dict[int, int] = field(default_factory=dict)  # complaint id -> new level


def escalation_level_for(overdue_by: timedelta, window: timedelta) -> int:
    if overdue_by <= timedelta(0):
        return 0
    if overdue_by >= window * LEVEL_3_AT:
        return 3
    if overdue_by >= window * LEVEL_2_AT:
        return 2
    return 1


def find_overdue(db: Session, now: Optional[datetime] = None) -> list[Complaint]:
    """Open complaints past their deadline, most overdue first."""
    now = now or utcnow()
    rows = [c for c in db.scalars(select(Complaint).where(Complaint.status.in_(OPEN_STATUSES),
                                                          Complaint.sla_due_at.is_not(None)))
            if ensure_utc(c.sla_due_at) < now]
    rows.sort(key=lambda c: ensure_utc(c.sla_due_at))
    return rows


def _log(db, c, kind, note, now, to_value=None):
    db.add(ComplaintEvent(complaint_id=c.id, event_type=kind, to_value=to_value, actor_id=None, note=note, created_at=now))


def run_sla_check(db: Session, now: Optional[datetime] = None) -> SlaCheckResult:
    now = now or utcnow()
    admins = admin_ids(db)
    result = SlaCheckResult()
    open_complaints = db.scalars(select(Complaint).where(Complaint.status.in_(OPEN_STATUSES),
                                                         Complaint.sla_due_at.is_not(None))).all()
    for c in open_complaints:
        result.checked += 1
        due = ensure_utc(c.sla_due_at)
        window = timedelta(hours=c.sla_hours or max((due - ensure_utc(c.created_at)).total_seconds() / 3600, 1))
        code = c.complaint_number
        deadline_key = int(due.timestamp())

        if now <= due:  # still on time: maybe warn
            remaining = due - now
            if not c.sla_warned and remaining <= window * WARN_FRACTION:
                hours_left = remaining.total_seconds() / 3600
                notify(db, [c.assigned_to] if c.assigned_to else admins, NotificationType.SLA_WARNING,
                       f"{code} due soon", f"'{c.label}' ({c.priority.value.upper()}) is due in {hours_left:.1f}h"
                       f"{'' if c.assigned_to else ' and is still unassigned'}.",
                       complaint_id=c.id, dedupe_key=f"warn:{c.id}:{deadline_key}", now=now)
                c.sla_warned = True
                _log(db, c, "sla_warning", f"{hours_left:.1f}h left", now)
                result.warned.append(c.id)
            continue

        result.overdue += 1
        level = escalation_level_for(now - due, window)
        if level <= c.escalation_level:
            continue
        hours_over = (now - due).total_seconds() / 3600
        text = (f"'{c.label}' ({c.priority.value.upper()}, {c.status.value.replace('_', ' ')}) is {hours_over:.1f}h past its "
                f"{c.sla_hours}h deadline{'' if c.assigned_to else ' and is UNASSIGNED'}.")
        recipients = list(admins)
        if c.assigned_to:
            recipients.insert(0, c.assigned_to)
        notify(db, recipients, NotificationType.ESCALATION, f"ESCALATION L{level} {code}", text,
               complaint_id=c.id, dedupe_key=f"esc:{c.id}:L{level}:{deadline_key}", now=now)
        if level >= 3:
            notify(db, [c.reported_by], NotificationType.STATUS_UPDATE, f"{code} escalated",
                   "Your complaint is overdue and has been escalated to the administrators.",
                   complaint_id=c.id, dedupe_key=f"esc-reporter:{c.id}:{deadline_key}", now=now)
        c.escalation_level, c.last_escalated_at = level, now
        _log(db, c, "escalated", text, now, to_value=f"L{level}")
        result.escalated[c.id] = level
    db.commit()
    return result
