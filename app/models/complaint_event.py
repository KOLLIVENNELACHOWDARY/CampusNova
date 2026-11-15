from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timeutil import utcnow
from app.db.base import Base


class ComplaintEvent(Base):
    """Append-only audit trail: registration, assignment, status changes, AI reviews, escalations."""

    __tablename__ = "complaint_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    complaint_id: Mapped[int] = mapped_column(ForeignKey("complaints.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(40))  # registered | assigned | status_changed | ai_review | sla_warning | escalated
    from_value: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    to_value: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    actor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)  # NULL = system/scheduler
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
