"""Real-integration checks: e-mail over an actual SMTP conversation, FCM HTTP v1 request shape, Firebase token flow."""
import json
import threading

import pytest

from app.core import firebase
from app.core.enums import NotificationChannel as Ch
from app.services import notification_service as ns
from tests.test_notifications import _notification


# ------------------------------------------------------------------ e-mail: a real SMTP server on localhost
@pytest.fixture()
def smtp_server():
    import socket

    pytest.importorskip("aiosmtpd")
    from aiosmtpd.controller import Controller

    with socket.socket() as probe:  # ask the OS for a free port
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]
    box = []

    class Handler:
        async def handle_DATA(self, server, session, envelope):
            box.append(envelope)
            return "250 OK"

    c = Controller(Handler(), hostname="127.0.0.1", port=free_port)
    c.start()
    yield free_port, box
    c.stop()


def test_email_is_really_delivered_over_smtp(db, users, smtp_server):
    port, box = smtp_server
    n = _notification(db, users["faculty"], channel=Ch.EMAIL)
    ns.EmailSender(host="127.0.0.1", port=port, sender="noreply@campusnova.edu", use_tls=False).send(n, users["faculty"])
    assert len(box) == 1
    mail = box[0]
    assert mail.rcpt_tos == [users["faculty"].email] and mail.mail_from == "noreply@campusnova.edu"
    body = mail.content.decode()
    assert "Subject: [CampusNova]" in body and "Sparks in lab" in body


def test_dispatch_job_delivers_email_end_to_end(db, users, smtp_server):
    port, box = smtp_server
    _notification(db, users["faculty"], channel=Ch.EMAIL)
    senders = {Ch.EMAIL: ns.EmailSender(host="127.0.0.1", port=port, use_tls=False)}
    assert ns.dispatch_pending(db, senders).sent == 1 and len(box) == 1


def test_unreachable_smtp_server_is_retried_then_given_up(db, users):
    n = _notification(db, users["faculty"], channel=Ch.EMAIL)
    senders = {Ch.EMAIL: ns.EmailSender(host="127.0.0.1", port=1, use_tls=False, timeout=2)}
    for _ in range(ns.MAX_RETRIES):
        ns.dispatch_pending(db, senders)
    db.refresh(n)
    assert n.status.value == "failed" and n.retry_count == ns.MAX_RETRIES and n.error_message
    assert ns.dispatch_pending(db, senders).failed == 0  # no more attempts after giving up


# ------------------------------------------------------------------ FCM HTTP v1
class FakeSession:
    def __init__(self, status=200, text='{"name": "projects/p/messages/1"}'):
        self.calls, self.status, self.text = [], status, text

    def post(self, url, json=None, timeout=None):
        self.calls.append((url, json))
        outer = self
        return type("R", (), {"status_code": outer.status, "text": outer.text, "json": lambda s: __import__("json").loads(outer.text)})()


def test_fcm_request_shape():
    s = FakeSession()
    name = firebase.send_push("device-token", "Title", "Body", {"complaint_id": 7}, session=s, pid="my-project", link="https://app/x")
    url, payload = s.calls[0]
    assert url == "https://fcm.googleapis.com/v1/projects/my-project/messages:send" and name.endswith("/1")
    m = payload["message"]
    assert m["token"] == "device-token" and m["notification"] == {"title": "Title", "body": "Body"}
    assert m["data"] == {"complaint_id": "7"} and m["webpush"]["fcm_options"]["link"] == "https://app/x"


def test_fcm_errors_are_classified():
    with pytest.raises(firebase.InvalidDeviceToken):
        firebase.send_push("t", "a", "b", session=FakeSession(404, '{"error": {"status": "NOT_FOUND", "details": "UNREGISTERED"}}'), pid="p")
    with pytest.raises(RuntimeError, match="FCM error 500"):
        firebase.send_push("t", "a", "b", session=FakeSession(500, "boom"), pid="p")


def test_push_needs_credentials_configured(monkeypatch):
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "p")
    monkeypatch.delenv("FIREBASE_CREDENTIALS_JSON", raising=False)
    with pytest.raises(firebase.FirebaseNotConfigured):
        firebase.send_push("t", "a", "b")


def test_service_account_credentials_are_parsed(monkeypatch):
    """A syntactically valid service-account key is accepted (a throw-away RSA key; nothing is sent)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    info = {"type": "service_account", "project_id": "p", "private_key_id": "x", "private_key": key,
            "client_email": "svc@p.iam.gserviceaccount.com", "client_id": "1", "token_uri": "https://oauth2.googleapis.com/token"}
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "p")
    monkeypatch.setenv("FIREBASE_CREDENTIALS_JSON", json.dumps(info))
    pid, session = firebase._session()
    assert pid == "p" and session is not None


# ------------------------------------------------------------------ Firebase ID tokens
def test_verify_id_token_accepts_good_and_rejects_bad(monkeypatch):
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "p")
    good = lambda tok, pid: {"sub": "uid1", "email": "a@x.t", "email_verified": True} if pid == "p" else {}
    assert firebase.verify_id_token("t", verify=good) == {"uid": "uid1", "email": "a@x.t"}
    with pytest.raises(ValueError):
        firebase.verify_id_token("t", verify=lambda t, p: {"email": "a@x.t"})  # no subject
    with pytest.raises(ValueError):
        firebase.verify_id_token("t", verify=lambda t, p: {"sub": "u", "email": "a@x.t", "email_verified": False})


def test_forged_firebase_token_is_rejected_by_the_real_verifier(monkeypatch):
    """No stub: google-auth itself must refuse a made-up token (it fails before any network call)."""
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "p")
    with pytest.raises(Exception):
        firebase.verify_id_token("not.a.realtoken", request=object())


def test_firebase_endpoint_uses_real_verifier_when_configured(client, monkeypatch):
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "p")
    r = client.post("/auth/firebase", json={"id_token": "forged-token-value"})
    assert r.status_code == 401  # verifier ran and refused


def test_firebase_endpoint_unconfigured_says_so(client, monkeypatch):
    monkeypatch.delenv("FIREBASE_PROJECT_ID", raising=False)
    r = client.post("/auth/firebase", json={"id_token": "forged-token-value"})
    assert r.status_code == 401 and "not configured" in r.json()["error"]["message"]
