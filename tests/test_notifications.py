import pytest
from sqlalchemy import select

from app.core.enums import NotificationChannel as Ch, NotificationStatus as St, NotificationType as Nt
from app.models import Notification
from app.services import notification_service as ns
from tests.conftest import T0


class Boom(ns.Sender):
    channel = Ch.EMAIL

    def __init__(self):
        self.calls = 0

    def send(self, notification, user):
        self.calls += 1
        raise ConnectionError("smtp down")


def senders(**over):
    base = {Ch.IN_APP: ns.InAppSender(), Ch.EMAIL: ns.LogSender(Ch.EMAIL), Ch.PUSH: ns.LogSender(Ch.PUSH)}
    base.update(over)
    return base


def test_notify_creates_one_row_per_user_and_channel(db, users):
    rows = ns.notify(db, [users["admin"].id, users["admin"].id, users["faculty"].id], Nt.URGENT_ALERT, "t", "m", now=T0)
    assert len(rows) == 2 * 3  # duplicate user ids collapse; urgent = in_app + email + push
    assert {r.channel for r in rows} == {Ch.IN_APP, Ch.EMAIL, Ch.PUSH}
    assert all(r.status == St.PENDING for r in rows)


def test_dedupe_key_makes_notify_idempotent(db, users):
    a = ns.notify(db, [users["admin"].id], Nt.ESCALATION, "t", "m", dedupe_key="esc:1:L1", now=T0)
    b = ns.notify(db, [users["admin"].id], Nt.ESCALATION, "t", "m", dedupe_key="esc:1:L1", now=T0)
    db.commit()
    assert len(a) == 3 and b == []
    assert len(db.scalars(select(Notification)).all()) == 3


def test_dispatch_sends_and_marks_sent(db, users):
    ns.notify(db, [users["admin"].id], Nt.URGENT_ALERT, "Fire", "msg", now=T0)
    s = senders()
    res = ns.dispatch_pending(db, s, now=T0)
    assert (res.sent, res.failed) == (3, 0)
    assert all(n.status == St.SENT and n.sent_at is not None for n in db.scalars(select(Notification)))
    assert s[Ch.EMAIL].sent[0][1] == "admin@campusnova.edu" and s[Ch.PUSH].sent[0][1] == "tok-admin"
    assert ns.dispatch_pending(db, s, now=T0).sent == 0  # nothing left to send


def test_failed_delivery_is_retried_then_given_up(db, users):
    ns.notify(db, [users["admin"].id], Nt.STATUS_UPDATE, "t", "m", channels=[Ch.EMAIL], now=T0)
    boom = Boom()
    for attempt in (1, 2, 3):
        res = ns.dispatch_pending(db, senders(**{Ch.EMAIL: boom}), now=T0)
        assert res.failed == 1
    n = db.scalars(select(Notification)).one()
    assert (n.status, n.retry_count, "smtp down" in n.error_message) == (St.FAILED, 3, True)
    assert res.gave_up == 1
    assert ns.dispatch_pending(db, senders(**{Ch.EMAIL: boom}), now=T0).failed == 0  # no 4th attempt
    assert boom.calls == 3


def test_retry_can_succeed_later(db, users):
    ns.notify(db, [users["admin"].id], Nt.STATUS_UPDATE, "t", "m", channels=[Ch.EMAIL], now=T0)
    ns.dispatch_pending(db, senders(**{Ch.EMAIL: Boom()}), now=T0)
    res = ns.dispatch_pending(db, senders(), now=T0)
    n = db.scalars(select(Notification)).one()
    assert res.sent == 1 and n.status == St.SENT and n.error_message is None


def test_undeliverable_is_failed_immediately_and_never_retried(db, users):
    # admin2 has no email and no device token
    ns.notify(db, [users["admin2"].id], Nt.URGENT_ALERT, "t", "m", now=T0)
    res = ns.dispatch_pending(db, senders(), now=T0)
    by_channel = {n.channel: n for n in db.scalars(select(Notification))}
    assert by_channel[Ch.IN_APP].status == St.SENT
    assert by_channel[Ch.EMAIL].status == St.FAILED and "email" in by_channel[Ch.EMAIL].error_message
    assert by_channel[Ch.PUSH].status == St.FAILED and "device token" in by_channel[Ch.PUSH].error_message
    assert (res.sent, res.gave_up) == (1, 2)
    assert ns.dispatch_pending(db, senders(), now=T0).failed == 0


def test_inactive_recipient_is_skipped(db, users):
    users["admin"].is_active = False
    db.commit()
    ns.notify(db, [users["admin"].id], Nt.STATUS_UPDATE, "t", "m", now=T0)
    res = ns.dispatch_pending(db, senders(), now=T0)
    assert res.sent == 0 and res.gave_up == 2


def test_missing_sender_for_channel_is_permanent(db, users):
    ns.notify(db, [users["admin"].id], Nt.STATUS_UPDATE, "t", "m", channels=[Ch.PUSH], now=T0)
    assert ns.dispatch_pending(db, {Ch.IN_APP: ns.InAppSender()}, now=T0).gave_up == 1


# ---------------- real senders with fakes
class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.log = host, port, []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        self.log.append("starttls")

    def login(self, u, p):
        self.log.append(("login", u, p))

    def send_message(self, msg):
        self.log.append(("send", msg["To"], msg["Subject"], msg.get_content()))


def _notification(db, user, **kw):
    n = ns.notify(db, [user.id], kw.pop("ntype", Nt.URGENT_ALERT), "Sparks in lab", "Please act now", complaint_id=None,
                  channels=[kw.pop("channel", Ch.EMAIL)], now=T0)[0]
    return n


def test_email_sender_speaks_smtp(db, users):
    FakeSMTP.instances.clear()
    sender = ns.EmailSender("smtp.test", 587, "u", "p", "noreply@x.test", smtp_factory=FakeSMTP)
    sender.send(_notification(db, users["admin"]), users["admin"])
    log = FakeSMTP.instances[0].log
    assert log[0] == "starttls" and log[1] == ("login", "u", "p")
    kind, to, subject, body = log[2]
    assert (kind, to, subject) == ("send", "admin@campusnova.edu", "[CampusNova] Sparks in lab")
    assert "Please act now" in body and "Hello Admin" in body


def test_email_sender_errors(db, users):
    n = _notification(db, users["admin"])
    with pytest.raises(RuntimeError, match="SMTP is not configured"):
        ns.EmailSender().send(n, users["admin"])
    with pytest.raises(ns.PermanentDeliveryError):
        ns.EmailSender("h", smtp_factory=FakeSMTP).send(n, users["admin2"])


def test_email_sender_from_env(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "mail.test")
    monkeypatch.setenv("SMTP_PORT", "2525")
    monkeypatch.setenv("SMTP_TLS", "0")
    s = ns.EmailSender.from_env()
    assert (s.host, s.port, s.use_tls) == ("mail.test", 2525, False)


def test_fcm_sender_passes_a_push_with_string_data(db, users):
    calls = []
    n = _notification(db, users["admin"], channel=Ch.PUSH)
    ns.FCMSender(send_fn=lambda *a: calls.append(a)).send(n, users["admin"])
    token, title, body, data = calls[0]
    assert token == "tok-admin" and title == "Sparks in lab" and data["type"] == "urgent_alert"


def test_fcm_sender_without_token_is_permanent(db, users):
    n = _notification(db, users["staff"], channel=Ch.PUSH)
    with pytest.raises(ns.PermanentDeliveryError):
        ns.FCMSender(send_fn=lambda *a: None).send(n, users["staff"])


def test_fcm_dead_token_is_forgotten_and_not_retried(db, users):
    from app.core import firebase

    def dead(*a):
        raise firebase.InvalidDeviceToken("UNREGISTERED")

    n = _notification(db, users["admin"], channel=Ch.PUSH)
    with pytest.raises(ns.PermanentDeliveryError):
        ns.FCMSender(send_fn=dead).send(n, users["admin"])
    assert users["admin"].fcm_token is None


def test_preferences_switch_channels_off(db, users):
    users["faculty"].notification_prefs = {"email": False, "push": True, "in_app": True}
    users["faculty"].fcm_token = "tok-f"
    e = _notification(db, users["faculty"], channel=Ch.EMAIL)
    p = _notification(db, users["faculty"], channel=Ch.PUSH)
    sent = []

    class Rec(ns.Sender):
        def __init__(self, ch):
            self.channel = ch

        def send(self, n, u):
            sent.append(n.channel)

    out = ns.dispatch_pending(db, {Ch.EMAIL: Rec(Ch.EMAIL), Ch.PUSH: Rec(Ch.PUSH)})
    assert out.skipped == 1 and out.sent == 1 and sent == [Ch.PUSH]
    assert "preferences" in db.get(type(e), e.id).error_message


def test_build_senders_modes(monkeypatch):
    log = ns.build_senders("log")
    assert isinstance(log[Ch.EMAIL], ns.LogSender) and isinstance(log[Ch.PUSH], ns.LogSender)
    live = ns.build_senders("live")
    assert isinstance(live[Ch.EMAIL], ns.EmailSender) and isinstance(live[Ch.PUSH], ns.FCMSender)
    monkeypatch.setenv("CAMPUSNOVA_NOTIFY_MODE", "live")
    assert isinstance(ns.build_senders()[Ch.EMAIL], ns.EmailSender)


# ---------------- notification center
def test_inbox_unread_and_mark_read(db, users):
    ns.notify(db, [users["admin"].id], Nt.STATUS_UPDATE, "one", "m", now=T0)
    ns.notify(db, [users["admin"].id], Nt.STATUS_UPDATE, "two", "m", now=T0)
    ns.notify(db, [users["faculty"].id], Nt.STATUS_UPDATE, "other", "m", now=T0)
    db.commit()
    inbox = ns.list_for_user(db, users["admin"].id)
    assert [n.title for n in inbox] == ["two", "one"]  # newest first, in-app channel only
    assert ns.unread_count(db, users["admin"].id) == 2
    assert ns.mark_read(db, inbox[0].id, users["admin"].id, now=T0) is True
    assert ns.unread_count(db, users["admin"].id) == 1
    assert [n.title for n in ns.list_for_user(db, users["admin"].id, unread_only=True)] == ["one"]


def test_cannot_read_someone_elses_notification(db, users):
    n = ns.notify(db, [users["admin"].id], Nt.STATUS_UPDATE, "x", "m", channels=[Ch.IN_APP], now=T0)[0]
    db.commit()
    assert ns.mark_read(db, n.id, users["faculty"].id) is False
    assert ns.mark_read(db, 9999, users["admin"].id) is False
    assert ns.unread_count(db, users["admin"].id) == 1


def test_mark_all_read(db, users):
    for t in "abc":
        ns.notify(db, [users["admin"].id], Nt.STATUS_UPDATE, t, "m", now=T0)
    db.commit()
    assert ns.mark_all_read(db, users["admin"].id, now=T0) == 3
    assert ns.unread_count(db, users["admin"].id) == 0
    # dispatch must not resurrect read messages as unread
    ns.dispatch_pending(db, senders(), now=T0)
    assert ns.unread_count(db, users["admin"].id) == 0
