"""Password hashing and JWT helpers (Chethana).

Passwords: scrypt (memory-hard, in the standard library) with a per-user random salt, stored as
`scrypt$N$r$p$salt_b64$hash_b64`. Verification is constant-time. We deliberately avoid extra dependencies.
Tokens: PyJWT, HS256, short-lived access token + rotating refresh token (the refresh `jti` is stored hashed).
"""
import base64
import hashlib
import hmac
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt

from app.core.config import settings

_N, _R, _P = 2 ** 14, 8, 1
_MAXMEM = 64 * 1024 * 1024
MIN_PASSWORD = 8


def validate_password_strength(password: str, *, email: str = "") -> Optional[str]:
    """Return a human-readable problem, or None if the password is acceptable."""
    if len(password) < MIN_PASSWORD:
        return f"Password must be at least {MIN_PASSWORD} characters."
    if len(password) > 128:
        return "Password must be at most 128 characters."
    if not (re.search(r"[A-Za-z]", password) and re.search(r"\d", password)):
        return "Password must contain at least one letter and one digit."
    if email and email.split("@")[0].lower() in password.lower() and len(email.split("@")[0]) >= 4:
        return "Password must not contain your email name."
    if password.lower() in {"password1", "password123", "12345678a", "qwerty123", "admin123"}:
        return "That password is too common."
    return None


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, maxmem=_MAXMEM, dklen=32)
    b64 = lambda b: base64.b64encode(b).decode()
    return f"scrypt${_N}${_R}${_P}${b64(salt)}${b64(digest)}"


def verify_password(password: str, stored: Optional[str]) -> bool:
    if not stored:
        hash_password("dummy")  # keep timing similar for accounts without a password
        return False
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest)
        got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                             maxmem=_MAXMEM, dklen=len(expected))
        return hmac.compare_digest(got, expected)
    except Exception:
        return False


def hash_token_id(jti: str) -> str:
    return hashlib.sha256(jti.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_token(user_id: int, role: str, token_type: str, *, expires: timedelta, now: Optional[datetime] = None) -> tuple[str, str, datetime]:
    now = now or _now()
    jti = uuid.uuid4().hex
    exp = now + expires
    payload = {"sub": str(user_id), "role": role, "type": token_type, "jti": jti, "iat": int(now.timestamp()), "exp": int(exp.timestamp())}
    return jwt.encode(payload, settings.secret_key, algorithm="HS256"), jti, exp


def decode_token(token: str, expected_type: str) -> dict:
    """Raises jwt.InvalidTokenError for anything wrong: bad signature, expired, wrong type, malformed."""
    payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"], options={"require": ["exp", "sub", "type", "jti"]})
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError("wrong token type")
    return payload


def random_password(n: int = 12) -> str:
    return secrets.token_urlsafe(n)[:n] + "a1"
