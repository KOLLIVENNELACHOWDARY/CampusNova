"""Thin wrappers so the original AI/notification/SLA test-suite runs unchanged against the integrated services.

Old code registered complaints with a free-text `location`; the team schema stores block/floor/room. `location`
is mapped to `block` (floor "G") so tests that group by place still behave the same.
"""
from app.core.enums import ComplaintStatus
from app.services import ai_service as _ai, complaints as _c, workflow as _w
from app.services.common import *  # noqa: F401,F403  (errors, OPEN_STATUSES, admin_ids, get_complaint)
from app.services.complaints import count_open, get_events, list_complaints  # noqa: F401
from app.services.ai_service import pending_reviews, review_prediction  # noqa: F401
from app.services.workflow import assign_complaint  # noqa: F401


def change_status(db, complaint_id, new_status, actor_id=None, note="", now=None):
    """The service insists on a note when resolving; the original tests did not pass one."""
    if new_status == ComplaintStatus.RESOLVED and not note:
        note = "Work completed"
    return _w.change_status(db, complaint_id, new_status, actor_id, note, now, enforce_actor=False)


def register_complaint(db, *, reporter_id, title, description="", location="", category=None, detector=None, now=None,
                       auto_assign=False):
    return _c.register_complaint(db, reporter_id=reporter_id, title=title, description=description or title,
                                 block=location.strip() or "-", floor="G" if location.strip() else "-", category=category, detector=detector,
                                 now=now, auto_assign=auto_assign)


def Complaint(**kw):
    """Build a Complaint row directly, filling the columns the team schema requires."""
    import uuid

    from app.models import Complaint as Row

    kw.setdefault("complaint_number", f"T-{uuid.uuid4().hex[:10]}")
    loc = kw.pop("location", None)
    kw.setdefault("block", loc or "Main block")
    kw.setdefault("floor", "G")
    kw.setdefault("reporter_department_id", 1)
    kw.setdefault("responsible_department_id", 1)
    kw.setdefault("reported_by", 1)
    kw.setdefault("description", kw.get("title") or "test complaint")
    return Row(**kw)


def ticket_code(complaint_id: int) -> str:
    return f"CN-{complaint_id:05d}"
