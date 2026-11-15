from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import Category, Level, Priority, PredictionSource
from app.db.base import Base


class AIPrediction(Base):
    """Every categorisation / priority prediction made for a complaint.

    Rows are append-only: a complaint can have an ML prediction, a rule-based
    fallback and a manual override. `is_applied` marks the one currently in effect.
    Keeping history lets us measure model accuracy against manual reviews later.
    """

    __tablename__ = "ai_predictions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    complaint_id: Mapped[int] = mapped_column(ForeignKey("complaints.id", ondelete="CASCADE"), index=True)

    source: Mapped[PredictionSource] = mapped_column(SAEnum(PredictionSource, name="prediction_source"))
    model_name: Mapped[str] = mapped_column(String(100))  # e.g. "tfidf_logreg", "rule_engine"
    model_version: Mapped[str] = mapped_column(String(50))

    predicted_category: Mapped[Category] = mapped_column(SAEnum(Category, name="category"))
    category_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    predicted_priority: Mapped[Priority] = mapped_column(SAEnum(Priority, name="priority"))
    priority_confidence: Mapped[float] = mapped_column(Float, default=0.0)

    severity: Mapped[Optional[Level]] = mapped_column(SAEnum(Level, name="severity_level"), nullable=True)
    impact: Mapped[Optional[Level]] = mapped_column(SAEnum(Level, name="impact_level"), nullable=True)
    safety_risk: Mapped[bool] = mapped_column(Boolean, default=False)

    input_text: Mapped[str] = mapped_column(Text)  # exact text the model saw
    features: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)  # e.g. image-derived signals
    rationale: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)  # matched rules / top terms
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    is_applied: Mapped[bool] = mapped_column(Boolean, default=False)
    needs_manual_review: Mapped[bool] = mapped_column(Boolean, default=False)

    # Manual review outcome (null until a reviewer acts)
    reviewed_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_category: Mapped[Optional[Category]] = mapped_column(SAEnum(Category, name="category"), nullable=True)
    reviewed_priority: Mapped[Optional[Priority]] = mapped_column(SAEnum(Priority, name="priority"), nullable=True)
    review_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_ai_predictions_review_queue", "needs_manual_review", "reviewed_at"),
        Index("ix_ai_predictions_complaint_applied", "complaint_id", "is_applied"),
    )
