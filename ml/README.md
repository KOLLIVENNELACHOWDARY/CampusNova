# CampusNova ML (Day 6-7)

```bash
cd backend
pip install -r requirements.txt
python -m ml.dataset     # regenerate data/complaints.csv (synthetic starter data)
python -m ml.train       # select + train models, evaluate, write artifacts/ and reports/
```

| File | Purpose |
|---|---|
| `dataset.py` | Synthetic labelled complaints; split by issue and scope phrase (no phrasing leakage) |
| `hand_labeled.py` | 36 hand-labelled realistic complaints, used only for evaluation |
| `features.py` | Rule-engine signals as 9 extra ML features |
| `train.py` | Category model selection (grouped CV) + severity / impact / safety models |
| `priority_detector.py` | Multi-factor priority: category + severity + impact + safety + urgency -> matrix |
| `evaluate.py` | ML vs rule-based comparison, writes `reports/REPORT.md` and `metrics.json` |

Trained `.joblib` models are committed in `artifacts/` (scikit-learn 1.9.1). If loading fails on another version, run `python -m ml.train` to rebuild them.
API: `POST /priority/predict` (503 until trained). Replace `data/complaints.csv` with real complaints when available.

Demo: `python -m streamlit run demo_app.py`
