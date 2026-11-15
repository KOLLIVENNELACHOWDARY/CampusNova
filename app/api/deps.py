"""Request authentication and RBAC (Chethana).

`acting_user` = the signed-in user, from `Authorization: Bearer <access token>`.
`require_permission("x")` builds a dependency that also checks the role-permission map in `app.core.permissions`.
"""
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.enums import UserRole
from app.core.permissions import has_permission
from app.db.session import get_db
from app.models import User
from app.services import auth


def acting_user(authorization: str = Header(default="", alias="Authorization"), db: Session = Depends(get_db)) -> User:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Sign in required", headers={"WWW-Authenticate": "Bearer"})
    try:
        return auth.user_from_access_token(db, token.strip())
    except auth.AuthError as e:
        raise HTTPException(status_code=401, detail=str(e), headers={"WWW-Authenticate": "Bearer"})


def require_permission(permission: str):
    def dependency(user: User = Depends(acting_user)) -> User:
        if not has_permission(user.role, permission):
            raise HTTPException(status_code=403, detail="You do not have permission to do this")
        return user

    dependency.__name__ = f"require_{permission.replace(':', '_')}"
    return dependency


def require_admin(user: User = Depends(acting_user)) -> User:
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
