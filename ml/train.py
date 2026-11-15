"""Train and evaluate the Scikit-learn text models.

    python -m ml.dataset     # (re)generate data/complaints.csv
    python -m ml.train       # select + train models, write artifacts/ and reports/

Four text models share one TF-IDF design (word 1-2 grams + character 3-5 grams, so typos
like "Knidly" still produce useful features, plus 9 domain features from the rule engine):

    category  - 6-way. Candidates (LogReg, calibrated LinearSVC, ComplementNB) are compared
                by grouped 5-fold CV on the TRAIN split only; the best macro-F1 wins.
    severity  - low / medium / high   (logistic regression)
    impact    - low / medium / high   (logistic regression)
    safety    - binary safety risk    (logistic regression)

The multi-factor priority itself is assembled in ml/priority_detector.py.
"""
import json
import time
from pathlib import Path

import joblib
import numpy as np
import sklearn
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, confusion_matrix, f1_score
from sklearn.model_selection import GroupKFold, cross_val_score
from sklearn.naive_bayes import ComplementNB
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.svm import LinearSVC

from ml.common import CATEGORIES, DATASET_PATH, DEFAULT_ARTIFACTS_DIR, LEVELS, REPORTS_DIR
from ml.dataset import read_csv
from ml.features import DomainFeatures

SEED = 42


def _features() -> FeatureUnion:
    return FeatureUnion(
        [
            ("word", TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=1)),
            ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, min_df=2)),
            ("domain", DomainFeatures(weight=2.0)),
        ]
    )


def _logreg(C: float = 10.0) -> LogisticRegression:
    return LogisticRegression(C=C, max_iter=3000, class_weight="balanced", random_state=SEED)


def category_candidates() -> dict[str, Pipeline]:
    return {
        "tfidf_logreg": Pipeline([("tfidf", _features()), ("clf", _logreg())]),
        "tfidf_linearsvc_calibrated": Pipeline(
            [
                ("tfidf", _features()),
                ("clf", CalibratedClassifierCV(LinearSVC(C=1.0, class_weight="balanced", random_state=SEED), cv=3)),
            ]
        ),
        "tfidf_complement_nb": Pipeline([("tfidf", _features()), ("clf", ComplementNB(alpha=0.3))]),
    }


def _xy(rows, field):
    return [r["text"] for r in rows], [str(r[field]) for r in rows]


def _report(pipe, rows, field, labels):
    X, y = _xy(rows, field)
    pred = pipe.predict(X)
    return {
        "accuracy": float(np.mean(np.array(pred) == np.array(y))),
        "macro_f1": float(f1_score(y, pred, average="macro", labels=labels, zero_division=0)),
        "per_class": classification_report(y, pred, labels=labels, output_dict=True, zero_division=0),
        "confusion_matrix": confusion_matrix(y, pred, labels=labels).tolist(),
        "labels": labels,
    }


def train(out_dir=DEFAULT_ARTIFACTS_DIR, data_path=DATASET_PATH, verbose: bool = True) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = read_csv(data_path)
    train_rows = [r for r in rows if r["split"] == "train"]
    test_rows = [r for r in rows if r["split"] == "test"]
    t0 = time.time()
    metrics: dict = {"n_train": len(train_rows), "n_test": len(test_rows), "sklearn_version": sklearn.__version__}

    # ---- category: model selection with grouped CV (groups = issue, so no phrasing leaks across folds)
    X_tr, y_tr = _xy(train_rows, "category")
    groups = [r["issue_id"] for r in train_rows]
    cv = GroupKFold(n_splits=5)
    cv_scores = {}
    for name, pipe in category_candidates().items():
        scores = cross_val_score(pipe, X_tr, y_tr, cv=cv, groups=groups, scoring="f1_macro", n_jobs=-1)
        cv_scores[name] = {"mean_macro_f1": float(scores.mean()), "std": float(scores.std())}
        if verbose:
            print(f"  CV category  {name:30s} macro-F1 = {scores.mean():.3f} +/- {scores.std():.3f}")
    best = max(cv_scores, key=lambda k: cv_scores[k]["mean_macro_f1"])
    metrics["category_model_selection"] = {"cv_macro_f1": cv_scores, "selected": best}

    models = {"category": category_candidates()[best].fit(X_tr, y_tr)}
    metrics["category_model_name"] = best

    # ---- severity / impact / safety
    for field, labels in (("severity", LEVELS), ("impact", LEVELS), ("safety_risk", ["0", "1"])):
        X, y = _xy(train_rows, field)
        models[field] = Pipeline([("tfidf", _features()), ("clf", _logreg())]).fit(X, y)

    # ---- hold-out evaluation (unseen issues AND unseen scope phrases)
    metrics["test"] = {
        "category": _report(models["category"], test_rows, "category", CATEGORIES),
        "severity": _report(models["severity"], test_rows, "severity", LEVELS),
        "impact": _report(models["impact"], test_rows, "impact", LEVELS),
        "safety_risk": _report(models["safety_risk"], test_rows, "safety_risk", ["0", "1"]),
    }

    for name, model in models.items():
        joblib.dump(model, out_dir / f"{name}.joblib")
    meta = {
        "sklearn_version": sklearn.__version__,
        "category_model": best,
        "min_confidence": 0.40,
        "review_confidence": 0.60,
        "safety_threshold": 0.35,
        "trained_on_rows": len(train_rows),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    metrics["train_seconds"] = round(time.time() - t0, 1)
    if verbose:
        t = metrics["test"]
        print(
            f"  test  category acc={t['category']['accuracy']:.3f} F1={t['category']['macro_f1']:.3f} | "
            f"severity F1={t['severity']['macro_f1']:.3f} | impact F1={t['impact']['macro_f1']:.3f} | "
            f"safety F1={t['safety_risk']['macro_f1']:.3f}"
        )
    return metrics


def main() -> None:
    from ml.evaluate import evaluate_all, write_reports
    from ml.priority_detector import PriorityDetector

    print("Training...")
    metrics = train()
    detector = PriorityDetector.load(DEFAULT_ARTIFACTS_DIR)
    metrics["priority"] = evaluate_all(detector)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    write_reports(metrics, REPORTS_DIR)
    print(f"Done in {metrics['train_seconds']}s. Artifacts: {DEFAULT_ARTIFACTS_DIR}  Reports: {REPORTS_DIR}")


if __name__ == "__main__":
    main()
