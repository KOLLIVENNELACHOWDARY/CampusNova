"""Workflow endpoints (Sadhvika): assign, claim/release, status changes, remarks, sign-off, routing rules."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.complaints import _load_visible
from app.api.deps import acting_user, require_permission
from app.core.enums import Category, ComplaintStatus, UserRole
from app.db.session import get_db
from app.models import User
from app.schemas.complaint import (AssignRequest, ComplaintRead, HistoryRead, ReleaseRequest, RemarkRequest,
                                   RoutingRuleRead, RoutingRuleWrite, StatusRequest)
from app.services import assignment, workflow
from app.services.common import get_complaint

router = APIRouter(tags=["workflow"])


@router.post("/complaints/{complaint_id}/assign", response_model=ComplaintRead)
def assign(complaint_id: int, body: AssignRequest, user: User = Depends(require_permission("complaint:assign")), db: Session = Depends(get_db)):
    return workflow.assign_complaint(db, complaint_id, body.assignee_id, user.id)


@router.post("/complaints/{complaint_id}/claim", response_model=ComplaintRead)
def claim(complaint_id: int, user: User = Depends(require_permission("workflow:work")), db: Session = Depends(get_db)):
    return assignment.claim_complaint(db, complaint_id, user.id)


@router.post("/complaints/{complaint_id}/release", response_model=ComplaintRead)
def release(complaint_id: int, body: ReleaseRequest, user: User = Depends(require_permission("workflow:work")), db: Session = Depends(get_db)):
    return assignment.release_complaint(db, complaint_id, user.id, body.reason)


@router.post("/complaints/{complaint_id}/status", response_model=ComplaintRead)
def set_status(complaint_id: int, body: StatusRequest, user: User = Depends(acting_user), db: Session = Depends(get_db)):
    c = _load_visible(db, complaint_id, user)  # 403 if the caller is not involved at all
    return workflow.change_status(db, c.id, body.status, user.id, body.note)


@router.post("/complaints/{complaint_id}/sign-off", response_model=ComplaintRead)
def sign_off(complaint_id: int, user: User = Depends(acting_user), db: Session = Depends(get_db)):
    """The reporter (or an admin) confirms the fix and closes the complaint."""
    c = _load_visible(db, complaint_id, user)
    return workflow.change_status(db, c.id, ComplaintStatus.CLOSED, user.id, "Signed off")


@router.post("/complaints/{complaint_id}/reopen", response_model=ComplaintRead)
def reopen(complaint_id: int, body: RemarkRequest, user: User = Depends(acting_user), db: Session = Depends(get_db)):
    c = _load_visible(db, complaint_id, user)
    return workflow.change_status(db, c.id, ComplaintStatus.IN_PROGRESS, user.id, body.text)


@router.post("/complaints/{complaint_id}/remarks", response_model=HistoryRead, status_code=201)
def add_remark(complaint_id: int, body: RemarkRequest, user: User = Depends(acting_user), db: Session = Depends(get_db)):
    _load_visible(db, complaint_id, user)
    return workflow.add_remark(db, complaint_id, user.id, body.text)


@router.get("/complaints/{complaint_id}/timeline", response_model=list[HistoryRead])
def timeline(complaint_id: int, user: User = Depends(acting_user), db: Session = Depends(get_db)):
    _load_visible(db, complaint_id, user)
    return workflow.timeline(db, complaint_id)


@router.get("/routing-rules", response_model=list[RoutingRuleRead])
def list_rules(_: User = Depends(acting_user), db: Session = Depends(get_db)):
    return workflow.list_rules(db)


@router.put("/routing-rules/{category}", response_model=RoutingRuleRead)
def put_rule(category: Category, body: RoutingRuleWrite, user: User = Depends(require_permission("routing:manage")), db: Session = Depends(get_db)):
    return workflow.set_rule(db, category, body.department_id, user.id, body.is_active)
