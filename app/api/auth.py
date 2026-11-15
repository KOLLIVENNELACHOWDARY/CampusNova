from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import acting_user
from app.db.session import get_db
from app.models import User
from app.schemas.auth import (ChangePasswordRequest, FirebaseLoginRequest, LoginRequest, LoginResponse, NotificationPrefs,
                              RefreshRequest, TokenPair, UserRead)
from app.services import auth

router = APIRouter(prefix="/auth", tags=["auth"])

_firebase_verifier = None  # set by app.main when firebase-admin is configured (and by tests)


def set_firebase_verifier(fn):
    global _firebase_verifier
    _firebase_verifier = fn


def _wrap(fn, *args):
    try:
        return fn(*args)
    except auth.AccountLocked as e:
        raise HTTPException(status_code=423, detail=str(e))
    except auth.AuthError as e:
        raise HTTPException(status_code=401, detail=str(e), headers={"WWW-Authenticate": "Bearer"})


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user, tokens = _wrap(auth.login, db, body.email, body.password)
    return {**tokens, "user": user}


def _default_verifier():
    """The real Firebase verifier, available once FIREBASE_PROJECT_ID is configured."""
    import os

    if not os.getenv("FIREBASE_PROJECT_ID"):
        return None
    from app.core import firebase

    return firebase.verify_id_token


@router.post("/firebase", response_model=LoginResponse)
def firebase_login(body: FirebaseLoginRequest, db: Session = Depends(get_db)):
    user, tokens = _wrap(auth.login_with_firebase, db, body.id_token, _firebase_verifier or _default_verifier())
    return {**tokens, "user": user}


@router.post("/refresh", response_model=TokenPair)
def refresh(body: RefreshRequest, db: Session = Depends(get_db)):
    return _wrap(auth.refresh, db, body.refresh_token)


@router.post("/logout", status_code=204)
def logout(body: RefreshRequest, db: Session = Depends(get_db)):
    auth.logout(db, body.refresh_token)


@router.get("/me", response_model=UserRead)
def me(user: User = Depends(acting_user)):
    return user


@router.post("/change-password", status_code=204)
def change_password(body: ChangePasswordRequest, user: User = Depends(acting_user), db: Session = Depends(get_db)):
    _wrap(auth.change_password, db, user, body.current_password, body.new_password)


@router.put("/me/notification-preferences", response_model=NotificationPrefs)
def set_prefs(body: NotificationPrefs, user: User = Depends(acting_user), db: Session = Depends(get_db)):
    user.notification_prefs = {"email": body.email, "push": body.push, "in_app": body.in_app}
    if body.fcm_token is not None:
        user.fcm_token = body.fcm_token or None
    db.commit()
    return body


@router.get("/me/notification-preferences", response_model=NotificationPrefs)
def get_prefs(user: User = Depends(acting_user)):
    prefs = user.notification_prefs or {}
    return NotificationPrefs(email=prefs.get("email", True), push=prefs.get("push", True), in_app=prefs.get("in_app", True),
                             fcm_token=user.fcm_token)
