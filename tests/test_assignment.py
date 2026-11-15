"""Auto-assignment by department and workload, worker self-service (claim / release), the scheduler safety net,
and the same flows through the HTTP API with real sign-in."""
from datetime import timedelta

import pytest

from app.core.enums import Category, ComplaintStatus, Priority, UserRole
from app.models import AIPrediction, Complaint, Notification, User
from app.services import assignment as asg
from tests import compat as cs
from tests.conftest import T0


@pytest.fixture()
def crew(users):
    return {"reporter": users["faculty"], "admin": users["admin"], "spark1": users["electrician"], "spark2": users["electrician2"],
            "plumber": users["plumber"], "netguy": users["network"], "civil": users["civil"]}


def file(db, crew, title, category, detector, *, now=T0, auto=True, desc=""):
    return cs.register_complaint(db, reporter_id=crew["reporter"].id, title=title, description=desc or title,
                                 category=category, detector=detector, now=now, auto_assign=auto)


def assignee(db, c):
    db.refresh(c)
    return db.get(User, c.assigned_to) if c.assigned_to else None


def deactivate_all(db):
    for u in db.query(User).filter(User.role == UserRole.MAINTENANCE):
        u.is_active = False
    db.commit()


# ------------------------------------------------------------------ routing
@pytest.mark.parametrize("category,who", [
    (Category.ELECTRICAL, {"electrician@campusnova.edu", "electrician2@campusnova.edu"}),
    (Category.SANITATION, {"plumber@campusnova.edu"}), (Category.NETWORKING, {"network@campusnova.edu"}),
    (Category.CIVIL, {"civil@campusnova.edu"}),
])
def test_goes_to_the_responsible_department(db, crew, detector, category, who):
    c = file(db, crew, "Something is broken here", category, detector)
    assert assignee(db, c).email in who and c.status == ComplaintStatus.ASSIGNED
    event = cs.get_events(db, c.id)[-1]
    assert event.event_type == "assigned" and event.actor_id is None and "Auto-assigned by AI" in event.note


def test_assignment_row_is_marked_auto(db, crew, detector):
    from app.models import Assignment

    c = file(db, crew, "Fan not working in room", Category.ELECTRICAL, detector)
    row = db.query(Assignment).filter_by(complaint_id=c.id).one()
    assert row.assignment_type == "auto" and row.assigned_by is None and row.assigned_to == c.assigned_to


def test_worker_and_reporter_are_told(db, crew, detector):
    file(db, crew, "Plumbing leak near the lab", Category.SANITATION, detector)
    mine = [n.title for n in db.query(Notification).filter(Notification.user_id == crew["plumber"].id)]
    theirs = [n.title for n in db.query(Notification).filter(Notification.user_id == crew["reporter"].id)]
    assert any("New task" in t for t in mine) and any("assigned" in t for t in theirs)


def test_each_job_goes_to_the_least_busy_matching_worker(db, crew, detector):
    for i in range(6):
        before = {n: asg.worker_load(db, crew[n].id) for n in ("spark1", "spark2")}
        least = min(before, key=lambda n: (before[n], crew[n].id))
        c = file(db, crew, f"Fan {i} not working in the room", Category.ELECTRICAL, detector)
        assert assignee(db, c).id == crew[least].id


def test_critical_jobs_weigh_more_than_low_ones(db, crew, detector):
    def job(worker, priority):
        db.add(cs.Complaint(title="t", description="d", category=Category.ELECTRICAL, priority=priority, reported_by=crew["reporter"].id,
                            assigned_to=crew[worker].id, status=ComplaintStatus.IN_PROGRESS, sla_hours=24,
                            sla_due_at=T0 + timedelta(hours=24)))
    job("spark1", Priority.CRITICAL)  # load 4, one job
    job("spark2", Priority.LOW)
    job("spark2", Priority.LOW)  # load 2, two jobs
    db.commit()
    c = file(db, crew, "Tube light is flickering", Category.ELECTRICAL, detector)
    assert assignee(db, c).id == crew["spark2"].id


def test_falls_back_to_the_least_busy_worker_when_the_department_has_nobody(db, crew, detector):
    c = file(db, crew, "Lab bench broken", Category.LABORATORY, detector)  # routes to the reporter's own dept (CSE): no workers
    assert assignee(db, c) is not None and "least busy" in cs.get_events(db, c.id)[-1].note
    for k in ("spark1", "spark2"):
        crew[k].is_active = False
    db.commit()
    c2 = file(db, crew, "Socket not working", Category.ELECTRICAL, detector)  # whole electrical crew inactive
    assert assignee(db, c2).id in {crew["plumber"].id, crew["netguy"].id, crew["civil"].id}


def test_no_active_workers_is_not_an_error(db, crew, detector):
    deactivate_all(db)
    c = file(db, crew, "Nobody can fix this", Category.ELECTRICAL, detector)
    assert c.assigned_to is None and c.status == ComplaintStatus.REGISTERED


def test_auto_assign_is_off_unless_asked(db, crew, detector):
    assert file(db, crew, "Fan not working", Category.ELECTRICAL, detector, auto=False).assigned_to is None


# ------------------------------------------------------------------ AI review interplay
def test_flagged_complaints_wait_for_the_admin_then_get_assigned(db, crew, detector):
    c = cs.register_complaint(db, reporter_id=crew["reporter"].id, title="asdfgh qwerty", description="zxcvb lkjhg",
                              detector=detector, now=T0, auto_assign=True)
    assert c.needs_manual_review and c.assigned_to is None
    assert not asg.is_claimable(c) and c not in asg.open_pool(db)
    pred = cs.pending_reviews(db)[0]
    cs.review_prediction(db, pred.id, crew["admin"].id, confirm=False, category=Category.NETWORKING,
                         priority=Priority.HIGH, notes="wifi", auto_assign=True)
    assert assignee(db, c).id == crew["netguy"].id
    assert c.responsible_department_id == crew["netguy"].department_id  # re-routed with the corrected category


def test_safety_risks_are_never_held_back():
    c = cs.Complaint(status=ComplaintStatus.REGISTERED, assigned_to=None, needs_manual_review=True, safety_risk=True)
    assert asg.is_claimable(c)


def test_only_admins_may_review(db, crew, detector):
    c = cs.register_complaint(db, reporter_id=crew["reporter"].id, title="asdfgh qwerty", description="zxcvb lkjhg",
                              detector=detector, now=T0)
    pred = cs.pending_reviews(db)[0]
    with pytest.raises(PermissionError):
        cs.review_prediction(db, pred.id, crew["spark1"].id, confirm=True)


def test_changing_the_category_moves_a_job_that_has_not_started(db, crew, detector):
    c = file(db, crew, "Water near the socket", Category.ELECTRICAL, detector)
    pred = db.query(AIPrediction).filter_by(complaint_id=c.id).one()
    pred.needs_manual_review = True
    db.commit()
    assert assignee(db, c).id in {crew["spark1"].id, crew["spark2"].id}
    cs.review_prediction(db, pred.id, crew["admin"].id, confirm=False, category=Category.SANITATION, priority=c.priority,
                         notes="it is a pipe", auto_assign=True)
    assert assignee(db, c).id == crew["plumber"].id

    started = file(db, crew, "Fan is noisy", Category.ELECTRICAL, detector)
    cs.change_status(db, started.id, ComplaintStatus.IN_PROGRESS, actor_id=started.assigned_to)
    worker = started.assigned_to
    pred2 = db.query(AIPrediction).filter_by(complaint_id=started.id).one()
    pred2.needs_manual_review = True
    db.commit()
    cs.review_prediction(db, pred2.id, crew["admin"].id, confirm=False, category=Category.NETWORKING, priority=started.priority,
                         auto_assign=True)
    assert started.assigned_to == worker  # work already started: never yanked away


# ------------------------------------------------------------------ claim / release
def test_pool_shows_own_department_first_and_claim_works_once(db, crew, detector):
    deactivate_all(db)  # nobody around when the complaints arrive
    low_net = file(db, crew, "Wifi slow in one room", Category.NETWORKING, detector)
    elec = file(db, crew, "Socket sparks badly", Category.ELECTRICAL, detector)
    for k in ("spark1", "netguy"):
        crew[k].is_active = True
    db.commit()
    pool_for_net = [c.id for c in asg.open_pool(db, crew["netguy"])]
    assert pool_for_net[0] == low_net.id and set(pool_for_net) == {low_net.id, elec.id}

    taken = asg.claim_complaint(db, elec.id, crew["spark1"].id, now=T0)
    assert taken.assigned_to == crew["spark1"].id and taken.status == ComplaintStatus.ASSIGNED
    from app.models import Assignment

    assert db.query(Assignment).filter_by(complaint_id=elec.id).one().assignment_type == "claimed"
    with pytest.raises(cs.BusinessRuleError, match="already taken by"):
        asg.claim_complaint(db, elec.id, crew["netguy"].id)
    with pytest.raises(PermissionError):
        asg.claim_complaint(db, low_net.id, crew["reporter"].id)
    assert [c.id for c in asg.open_pool(db)] == [low_net.id]


def test_cannot_claim_a_flagged_or_finished_complaint(db, crew, detector):
    flagged = cs.register_complaint(db, reporter_id=crew["reporter"].id, title="asdfgh qwerty", description="zxcvb lkjhg",
                                    detector=detector, now=T0)
    with pytest.raises(cs.BusinessRuleError, match="confirm the AI"):
        asg.claim_complaint(db, flagged.id, crew["spark1"].id)
    done = file(db, crew, "Fan not working", Category.ELECTRICAL, detector, auto=False)
    done.status = ComplaintStatus.CLOSED
    db.commit()
    with pytest.raises(cs.BusinessRuleError, match="closed"):
        asg.claim_complaint(db, done.id, crew["spark1"].id)


def test_release_returns_job_to_the_pool_and_not_back_to_the_same_worker(db, crew, detector):
    c = file(db, crew, "Tube light not working", Category.ELECTRICAL, detector)
    first = c.assigned_to
    with pytest.raises(PermissionError):
        asg.release_complaint(db, c.id, crew["plumber"].id)
    asg.release_complaint(db, c.id, first, "I am on leave today", now=T0)
    assert c.assigned_to is None and c.status == ComplaintStatus.REGISTERED and c in asg.open_pool(db)
    assert any(e.event_type == "released" and e.note == "I am on leave today" for e in cs.get_events(db, c.id))
    worker = asg.auto_assign(db, c.id, now=T0)  # AI picks again, but not the one who handed it back
    assert worker is not None and worker.id != first


def test_started_jobs_cannot_be_handed_back(db, crew, detector):
    c = file(db, crew, "Fan not working", Category.ELECTRICAL, detector)
    cs.change_status(db, c.id, ComplaintStatus.IN_PROGRESS, actor_id=c.assigned_to)
    with pytest.raises(cs.BusinessRuleError, match="not started"):
        asg.release_complaint(db, c.id, c.assigned_to)


# ------------------------------------------------------------------ scheduler safety net
def test_sweep_waits_for_the_grace_period_then_assigns(db, crew, detector):
    deactivate_all(db)
    c = file(db, crew, "Wifi down in the library", Category.NETWORKING, detector)
    assert c.assigned_to is None
    crew["netguy"].is_active = True
    db.commit()
    early = asg.sweep_unassigned(db, now=T0 + timedelta(minutes=5), grace_minutes=10)
    assert early["assigned"] == {} and early["still_waiting"] == 1  # give workers a chance to take it first
    late = asg.sweep_unassigned(db, now=T0 + timedelta(minutes=11), grace_minutes=10)
    assert late["assigned"] == {c.id: crew["netguy"].id} and late["still_waiting"] == 0
    assert asg.sweep_unassigned(db, now=T0 + timedelta(hours=1))["assigned"] == {}  # nothing left, nothing repeated


# ------------------------------------------------------------------ through the HTTP API
@pytest.fixture()
def api(client, detector, monkeypatch):
    monkeypatch.setattr("app.services.ai_service.get_default_detector", lambda: detector)
    monkeypatch.setenv("CAMPUSNOVA_AUTO_ASSIGN", "1")
    return client


def test_api_auto_assign_pool_claim_release(api, auth, users):
    r = api.post("/complaints", headers=auth(users["faculty"]), json={
        "title": "Sparks from switch board", "description": "Sparks coming from the switch board", "block": "Physics lab", "floor": "1"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "assigned" and body["assigned_to"] in (users["electrician"].id, users["electrician2"].id)
    cid, owner = body["id"], body["assigned_to"]
    owner_user = users["electrician"] if owner == users["electrician"].id else users["electrician2"]
    assert api.get("/complaints/pool", headers=auth(users["faculty"])).status_code == 403
    assert api.post(f"/complaints/{cid}/release", json={}, headers=auth(users["plumber"])).status_code == 403
    assert api.post(f"/complaints/{cid}/release", json={"reason": "busy"}, headers=auth(owner_user)).status_code == 200
    assert [c["id"] for c in api.get("/complaints/pool", headers=auth(users["electrician"])).json()] == [cid]
    taker = users["plumber"]
    assert api.post(f"/complaints/{cid}/claim", headers=auth(taker)).json()["assigned_to"] == taker.id
    assert api.post(f"/complaints/{cid}/claim", headers=auth(users["network"])).status_code == 409
    assert api.post(f"/complaints/{cid}/claim", headers=auth(users["faculty"])).status_code == 403
    assert api.get("/complaints/pool", headers=auth(users["electrician"])).json() == []


def test_api_admin_sweep_endpoint(api, auth, users):
    assert api.post("/admin/jobs/auto-assign", headers=auth(users["faculty"])).status_code == 403
    res = api.post("/admin/jobs/auto-assign", params={"minutes_ahead": 30}, headers=auth(users["admin"])).json()["result"]
    assert res == {"assigned": {}, "still_waiting": 0}
