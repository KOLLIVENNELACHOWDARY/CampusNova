from datetime import timedelta

import pytest

from app.core.enums import Category, ComplaintStatus as S, Priority as P
from tests import compat as cs
from app.services.dashboard_aggregator import DashboardAggregator
from app.services.escalation import run_sla_check
from tests.conftest import T0

WIFI = ("Wifi down", "wifi is down in the entire CSE block")  # HIGH, networking
SPARK = ("Sparks from switch board", "Sparks coming from the switch board in the physics lab")  # CRITICAL, electrical
FLICKER = ("Tube light flickering", "Tube light in room 204 is flickering")  # LOW, electrical


def add(db, users, detector, spec, now=T0, location=""):
    return cs.register_complaint(db, reporter_id=users["faculty"].id, title=spec[0], description=spec[1],
                                 location=location, detector=detector, now=now)


def test_empty_database(db):
    d = DashboardAggregator(db).admin_overview(T0)
    assert (d.total_complaints, d.open_complaints, d.overdue_complaints, d.avg_resolution_hours) == (0, 0, 0, None)
    assert len(d.by_status) == 5 and len(d.by_priority) == 4 and len(d.by_category) == 6  # zero-filled
    assert d.is_stub is False
    assert DashboardAggregator(db).institution_analytics(30, T0).sla_compliance_pct is None


def test_admin_overview_numbers(db, users, detector):
    a = add(db, users, detector, WIFI)
    b = add(db, users, detector, SPARK)
    c = add(db, users, detector, FLICKER)
    cs.assign_complaint(db, a.id, users["maint"].id, now=T0)
    cs.change_status(db, a.id, S.IN_PROGRESS, now=T0 + timedelta(hours=1))
    cs.change_status(db, a.id, S.RESOLVED, now=T0 + timedelta(hours=5))  # took 5h
    run_sla_check(db, T0 + timedelta(hours=10))  # SPARK (4h SLA) is now overdue, still unassigned

    d = DashboardAggregator(db).admin_overview(T0 + timedelta(hours=10))
    assert (d.total_complaints, d.open_complaints) == (3, 2)
    assert (d.overdue_complaints, d.critical_open, d.escalated_open, d.unassigned_open) == (1, 1, 1, 2)
    assert d.avg_resolution_hours == 5.0
    assert {x.status: x.count for x in d.by_status}[S.RESOLVED] == 1
    assert {x.priority: x.count for x in d.by_priority} == {P.LOW: 1, P.MEDIUM: 0, P.HIGH: 1, P.CRITICAL: 1}
    assert {x.category: x.count for x in d.by_category}[Category.ELECTRICAL] == 2


def test_pending_ai_reviews_counter(db, users, detector):
    add(db, users, detector, ("asdfgh qwerty", "zxcvb lkjhg"))
    assert DashboardAggregator(db).admin_overview(T0).pending_ai_reviews == 1


def test_maintenance_workload(db, users, detector):
    a, b, c = (add(db, users, detector, s) for s in (WIFI, SPARK, FLICKER))
    for x in (a, b, c):
        cs.assign_complaint(db, x.id, users["maint"].id, now=T0)
    cs.change_status(db, b.id, S.IN_PROGRESS, now=T0)
    cs.change_status(db, c.id, S.IN_PROGRESS, now=T0)
    cs.change_status(db, c.id, S.RESOLVED, now=T0 + timedelta(hours=2))
    w = DashboardAggregator(db).maintenance_workload(users["maint"].id, T0 + timedelta(hours=3))
    assert (w.assigned, w.in_progress, w.resolved_today) == (1, 1, 1)
    assert [t.complaint_id for t in w.tasks] == [b.id, a.id]  # most urgent first, resolved task excluded
    assert w.tasks[0].priority == P.CRITICAL and w.tasks[0].sla_deadline is not None
    other = DashboardAggregator(db).maintenance_workload(users["maint2"].id, T0)
    assert (other.assigned, other.tasks) == (0, [])
    assert DashboardAggregator(db).maintenance_workload(users["maint"].id, T0 + timedelta(days=1)).resolved_today == 0


def test_institution_analytics(db, users, detector):
    a = add(db, users, detector, FLICKER, location="CSE block")
    b = add(db, users, detector, FLICKER, location="cse block ")
    c = add(db, users, detector, FLICKER, location="CSE Block")
    d = add(db, users, detector, WIFI, location="Library")
    old = add(db, users, detector, WIFI, now=T0 - timedelta(days=60))  # outside the 30-day window
    for x, hrs in ((a, 10), (b, 200)):  # a on time (168h SLA), b late
        cs.assign_complaint(db, x.id, users["maint"].id, now=T0)
        cs.change_status(db, x.id, S.IN_PROGRESS, now=T0)
        cs.change_status(db, x.id, S.RESOLVED, now=T0 + timedelta(hours=hrs))
    r = DashboardAggregator(db).institution_analytics(30, T0 + timedelta(days=10))
    assert r.complaints_in_period == 4
    assert r.sla_compliance_pct == 50.0
    trends = {t.category: t for t in r.category_trends}
    assert trends[Category.ELECTRICAL].count == 3 and trends[Category.ELECTRICAL].avg_resolution_hours == 105.0
    assert trends[Category.NETWORKING].count == 1 and trends[Category.NETWORKING].avg_resolution_hours is None
    assert r.repeat_issue_locations == ["CSE block, G (electrical x3)"]  # same place + category, case-insensitive
    assert DashboardAggregator(db).institution_analytics(90, T0 + timedelta(days=10)).complaints_in_period == 5
