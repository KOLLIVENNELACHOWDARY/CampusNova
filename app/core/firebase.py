"""Firebase integration without the heavy firebase-admin package (it would not fit a Vercel function comfortably).

* `verify_id_token`  — checks a Firebase Authentication ID token with Google's public keys (google-auth).
* `send_push`        — sends a Cloud Messaging (FCM HTTP v1) message with a service-account access token.

Configuration (server side only, never in the browser):
    FIREBASE_PROJECT_ID          your Firebase project id
    FIREBASE_CREDENTIALS_JSON    the service-account key JSON as a single string (needed for push)
Both functions take their network dependencies as arguments so tests can supply fakes.
"""
import json
import os
from typing import Callable, Optional

FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"


class FirebaseNotConfigured(RuntimeError):
    pass


def project_id() -> str:
    pid = os.getenv("FIREBASE_PROJECT_ID", "")
    if not pid:
        raise FirebaseNotConfigured("FIREBASE_PROJECT_ID is not set")
    return pid


def verify_id_token(id_token: str, *, request=None, verify: Optional[Callable] = None) -> dict:
    """Return {"uid", "email"} for a valid Firebase ID token; raise on anything else (expired, wrong project, forged)."""
    pid = project_id()
    if verify is None:
        from google.auth.transport import requests as g_requests
        from google.oauth2 import id_token as g_id_token

        request = request or g_requests.Request()
        claims = g_id_token.verify_firebase_token(id_token, request, audience=pid)
    else:
        claims = verify(id_token, pid)
    if not claims or not claims.get("sub"):
        raise ValueError("token has no subject")
    if claims.get("email") and claims.get("email_verified") is False:
        raise ValueError("e-mail address is not verified")
    return {"uid": claims["sub"], "email": claims.get("email")}


def _session():
    pid = project_id()
    raw = os.getenv("FIREBASE_CREDENTIALS_JSON", "")
    if not raw:
        raise FirebaseNotConfigured("FIREBASE_CREDENTIALS_JSON is not set (push needs a service-account key)")
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2 import service_account

    creds = service_account.Credentials.from_service_account_info(json.loads(raw), scopes=[FCM_SCOPE])
    return pid, AuthorizedSession(creds)


def build_message(token: str, title: str, body: str, data: Optional[dict] = None, link: Optional[str] = None) -> dict:
    message = {"token": token, "notification": {"title": title[:200], "body": body[:500]},
               "data": {k: str(v) for k, v in (data or {}).items()}}
    if link:
        message["webpush"] = {"fcm_options": {"link": link}}
    return {"message": message}


class InvalidDeviceToken(Exception):
    """FCM says the device token is no longer valid (app uninstalled / token rotated): do not retry."""


def send_push(token: str, title: str, body: str, data: Optional[dict] = None, *, session=None, pid: Optional[str] = None,
              link: Optional[str] = None, timeout: int = 15) -> str:
    if session is None:
        pid, session = _session()
    pid = pid or project_id()
    resp = session.post(f"https://fcm.googleapis.com/v1/projects/{pid}/messages:send",
                        json=build_message(token, title, body, data, link), timeout=timeout)
    if resp.status_code in (400, 404) and any(k in resp.text for k in ("UNREGISTERED", "INVALID_ARGUMENT", "NOT_FOUND")):
        raise InvalidDeviceToken(resp.text[:200])
    if resp.status_code >= 300:
        raise RuntimeError(f"FCM error {resp.status_code}: {resp.text[:200]}")
    return resp.json().get("name", "")
