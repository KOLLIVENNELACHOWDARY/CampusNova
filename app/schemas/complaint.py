"""Complaint request/response models. The reporter always comes from the sign-in token, never from the request body."""
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import Category, ComplaintStatus, Priority


class ComplaintCreate(BaseModel):
    block: str = Field(min_length=1, max_length=100)
    floor: str = Field(min_length=1, max_length=50)
    room_number: Optional[str] = Field(default=None, max_length=30)
    title: Optional[str] = Field(default=None, max_length=200)
    description: str = Field(min_length=1, max_length=2000)
    category: Optional[Category] = None  # None = the AI decides
    responsible_department_id: Optional[int] = Field(default=None, gt=0)  # None = routing rules decide


class ImageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    original_name: Optional[str] = None
    content_type: Optional[str] = None
    size_bytes: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    uploaded_at: Optional[datetime] = None
    uploaded_by: Optional[int] = None


class ComplaintRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    complaint_number: str
    title: Optional[str]
    description: str
    block: str
    floor: str
    room_number: Optional[str]
    location: str
    category: Category
    priority: Optional[Priority]
    status: ComplaintStatus
    reported_by: int
    reporter_department_id: int
    responsible_department_id: int
    assigned_to: Optional[int]
    safety_risk: bool
    needs_manual_review: bool
    sla_hours: Optional[int]
    sla_due_at: Optional[datetime]
    escalation_level: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    resolved_at: Optional[datetime]
    closed_at: Optional[datetime] = None


class ComplaintPage(BaseModel):
    items: list[ComplaintRead]
    total: int
    page: int
    page_size: int


class AssignRequest(BaseModel):
    assignee_id: int


class StatusRequest(BaseModel):
    status: ComplaintStatus
    note: str = Field(default="", max_length=1000)


class RemarkRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class ReleaseRequest(BaseModel):
    reason: str = Field(default="", max_length=300)


class RoutingRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category: Category
    department_id: Optional[int]
    is_active: bool


class RoutingRuleWrite(BaseModel):
    department_id: Optional[int] = None
    is_active: bool = True


class HistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    changed_by: Optional[int]
    old_status: Optional[ComplaintStatus]
    new_status: ComplaintStatus
    remarks: Optional[str]
    created_at: datetime


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_type: str
    from_value: Optional[str]
    to_value: Optional[str]
    actor_id: Optional[int]
    note: Optional[str]
    created_at: datetime


class ComplaintDetail(ComplaintRead):
    images: list[ImageRead] = Field(default_factory=list)
    history: list[HistoryRead] = Field(default_factory=list)


class ReviewConfirm(BaseModel):
    notes: str = Field(default="", max_length=500)


class ReviewOverride(ReviewConfirm):
    category: Optional[Category] = None
    priority: Optional[Priority] = None


class ReviewItem(BaseModel):
    prediction_id: int
    complaint_id: int
    title: str
    input_text: str
    predicted_category: Category
    predicted_priority: Priority
    category_confidence: float
    priority_confidence: float
    reasons: list[str]
    source: str


class JobRunResult(BaseModel):
    result: dict[str, Any]
