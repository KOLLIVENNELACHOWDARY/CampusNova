from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import Category, Level, PredictionSource, Priority


class AIPredictionCreate(BaseModel):
    complaint_id: int
    source: PredictionSource
    model_name: str
    model_version: str
    predicted_category: Category
    category_confidence: float = Field(ge=0.0, le=1.0)
    predicted_priority: Priority
    priority_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    severity: Optional[Level] = None
    impact: Optional[Level] = None
    safety_risk: bool = False
    input_text: str
    features: Optional[dict[str, Any]] = None
    rationale: Optional[dict[str, Any]] = None
    latency_ms: Optional[int] = None
    needs_manual_review: bool = False


class AIPredictionReview(BaseModel):
    """Payload a reviewer sends to confirm or override a prediction."""

    reviewed_category: Category
    reviewed_priority: Priority
    review_notes: Optional[str] = None


class AIPredictionRead(AIPredictionCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_applied: bool
    reviewed_by: Optional[int]
    reviewed_category: Optional[Category]
    reviewed_priority: Optional[Priority]
    review_notes: Optional[str]
    reviewed_at: Optional[datetime]
    created_at: datetime
