"""Domain features: the Day 2 rule engine's keyword signals, fed to the ML models as extra columns.

TF-IDF only knows words it saw in training. These nine numbers carry campus-maintenance
knowledge ("spark" = safety, "no internet" = severe, "wifi" = networking) so the models can
still do sensible things with phrasings they have never seen. Values are clipped to >= 0 so
they work with Naive Bayes too.
"""
import numpy as np
from scipy import sparse
from sklearn.base import BaseEstimator, TransformerMixin

from app.core.enums import Category, RuleSignal
from app.services.priority_engine import PriorityEngine

_CATS = [Category.ELECTRICAL, Category.CIVIL, Category.NETWORKING, Category.SANITATION, Category.LABORATORY]


class DomainFeatures(BaseEstimator, TransformerMixin):
    def __init__(self, weight: float = 2.0):
        self.weight = weight

    def fit(self, X, y=None):
        return self

    def transform(self, X):
        engine = PriorityEngine()
        rows = []
        for text in X:
            totals, hits = engine.signal_scores(text)
            rows.append(
                [
                    min(max(totals[RuleSignal.SEVERITY], 0), 8) / 4,
                    min(max(totals[RuleSignal.IMPACT], 0), 8) / 4,
                    min(max(totals[RuleSignal.SAFETY], 0), 10) / 5,
                    *[min(hits[c], 3) / 3 for c in _CATS],
                ]
            )
        return sparse.csr_matrix(np.array(rows, dtype=float) * self.weight)
