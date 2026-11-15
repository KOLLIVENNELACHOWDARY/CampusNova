"""Complaint registration and queries (Jahnavi), with the AI classification step (Vennela) in the middle."""
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.enums import Category, ComplaintStatus, NotificationType, Priority, UserRole
from app.core.timeutil import ensure_utc, utcnow
from app.models import Complaint, ComplaintEvent, Department, User
from app.services import ai_service
from app.services.common import (OPEN_STATUSES, PRIORITY_RANK, ComplaintValidationError, NotFoundError, admin_ids,
                                 log_event)
from app.services.notification_service import notify
from app.services.workflow import resolve_department
from ml.validation import validate_complaint


def _title_from(description: str) -> str:
    first = description.strip().split("\n")[0].strip()
    return first if len(first) <= 80 else first[:77].rstrip() + "..."


def register_complaint(
    db: Session, *, reporter_id: int, description: str, block: str, floor: str, room_number: Optional[str] = None,
    title: Optional[str] = None, category: Optional[Category] = None, responsible_department_id: Optional[int] = None,
    reporter_department_id: Optional[int] = None, detector=None, now: Optional[datetime] = None, auto_assign: bool = False,
    strict_description: bool = False,
) -> Complaint:
    now = now or utcnow()
    description = (description or "").strip()
    title = (title or "").strip() or None
    block, floor, room_number = (block or "").strip(), (floor or "").strip(), (room_number or "").strip() or None
    if not block or not floor:
        raise ComplaintValidationError("Block and floor are required so a technician can find the place.")
    error = validate_complaint(title or _title_from(description), description)
    if not error and strict_description:  # web/API users: the description must stand on its own, not just the title
        error = validate_complaint(description, "") if description else "Please describe the problem."
    if error:
        raise ComplaintValidationError(error)
    reporter = db.get(User, reporter_id)
    if reporter is None:
        raise NotFoundError(f"user {reporter_id} not found")
    dept_id = reporter_department_id or reporter.department_id
    if dept_id is None or db.get(Department, dept_id) is None:
        raise ComplaintValidationError("The reporter's department is unknown; set a department on the account first.")
    if responsible_department_id is not None and db.get(Department, responsible_department_id) is None:
        raise NotFoundError(f"department {responsible_department_id} not found")

    title = title or _title_from(description)
    location = ", ".join(p for p in (block, floor, room_number) if p)
    body = f"{description} ({location})"
    result = ai_service.predict(detector, title, body, category)
    resp_dept = responsible_department_id or resolve_department(db, result.category, dept_id)

    c = Complaint(
        complaint_number=f"TMP-{now.timestamp():.6f}", reported_by=reporter_id, reporter_department_id=dept_id,
        block=block, floor=floor, room_number=room_number, title=title, description=description,
        category=result.category, priority=result.priority, status=ComplaintStatus.REGISTERED,
        responsible_department_id=resp_dept, safety_risk=result.safety_risk, needs_manual_review=result.needs_manual_review,
        sla_hours=result.sla_hours, sla_due_at=now + timedelta(hours=result.sla_hours), created_at=now)
    db.add(c)
    db.flush()
    c.complaint_number = f"CN-{c.id:05d}"
    ai_service.record_prediction(db, c, result, f"{title}. {body}", now)
    log_event(db, c.id, "registered", to_value=result.priority.value, actor_id=reporter_id,
              note=f"AI: {result.category.value}/{result.priority.value} via {result.source}", now=now)
    from app.models import ComplaintHistory

    db.add(ComplaintHistory(complaint_id=c.id, changed_by=reporter_id, old_status=None, new_status=ComplaintStatus.REGISTERED,
                            remarks="Complaint registered", created_at=now))

    code = c.complaint_number
    notify(db, [reporter_id], NotificationType.STATUS_UPDATE, f"{code} registered",
           f"Your complaint '{title}' was registered as {result.priority.value.upper()} priority. "
           f"Target resolution: within {result.sla_hours} hours.", complaint_id=c.id, now=now)
    admins = admin_ids(db)
    if result.priority == Priority.CRITICAL or result.safety_risk:
        notify(db, admins, NotificationType.URGENT_ALERT, f"URGENT {code}: {title}",
               f"Critical complaint reported{' (safety risk)' if result.safety_risk else ''} at {location}. "
               "Needs immediate assignment.", complaint_id=c.id, dedupe_key=f"urgent:{c.id}", now=now)
    if result.needs_manual_review:
        notify(db, admins, NotificationType.STATUS_UPDATE, f"AI review needed for {code}",
               f"The AI was not sure about '{title}'. Please confirm or correct its category and priority.",
               complaint_id=c.id, dedupe_key=f"review:{c.id}", now=now)
    db.commit()
    if auto_assign:
        from app.services.assignment import auto_assign as assign_best_worker

        assign_best_worker(db, c.id, now=now)
    return c


# ------------------------------------------------------------------------------------------------ queries
SORTS = {"newest": (Complaint.created_at.desc(), Complaint.id.desc()), "oldest": (Complaint.created_at.asc(), Complaint.id.asc()),
         "due": (Complaint.sla_due_at.asc(), Complaint.id.asc())}


def search_complaints(db: Session, *, reporter_id: Optional[int] = None, assignee_id: Optional[int] = None,
                      status: Optional[ComplaintStatus] = None, category: Optional[Category] = None,
                      priority: Optional[Priority] = None, department_id: Optional[int] = None,
                      block: Optional[str] = None, q: Optional[str] = None, open_only: bool = False,
                      date_from: Optional[datetime] = None, date_to: Optional[datetime] = None,
                      sort: str = "newest", page: int = 1, page_size: int = 20) -> tuple[list[Complaint], int]:
    """Filtered, sorted, paginated list. Returns (rows, total matching)."""
    stmt = select(Complaint)
    if reporter_id is not None:
        stmt = stmt.where(Complaint.reported_by == reporter_id)
    if assignee_id is not None:
        stmt = stmt.where(Complaint.assigned_to == assignee_id)
    if status is not None:
        stmt = stmt.where(Complaint.status == status)
    if category is not None:
        stmt = stmt.where(Complaint.category == category)
    if priority is not None:
        stmt = stmt.where(Complaint.priority == priority)
    if department_id is not None:
        stmt = stmt.where(or_(Complaint.responsible_department_id == department_id,
                              Complaint.reporter_department_id == department_id))
    if block:
        stmt = stmt.where(func.lower(Complaint.block) == block.strip().lower())
    if open_only:
        stmt = stmt.where(Complaint.status.in_(OPEN_STATUSES))
    if date_from:
        stmt = stmt.where(Complaint.created_at >= date_from)
    if date_to:
        stmt = stmt.where(Complaint.created_at <= date_to)
    if q and q.strip():
        like = f"%{q.strip().lower().replace('%', '').replace('_', '')}%"
        stmt = stmt.where(or_(func.lower(Complaint.description).like(like), func.lower(Complaint.title).like(like),
                              func.lower(Complaint.complaint_number).like(like)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    page, page_size = max(1, page), min(max(1, page_size), 100)
    rows = list(db.scalars(stmt.order_by(*SORTS.get(sort, SORTS["newest"])).offset((page - 1) * page_size).limit(page_size)))
    return rows, total


def list_complaints(db: Session, *, reporter_id: Optional[int] = None, assignee_id: Optional[int] = None,
                    open_only: bool = False) -> list[Complaint]:
    """All matching complaints, most urgent first (used by work queues and the dashboards)."""
    q = select(Complaint)
    if reporter_id is not None:
        q = q.where(Complaint.reported_by == reporter_id)
    if assignee_id is not None:
        q = q.where(Complaint.assigned_to == assignee_id)
    if open_only:
        q = q.where(Complaint.status.in_(OPEN_STATUSES))
    rows = list(db.scalars(q))
    rows.sort(key=lambda c: (PRIORITY_RANK.get(c.priority, 9), ensure_utc(c.created_at)))
    return rows


def get_events(db: Session, complaint_id: int) -> list[ComplaintEvent]:
    return list(db.scalars(select(ComplaintEvent).where(ComplaintEvent.complaint_id == complaint_id).order_by(ComplaintEvent.id)))


def count_open(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Complaint).where(Complaint.status.in_(OPEN_STATUSES))) or 0
