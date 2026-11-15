from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, DateTime, Enum as SAEnum, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import NotificationChannel, NotificationStatus, NotificationType
from app.db.base import Base


class Notification(Base):
    """One outbound message (email / FCM push / in-app) to one user.

    A single complaint event can fan out into several rows, one per channel and
    recipient, so delivery status and retries are tracked independently.
    """

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    complaint_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("complaints.id"), index=True, nullable=True
    )

    type: Mapped[NotificationType] = mapped_column(SAEnum(NotificationType, name="notification_type"))
    channel: Mapped[NotificationChannel] = mapped_column(SAEnum(NotificationChannel, name="notification_channel"))
    status: Mapped[NotificationStatus] = mapped_column(
        SAEnum(NotificationStatus, name="notification_status"), default=NotificationStatus.PENDING
    )

    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text)
    payload: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)  # extra FCM / template data

    # Makes jobs idempotent: the same escalation/warning can never be queued twice for the same user+channel.
    dedupe_key: Mapped[Optional[str]] = mapped_column(String(190), nullable=True, unique=True)

    is_read: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")  # kept from the original table
    retry_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_notifications_user_status", "user_id", "status"),
        Index("ix_notifications_status_created", "status", "created_at"),  # dispatcher polls PENDING/FAILED
    )
