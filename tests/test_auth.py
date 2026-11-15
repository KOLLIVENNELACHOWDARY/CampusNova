"""Authentication, token handling, lockout, RBAC and the security 'pen test' cases (Chethana)."""
import base64
import json
from datetime import timedelta

import jwt
import pytest

from app.core import security
from app.core.config import settings
from app.core.enums import UserRole
from app.core.permissions import PERMISSIONS, has_permission
from app.core.timeutil import utcnow
from tests.conftest import PASSWORD, login

EMAIL = "faculty.cse@campusnova.edu"


# ------------------------------------------------------------------ passwords
def test_password_hash_is_salted_and_verifies():
    a, b = security.hash_password("Secret123"), security.hash_password("Secret123")
    assert a != b and a.startswith("scrypt$")
    assert security.verify_password("Secret123", a) and not security.verify_password("secret123", a)
    assert not security.verify_password("x", None) and not security.verify_password("x", "garbage")


@pytest.mark.parametrize("pw,ok", [("short1", False), ("allletters", False), ("12345678", False), ("Passw0rdOK", True), ("a" * 200 + "1", False)])
def test_password_strength(pw, ok):
    assert (security.validate_password_strength(pw) is None) == ok


# ------------------------------------------------------------------ login / refresh / logout
def test_login_returns_tokens_and_user(client):
    body = login(client, EMAIL)
    assert body["token_type"] == "bearer" and body["user"]["email"] == EMAIL and "password_hash" not in json.dumps(body)
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200 and me.json()["role"] == "faculty"


def test_email_is_case_insensitive(client):
    assert client.post("/auth/login", json={"email": EMAIL.upper(), "password": PASSWORD}).status_code == 200


def test_wrong_password_and_unknown_user_look_the_same(client):
    a = client.post("/auth/login", json={"email": EMAIL, "password": "Wrong123"})
    b = client.post("/auth/login", json={"email": "nobody@x.test", "password": "Wrong123"})
    assert a.status_code == b.status_code == 401 and a.json()["error"]["message"] == b.json()["error"]["message"]


def test_account_locks_after_repeated_failures_then_unlocks(client, db, users):
    for _ in range(settings.max_failed_logins - 1):
        assert client.post("/auth/login", json={"email": EMAIL, "password": "Wrong123"}).status_code == 401
    last = client.post("/auth/login", json={"email": EMAIL, "password": "Wrong123"})
    assert last.status_code == 423 and last.json()["error"]["code"] == "account_locked"
    assert client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD}).status_code == 423  # even the right password
    db.refresh(users["faculty"])
    users["faculty"].locked_until = utcnow().replace(tzinfo=None) - timedelta(minutes=1)
    db.commit()
    assert client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD}).status_code == 200


def test_successful_login_resets_the_failure_counter(client):
    for _ in range(settings.max_failed_logins - 1):
        client.post("/auth/login", json={"email": EMAIL, "password": "Wrong123"})
    assert client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD}).status_code == 200
    for _ in range(settings.max_failed_logins - 1):
        assert client.post("/auth/login", json={"email": EMAIL, "password": "Wrong123"}).status_code == 401


def test_disabled_account_cannot_sign_in_and_old_tokens_stop_working(client, auth, users):
    h = auth(users["faculty"])
    assert client.get("/auth/me", headers=h).status_code == 200
    assert client.patch(f"/users/{users['faculty'].id}", json={"is_active": False}, headers=auth(users["admin"])).status_code == 200
    assert client.get("/auth/me", headers=h).status_code == 401
    assert client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD}).status_code == 401


def test_refresh_rotates_and_reuse_revokes_the_family(client):
    first = login(client, EMAIL)
    second = client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert second.status_code == 200 and second.json()["refresh_token"] != first["refresh_token"]
    reuse = client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})  # stolen / replayed
    assert reuse.status_code == 401
    assert client.post("/auth/refresh", json={"refresh_token": second.json()["refresh_token"]}).status_code == 401  # family revoked


def test_logout_revokes_the_refresh_token(client):
    t = login(client, EMAIL)
    assert client.post("/auth/logout", json={"refresh_token": t["refresh_token"]}).status_code == 204
    assert client.post("/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code == 401
    assert client.post("/auth/logout", json={"refresh_token": "not-a-token"}).status_code == 204  # harmless


def test_access_and_refresh_tokens_are_not_interchangeable(client):
    t = login(client, EMAIL)
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {t['refresh_token']}"}).status_code == 401
    assert client.post("/auth/refresh", json={"refresh_token": t["access_token"]}).status_code == 401


def test_change_password(client, auth, users):
    h = auth(users["faculty"])
    assert client.post("/auth/change-password", json={"current_password": "Wrong123", "new_password": "NewPass123"}, headers=h).status_code == 401
    assert client.post("/auth/change-password", json={"current_password": PASSWORD, "new_password": "weak"}, headers=h).status_code == 409
    assert client.post("/auth/change-password", json={"current_password": PASSWORD, "new_password": PASSWORD}, headers=h).status_code == 409
    assert client.post("/auth/change-password", json={"current_password": PASSWORD, "new_password": "NewPass123"}, headers=h).status_code == 204
    assert client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD}).status_code == 401
    assert client.post("/auth/login", json={"email": EMAIL, "password": "NewPass123"}).status_code == 200


def test_notification_preferences_roundtrip(client, auth, users):
    h = auth(users["faculty"])
    assert client.get("/auth/me/notification-preferences", headers=h).json()["email"] is True
    r = client.put("/auth/me/notification-preferences", json={"email": False, "push": True, "in_app": True, "fcm_token": "tok-1"}, headers=h)
    assert r.status_code == 200
    assert client.get("/auth/me/notification-preferences", headers=h).json() == {"email": False, "push": True, "in_app": True, "fcm_token": "tok-1"}


def test_firebase_login_hook(client, db, users, monkeypatch):
    from app.api import auth as auth_api

    assert client.post("/auth/firebase", json={"id_token": "x" * 20}).status_code == 401  # not configured
    auth_api.set_firebase_verifier(lambda tok: {"uid": "fb-1", "email": EMAIL} if tok == "good-token-123" else (_ for _ in ()).throw(ValueError()))
    try:
        assert client.post("/auth/firebase", json={"id_token": "bad-token-123"}).status_code == 401
        ok = client.post("/auth/firebase", json={"id_token": "good-token-123"})
        assert ok.status_code == 200 and ok.json()["user"]["email"] == EMAIL
        db.refresh(users["faculty"])
        assert users["faculty"].firebase_uid == "fb-1"  # linked on first sign-in
    finally:
        auth_api.set_firebase_verifier(None)


# ------------------------------------------------------------------ user management
def test_admin_manages_users(client, auth, users):
    h = auth(users["admin"])
    body = {"full_name": "New Worker", "email": "new.worker@campusnova.edu", "staff_id": "MNT100", "role": "maintenance",
            "department_id": users["civil"].department_id, "password": "Worker123"}
    r = client.post("/users", json=body, headers=h)
    assert r.status_code == 201 and "password" not in r.json()
    assert client.post("/users", json=body, headers=h).status_code == 409  # duplicate email
    assert client.post("/users", json={**body, "email": "x@y.z", "staff_id": "MNT101", "password": "weak"}, headers=h).status_code == 409
    assert client.post("/auth/login", json={"email": body["email"], "password": body["password"]}).status_code == 200
    assert any(u["staff_id"] == "MNT100" for u in client.get("/users", params={"role": "maintenance"}, headers=h).json())
    assert client.post(f"/users/{r.json()['id']}/reset-password", json={"new_password": "Reset12345"}, headers=h).status_code == 200


def test_admin_cannot_lock_themselves_out(client, auth, users):
    h = auth(users["admin"])
    assert client.patch(f"/users/{users['admin'].id}", json={"is_active": False}, headers=h).status_code == 409
    assert client.patch(f"/users/{users['admin'].id}", json={"role": "faculty"}, headers=h).status_code == 409


def test_role_change_invalidates_existing_tokens(client, auth, users):
    h = auth(users["faculty"])
    assert client.patch(f"/users/{users['faculty'].id}", json={"role": "staff"}, headers=auth(users["admin"])).status_code == 200
    assert client.get("/auth/me", headers=h).status_code == 401  # token carries the old role


# ------------------------------------------------------------------ RBAC
def test_permission_table_is_sane():
    assert has_permission(UserRole.ADMIN, "complaint:assign") and not has_permission(UserRole.FACULTY, "complaint:assign")
    assert not has_permission("nonsense", "complaint:assign") and not has_permission(UserRole.ADMIN, "does:not:exist")
    for perm, roles in PERMISSIONS.items():
        assert roles, f"{perm} is granted to nobody"


PROTECTED = [("get", "/auth/me"), ("get", "/users"), ("get", "/complaints"), ("post", "/complaints"), ("get", "/complaints/pool"),
             ("get", "/complaints/1"), ("post", "/complaints/1/assign"), ("post", "/complaints/1/status"), ("get", "/notifications"),
             ("get", "/dashboard/admin"), ("get", "/ai/reviews"), ("post", "/priority/evaluate"), ("post", "/admin/jobs/dispatch"),
             ("get", "/routing-rules"), ("put", "/routing-rules/electrical")]


@pytest.mark.parametrize("method,path", PROTECTED)
def test_every_protected_endpoint_requires_sign_in(client, method, path):
    r = client.request(method.upper(), path, json={})
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"


ADMIN_ONLY = [("get", "/users"), ("get", "/dashboard/admin"), ("get", "/dashboard/institution"), ("get", "/dashboard/emergencies"),
              ("get", "/dashboard/ai-performance"), ("get", "/ai/reviews"), ("post", "/admin/jobs/sla-check"),
              ("post", "/admin/jobs/auto-assign"), ("post", "/admin/jobs/dispatch"), ("put", "/routing-rules/electrical")]


@pytest.mark.parametrize("who", ["faculty", "incharge", "staff", "electrician"])
@pytest.mark.parametrize("method,path", ADMIN_ONLY)
def test_admin_endpoints_reject_everyone_else(client, auth, users, who, method, path):
    r = client.request(method.upper(), path, json={}, headers=auth(users[who]))
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"


# ------------------------------------------------------------------ pen-test style cases
def _forge(payload: dict, key: str = "wrong-key-wrong-key-123") -> str:
    return jwt.encode(payload, key, algorithm="HS256")


def test_forged_expired_and_malformed_tokens_are_rejected(client, users):
    now = int(utcnow().timestamp())
    base = {"sub": str(users["admin"].id), "role": "admin", "type": "access", "jti": "x", "iat": now, "exp": now + 600}
    bad = {
        "wrong signature": _forge(base),
        "expired": jwt.encode({**base, "exp": now - 10}, settings.secret_key, algorithm="HS256"),
        "no exp": jwt.encode({k: v for k, v in base.items() if k != "exp"}, settings.secret_key, algorithm="HS256"),
        "garbage": "abc.def.ghi",
        "empty": "",
    }
    header = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=").decode()
    body = base64.urlsafe_b64encode(json.dumps(base).encode()).rstrip(b"=").decode()
    bad["alg none"] = f"{header}.{body}."
    for name, token in bad.items():
        r = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401, name


def test_role_claim_cannot_be_escalated_by_a_valid_signature_with_a_stale_role(client, users):
    now = int(utcnow().timestamp())
    token = jwt.encode({"sub": str(users["faculty"].id), "role": "admin", "type": "access", "jti": "x", "iat": now, "exp": now + 600},
                       settings.secret_key, algorithm="HS256")
    assert client.get("/users", headers={"Authorization": f"Bearer {token}"}).status_code == 401  # role must match the database


@pytest.mark.parametrize("header", ["", "Bearer", "Bearer ", "Basic abc", "bearer   ", "Token abc"])
def test_malformed_authorization_headers(client, header):
    assert client.get("/auth/me", headers={"Authorization": header}).status_code == 401


@pytest.mark.parametrize("payload", ["' OR '1'='1", "admin@campusnova.edu' --", "\" OR \"\"=\"", "'; DROP TABLE users; --"])
def test_sql_injection_in_login_does_nothing(client, db, payload):
    assert client.post("/auth/login", json={"email": payload, "password": payload}).status_code == 401
    assert client.post("/auth/login", json={"email": EMAIL, "password": payload}).status_code == 401
    assert client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD}).status_code == 200  # tables intact


def test_security_headers_present(client):
    r = client.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert "default-src 'none'" in r.headers["content-security-policy"]


def test_cors_only_allows_configured_origins(client):
    ok = client.options("/health", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    bad = client.options("/health", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-origin" not in bad.headers


def test_password_never_appears_in_any_response(client, auth, users):
    h = auth(users["admin"])
    blob = client.get("/users", headers=h).text + client.get("/auth/me", headers=h).text
    assert "password" not in blob.lower() and "scrypt" not in blob


def test_reporter_identity_comes_from_the_token_not_the_body(client, auth, users):
    r = client.post("/complaints", headers=auth(users["faculty"]), json={
        "block": "A", "floor": "1", "description": "Fan not working in the classroom", "reported_by": users["admin"].id})
    assert r.status_code == 201 and r.json()["reported_by"] == users["faculty"].id
