"""Authentication and user management (Chethana): login with lockout, rotating refresh tokens, logout, password
change, Firebase hook, and admin user management."""
from datetime import datetime, timedelta
from typing import Optional

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import UserRole
from app.core.security import (create_token, decode_token, hash_password, hash_token_id, validate_password_strength,
                               verify_password)
from app.core.timeutil import ensure_utc, utcnow
from app.models import Department, RefreshToken, User
from app.services.common import BusinessRuleError, NotFoundError


class AuthError(Exception):
    """Bad credentials / token (maps to 401)."""


class AccountLocked(AuthError):
    def __init__(self, until: datetime):
        super().__init__("Too many failed attempts. Try again later.")
        self.until = until


def _normalise_email(email: str) -> str:
    return (email or "").strip().lower()


def _issue_tokens(db: Session, user: User, now: datetime) -> dict:
    access, _, access_exp = create_token(user.id, user.role.value, "access", expires=timedelta(minutes=settings.access_token_minutes), now=now)
    refresh, jti, refresh_exp = create_token(user.id, user.role.value, "refresh", expires=timedelta(days=settings.refresh_token_days), now=now)
    db.add(RefreshToken(user_id=user.id, jti_hash=hash_token_id(jti), expires_at=refresh_exp.replace(tzinfo=None), created_at=now))
    return {"access_token": access, "refresh_token": refresh, "token_type": "bearer",
            "expires_in": settings.access_token_minutes * 60}


def login(db: Session, email: str, password: str, now: Optional[datetime] = None) -> tuple[User, dict]:
    now = now or utcnow()
    user = db.scalar(select(User).where(User.email == _normalise_email(email)))
    if user is None:
        verify_password(password, None)  # same cost whether or not the account exists
        raise AuthError("Invalid email or password.")
    if user.locked_until is not None and ensure_utc(user.locked_until) > now:
        raise AccountLocked(ensure_utc(user.locked_until))
    if not user.is_active:
        raise AuthError("Invalid email or password.")  # do not reveal that the account exists but is disabled
    if not verify_password(password, user.password_hash):
        user.failed_login_count = (user.failed_login_count or 0) + 1
        if user.failed_login_count >= settings.max_failed_logins:
            user.locked_until = (now + timedelta(minutes=settings.lockout_minutes)).replace(tzinfo=None)
            user.failed_login_count = 0
            db.commit()
            raise AccountLocked(ensure_utc(user.locked_until))
        db.commit()
        raise AuthError("Invalid email or password.")
    user.failed_login_count, user.locked_until, user.last_login_at = 0, None, now.replace(tzinfo=None)
    tokens = _issue_tokens(db, user, now)
    db.commit()
    return user, tokens


def refresh(db: Session, refresh_token: str, now: Optional[datetime] = None) -> dict:
    """Exchange a refresh token for a new pair. The old one is revoked; presenting it again revokes the whole family
    (a sign it was stolen)."""
    now = now or utcnow()
    try:
        payload = decode_token(refresh_token, "refresh")
    except jwt.InvalidTokenError:
        raise AuthError("Invalid or expired refresh token.")
    row = db.scalar(select(RefreshToken).where(RefreshToken.jti_hash == hash_token_id(payload["jti"])))
    if row is None:
        raise AuthError("Invalid or expired refresh token.")
    if row.revoked_at is not None:
        for other in db.scalars(select(RefreshToken).where(RefreshToken.user_id == row.user_id, RefreshToken.revoked_at.is_(None))):
            other.revoked_at = now.replace(tzinfo=None)
        db.commit()
        raise AuthError("This refresh token was already used. Please sign in again.")
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise AuthError("Invalid or expired refresh token.")
    tokens = _issue_tokens(db, user, now)
    new_payload = decode_token(tokens["refresh_token"], "refresh")
    row.revoked_at, row.replaced_by_hash = now.replace(tzinfo=None), hash_token_id(new_payload["jti"])
    db.commit()
    return tokens


def logout(db: Session, refresh_token: str, now: Optional[datetime] = None) -> None:
    now = now or utcnow()
    try:
        payload = decode_token(refresh_token, "refresh")
    except jwt.InvalidTokenError:
        return  # logging out with a bad token is a no-op
    row = db.scalar(select(RefreshToken).where(RefreshToken.jti_hash == hash_token_id(payload["jti"])))
    if row and row.revoked_at is None:
        row.revoked_at = now.replace(tzinfo=None)
        db.commit()


def revoke_all(db: Session, user_id: int, now: Optional[datetime] = None) -> int:
    now = (now or utcnow()).replace(tzinfo=None)
    n = 0
    for row in db.scalars(select(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))):
        row.revoked_at, n = now, n + 1
    return n


def user_from_access_token(db: Session, token: str) -> User:
    try:
        payload = decode_token(token, "access")
    except jwt.InvalidTokenError:
        raise AuthError("Invalid or expired token.")
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise AuthError("Invalid or expired token.")
    if user.role.value != payload.get("role"):
        raise AuthError("Your role changed; please sign in again.")
    return user


def change_password(db: Session, user: User, current: str, new: str) -> None:
    if not verify_password(current, user.password_hash):
        raise AuthError("Current password is incorrect.")
    problem = validate_password_strength(new, email=user.email)
    if problem:
        raise BusinessRuleError(problem)
    if verify_password(new, user.password_hash):
        raise BusinessRuleError("The new password must be different from the current one.")
    user.password_hash = hash_password(new)
    revoke_all(db, user.id)  # other devices must sign in again
    db.commit()


def login_with_firebase(db: Session, id_token: str, verifier=None) -> tuple[User, dict]:
    """Sign in with a Firebase ID token. `verifier(id_token) -> {"uid", "email"}` is injected (firebase-admin in
    production, a stub in tests). The account must already exist (created by an admin) and is matched by UID or email."""
    if verifier is None:
        raise AuthError("Firebase sign-in is not configured on this server.")
    try:
        claims = verifier(id_token)
    except Exception:
        raise AuthError("Invalid Firebase token.")
    user = db.scalar(select(User).where(User.firebase_uid == claims["uid"]))
    if user is None and claims.get("email"):
        user = db.scalar(select(User).where(User.email == _normalise_email(claims["email"])))
        if user is not None and not user.firebase_uid:
            user.firebase_uid = claims["uid"]
    if user is None or not user.is_active:
        raise AuthError("No active account for this Firebase user.")
    tokens = _issue_tokens(db, user, utcnow())
    user.last_login_at = utcnow().replace(tzinfo=None)
    db.commit()
    return user, tokens


# ------------------------------------------------------------------------------------------ user management
def create_user(db: Session, *, full_name: str, email: str, staff_id: str, role: UserRole, password: Optional[str],
                department_id: Optional[int] = None) -> User:
    email = _normalise_email(email)
    full_name, staff_id = (full_name or "").strip(), (staff_id or "").strip()
    if not full_name or not staff_id or "@" not in email:
        raise BusinessRuleError("Name, staff id and a valid email are required.")
    if db.scalar(select(User).where(User.email == email)):
        raise BusinessRuleError("An account with this email already exists.")
    if db.scalar(select(User).where(User.staff_id == staff_id)):
        raise BusinessRuleError("An account with this staff id already exists.")
    if department_id is not None and db.get(Department, department_id) is None:
        raise NotFoundError(f"department {department_id} not found")
    if password is not None:
        problem = validate_password_strength(password, email=email)
        if problem:
            raise BusinessRuleError(problem)
    u = User(full_name=full_name, email=email, staff_id=staff_id, role=role, department_id=department_id,
             password_hash=hash_password(password) if password else None, is_active=True)
    db.add(u)
    db.commit()
    return u


def update_user(db: Session, user_id: int, *, actor: User, full_name=None, role: Optional[UserRole] = None,
                department_id=None, is_active: Optional[bool] = None, set_department=False) -> User:
    u = db.get(User, user_id)
    if u is None:
        raise NotFoundError(f"user {user_id} not found")
    if u.id == actor.id and (is_active is False or (role is not None and role != u.role)):
        raise BusinessRuleError("You cannot disable or change the role of your own account.")
    if full_name is not None:
        u.full_name = full_name.strip() or u.full_name
    if set_department:
        if department_id is not None and db.get(Department, department_id) is None:
            raise NotFoundError(f"department {department_id} not found")
        u.department_id = department_id
    if role is not None and role != u.role:
        u.role = role
        revoke_all(db, u.id)
    if is_active is not None and is_active != u.is_active:
        u.is_active = is_active
        if not is_active:
            revoke_all(db, u.id)
    db.commit()
    return u


def reset_password(db: Session, user_id: int, new_password: str) -> User:
    u = db.get(User, user_id)
    if u is None:
        raise NotFoundError(f"user {user_id} not found")
    problem = validate_password_strength(new_password, email=u.email)
    if problem:
        raise BusinessRuleError(problem)
    u.password_hash, u.failed_login_count, u.locked_until = hash_password(new_password), 0, None
    revoke_all(db, u.id)
    db.commit()
    return u
