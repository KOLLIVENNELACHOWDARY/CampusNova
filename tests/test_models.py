import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.enums import (
    Category,
    NotificationChannel,
    NotificationStatus,
    NotificationType,
    PredictionSource,
    Priority,
    UserRole,
)
from app.db.base import Base
from tests import compat as cs
from app.models import AIPrediction, Complaint, Notification, PriorityMatrixEntry, User
from app.schemas.notification import NotificationRead
from app.services.priority_matrix import seed_priority_matrix


@pytest.fixture()
def complaint(db, users):
    c = cs.Complaint(title="Light broken", description="Tube light not working", reported_by=users["faculty"].id,
                     reporter_department_id=users["faculty"].department_id, responsible_department_id=users["faculty"].department_id)
    db.add(c)
    db.commit()
    return c


def test_expected_tables_exist():
    names = set(Base.metadata.tables)
    assert {"notifications", "priority_matrix", "priority_keyword_rules", "ai_predictions", "users", "complaints", "assignments", "complaint_history", "complaint_images", "routing_rules", "refresh_tokens", "departments"} <= names


def test_notification_defaults_and_schema(db, complaint):
    n = Notification(
        user_id=complaint.reported_by,
        complaint_id=complaint.id,
        type=NotificationType.STATUS_UPDATE,
        channel=NotificationChannel.EMAIL,
        title="Assigned",
        message="Your complaint was assigned.",
    )
    db.add(n)
    db.commit()
    assert n.status == NotificationStatus.PENDING
    assert n.retry_count == 0
    assert NotificationRead.model_validate(n).title == "Assigned"


def test_ai_prediction_storage(db, complaint):
    p = AIPrediction(
        complaint_id=complaint.id,
        source=PredictionSource.RULE_BASED,
        model_name="rule_engine",
        model_version="0.1",
        predicted_category=Category.ELECTRICAL,
        category_confidence=0.8,
        predicted_priority=Priority.MEDIUM,
        input_text="Light broken Tube light not working",
        rationale={"matched": ["severity:not working(+2)"]},
        needs_manual_review=True,
    )
    db.add(p)
    db.commit()
    assert p.is_applied is False
    assert p.reviewed_at is None
    assert p.rationale["matched"]


def test_seed_matrix_is_idempotent(db):
    first = seed_priority_matrix(db)
    second = seed_priority_matrix(db)
    assert first == len(Category) * 3 * 3 * 2
    assert second == 0
    assert db.scalar(select(func.count()).select_from(PriorityMatrixEntry)) == first
