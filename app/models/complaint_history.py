from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text, func

from app.core.enums import ComplaintStatus
from app.db.base import Base
from app.db.types import enum_column


class ComplaintHistory(Base):
    """Status audit trail. Owner: Sadhvika. `changed_by` is NULL for changes made by the system (auto-assignment)."""

    __tablename__ = "complaint_history"

    id = Column(Integer, primary_key=True, index=True)
    complaint_id = Column(Integer, ForeignKey("complaints.id"), nullable=False, index=True)
    changed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    old_status = Column(enum_column(ComplaintStatus), nullable=True)
    new_status = Column(enum_column(ComplaintStatus), nullable=False)
    remarks = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.current_timestamp())
