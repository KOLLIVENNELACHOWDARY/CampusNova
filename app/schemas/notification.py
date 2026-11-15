from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import NotificationChannel, NotificationStatus, NotificationType


class NotificationCreate(BaseModel):
    user_id: int
    complaint_id: Optional[int] = None
    type: NotificationType
    channel: NotificationChannel = NotificationChannel.IN_APP
    title: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1)
    payload: Optional[dict[str, Any]] = None


class NotificationStatusUpdate(BaseModel):
    """Used by the dispatcher to record delivery results."""

    status: NotificationStatus
    error_message: Optional[str] = None


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    complaint_id: Optional[int]
    type: NotificationType
    channel: NotificationChannel
    status: NotificationStatus
    title: str
    message: str
    payload: Optional[dict[str, Any]]
    retry_count: int
    error_message: Optional[str]
    created_at: datetime
    sent_at: Optional[datetime]
    read_at: Optional[datetime]
