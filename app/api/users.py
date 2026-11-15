from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import acting_user, require_permission
from app.core.enums import UserRole
from app.db.session import get_db
from app.models import User
from app.schemas.auth import PasswordReset, UserCreate, UserRead, UserUpdate
from app.services import auth

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserRead])
def list_users(role: Optional[UserRole] = None, active: Optional[bool] = None, department_id: Optional[int] = None,
               _: User = Depends(require_permission("user:manage")), db: Session = Depends(get_db)):
    q = select(User).order_by(User.id)
    if role:
        q = q.where(User.role == role)
    if active is not None:
        q = q.where(User.is_active.is_(active))
    if department_id:
        q = q.where(User.department_id == department_id)
    return list(db.scalars(q))


@router.get("/workers", response_model=list[UserRead])
def workers(_: User = Depends(require_permission("complaint:assign")), db: Session = Depends(get_db)):
    """Active maintenance staff an admin can assign to."""
    return list(db.scalars(select(User).where(User.role == UserRole.MAINTENANCE, User.is_active.is_(True)).order_by(User.id)))


@router.post("", response_model=UserRead, status_code=201)
def create_user(body: UserCreate, _: User = Depends(require_permission("user:manage")), db: Session = Depends(get_db)):
    return auth.create_user(db, full_name=body.full_name, email=body.email, staff_id=body.staff_id, role=body.role,
                            password=body.password, department_id=body.department_id)


@router.patch("/{user_id}", response_model=UserRead)
def update_user(user_id: int, body: UserUpdate, actor: User = Depends(require_permission("user:manage")), db: Session = Depends(get_db)):
    fields = body.model_fields_set
    return auth.update_user(db, user_id, actor=actor, full_name=body.full_name, role=body.role, is_active=body.is_active,
                            department_id=body.department_id, set_department="department_id" in fields)


@router.post("/{user_id}/reset-password", response_model=UserRead)
def reset_password(user_id: int, body: PasswordReset, _: User = Depends(require_permission("user:manage")), db: Session = Depends(get_db)):
    return auth.reset_password(db, user_id, body.new_password)
