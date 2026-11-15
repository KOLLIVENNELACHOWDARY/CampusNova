"""Small helpers every service module shares: errors, the open-status set, the audit-event writer."""
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import ComplaintStatus, Priority, UserRole
from app.core.timeutil import utcnow
from app.models import Complaint, ComplaintEvent, User

OPEN_STATUSES = (ComplaintStatus.REGISTERED, ComplaintStatus.ASSIGNED, ComplaintStatus.IN_PROGRESS)
PRIORITY_RANK = {Priority.CRITICAL: 0, Priority.HIGH: 1, Priority.MEDIUM: 2, Priority.LOW: 3}


class BusinessRuleError(ValueError):
    """A request that is well-formed but not allowed (wrong status move, bad assignee, already reviewed)."""


class ComplaintValidationError(BusinessRuleError):
    """The complaint text itself is not acceptable (empty, gibberish, too long)."""


class NotFoundError(LookupError):
    pass


def log_event(db: Session, complaint_id: int, event_type: str, from_value=None, to_value=None,
              actor_id: Optional[int] = None, note: Optional[str] = None, now: Optional[datetime] = None) -> None:
    """Append to the detailed audit trail (registration, assignment, status, AI review, SLA warnings, escalations)."""
    db.add(ComplaintEvent(complaint_id=complaint_id, event_type=event_type, from_value=from_value, to_value=to_value,
                          actor_id=actor_id, note=note, created_at=now or utcnow()))


def admin_ids(db: Session) -> list[int]:
    return list(db.scalars(select(User.id).where(User.role == UserRole.ADMIN, User.is_active.is_(True)).order_by(User.id)))


def get_complaint(db: Session, complaint_id: int) -> Complaint:
    c = db.get(Complaint, complaint_id)
    if c is None:
        raise NotFoundError(f"complaint {complaint_id} not found")
    return c


def get_user(db: Session, user_id: int) -> User:
    u = db.get(User, user_id)
    if u is None:
        raise NotFoundError(f"user {user_id} not found")
    return u
