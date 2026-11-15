from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, func

from app.core.enums import Category
from app.db.base import Base
from app.db.types import enum_column


class RoutingRule(Base):
    """Which department is responsible for a category. Owner: Sadhvika.

    `department_id` NULL means "the reporter's own department" (used for lab and general issues).
    """

    __tablename__ = "routing_rules"

    id = Column(Integer, primary_key=True)
    category = Column(enum_column(Category, 100), nullable=False, unique=True)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="1")
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime, nullable=False, server_default=func.current_timestamp(), onupdate=func.current_timestamp())
