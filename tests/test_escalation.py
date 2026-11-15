from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.enums import ComplaintStatus as S, NotificationChannel as Ch, NotificationType as Nt
from app.models import Complaint, ComplaintEvent, Notification
from tests import compat as cs
from app.services.escalation import SlaCheckResult, escalation_level_for, find_overdue, run_sla_check
from tests.conftest import T0

H = timedelta(hours=1)


@pytest.fixture()
def high(db, users, detector):
    """A HIGH priority complaint (24h SLA), assigned to Mohan, filed at T0."""
    c = cs.register_complaint(db, reporter_id=users["faculty"].id, title="Wifi down",
                              description="wifi is down in the entire CSE block", detector=detector, now=T0)
    assert c.sla_hours == 24, c.priority
    cs.assign_complaint(db, c.id, users["maint"].id, users["admin"].id, now=T0)
    return c


def inbox(db, user, ntype):
    return list(db.scalars(select(Notification).where(Notification.user_id == user.id, Notification.type == ntype,
                                                      Notification.channel == Ch.IN_APP)))


@pytest.mark.parametrize(
    "late_hours,expected", [(-5, 0), (0, 0), (0.01, 1), (11.9, 1), (12, 2), (23.9, 2), (24, 3), (100, 3)])
def test_level_boundaries(late_hours, expected):
    assert escalation_level_for(timedelta(hours=late_hours), timedelta(hours=24)) == expected


def test_no_action_early_in_the_window(db, high):
    r = run_sla_check(db, T0 + 2 * H)
    assert r == SlaCheckResult(checked=1, overdue=0, warned=[], escalated={})
    assert high.sla_warned is False


def test_warning_goes_to_the_assignee_once(db, users, high):
    r = run_sla_check(db, T0 + 19 * H)  # 5h left of 24h = 20.8% <= 25%
    assert r.warned == [high.id] and high.sla_warned
    warn = inbox(db, users["maint"], Nt.SLA_WARNING)
    assert len(warn) == 1 and "due in 5.0h" in warn[0].message
    assert inbox(db, users["admin"], Nt.SLA_WARNING) == []
    assert run_sla_check(db, T0 + 20 * H).warned == []  # not repeated
    assert len(inbox(db, users["maint"], Nt.SLA_WARNING)) == 1


def test_warning_for_unassigned_complaint_goes_to_admins(db, users, detector):
    c = cs.register_complaint(db, reporter_id=users["faculty"].id, title="Wifi down",
                              description="wifi is down in the entire CSE block", detector=detector, now=T0)
    run_sla_check(db, T0 + 20 * H)
    msg = inbox(db, users["admin"], Nt.SLA_WARNING)[0].message
    assert "unassigned" in msg and len(inbox(db, users["admin2"], Nt.SLA_WARNING)) == 1


def test_escalation_ladder(db, users, high):
    run_sla_check(db, T0 + 19 * H)
    assert run_sla_check(db, T0 + 25 * H).escalated == {high.id: 1}
    esc1 = inbox(db, users["admin"], Nt.ESCALATION)
    assert len(esc1) == 1 and "L1" in esc1[0].title and "1.0h past" in esc1[0].message
    assert len(inbox(db, users["maint"], Nt.ESCALATION)) == 1  # the assignee is told too
    assert inbox(db, users["faculty"], Nt.STATUS_UPDATE)[-1].title.endswith("assigned")  # reporter not yet told

    assert run_sla_check(db, T0 + 30 * H).escalated == {}  # same level: no repeat
    assert run_sla_check(db, T0 + 37 * H).escalated == {high.id: 2}  # 13h late >= 12h
    assert not any("escalated" in n.title for n in inbox(db, users["faculty"], Nt.STATUS_UPDATE))
    assert run_sla_check(db, T0 + 49 * H).escalated == {high.id: 3}  # 25h late >= 24h
    assert any("escalated" in n.title for n in inbox(db, users["faculty"], Nt.STATUS_UPDATE))  # reporter told at L3
    assert run_sla_check(db, T0 + 400 * H).escalated == {}  # top of the ladder
    assert (high.escalation_level, len(inbox(db, users["admin"], Nt.ESCALATION))) == (3, 3)
    events = [(e.event_type, e.to_value) for e in db.scalars(select(ComplaintEvent)) if e.event_type == "escalated"]
    assert events == [("escalated", "L1"), ("escalated", "L2"), ("escalated", "L3")]


def test_jump_straight_to_level_3_after_downtime(db, users, high):
    assert run_sla_check(db, T0 + 100 * H).escalated == {high.id: 3}  # scheduler was down for days
    assert len(inbox(db, users["admin"], Nt.ESCALATION)) == 1  # one alert, not three


def test_unassigned_overdue_is_flagged_for_admins(db, users, detector):
    c = cs.register_complaint(db, reporter_id=users["faculty"].id, title="Wifi down",
                              description="wifi is down in the entire CSE block", detector=detector, now=T0)
    run_sla_check(db, T0 + 25 * H)
    assert "UNASSIGNED" in inbox(db, users["admin"], Nt.ESCALATION)[0].message
    assert inbox(db, users["maint"], Nt.ESCALATION) == []


def test_resolved_complaints_are_never_escalated(db, users, high):
    cs.change_status(db, high.id, S.IN_PROGRESS, now=T0 + H)
    cs.change_status(db, high.id, S.RESOLVED, now=T0 + 2 * H)
    r = run_sla_check(db, T0 + 100 * H)
    assert r.checked == 0 and r.escalated == {} and find_overdue(db, T0 + 100 * H) == []


def test_running_twice_at_the_same_moment_never_duplicates(db, users, high):
    run_sla_check(db, T0 + 25 * H)
    high.escalation_level = 0  # simulate a lost update / a second scheduler instance
    db.commit()
    run_sla_check(db, T0 + 25 * H)
    assert len(inbox(db, users["admin"], Nt.ESCALATION)) == 1  # dedupe key protects the recipients


def test_changing_priority_gives_a_fresh_warning_and_escalation_cycle(db, users, high):
    from app.core.enums import Priority

    run_sla_check(db, T0 + 25 * H)
    assert high.escalation_level == 1
    pred = cs.pending_reviews(db)  # none: ML was confident
    p = db.scalars(select(__import__("app.models", fromlist=["AIPrediction"]).AIPrediction)).first()
    p.needs_manual_review = True
    db.commit()
    cs.review_prediction(db, p.id, users["admin"].id, confirm=False, priority=Priority.LOW, now=T0 + 26 * H)
    assert (high.sla_hours, high.escalation_level, high.sla_warned) == (168, 0, False)
    assert run_sla_check(db, T0 + 27 * H).overdue == 0  # LOW gives 7 days from filing


def test_find_overdue_is_sorted_most_overdue_first(db, users, detector):
    a = cs.register_complaint(db, reporter_id=users["faculty"].id, title="Wifi down", description="wifi is down in the entire CSE block",
                              detector=detector, now=T0)
    b = cs.register_complaint(db, reporter_id=users["faculty"].id, title="Wifi down", description="wifi is down in the entire CSE block",
                              detector=detector, now=T0 + 5 * H)
    assert [c.id for c in find_overdue(db, T0 + 40 * H)] == [a.id, b.id]
    assert [c.id for c in find_overdue(db, T0 + 26 * H)] == [a.id]
