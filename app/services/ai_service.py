"""AI side of a complaint: predict category/priority, store the prediction, and let an admin confirm or override it.

`detector` is the ML PriorityDetector; when it is None the rule-based engine is used, so the system keeps working
before any model has been trained.
"""
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import Category, NotificationType, PredictionSource, Priority
from app.core.permissions import has_permission
from app.core.timeutil import ensure_utc, utcnow
from app.models import AIPrediction, Complaint
from app.services.common import BusinessRuleError, NotFoundError, get_complaint, get_user, log_event
from app.services.notification_service import notify
from app.services.priority_engine import PriorityEngine, PriorityResult
from app.services.priority_matrix import SLA_HOURS


@lru_cache(maxsize=1)
def get_default_detector():
    """Trained ML detector if available, else None (the rule-based engine is used instead)."""
    try:
        from ml.priority_detector import PriorityDetector

        return PriorityDetector.load()
    except Exception:
        return None


def predict(detector, title: str, body: str, category: Optional[Category]) -> PriorityResult:
    detector = detector if detector is not None else get_default_detector()
    if detector is not None:
        return detector.predict(title, body, category)
    return PriorityEngine().evaluate(title, body, category)


def record_prediction(db: Session, complaint: Complaint, result: PriorityResult, input_text: str, now: datetime) -> AIPrediction:
    is_ml = result.source == "ml_multi_factor"
    pred = AIPrediction(
        complaint_id=complaint.id, source=PredictionSource.ML if is_ml else PredictionSource.RULE_BASED,
        model_name="multi_factor_detector" if is_ml else "rule_engine", model_version="1.0",
        predicted_category=result.category, category_confidence=result.category_confidence,
        predicted_priority=result.priority, priority_confidence=result.confidence,
        severity=result.severity, impact=result.impact, safety_risk=result.safety_risk, input_text=input_text,
        rationale={"reasons": result.matched_rules, "source": result.source}, is_applied=True,
        needs_manual_review=result.needs_manual_review, created_at=now)
    db.add(pred)
    return pred


def pending_reviews(db: Session) -> list[AIPrediction]:
    """Applied predictions flagged for manual review and not yet confirmed/overridden."""
    return list(db.scalars(
        select(AIPrediction).where(AIPrediction.needs_manual_review.is_(True), AIPrediction.is_applied.is_(True),
                                   AIPrediction.reviewed_at.is_(None)).order_by(AIPrediction.id)))


def review_prediction(db: Session, prediction_id: int, reviewer_id: int, *, confirm: bool,
                      category: Optional[Category] = None, priority: Optional[Priority] = None, notes: str = "",
                      now: Optional[datetime] = None, auto_assign: bool = False) -> AIPrediction:
    """Confirm the AI result, or override category/priority.

    An override appends a MANUAL prediction (the AI row is kept as history, no longer applied), updates the complaint,
    re-routes it to the right department, and recomputes its SLA from the original creation time.
    """
    from app.services.workflow import resolve_department  # workflow owns routing

    now = now or utcnow()
    pred = db.get(AIPrediction, prediction_id)
    if pred is None:
        raise NotFoundError(f"prediction {prediction_id} not found")
    reviewer = get_user(db, reviewer_id)
    if not has_permission(reviewer.role, "ai:review"):
        raise PermissionError("You are not allowed to review AI predictions.")
    if pred.reviewed_at is not None or not pred.is_applied:
        raise BusinessRuleError("This prediction was already reviewed or replaced.")
    c = get_complaint(db, pred.complaint_id)

    new_cat = pred.predicted_category if confirm else (category or pred.predicted_category)
    new_pri = pred.predicted_priority if confirm else (priority or pred.predicted_priority)
    pred.reviewed_by, pred.reviewed_at, pred.review_notes = reviewer_id, now, notes or None
    pred.reviewed_category, pred.reviewed_priority = new_cat, new_pri
    pred.needs_manual_review = False
    c.needs_manual_review = False
    changed = (new_cat != pred.predicted_category) or (new_pri != pred.predicted_priority)
    result = pred

    if changed:
        pred.is_applied = False
        result = AIPrediction(
            complaint_id=c.id, source=PredictionSource.MANUAL, model_name="manual_review", model_version="-",
            predicted_category=new_cat, category_confidence=1.0, predicted_priority=new_pri, priority_confidence=1.0,
            severity=pred.severity, impact=pred.impact, safety_risk=pred.safety_risk, input_text=pred.input_text,
            rationale={"overrides_prediction": pred.id, "from": [pred.predicted_category.value, pred.predicted_priority.value]},
            is_applied=True, needs_manual_review=False, reviewed_by=reviewer_id, reviewed_category=new_cat,
            reviewed_priority=new_pri, review_notes=notes or None, reviewed_at=now, created_at=now)
        db.add(result)
        old_pri = c.priority
        if new_cat != c.category:
            c.category = new_cat
            c.responsible_department_id = resolve_department(db, new_cat, c.reporter_department_id)
        c.priority = new_pri
        if new_pri != old_pri:  # new SLA window, measured from when the complaint was filed
            c.sla_hours = SLA_HOURS[new_pri]
            c.sla_due_at = ensure_utc(c.created_at) + timedelta(hours=c.sla_hours)
            c.sla_warned, c.escalation_level = False, 0
        notify(db, [c.reported_by] + ([c.assigned_to] if c.assigned_to else []), NotificationType.STATUS_UPDATE,
               f"{c.complaint_number} updated after review",
               f"An admin reviewed the AI result: category {new_cat.value}, priority {new_pri.value.upper()}.",
               complaint_id=c.id, now=now)
    log_event(db, c.id, "ai_review", f"{pred.predicted_category.value}/{pred.predicted_priority.value}",
              f"{new_cat.value}/{new_pri.value}", reviewer_id, ("overridden: " if changed else "confirmed: ") + (notes or ""), now)
    db.commit()
    if auto_assign:  # a confirmed/corrected category can now be routed; a changed department moves jobs not yet started
        from app.services.assignment import auto_assign as assign_best_worker

        assign_best_worker(db, c.id, now=now, allow_reassign=changed)
    return result
