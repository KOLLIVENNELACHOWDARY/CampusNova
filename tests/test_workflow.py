"""Status state machine, assignment, remarks, sign-off, routing rules and the escalation scheduler (Sadhvika)."""
from datetime import timedelta

import pytest

from app.core.enums import Category, ComplaintStatus as S
from app.models import Assignment, Complaint, ComplaintHistory
from app.services import workflow
from app.services.escalation import run_sla_check
from tests import compat as cs
from tests.conftest import T0

BODY = {"block": "Block A", "floor": "2", "description": "The ceiling fan in the classroom stopped working"}


@pytest.fixture(autouse=True)
def _no_auto_assign(monkeypatch):
    monkeypatch.setenv("CAMPUSNOVA_AUTO_ASSIGN", "0")


@pytest.fixture()
def cid(client, auth, users):
    return client.post("/complaints", json=BODY, headers=auth(users["faculty"])).json()["id"]


def post(client, h, path, **body):
    return client.post(path, json=body, headers=h)


def status(client, h, cid, new, note=""):
    return post(client, h, f"/complaints/{cid}/status", status=new, note=note)


# ------------------------------------------------------------------ the happy path, end to end
def test_full_lifecycle_with_history(client, auth, users, cid, db):
    admin, worker, rep = auth(users["admin"]), auth(users["electrician"]), auth(users["faculty"])
    assert post(client, admin, f"/complaints/{cid}/assign", assignee_id=users["electrician"].id).json()["status"] == "assigned"
    assert status(client, worker, cid, "in_progress").json()["status"] == "in_progress"
    done = status(client, worker, cid, "resolved", "Replaced the capacitor")
    assert done.status_code == 200 and done.json()["resolved_at"]
    closed = client.post(f"/complaints/{cid}/sign-off", headers=rep)
    assert closed.status_code == 200 and closed.json()["status"] == "closed" and closed.json()["closed_at"]
    path = [(h["old_status"], h["new_status"]) for h in client.get(f"/complaints/{cid}/timeline", headers=rep).json()]
    assert path == [(None, "registered"), ("registered", "assigned"), ("assigned", "in_progress"),
                    ("in_progress", "resolved"), ("resolved", "closed")]
    assert db.query(Assignment).filter_by(complaint_id=cid).one().assignment_type == "manual"


def test_reporter_is_notified_at_each_step(client, auth, users, cid):
    admin, worker = auth(users["admin"]), auth(users["electrician"])
    post(client, admin, f"/complaints/{cid}/assign", assignee_id=users["electrician"].id)
    status(client, worker, cid, "in_progress")
    status(client, worker, cid, "resolved", "Fixed")
    titles = [n["title"] for n in client.get("/notifications", headers=auth(users["faculty"])).json()]
    assert any("assigned" in t for t in titles) and any("in progress" in t for t in titles) and any("resolved" in t for t in titles)


# ------------------------------------------------------------------ state machine
ALL = list(S)
LEGAL = {(S.REGISTERED, S.ASSIGNED), (S.ASSIGNED, S.IN_PROGRESS), (S.IN_PROGRESS, S.RESOLVED), (S.RESOLVED, S.CLOSED), (S.RESOLVED, S.IN_PROGRESS)}


@pytest.mark.parametrize("old", ALL)
@pytest.mark.parametrize("new", ALL)
def test_transition_matrix(db, users, detector, old, new):
    """Every (old, new) pair: legal ones succeed, everything else raises, nothing is changed on failure."""
    c = cs.register_complaint(db, reporter_id=users["faculty"].id, title="Fan broken", description="Fan broken in room", detector=detector, now=T0)
    c.status, c.assigned_to = old, users["electrician"].id
    db.commit()
    if new == S.ASSIGNED:  # assigning goes through assign_complaint, never through a plain status change
        with pytest.raises(cs.BusinessRuleError):
            workflow.change_status(db, c.id, new, users["admin"].id, "x")
        return
    if (old, new) in LEGAL:
        workflow.change_status(db, c.id, new, users["admin"].id, "note")
        assert c.status == new
    else:
        with pytest.raises(cs.BusinessRuleError):
            workflow.change_status(db, c.id, new, users["admin"].id, "note")
        assert c.status == old


def test_cannot_skip_steps_over_http(client, auth, users, cid):
    admin = auth(users["admin"])
    for bad in ("in_progress", "resolved", "closed", "assigned"):
        assert status(client, admin, cid, bad, "x").status_code == 409
    assert status(client, admin, cid, "bogus").status_code == 422


def test_resolving_requires_a_note(client, auth, users, cid):
    admin = auth(users["admin"])
    post(client, admin, f"/complaints/{cid}/assign", assignee_id=users["electrician"].id)
    status(client, admin, cid, "in_progress")
    r = status(client, admin, cid, "resolved", "   ")
    assert r.status_code == 409 and "note" in r.json()["error"]["message"]


def test_reopen_clears_resolution_and_needs_a_reason(client, auth, users, cid):
    admin, rep = auth(users["admin"]), auth(users["faculty"])
    post(client, admin, f"/complaints/{cid}/assign", assignee_id=users["electrician"].id)
    status(client, admin, cid, "in_progress")
    status(client, admin, cid, "resolved", "done")
    assert post(client, rep, f"/complaints/{cid}/reopen", text="Still not working").json()["resolved_at"] is None
    assert post(client, rep, f"/complaints/{cid}/reopen", text="again").status_code == 409  # not resolved any more


def test_closed_is_final(client, auth, users, cid):
    admin = auth(users["admin"])
    post(client, admin, f"/complaints/{cid}/assign", assignee_id=users["electrician"].id)
    for s, n in (("in_progress", ""), ("resolved", "ok"), ("closed", "ok")):
        assert status(client, admin, cid, s, n).status_code == 200
    assert status(client, admin, cid, "in_progress", "again").status_code == 409
    assert post(client, admin, f"/complaints/{cid}/assign", assignee_id=users["electrician2"].id).status_code == 409


# ------------------------------------------------------------------ who may do what
def test_only_the_assigned_worker_can_start_and_finish(client, auth, users, cid):
    post(client, auth(users["admin"]), f"/complaints/{cid}/assign", assignee_id=users["electrician"].id)
    assert status(client, auth(users["electrician2"]), cid, "in_progress").status_code == 403
    assert status(client, auth(users["faculty"]), cid, "in_progress").status_code == 403
    assert status(client, auth(users["electrician"]), cid, "in_progress").status_code == 200
    assert status(client, auth(users["faculty"]), cid, "resolved", "I fixed it").status_code == 403  # reporters cannot resolve


def test_only_the_reporter_or_admin_can_sign_off(client, auth, users, cid):
    admin, worker = auth(users["admin"]), auth(users["electrician"])
    post(client, admin, f"/complaints/{cid}/assign", assignee_id=users["electrician"].id)
    status(client, worker, cid, "in_progress")
    status(client, worker, cid, "resolved", "done")
    assert client.post(f"/complaints/{cid}/sign-off", headers=worker).status_code == 403  # a worker cannot close their own job
    assert client.post(f"/complaints/{cid}/sign-off", headers=auth(users["staff"])).status_code == 403
    assert client.post(f"/complaints/{cid}/sign-off", headers=auth(users["faculty"])).status_code == 200


def test_assigning_rules(client, auth, users, cid):
    admin = auth(users["admin"])
    assert post(client, auth(users["faculty"]), f"/complaints/{cid}/assign", assignee_id=users["electrician"].id).status_code == 403
    assert post(client, auth(users["electrician"]), f"/complaints/{cid}/assign", assignee_id=users["electrician"].id).status_code == 403
    for bad in (users["faculty"].id, users["admin"].id, 9999):  # only maintenance staff can be assigned
        assert post(client, admin, f"/complaints/{cid}/assign", assignee_id=bad).status_code == 409
    assert post(client, admin, f"/complaints/{cid}/assign", assignee_id=users["electrician"].id).status_code == 200
    again = post(client, admin, f"/complaints/{cid}/assign", assignee_id=users["electrician2"].id)  # reassign
    assert again.status_code == 200 and again.json()["assigned_to"] == users["electrician2"].id and again.json()["status"] == "assigned"
    assert len([e for e in client.get(f"/complaints/{cid}/events", headers=admin).json() if e["event_type"] == "assigned"]) == 2


def test_inactive_worker_cannot_be_assigned(client, auth, users, cid, db):
    users["electrician"].is_active = False
    db.commit()
    assert post(client, auth(users["admin"]), f"/complaints/{cid}/assign", assignee_id=users["electrician"].id).status_code == 409


# ------------------------------------------------------------------ remarks
def test_remarks_appear_on_the_timeline_without_changing_status(client, auth, users, cid):
    post(client, auth(users["admin"]), f"/complaints/{cid}/assign", assignee_id=users["electrician"].id)
    r = post(client, auth(users["faculty"]), f"/complaints/{cid}/remarks", text="Please come after 2 pm")
    assert r.status_code == 201 and r.json()["old_status"] == r.json()["new_status"] == "assigned"
    assert post(client, auth(users["electrician"]), f"/complaints/{cid}/remarks", text="Will do").status_code == 201
    got = [h["remarks"] for h in client.get(f"/complaints/{cid}/timeline", headers=auth(users["admin"])).json()]
    assert "Please come after 2 pm" in got and "Will do" in got
    assert any("remark" in n["title"].lower() for n in client.get("/notifications", headers=auth(users["electrician"])).json())


@pytest.mark.parametrize("text,code", [("", 422), ("   ", 409), ("x" * 1001, 422)])
def test_remark_validation(client, auth, users, cid, text, code):
    assert post(client, auth(users["faculty"]), f"/complaints/{cid}/remarks", text=text).status_code == code


def test_uninvolved_users_cannot_comment_or_read_the_timeline(client, auth, users, cid):
    assert post(client, auth(users["staff"]), f"/complaints/{cid}/remarks", text="hi").status_code == 403
    assert client.get(f"/complaints/{cid}/timeline", headers=auth(users["staff"])).status_code == 403


# ------------------------------------------------------------------ routing rules
def test_routing_rules_decide_the_department(client, auth, users, db):
    admin = auth(users["admin"])
    rules = {r["category"]: r for r in client.get("/routing-rules", headers=admin).json()}
    assert set(rules) == {c.value for c in Category}
    civil_dept = users["civil"].department_id
    assert client.put("/routing-rules/electrical", json={"department_id": civil_dept}, headers=admin).status_code == 200
    c = client.post("/complaints", json=BODY, headers=auth(users["faculty"])).json()
    assert c["responsible_department_id"] == civil_dept


def test_inactive_or_null_rule_falls_back_to_the_reporters_department(client, auth, users):
    admin = auth(users["admin"])
    client.put("/routing-rules/electrical", json={"department_id": None, "is_active": True}, headers=admin)
    c = client.post("/complaints", json=BODY, headers=auth(users["faculty"])).json()
    assert c["responsible_department_id"] == users["faculty"].department_id
    client.put("/routing-rules/electrical", json={"department_id": users["civil"].department_id, "is_active": False}, headers=admin)
    c2 = client.post("/complaints", json=BODY, headers=auth(users["faculty"])).json()
    assert c2["responsible_department_id"] == users["faculty"].department_id


def test_routing_rule_validation(client, auth, users):
    admin = auth(users["admin"])
    assert client.put("/routing-rules/electrical", json={"department_id": 9999}, headers=admin).status_code == 404
    assert client.put("/routing-rules/magic", json={}, headers=admin).status_code == 422


# ------------------------------------------------------------------ escalation scheduler on real complaints
def test_overdue_complaints_escalate_through_three_levels_and_resolved_ones_do_not(db, users, detector):
    c = cs.register_complaint(db, reporter_id=users["faculty"].id, title="Wifi down", description="wifi is down in the entire CSE block",
                              detector=detector, now=T0)
    cs.assign_complaint(db, c.id, users["network"].id, now=T0)
    window = timedelta(hours=c.sla_hours)
    assert run_sla_check(db, T0 + window * 0.5).escalated == {}
    assert run_sla_check(db, T0 + window * 0.8).warned == [c.id]
    assert run_sla_check(db, T0 + window * 1.01).escalated == {c.id: 1}
    assert run_sla_check(db, T0 + window * 1.6).escalated == {c.id: 2}
    assert run_sla_check(db, T0 + window * 2.1).escalated == {c.id: 3}
    assert run_sla_check(db, T0 + window * 5).escalated == {}  # levels only go up
    n_events = len([e for e in cs.get_events(db, c.id) if e.event_type.startswith("escalat")])
    run_sla_check(db, T0 + window * 5)
    assert len([e for e in cs.get_events(db, c.id) if e.event_type.startswith("escalat")]) == n_events  # no duplicates

    done = cs.register_complaint(db, reporter_id=users["faculty"].id, title="Fan broken", description="Fan broken in room", detector=detector, now=T0)
    cs.assign_complaint(db, done.id, users["electrician"].id, now=T0)
    cs.change_status(db, done.id, S.IN_PROGRESS)
    cs.change_status(db, done.id, S.RESOLVED)
    assert done.id not in run_sla_check(db, T0 + timedelta(days=60)).escalated


def test_changing_priority_through_review_resets_the_sla(db, users, detector):
    c = cs.register_complaint(db, reporter_id=users["faculty"].id, title="Wifi slow", description="wifi is slow in one room", detector=detector, now=T0)
    pred = db.query(__import__("app.models", fromlist=["AIPrediction"]).AIPrediction).filter_by(complaint_id=c.id).one()
    pred.needs_manual_review = True
    db.commit()
    cs.review_prediction(db, pred.id, users["admin"].id, confirm=False, category=Category.NETWORKING,
                         priority=__import__("app.core.enums", fromlist=["Priority"]).Priority.CRITICAL, now=T0)
    assert c.sla_hours == 4 and c.escalation_level == 0
