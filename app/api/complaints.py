"""Complaint endpoints (Jahnavi): create, list/filter/paginate, detail, photos. Workflow actions live in workflow.py."""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import acting_user, require_permission
from app.core.enums import Category, ComplaintStatus, Priority, UserRole
from app.core.permissions import has_permission
from app.db.session import get_db
from app.models import Complaint, ComplaintImage, User
from app.schemas.complaint import ComplaintCreate, ComplaintDetail, ComplaintPage, ComplaintRead, EventRead, ImageRead
from app.services import assignment, complaints as svc, images, workflow
from app.services.common import get_complaint

router = APIRouter(prefix="/complaints", tags=["complaints"])


def can_view(user: User, c: Complaint) -> bool:
    if user.role == UserRole.ADMIN:
        return True
    if user.role == UserRole.MAINTENANCE:
        return c.assigned_to == user.id or (c.assigned_to is None and assignment.is_claimable(c))
    return c.reported_by == user.id


def _load_visible(db: Session, complaint_id: int, user: User) -> Complaint:
    c = get_complaint(db, complaint_id)
    if not can_view(user, c):
        raise HTTPException(status_code=403, detail="You cannot view this complaint")
    return c


@router.post("", response_model=ComplaintRead, status_code=201)
def create_complaint(body: ComplaintCreate, user: User = Depends(require_permission("complaint:create")), db: Session = Depends(get_db)):
    return svc.register_complaint(
        db, reporter_id=user.id, description=body.description, block=body.block, floor=body.floor,
        room_number=body.room_number, title=body.title, category=body.category,
        responsible_department_id=body.responsible_department_id, auto_assign=assignment.auto_assign_enabled(),
        strict_description=True)


@router.get("", response_model=ComplaintPage)
def list_complaints(
    status: Optional[ComplaintStatus] = None, category: Optional[Category] = None, priority: Optional[Priority] = None,
    department_id: Optional[int] = Query(None, gt=0), block: Optional[str] = Query(None, max_length=100),
    q: Optional[str] = Query(None, max_length=100), open_only: bool = False, mine: bool = False,
    date_from: Optional[datetime] = None, date_to: Optional[datetime] = None,
    sort: str = Query("newest", pattern="^(newest|oldest|due)$"),
    page: int = Query(1, ge=1, le=10_000), page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(acting_user), db: Session = Depends(get_db)):
    """Admins see everything (or just theirs with mine=true); workers see their assigned jobs; reporters see their own."""
    scope: dict = {}
    if user.role == UserRole.MAINTENANCE:
        scope["assignee_id"] = user.id
    elif user.role != UserRole.ADMIN or mine:
        scope["reporter_id"] = user.id
    rows, total = svc.search_complaints(
        db, status=status, category=category, priority=priority, department_id=department_id, block=block, q=q,
        open_only=open_only, date_from=date_from, date_to=date_to, sort=sort, page=page, page_size=page_size, **scope)
    return ComplaintPage(items=rows, total=total, page=page, page_size=page_size)


@router.get("/pool", response_model=list[ComplaintRead])
def open_pool(user: User = Depends(require_permission("dashboard:maintenance")), db: Session = Depends(get_db)):
    """Unassigned jobs a worker can take; the worker's own department comes first."""
    return assignment.open_pool(db, user if user.role == UserRole.MAINTENANCE else None)


@router.get("/{complaint_id}", response_model=ComplaintDetail)
def complaint_detail(complaint_id: int, user: User = Depends(acting_user), db: Session = Depends(get_db)):
    c = _load_visible(db, complaint_id, user)
    detail = ComplaintDetail.model_validate(c)
    detail.images = [ImageRead.model_validate(i) for i in db.query(ComplaintImage).filter_by(complaint_id=c.id).order_by(ComplaintImage.id)]
    detail.history = workflow.timeline(db, c.id)
    return detail


@router.get("/{complaint_id}/events", response_model=list[EventRead])
def events(complaint_id: int, user: User = Depends(acting_user), db: Session = Depends(get_db)):
    _load_visible(db, complaint_id, user)
    return svc.get_events(db, complaint_id)


@router.post("/{complaint_id}/images", response_model=ImageRead, status_code=201)
def upload_image(complaint_id: int, file: UploadFile = File(...), user: User = Depends(require_permission("complaint:upload_image")),
                 db: Session = Depends(get_db)):
    c = _load_visible(db, complaint_id, user)
    if c.reported_by != user.id and user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Only the reporter can add photos")
    try:
        # read at most limit+1 bytes so a huge upload cannot exhaust memory
        from app.core.config import settings

        data = file.file.read(settings.max_upload_mb * 1024 * 1024 + 1)
        return images.add_image(db, complaint_id, user.id, file.filename, data)
    except images.ImageRejected as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


@router.get("/images/{image_id}/file")
def image_file(image_id: int, thumbnail: bool = False, user: User = Depends(acting_user), db: Session = Depends(get_db)):
    img, blob = images.image_bytes(db, image_id, thumbnail)
    _load_visible(db, img.complaint_id, user)
    return Response(content=blob, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})
