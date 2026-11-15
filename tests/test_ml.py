import pytest

from app.core.enums import Category, Priority
from ml import dataset
from ml.common import bump, final_priority, has_urgency
from ml.priority_detector import ModelsNotTrainedError, PriorityDetector
from ml.train import train


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    d = tmp_path_factory.mktemp("ml")
    csv_path = d / "complaints.csv"
    dataset.write_csv(dataset.generate(), csv_path)
    metrics = train(out_dir=d / "artifacts", data_path=csv_path, verbose=False)
    return metrics, PriorityDetector.load(d / "artifacts"), d / "artifacts"


def test_dataset_split_has_no_issue_or_scope_overlap():
    rows = dataset.generate()
    train_ids = {r["issue_id"] for r in rows if r["split"] == "train"}
    test_ids = {r["issue_id"] for r in rows if r["split"] == "test"}
    assert not train_ids & test_ids
    assert len(rows) > 1000


def test_helpers():
    assert has_urgency("Needs URGENT attention") and not has_urgency("download slow")
    assert bump("low") == "medium" and bump("high") == "high"
    assert final_priority("medium", "medium", False, True) == "high"  # urgency bumps severity
    assert final_priority("low", "low", True, False) == "critical"  # safety always critical


def test_models_meet_minimum_quality(trained):
    metrics, _, _ = trained
    t = metrics["test"]
    assert t["category"]["macro_f1"] > 0.70
    assert t["severity"]["accuracy"] > 0.55
    assert t["impact"]["accuracy"] > 0.55
    assert t["safety_risk"]["accuracy"] > 0.90


def test_detector_safety_is_critical(trained):
    _, det, _ = trained
    r = det.predict("Sparks coming from the switch board in the lab", "students are scared")
    assert r.safety_risk and r.priority == Priority.CRITICAL
    assert r.sla_hours == 4


def test_detector_urgency_bumps_severity(trained):
    _, det, _ = trained
    calm = det.predict("Ceiling fan is not working in the staff room")
    urgent = det.predict("Ceiling fan is not working in the staff room, needs urgent attention")
    order = ["low", "medium", "high", "critical"]
    assert order.index(urgent.priority.value) >= order.index(calm.priority.value)


def test_detector_respects_explicit_category(trained):
    _, det, _ = trained
    r = det.predict("Something is wrong in the building", category=Category.CIVIL)
    assert r.category == Category.CIVIL and r.category_confidence == 1.0


def test_detector_explains_itself(trained):
    _, det, _ = trained
    r = det.predict("Wifi is down in the entire CSE block")
    assert any(m.startswith("ml:severity=") for m in r.matched_rules) or r.source == "rule_based_fallback"


def test_missing_models_raise_clear_error(tmp_path):
    with pytest.raises(ModelsNotTrainedError):
        PriorityDetector.load(tmp_path)


def test_predict_endpoint(trained, monkeypatch, client, auth, users):
    from app.api import priority as api

    _, _, art = trained
    h = auth(users["faculty"])
    api._load_detector.cache_clear()
    monkeypatch.setenv("CAMPUSNOVA_MODEL_DIR", str(art))
    res = client.post("/priority/predict", json={"title": "Exposed live wire near the door", "description": "in the corridor"}, headers=h)
    assert res.status_code == 200 and res.json()["priority"] == "critical"
    assert client.post("/priority/predict", json={"title": "Exposed live wire"}).status_code == 401  # sign-in required

    api._load_detector.cache_clear()
    monkeypatch.setenv("CAMPUSNOVA_MODEL_DIR", str(art / "nope"))
    assert client.post("/priority/predict", json={"title": "x"}, headers=h).status_code == 503
    api._load_detector.cache_clear()
