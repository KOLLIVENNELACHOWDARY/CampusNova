"""Notifications: creation, delivery (in-app / email via SMTP / push via Firebase Cloud Messaging) and the inbox.

Flow: business code calls `notify(...)` which only INSERTS rows (status PENDING). A background job calls
`dispatch_pending(...)` which delivers them through the right sender, records SENT/FAILED, and retries failures.
Keeping creation and delivery apart means a slow or broken mail server can never block a complaint from being filed.

Delivery modes (env CAMPUSNOVA_NOTIFY_MODE):
    log   (default) email and push are written to the log only: safe for development and demos
    live  email uses SMTP_* settings, push uses firebase-admin (GOOGLE_APPLICATION_CREDENTIALS)
"""
import logging
import os
import smtplib
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from typing import Iterable, Optional

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.enums import NotificationChannel, NotificationStatus, NotificationType
from app.core.timeutil import utcnow
from app.models import Notification, User

logger = logging.getLogger("campusnova.notify")

MAX_RETRIES = 3

# Which channels each kind of message uses.
DEFAULT_CHANNELS: dict[NotificationType, list[NotificationChannel]] = {
    NotificationType.STATUS_UPDATE: [NotificationChannel.IN_APP, NotificationChannel.EMAIL],
    NotificationType.ASSIGNMENT: [NotificationChannel.IN_APP, NotificationChannel.EMAIL, NotificationChannel.PUSH],
    NotificationType.URGENT_ALERT: [NotificationChannel.IN_APP, NotificationChannel.EMAIL, NotificationChannel.PUSH],
    NotificationType.SLA_WARNING: [NotificationChannel.IN_APP, NotificationChannel.EMAIL, NotificationChannel.PUSH],
    NotificationType.ESCALATION: [NotificationChannel.IN_APP, NotificationChannel.EMAIL, NotificationChannel.PUSH],
}


class PermanentDeliveryError(Exception):
    """Retrying cannot help (no email address, no device token, inactive user)."""


# ----------------------------------------------------------------------------------------- senders
class Sender:
    channel: NotificationChannel

    def send(self, notification: Notification, user: User) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class InAppSender(Sender):
    """In-app messages are already visible in the notification center once the row exists."""

    channel = NotificationChannel.IN_APP

    def send(self, notification, user):
        return None


class LogSender(Sender):
    """Development sender: records what would have been sent instead of contacting a provider."""

    def __init__(self, channel: NotificationChannel):
        self.channel = channel
        self.sent: list[tuple[int, str, str]] = []

    def send(self, notification, user):
        target = user.email if self.channel == NotificationChannel.EMAIL else (user.fcm_token or "no-device-token")
        if self.channel == NotificationChannel.EMAIL and not user.email:
            raise PermanentDeliveryError("user has no email address")
        if self.channel == NotificationChannel.PUSH and not user.fcm_token:
            raise PermanentDeliveryError("user has no registered device token")
        self.sent.append((notification.id, target, notification.title))
        logger.info("[%s simulated] to=%s title=%s", self.channel.value, target, notification.title)


class EmailSender(Sender):
    channel = NotificationChannel.EMAIL

    def __init__(self, host=None, port=587, username=None, password=None, sender=None, use_tls=True,
                 smtp_factory=smtplib.SMTP, timeout=15):
        self.host, self.port, self.username, self.password = host, int(port), username, password
        self.sender = sender or username or "campusnova@localhost"
        self.use_tls, self.smtp_factory, self.timeout = use_tls, smtp_factory, timeout

    @classmethod
    def from_env(cls) -> "EmailSender":
        return cls(
            host=os.getenv("SMTP_HOST"), port=os.getenv("SMTP_PORT", "587"), username=os.getenv("SMTP_USER"),
            password=os.getenv("SMTP_PASSWORD"), sender=os.getenv("SMTP_FROM"),
            use_tls=os.getenv("SMTP_TLS", "1") != "0",
        )

    def send(self, notification, user):
        if not user.email:
            raise PermanentDeliveryError("user has no email address")
        if not self.host:
            raise RuntimeError("SMTP is not configured (set SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM)")
        msg = EmailMessage()
        msg["Subject"] = f"[CampusNova] {notification.title}"
        msg["From"] = self.sender
        msg["To"] = user.email
        msg.set_content(f"Hello {user.name},\n\n{notification.message}\n\n-- CampusNova")
        with self.smtp_factory(self.host, self.port, timeout=self.timeout) as smtp:
            if self.use_tls:
                smtp.starttls()
            if self.username:
                smtp.login(self.username, self.password or "")
            smtp.send_message(msg)


class FCMSender(Sender):
    """Firebase Cloud Messaging push (HTTP v1 API). `send_fn` can be injected for tests."""

    channel = NotificationChannel.PUSH

    def __init__(self, send_fn=None):
        self._send = send_fn

    def send(self, notification, user):
        from app.core import firebase

        if not user.fcm_token:
            raise PermanentDeliveryError("user has no registered device token")
        send = self._send or firebase.send_push
        data = {"notification_id": notification.id, "type": notification.type.value}
        if notification.complaint_id:
            data["complaint_id"] = notification.complaint_id
        try:
            send(user.fcm_token, notification.title, notification.message, data)
        except firebase.InvalidDeviceToken as exc:
            user.fcm_token = None  # forget the dead token so we stop trying
            raise PermanentDeliveryError(f"device token no longer valid: {exc}") from exc


def build_senders(mode: Optional[str] = None) -> dict[NotificationChannel, Sender]:
    mode = (mode or os.getenv("CAMPUSNOVA_NOTIFY_MODE", "log")).lower()
    if mode == "live":
        return {NotificationChannel.IN_APP: InAppSender(), NotificationChannel.EMAIL: EmailSender.from_env(),
                NotificationChannel.PUSH: FCMSender()}
    return {NotificationChannel.IN_APP: InAppSender(), NotificationChannel.EMAIL: LogSender(NotificationChannel.EMAIL),
            NotificationChannel.PUSH: LogSender(NotificationChannel.PUSH)}


# ----------------------------------------------------------------------------------------- creation
def notify(
    db: Session,
    user_ids: Iterable[int],
    ntype: NotificationType,
    title: str,
    message: str,
    *,
    complaint_id: Optional[int] = None,
    channels: Optional[list[NotificationChannel]] = None,
    payload: Optional[dict] = None,
    dedupe_key: Optional[str] = None,
    now: Optional[datetime] = None,
) -> list[Notification]:
    """Queue a notification for each user on each channel. With `dedupe_key`, repeating the call is harmless."""
    now = now or utcnow()
    channels = channels or DEFAULT_CHANNELS[ntype]
    created: list[Notification] = []
    for uid in dict.fromkeys(user_ids):  # unique, order kept
        for ch in channels:
            key = f"{dedupe_key}:{uid}:{ch.value}"[:190] if dedupe_key else None
            if key and db.scalar(select(Notification.id).where(Notification.dedupe_key == key)):
                continue
            n = Notification(
                user_id=uid, complaint_id=complaint_id, type=ntype, channel=ch, status=NotificationStatus.PENDING,
                title=title[:200], message=message, payload=payload, dedupe_key=key, created_at=now,
            )
            db.add(n)
            created.append(n)
    db.flush()
    return created


# ----------------------------------------------------------------------------------------- delivery
@dataclass
class DispatchResult:
    sent: int = 0
    failed: int = 0  # failed this run (may be retried next run)
    gave_up: int = 0  # reached MAX_RETRIES or permanently undeliverable
    skipped: int = 0  # the user switched this channel off in their preferences


def _wants(user: User, channel: NotificationChannel) -> bool:
    """Respect the user's notification preferences (e-mail / push switches). In-app is always delivered."""
    prefs = user.notification_prefs or {}
    if channel == NotificationChannel.EMAIL:
        return bool(prefs.get("email", True))
    if channel == NotificationChannel.PUSH:
        return bool(prefs.get("push", True))
    return True


def dispatch_pending(
    db: Session,
    senders: Optional[dict[NotificationChannel, Sender]] = None,
    *,
    now: Optional[datetime] = None,
    max_retries: int = MAX_RETRIES,
    batch: int = 200,
) -> DispatchResult:
    senders = senders if senders is not None else build_senders()
    now = now or utcnow()
    rows = db.scalars(
        select(Notification)
        .where(Notification.status.in_([NotificationStatus.PENDING, NotificationStatus.FAILED]),
               Notification.retry_count < max_retries)
        .order_by(Notification.id)
        .limit(batch)
    ).all()
    result = DispatchResult()
    for n in rows:
        user = db.get(User, n.user_id)
        sender = senders.get(n.channel)
        try:
            if user is None or not user.is_active:
                raise PermanentDeliveryError("recipient missing or inactive")
            if sender is None:
                raise PermanentDeliveryError(f"no sender configured for channel {n.channel.value}")
            if not _wants(user, n.channel):
                n.status, n.sent_at, n.error_message = NotificationStatus.SENT, now, "skipped: turned off in the user's preferences"
                result.skipped += 1
                continue
            sender.send(n, user)
        except PermanentDeliveryError as exc:
            n.status, n.retry_count, n.error_message = NotificationStatus.FAILED, max_retries, str(exc)[:500]
            result.failed += 1
            result.gave_up += 1
            logger.warning("notification %s undeliverable: %s", n.id, exc)
        except Exception as exc:  # network errors, provider errors, misconfiguration: retry later
            n.status, n.retry_count, n.error_message = NotificationStatus.FAILED, n.retry_count + 1, str(exc)[:500]
            result.failed += 1
            result.gave_up += int(n.retry_count >= max_retries)
            logger.warning("notification %s failed (attempt %s): %s", n.id, n.retry_count, exc)
        else:
            n.status, n.sent_at, n.error_message = NotificationStatus.SENT, now, None
            result.sent += 1
    db.commit()
    return result


# ----------------------------------------------------------------------------------------- notification center
def list_for_user(db: Session, user_id: int, *, unread_only: bool = False, limit: int = 50) -> list[Notification]:
    q = select(Notification).where(Notification.user_id == user_id, Notification.channel == NotificationChannel.IN_APP)
    if unread_only:
        q = q.where(Notification.read_at.is_(None))
    return list(db.scalars(q.order_by(Notification.id.desc()).limit(limit)))


def unread_count(db: Session, user_id: int) -> int:
    return db.scalar(
        select(func.count()).select_from(Notification).where(
            Notification.user_id == user_id, Notification.channel == NotificationChannel.IN_APP,
            Notification.read_at.is_(None),
        )
    ) or 0


def mark_read(db: Session, notification_id: int, user_id: int, now: Optional[datetime] = None) -> bool:
    """Only the owner can mark a notification as read. Returns False if it was not theirs / not found."""
    n = db.get(Notification, notification_id)
    if n is None or n.user_id != user_id:
        return False
    if n.read_at is None:
        n.read_at, n.status = now or utcnow(), NotificationStatus.READ
        db.commit()
    return True


def mark_all_read(db: Session, user_id: int, now: Optional[datetime] = None) -> int:
    res = db.execute(
        update(Notification)
        .where(Notification.user_id == user_id, Notification.channel == NotificationChannel.IN_APP,
               Notification.read_at.is_(None))
        .values(read_at=now or utcnow(), status=NotificationStatus.READ)
    )
    db.commit()
    return res.rowcount or 0
