"""Multi-factor priority detector.

Priority is not predicted directly. It is assembled from independent factors so every
decision can be explained and each factor can be improved on its own:

    1. category   - ML text classifier (or the reporter's explicit choice)
    2. severity   - ML text classifier (low / medium / high)
    3. impact     - ML text classifier (how many people / how critical the place)
    4. safety     - ML probability OR the rule engine's safety keywords (either one escalates)
    5. urgency    - urgency wording ("urgent", "immediately", ...) bumps severity one level
    6. matrix     - (severity, impact, safety) -> priority and SLA hours, shared with the rule engine

Fallback: when the models are not confident, the Day 2 rule-based engine decides and the
result is flagged for manual review.
"""
import json
from pathlib import Path
from typing import Optional

import joblib
import numpy as np

from app.core.enums import Category, Level, Priority
from ml import typos
from app.services.priority_engine import PriorityEngine, PriorityResult
from app.services.priority_matrix import SLA_HOURS, build_default_matrix
from ml.common import DEFAULT_ARTIFACTS_DIR, bump, has_problem_cue, has_urgency

_MODEL_FILES = ("category", "severity", "impact", "safety_risk")


class ModelsNotTrainedError(RuntimeError):
    pass


class PriorityDetector:
    def __init__(self, models: dict, meta: Optional[dict] = None, rule_engine: Optional[PriorityEngine] = None):
        self.models = models
        meta = meta or {}
        self.min_confidence = meta.get("min_confidence", 0.40)
        self.review_confidence = meta.get("review_confidence", 0.60)
        # Safety-first: escalate at a lower probability than 0.5 (a missed hazard costs more than a false alarm).
        self.safety_threshold = meta.get("safety_threshold", 0.35)
        self.rule_engine = rule_engine or PriorityEngine()
        self.matrix = build_default_matrix()

    @classmethod
    def load(cls, artifacts_dir=DEFAULT_ARTIFACTS_DIR) -> "PriorityDetector":
        d = Path(artifacts_dir)
        missing = [n for n in _MODEL_FILES if not (d / f"{n}.joblib").exists()]
        if missing:
            raise ModelsNotTrainedError(
                f"Missing trained models {missing} in {d}. Run `python -m ml.dataset` then `python -m ml.train`."
            )
        models = {n: joblib.load(d / f"{n}.joblib") for n in _MODEL_FILES}
        meta_path = d / "meta.json"
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        return cls(models, meta)

    @staticmethod
    def _top(model, text: str) -> tuple[str, float, dict]:
        proba = model.predict_proba([text])[0]
        classes = [str(c) for c in model.classes_]
        k = int(np.argmax(proba))
        return classes[k], float(proba[k]), dict(zip(classes, proba.astype(float)))

    def predict(self, title: str, description: str = "", category: Optional[Category] = None) -> PriorityResult:
        if not (title or "").strip() and not (description or "").strip():
            raise ValueError("Complaint text is empty")
        title = typos.correct((title or "").strip())
        description = typos.correct(description or "")
        text = f"{title}. {description}".strip(" .") if description else title
        rule = self.rule_engine.evaluate(title, description or "", category)

        # No keyword evidence AND no sign of a problem (gibberish, numbers, chit-chat): do not guess.
        # Triage as MEDIUM so it is not buried, and send it to a human.
        totals, hits = self.rule_engine.signal_scores(text)
        has_evidence = any(totals.values()) or any(hits.values())
        problem_cue = has_problem_cue(text)
        if not has_evidence and not problem_cue:
            rule.matched_rules.insert(0, "fallback:no_recognised_keywords")
            rule.priority = Priority.MEDIUM
            rule.sla_hours = SLA_HOURS[Priority.MEDIUM]
            rule.needs_manual_review = True
            rule.source = "rule_based_fallback"
            return rule

        cat_label, cat_conf, _ = self._top(self.models["category"], text)
        if category is not None:
            cat_label, cat_conf = category.value, 1.0
        sev_label, sev_conf, _ = self._top(self.models["severity"], text)
        imp_label, imp_conf, _ = self._top(self.models["impact"], text)
        _, _, safety_probs = self._top(self.models["safety_risk"], self.rule_engine._strip_negated_safety(text))
        p_safety = safety_probs.get("1", 0.0)

        confidence = float(np.mean([cat_conf, sev_conf, imp_conf]))
        if confidence < self.min_confidence:
            rule.matched_rules.insert(0, f"fallback:low_model_confidence({confidence:.2f})")
            rule.needs_manual_review = True
            rule.source = "rule_based_fallback"
            return rule

        reasons = [
            f"ml:category={cat_label}({cat_conf:.2f})",
            f"ml:severity={sev_label}({sev_conf:.2f})",
            f"ml:impact={imp_label}({imp_conf:.2f})",
            f"ml:safety_prob={p_safety:.2f}",
        ]
        safety = p_safety >= self.safety_threshold or rule.safety_risk
        if rule.safety_risk and p_safety < self.safety_threshold:
            reasons.append("rule:safety_keyword_override")

        severity = sev_label
        if has_urgency(text):
            severity = bump(severity)
            if severity != sev_label:
                reasons.append(f"urgency:severity {sev_label}->{severity}")

        priority = self.matrix[(Level(severity), Level(imp_label), safety)]
        needs_review = confidence < self.review_confidence
        if not problem_cue:
            needs_review = True
            reasons.append("review:no_problem_described (may not be a complaint)")
        if not has_evidence:
            needs_review = True
            reasons.append("review:no_keyword_evidence (unfamiliar wording, ML guess only)")
        return PriorityResult(
            category=Category(cat_label),
            category_confidence=round(cat_conf, 2),
            priority=Priority(priority),
            severity=Level(severity),
            impact=Level(imp_label),
            safety_risk=safety,
            sla_hours=SLA_HOURS[priority],
            needs_manual_review=needs_review,
            matched_rules=reasons,
            source="ml_multi_factor",
            confidence=round(confidence, 3),
        )