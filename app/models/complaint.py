from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, func

from app.core.enums import Category, ComplaintStatus, Priority
from app.db.base import Base
from app.db.types import enum_column


class Complaint(Base):
    """A reported problem. Owner: Jahnavi (complaint module). Workflow (Sadhvika) and AI/SLA (Vennela) columns added."""

    __tablename__ = "complaints"

    id = Column(Integer, primary_key=True, index=True)
    complaint_number = Column(String(30), unique=True, nullable=False, index=True)

    reported_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    reporter_department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)

    block = Column(String(100), nullable=False)
    floor = Column(String(50), nullable=False)
    room_number = Column(String(30), nullable=True)

    title = Column(String(200), nullable=True)  # short summary; derived from the description when not given
    category = Column(enum_column(Category, 100), nullable=False, default=Category.GENERAL)
    description = Column(Text, nullable=False)

    responsible_department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)

    priority = Column(enum_column(Priority), nullable=True, default=Priority.MEDIUM)
    status = Column(enum_column(ComplaintStatus), nullable=False, default=ComplaintStatus.REGISTERED)

    # --- workflow (Sadhvika)
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)  # current assignee
    assigned_at = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)

    # --- AI + SLA (Vennela)
    safety_risk = Column(Boolean, nullable=False, default=False, server_default="0")
    needs_manual_review = Column(Boolean, nullable=False, default=False, server_default="0")
    sla_hours = Column(Integer, nullable=True)
    sla_due_at = Column(DateTime, nullable=True)
    sla_warned = Column(Boolean, nullable=False, default=False, server_default="0")
    escalation_level = Column(Integer, nullable=False, default=0, server_default="0")
    last_escalated_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, nullable=False, server_default=func.current_timestamp())
    updated_at = Column(DateTime, nullable=False, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    @property
    def location(self) -> str:
        return ", ".join(p for p in (self.block, self.floor, self.room_number) if p)

    @location.setter
    def location(self, value: str) -> None:  # free-text place (used by tests/importers): stored as block, floor "G"
        self.block, self.floor, self.room_number = (value or "Main block"), "G", None

    @property
    def label(self) -> str:
        return self.title or (self.description[:60] + ("..." if len(self.description) > 60 else ""))
