from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.core.enums import Category, ComplaintStatus, Priority


class StatusCount(BaseModel):
    status: ComplaintStatus
    count: int = 0


class PriorityCount(BaseModel):
    priority: Priority
    count: int = 0


class CategoryCount(BaseModel):
    category: Category
    count: int = 0


class AdminDashboard(BaseModel):
    """Admin view: monitoring, emergencies, resolution metrics."""

    total_complaints: int = 0
    open_complaints: int = 0
    overdue_complaints: int = 0  # past SLA, not resolved
    critical_open: int = 0
    escalated_open: int = 0  # open complaints at escalation level >= 1
    unassigned_open: int = 0
    pending_ai_reviews: int = 0
    avg_resolution_hours: Optional[float] = None
    by_status: list[StatusCount] = Field(default_factory=list)
    by_priority: list[PriorityCount] = Field(default_factory=list)
    by_category: list[CategoryCount] = Field(default_factory=list)
    generated_at: datetime
    is_stub: bool = False


class MaintenanceTask(BaseModel):
    complaint_id: int
    title: str
    category: Category
    priority: Priority
    status: ComplaintStatus
    sla_deadline: Optional[datetime] = None


class MaintenanceDashboard(BaseModel):
    """Maintenance staff view: assigned tasks and progress."""

    staff_id: int
    assigned: int = 0
    in_progress: int = 0
    resolved_today: int = 0
    tasks: list[MaintenanceTask] = Field(default_factory=list)
    generated_at: datetime
    is_stub: bool = False


class CategoryTrend(BaseModel):
    category: Category
    count: int = 0
    avg_resolution_hours: Optional[float] = None


class InstitutionAnalytics(BaseModel):
    """Institution view: resource allocation and preventive maintenance planning."""

    period_days: int
    complaints_in_period: int = 0
    sla_compliance_pct: Optional[float] = None
    category_trends: list[CategoryTrend] = Field(default_factory=list)
    repeat_issue_locations: list[str] = Field(default_factory=list)  # candidates for preventive maintenance
    generated_at: datetime
    is_stub: bool = False


class EmergencyItem(BaseModel):
    """One row of the high-priority emergency list (open critical/high, or any open safety risk)."""

    complaint_id: int
    title: str
    location: Optional[str] = None
    category: Optional[Category] = None
    priority: Priority
    status: ComplaintStatus
    safety_risk: bool = False
    assigned_to: Optional[int] = None
    escalation_level: int = 0
    sla_due_at: Optional[datetime] = None
    hours_to_deadline: Optional[float] = None  # negative = overdue by that many hours
    is_overdue: bool = False


class PriorityAgreement(BaseModel):
    priority: Priority
    ai_predictions_reviewed: int = 0
    kept: int = 0
    changed: int = 0


class AIPerformance(BaseModel):
    """How the AI is doing in real use, judged by what admins did with its flagged predictions."""

    total_predictions: int = 0  # ML/rule predictions made
    flagged_for_review: int = 0
    reviewed: int = 0
    pending_review: int = 0
    confirmed: int = 0
    overridden: int = 0
    category_changed: int = 0
    priority_changed: int = 0
    agreement_rate_pct: Optional[float] = None  # confirmed / reviewed
    flag_rate_pct: Optional[float] = None  # flagged / total
    avg_category_confidence: Optional[float] = None
    avg_priority_confidence: Optional[float] = None
    by_ai_priority: list[PriorityAgreement] = Field(default_factory=list)
    generated_at: datetime


class ChannelDelivery(BaseModel):
    channel: str
    total: int = 0
    sent: int = 0
    pending: int = 0
    failed: int = 0
    gave_up: int = 0
    delivery_rate_pct: Optional[float] = None  # sent / total


class NotificationStats(BaseModel):
    total: int = 0
    sent: int = 0
    pending: int = 0
    failed_retrying: int = 0
    gave_up: int = 0
    delivery_rate_pct: Optional[float] = None  # sent / (sent + gave_up); pending/retrying not counted yet
    avg_attempts_for_sent: Optional[float] = None
    avg_delivery_delay_seconds: Optional[float] = None
    unread_in_app: int = 0
    by_channel: list[ChannelDelivery] = Field(default_factory=list)
    top_errors: list[str] = Field(default_factory=list)
    generated_at: datetime
