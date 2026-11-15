from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import acting_user
from app.db.session import get_db
from app.models import User
from app.schemas.notification import NotificationRead
from app.services import notification_service as ns

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationRead])
def inbox(unread_only: bool = False, limit: int = 50, user: User = Depends(acting_user), db: Session = Depends(get_db)):
    return ns.list_for_user(db, user.id, unread_only=unread_only, limit=min(max(limit, 1), 200))


@router.get("/unread-count")
def unread(user: User = Depends(acting_user), db: Session = Depends(get_db)):
    return {"unread": ns.unread_count(db, user.id)}


@router.post("/read-all")
def read_all(user: User = Depends(acting_user), db: Session = Depends(get_db)):
    return {"marked": ns.mark_all_read(db, user.id)}


@router.post("/{notification_id}/read")
def read_one(notification_id: int, user: User = Depends(acting_user), db: Session = Depends(get_db)):
    if not ns.mark_read(db, notification_id, user.id):
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"read": True}
