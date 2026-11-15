from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func

from app.db.base import Base


class Assignment(Base):
    """One row per (re)assignment. Owner: Sadhvika. `assigned_by` is NULL when the AI auto-assigned the complaint."""

    __tablename__ = "assignments"

    id = Column(Integer, primary_key=True, index=True)
    complaint_id = Column(Integer, ForeignKey("complaints.id"), nullable=False, index=True)
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=False)
    assigned_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    assignment_type = Column(String(20), nullable=False, default="manual", server_default="manual")  # manual | auto | claimed
    assigned_at = Column(DateTime, nullable=False, server_default=func.current_timestamp())
    notes = Column(Text, nullable=True)
