from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.db.session import get_db
from app.models import Complaint, User
from app.schemas.ai_prediction import AIPredictionRead
from app.schemas.complaint import ReviewConfirm, ReviewItem, ReviewOverride
from app.services import assignment
from app.services import ai_service as cs

router = APIRouter(prefix="/ai", tags=["ai-review"])


@router.get("/reviews", response_model=list[ReviewItem])
def review_queue(_: User = Depends(require_permission("ai:review")), db: Session = Depends(get_db)):
    items = []
    for p in cs.pending_reviews(db):
        c = db.get(Complaint, p.complaint_id)
        items.append(ReviewItem(
            prediction_id=p.id, complaint_id=p.complaint_id, title=c.label if c else "", input_text=p.input_text,
            predicted_category=p.predicted_category, predicted_priority=p.predicted_priority,
            category_confidence=p.category_confidence, priority_confidence=p.priority_confidence,
            reasons=(p.rationale or {}).get("reasons", []), source=p.source.value,
        ))
    return items


@router.post("/predictions/{prediction_id}/confirm", response_model=AIPredictionRead)
def confirm(prediction_id: int, body: ReviewConfirm, user: User = Depends(require_permission("ai:review")), db: Session = Depends(get_db)):
    return cs.review_prediction(db, prediction_id, user.id, confirm=True, notes=body.notes,
                                auto_assign=assignment.auto_assign_enabled())


@router.post("/predictions/{prediction_id}/override", response_model=AIPredictionRead)
def override(prediction_id: int, body: ReviewOverride, user: User = Depends(require_permission("ai:review")), db: Session = Depends(get_db)):
    return cs.review_prediction(db, prediction_id, user.id, confirm=False, category=body.category,
                                priority=body.priority, notes=body.notes,
                                auto_assign=assignment.auto_assign_enabled())
