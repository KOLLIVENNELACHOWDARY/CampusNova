from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import Category, Level, Priority, RuleSignal
from app.db.base import Base


class PriorityMatrixEntry(Base):
    """One cell of the Priority Matrix.

    (category, severity, impact, safety_risk) -> priority + SLA hours.
    Seeded from services/priority_matrix.py; admins can tune rows later without
    a deploy.
    """

    __tablename__ = "priority_matrix"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    category: Mapped[Category] = mapped_column(SAEnum(Category, name="category"))
    severity: Mapped[Level] = mapped_column(SAEnum(Level, name="severity_level"))
    impact: Mapped[Level] = mapped_column(SAEnum(Level, name="impact_level"))
    safety_risk: Mapped[bool] = mapped_column(Boolean, default=False)

    priority: Mapped[Priority] = mapped_column(SAEnum(Priority, name="priority"))
    sla_hours: Mapped[int] = mapped_column(Integer)  # resolution deadline used for escalation
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("category", "severity", "impact", "safety_risk", name="uq_priority_matrix_cell"),
    )


class PriorityKeywordRule(Base):
    """Tunable keyword rule used by the rule-based priority engine.

    category NULL means the rule applies to every category.
    """

    __tablename__ = "priority_keyword_rules"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    keyword: Mapped[str] = mapped_column(String(100))
    signal: Mapped[RuleSignal] = mapped_column(SAEnum(RuleSignal, name="rule_signal"))
    weight: Mapped[int] = mapped_column(Integer, default=1)
    category: Mapped[Optional[Category]] = mapped_column(SAEnum(Category, name="category"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (Index("ix_priority_rules_signal_active", "signal", "is_active"),)
