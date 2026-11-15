import os
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import require_permission

from app.schemas.priority import PriorityEvaluateRequest, PriorityEvaluateResponse
from app.services.priority_engine import PriorityEngine
from ml.validation import validate_complaint

router = APIRouter(prefix="/priority", tags=["priority"], dependencies=[Depends(require_permission("ai:predict"))])

_engine = PriorityEngine()


@router.post("/evaluate", response_model=PriorityEvaluateResponse)
def evaluate_priority(body: PriorityEvaluateRequest):
    """Dry-run the rule-based engine (handy for Postman demos and tuning rules)."""
    result = _engine.evaluate(body.title, body.description, body.category)
    return PriorityEvaluateResponse(**result.__dict__)


@lru_cache(maxsize=1)
def _load_detector(model_dir: str):
    from ml.priority_detector import PriorityDetector

    return PriorityDetector.load(model_dir)


@router.post("/predict", response_model=PriorityEvaluateResponse)
def predict_priority(body: PriorityEvaluateRequest):
    """Multi-factor ML priority (falls back to the rule engine when models are unsure)."""
    from ml.common import DEFAULT_ARTIFACTS_DIR
    from ml.priority_detector import ModelsNotTrainedError

    model_dir = os.getenv("CAMPUSNOVA_MODEL_DIR", str(DEFAULT_ARTIFACTS_DIR))
    try:
        detector = _load_detector(model_dir)
    except ModelsNotTrainedError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    error = validate_complaint(body.title, body.description)
    if error:
        raise HTTPException(status_code=422, detail=error)
    result = detector.predict(body.title, body.description, body.category)
    return PriorityEvaluateResponse(**result.__dict__)
