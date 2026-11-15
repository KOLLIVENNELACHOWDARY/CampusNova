from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.enums import (
    Category, ComplaintStatus as S, NotificationChannel as Ch, NotificationType as Nt, PredictionSource, Priority as P,
)
from app.models import AIPrediction, ComplaintEvent, Notification
from tests import compat as cs
from tests.conftest import T0


def register(db, users, detector, title="Sparks from switch board", desc="Sparks coming from the switch board in the physics lab",
             location="Physics lab", **kw):
    return cs.register_complaint(db, reporter_id=users["faculty"].id, title=title, description=desc, location=location,
                                 detector=detector, now=kw.pop("now", T0), **kw)


def notifs(db, user, ntype=None):
    q = select(Notification).where(Notification.user_id == user.id, Notification.channel == Ch.IN_APP)
    if ntype:
        q = q.where(Notification.type == ntype)
    return list(db.scalars(q))


# ---------------------------------------------------------------- registration
def test_register_critical_complaint(db, users, detector):
    c = register(db, users, detector)
    assert (c.priority, c.category, c.safety_risk, c.status) == (P.CRITICAL, Category.ELECTRICAL, True, S.REGISTERED)
    assert c.sla_hours == 4 and c.sla_due_at.replace(tzinfo=None) == (T0 + timedelta(hours=4)).replace(tzinfo=None)
    pred = db.scalars(select(AIPrediction)).one()
    assert pred.source == PredictionSource.ML and pred.is_applied and pred.predicted_priority == P.CRITICAL
    assert pred.rationale["reasons"] and pred.input_text.startswith("Sparks")
    assert [e.event_type for e in cs.get_events(db, c.id)] == ["registered"]
    assert len(notifs(db, users["faculty"])) == 1  # confirmation to the reporter
    urgent = notifs(db, users["admin"], Nt.URGENT_ALERT)
    assert len(urgent) == 1 and "URGENT" in urgent[0].title
    assert len(notifs(db, users["admin2"], Nt.URGENT_ALERT)) == 1  # every admin is alerted
    assert notifs(db, users["maint"]) == []


def test_register_low_priority_does_not_alert_admins(db, users, detector):
    c = register(db, users, detector, "Tube light flickering", "Tube light in room 204 is flickering", "Room 204")
    assert c.priority == P.LOW and not c.safety_risk
    assert notifs(db, users["admin"], Nt.URGENT_ALERT) == []


def test_unclear_complaint_goes_to_review_queue(db, users, detector):
    c = register(db, users, detector, "asdfgh qwerty", "zxcvb lkjhg", location="")
    assert c.needs_manual_review and c.priority == P.MEDIUM
    assert [p.complaint_id for p in cs.pending_reviews(db)] == [c.id]
    assert any("AI review needed" in n.title for n in notifs(db, users["admin"]))


def test_register_without_a_trained_model_uses_rules(db, users, monkeypatch):
    monkeypatch.setattr("app.services.ai_service.get_default_detector", lambda: None)
    c = cs.register_complaint(db, reporter_id=users["faculty"].id, title="Sparks from switch board",
                              description="sparks near the lab", now=T0)
    assert c.priority == P.CRITICAL
    assert db.scalars(select(AIPrediction)).one().source == PredictionSource.RULE_BASED


@pytest.mark.parametrize("title,desc", [("", ""), ("12345", ""), ("aaaaaaaaaa", ""), ("x" * 3000, "")])
def test_invalid_text_is_rejected_and_nothing_is_saved(db, users, detector, title, desc):
    with pytest.raises(cs.ComplaintValidationError):
        register(db, users, detector, title, desc)
    assert cs.list_complaints(db) == [] and db.scalars(select(AIPrediction)).all() == []


def test_unknown_reporter(db, users, detector):
    with pytest.raises(cs.NotFoundError):
        cs.register_complaint(db, reporter_id=999, title="Fan not working", description="in room 3", detector=detector)


def test_explicit_category_is_kept(db, users, detector):
    c = register(db, users, detector, "Something is broken", "It is broken in the building", category=Category.CIVIL)
    assert c.category == Category.CIVIL


# ---------------------------------------------------------------- assignment and status
def test_assign_moves_to_assigned_and_notifies(db, users, detector):
    c = register(db, users, detector)
    cs.assign_complaint(db, c.id, users["maint"].id, users["admin"].id, now=T0)
    assert (c.status, c.assigned_to) == (S.ASSIGNED, users["maint"].id)
    task = notifs(db, users["maint"], Nt.ASSIGNMENT)
    assert len(task) == 1 and "Physics lab" in task[0].message
    assert any("assigned to Ravi" in n.message for n in notifs(db, users["faculty"]))
    assert [e.event_type for e in cs.get_events(db, c.id)] == ["registered", "assigned"]


@pytest.mark.parametrize("who", ["faculty", "staff", "admin"])
def test_only_maintenance_staff_can_be_assigned(db, users, detector, who):
    c = register(db, users, detector)
    with pytest.raises(cs.BusinessRuleError):
        cs.assign_complaint(db, c.id, users[who].id)


def test_reassign_keeps_status_and_closed_cannot_be_assigned(db, users, detector):
    c = register(db, users, detector)
    cs.assign_complaint(db, c.id, users["maint"].id)
    cs.change_status(db, c.id, S.IN_PROGRESS)
    cs.assign_complaint(db, c.id, users["maint2"].id)
    assert c.status == S.IN_PROGRESS and c.assigned_to == users["maint2"].id
    cs.change_status(db, c.id, S.RESOLVED)
    cs.change_status(db, c.id, S.CLOSED)
    with pytest.raises(cs.BusinessRuleError):
        cs.assign_complaint(db, c.id, users["maint"].id)


def test_status_lifecycle_and_timestamps(db, users, detector):
    c = register(db, users, detector)
    cs.assign_complaint(db, c.id, users["maint"].id)
    cs.change_status(db, c.id, S.IN_PROGRESS, users["maint"].id, now=T0 + timedelta(hours=1))
    cs.change_status(db, c.id, S.RESOLVED, users["maint"].id, "Replaced the switch board", now=T0 + timedelta(hours=3))
    assert c.resolved_at.replace(tzinfo=None) == (T0 + timedelta(hours=3)).replace(tzinfo=None)
    assert any("resolved" in n.title for n in notifs(db, users["faculty"]))
    cs.change_status(db, c.id, S.IN_PROGRESS, users["admin"].id, "Fault came back")  # reopen
    assert c.resolved_at is None
    cs.change_status(db, c.id, S.RESOLVED)
    cs.change_status(db, c.id, S.CLOSED)
    assert c.status == S.CLOSED
    assert [e.to_value for e in cs.get_events(db, c.id) if e.event_type == "status_changed"] == [
        "in_progress", "resolved", "in_progress", "resolved", "closed"]


@pytest.mark.parametrize("target", [S.IN_PROGRESS, S.RESOLVED, S.CLOSED, S.ASSIGNED, S.REGISTERED])
def test_cannot_skip_steps_from_registered(db, users, detector, target):
    c = register(db, users, detector)
    with pytest.raises(cs.BusinessRuleError):
        cs.change_status(db, c.id, target)


def test_closed_is_final(db, users, detector):
    c = register(db, users, detector)
    cs.assign_complaint(db, c.id, users["maint"].id)
    for s in (S.IN_PROGRESS, S.RESOLVED, S.CLOSED):
        cs.change_status(db, c.id, s)
    for s in S:
        with pytest.raises(cs.BusinessRuleError):
            cs.change_status(db, c.id, s)


def test_unknown_complaint(db, users):
    with pytest.raises(cs.NotFoundError):
        cs.change_status(db, 404, S.ASSIGNED)


# ---------------------------------------------------------------- AI review
def _flagged(db, users, detector):
    c = register(db, users, detector, "asdfgh qwerty", "zxcvb lkjhg", location="")
    return c, cs.pending_reviews(db)[0]


def test_confirm_keeps_the_ai_result(db, users, detector):
    c, pred = _flagged(db, users, detector)
    out = cs.review_prediction(db, pred.id, users["admin"].id, confirm=True, notes="looks right", now=T0)
    assert out.id == pred.id and pred.is_applied and pred.reviewed_by == users["admin"].id
    assert (pred.reviewed_category, pred.reviewed_priority) == (pred.predicted_category, pred.predicted_priority)
    assert not c.needs_manual_review and cs.pending_reviews(db) == []
    assert db.scalars(select(AIPrediction)).all().__len__() == 1


def test_override_appends_a_manual_prediction_and_resets_sla(db, users, detector):
    c, pred = _flagged(db, users, detector)
    c.sla_warned, c.escalation_level = True, 2
    db.commit()
    new = cs.review_prediction(db, pred.id, users["admin"].id, confirm=False, category=Category.NETWORKING,
                               priority=P.HIGH, notes="wifi issue", now=T0 + timedelta(hours=1))
    assert new.source == PredictionSource.MANUAL and new.is_applied and new.predicted_priority == P.HIGH
    assert pred.is_applied is False and pred.reviewed_priority == P.HIGH  # history kept, no longer applied
    assert (c.category, c.priority, c.sla_hours) == (Category.NETWORKING, P.HIGH, 24)
    assert c.sla_due_at.replace(tzinfo=None) == (T0 + timedelta(hours=24)).replace(tzinfo=None)  # from filing time
    assert (c.sla_warned, c.escalation_level, c.needs_manual_review) == (False, 0, False)
    assert any("updated after review" in n.title for n in notifs(db, users["faculty"]))
    assert cs.pending_reviews(db) == []
    assert cs.get_events(db, c.id)[-1].event_type == "ai_review"


def test_override_with_same_values_counts_as_confirmation(db, users, detector):
    c, pred = _flagged(db, users, detector)
    cs.review_prediction(db, pred.id, users["admin"].id, confirm=False, category=pred.predicted_category,
                         priority=pred.predicted_priority)
    assert len(db.scalars(select(AIPrediction)).all()) == 1 and pred.is_applied


def test_only_admins_review_and_only_once(db, users, detector):
    c, pred = _flagged(db, users, detector)
    for who in ("faculty", "maint"):
        with pytest.raises(PermissionError):
            cs.review_prediction(db, pred.id, users[who].id, confirm=True)
    cs.review_prediction(db, pred.id, users["admin"].id, confirm=True)
    with pytest.raises(cs.BusinessRuleError):
        cs.review_prediction(db, pred.id, users["admin"].id, confirm=True)
    with pytest.raises(cs.NotFoundError):
        cs.review_prediction(db, 999, users["admin"].id, confirm=True)


# ---------------------------------------------------------------- queries
def test_list_complaints_orders_by_priority_and_filters(db, users, detector):
    low = register(db, users, detector, "Tube light flickering", "Tube light in room 204 is flickering", "Room 204",
                   now=T0)
    crit = register(db, users, detector, now=T0 + timedelta(minutes=5))
    assert [c.id for c in cs.list_complaints(db)] == [crit.id, low.id]
    cs.assign_complaint(db, crit.id, users["maint"].id)
    assert [c.id for c in cs.list_complaints(db, assignee_id=users["maint"].id)] == [crit.id]
    assert len(cs.list_complaints(db, reporter_id=users["staff"].id)) == 0
    cs.change_status(db, crit.id, S.IN_PROGRESS)
    cs.change_status(db, crit.id, S.RESOLVED)
    assert [c.id for c in cs.list_complaints(db, open_only=True)] == [low.id]
    assert cs.count_open(db) == 1
