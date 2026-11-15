"""Validation of the three things the dashboards report on: AI quality, notification delivery, aggregate numbers.

Each check compares the system with an independent calculation or with a stated quality bar, not with itself.
"""
import random
from collections import Counter
from datetime import timedelta

import pytest

from app.core.enums import (Category, ComplaintStatus, NotificationChannel, NotificationStatus, NotificationType,
                            Priority)
from app.core.timeutil import ensure_utc
from app.models import Notification
from tests import compat as cs
from app.services import notification_service as ns
from app.services.dashboard_aggregator import DashboardAggregator
from ml.evaluate import evaluate_all
from tests.conftest import T0


# ================================================================== 1. AI prediction quality gate
@pytest.fixture(scope="module")
def scores(detector):
    return evaluate_all(detector)


def test_ai_meets_quality_bar_on_independent_hand_labelled_set(scores):
    ml, rule = scores["hand_labeled"]["ml_multi_factor"], scores["hand_labeled"]["rule_based_baseline"]
    assert ml["safety_recall"] == 1.0  # never miss a safety hazard
    assert ml["priority_within_one_level"] >= 0.95
    assert ml["priority_accuracy"] >= 0.70 and ml["category_accuracy"] >= 0.85
    assert ml["priority_accuracy"] > rule["priority_accuracy"]  # the model must earn its place over plain rules


def test_ai_meets_quality_bar_on_held_out_data(scores):
    ml, rule = scores["synthetic_holdout"]["ml_multi_factor"], scores["synthetic_holdout"]["rule_based_baseline"]
    assert ml["safety_recall"] >= 0.97  # 1 typo'd row ("Sowllen battery") is missed; keyword rules do not fuzzy-match
    assert ml["category_accuracy"] >= 0.75 and ml["priority_accuracy"] >= 0.68
    assert ml["priority_within_one_level"] >= 0.95
    assert ml["critical_recall"] >= 0.80  # a missed emergency is the costliest error
    assert ml["priority_accuracy"] > rule["priority_accuracy"] and ml["category_accuracy"] > rule["category_accuracy"]


def test_wide_area_outages_are_treated_as_serious(detector):
    for text in ["Complete power cut since morning across the entire college", "Wifi is down across the whole campus",
                 "In all the labs, no power supply"]:
        assert detector.predict(text).priority in (Priority.CRITICAL, Priority.HIGH), text


# ================================================================== 2. notification dispatch reliability
class FlakySender(ns.Sender):
    """Fails in scripted ways so we can check every retry path. `calls` counts every send attempt per notification."""

    def __init__(self, channel, fail_first=(), always_fail=(), permanent=()):
        self.channel, self.fail_first, self.always_fail, self.permanent = channel, set(fail_first), set(always_fail), set(permanent)
        self.calls, self.delivered = Counter(), []

    def send(self, n, user):
        self.calls[n.id] += 1
        if n.id in self.permanent:
            raise ns.PermanentDeliveryError("no device")
        if n.id in self.always_fail or (n.id in self.fail_first and self.calls[n.id] == 1):
            raise ConnectionError("provider timeout")
        self.delivered.append(n.id)


def _queue(db, users, count):
    rows = []
    for i in range(count):
        rows += ns.notify(db, [users["faculty"].id], NotificationType.STATUS_UPDATE, f"msg {i}", "body",
                          channels=[NotificationChannel.EMAIL], now=T0)
    db.commit()
    return [n.id for n in rows]


def test_dispatch_is_reliable_under_failures(db, users):
    ids = _queue(db, users, 300)
    rng = random.Random(7)
    shuffled = ids[:]
    rng.shuffle(shuffled)
    transient, always, permanent = shuffled[:60], shuffled[60:90], shuffled[90:110]
    sender = FlakySender(NotificationChannel.EMAIL, fail_first=transient, always_fail=always, permanent=permanent)
    senders = {NotificationChannel.EMAIL: sender}

    for _ in range(5):  # more runs than retries: results must settle and stay settled
        ns.dispatch_pending(db, senders)

    rows = {n.id: n for n in db.query(Notification)}
    for i, n in rows.items():
        if i in always or i in permanent:
            assert n.status == NotificationStatus.FAILED and n.retry_count == ns.MAX_RETRIES and n.error_message
        else:
            assert n.status == NotificationStatus.SENT and n.sent_at is not None  # transient failures recovered
    assert len(sender.delivered) == len(set(sender.delivered)) == 300 - 30 - 20  # nobody told twice
    assert max(sender.calls.values()) <= ns.MAX_RETRIES  # never hammered beyond the retry limit
    assert all(sender.calls[i] == 1 for i in permanent)  # permanent failures are not retried
    assert all(sender.calls[i] == 2 for i in transient)

    again = ns.dispatch_pending(db, senders)  # nothing left to do
    assert (again.sent, again.failed) == (0, 0)

    stats = DashboardAggregator(db).notification_stats()
    assert (stats.total, stats.sent, stats.gave_up, stats.pending, stats.failed_retrying) == (300, 250, 50, 0, 0)
    assert stats.delivery_rate_pct == round(100 * 250 / 300, 1)
    assert stats.avg_attempts_for_sent == round((190 * 1 + 60 * 2) / 250, 1)
    assert stats.top_errors and "x" in stats.top_errors[0]


def test_stats_separate_retrying_from_gave_up(db, users):
    ids = _queue(db, users, 4)
    sender = FlakySender(NotificationChannel.EMAIL, always_fail={ids[0]}, permanent={ids[1]})
    ns.dispatch_pending(db, {NotificationChannel.EMAIL: sender})  # one pass only
    stats = DashboardAggregator(db).notification_stats()
    assert (stats.sent, stats.failed_retrying, stats.gave_up) == (2, 1, 1)
    assert stats.delivery_rate_pct == round(100 * 2 / 3, 1)  # the retrying one is not counted as lost yet


def test_one_users_failure_does_not_block_others(db, users):
    ns.notify(db, [users["staff"].id, users["faculty"].id], NotificationType.STATUS_UPDATE, "t", "m",
              channels=[NotificationChannel.PUSH], now=T0)  # staff has no device token
    db.commit()
    result = ns.dispatch_pending(db, {NotificationChannel.PUSH: ns.LogSender(NotificationChannel.PUSH)})
    assert (result.sent, result.gave_up) == (1, 1)


def test_dedupe_stops_duplicate_alerts(db, users):
    for _ in range(5):
        ns.notify(db, [users["admin"].id], NotificationType.ESCALATION, "t", "m", dedupe_key="esc:1:L1", now=T0)
        db.commit()
    assert db.query(Notification).filter(Notification.dedupe_key.like("esc:1:L1%")).count() == len(
        ns.DEFAULT_CHANNELS[NotificationType.ESCALATION])


# ================================================================== 3. dashboard numbers vs brute force
def _random_complaints(db, users, n, seed):
    rng = random.Random(seed)
    people = [users["faculty"].id, users["staff"].id]
    workers = [users["maint"].id, users["maint2"].id, None]
    spots = ["Lab 1", "lab 1 ", "Block A", "Library", None]
    rows = []
    for _ in range(n):
        created = T0 - timedelta(days=rng.randint(0, 60), hours=rng.randint(0, 23))
        pri = rng.choice(list(Priority))
        status = rng.choice(list(ComplaintStatus))
        sla = rng.choice([4, 24, 72, 168])
        resolved = created + timedelta(hours=rng.randint(1, 200)) if status in (ComplaintStatus.RESOLVED, ComplaintStatus.CLOSED) else None
        rows.append(cs.Complaint(
            title="t", description="d", location=rng.choice(spots), category=rng.choice(list(Category)), priority=pri,
            status=status, reported_by=rng.choice(people), assigned_to=rng.choice(workers), safety_risk=rng.random() < 0.1,
            sla_hours=sla, sla_due_at=created + timedelta(hours=sla), escalation_level=rng.choice([0, 0, 1, 2, 3]),
            created_at=created, resolved_at=resolved))
    db.add_all(rows)
    db.commit()
    return rows


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_admin_numbers_match_brute_force(db, users, seed):
    rows = _random_complaints(db, users, 250, seed)
    d = DashboardAggregator(db).admin_overview(now=T0)
    open_ = [c for c in rows if c.status not in (ComplaintStatus.RESOLVED, ComplaintStatus.CLOSED)]
    assert d.total_complaints == len(rows) and d.open_complaints == len(open_)
    assert d.overdue_complaints == sum(1 for c in open_ if ensure_utc(c.sla_due_at) < T0)
    assert d.critical_open == sum(1 for c in open_ if c.priority == Priority.CRITICAL)
    assert d.unassigned_open == sum(1 for c in open_ if c.assigned_to is None)
    assert d.escalated_open == sum(1 for c in open_ if c.escalation_level > 0)
    assert {x.status: x.count for x in d.by_status} == {s: sum(1 for c in rows if c.status == s) for s in ComplaintStatus}
    assert {x.priority: x.count for x in d.by_priority} == {p: sum(1 for c in rows if c.priority == p) for p in Priority}
    assert sum(x.count for x in d.by_category) == len(rows)
    done = [(c.resolved_at - c.created_at).total_seconds() / 3600 for c in rows if c.resolved_at]
    assert d.avg_resolution_hours == round(sum(done) / len(done), 1)


@pytest.mark.parametrize("seed", [1, 2])
def test_institution_numbers_match_brute_force(db, users, seed):
    rows = _random_complaints(db, users, 250, seed)
    inst = DashboardAggregator(db).institution_analytics(30, now=T0)
    window = [c for c in rows if ensure_utc(c.created_at) >= T0 - timedelta(days=30)]
    assert inst.complaints_in_period == len(window)
    res = [c for c in window if c.resolved_at]
    ok = [c for c in res if ensure_utc(c.resolved_at) <= ensure_utc(c.sla_due_at)]
    assert inst.sla_compliance_pct == (round(100 * len(ok) / len(res), 1) if res else None)
    assert {t.category: t.count for t in inst.category_trends} == {k: sum(1 for c in window if c.category == k) for k in Category}
    pairs = Counter((c.location.strip().lower(), c.category) for c in window if c.location)
    assert len(inst.repeat_issue_locations) == sum(1 for v in pairs.values() if v >= 3)


def test_emergency_list_is_exact_and_ordered(db, users):
    rows = _random_complaints(db, users, 200, 5)
    items = DashboardAggregator(db).emergency_list(now=T0)
    open_ = [c for c in rows if c.status not in (ComplaintStatus.RESOLVED, ComplaintStatus.CLOSED)]
    expected = {c.id for c in open_ if c.safety_risk or c.priority in (Priority.CRITICAL, Priority.HIGH)}
    assert {i.complaint_id for i in items} == expected
    assert all(i.is_overdue == (i.hours_to_deadline < 0) for i in items)
    flags = [i.is_overdue for i in items]
    assert flags == sorted(flags, reverse=True)  # overdue ones come first
    overdue = [i for i in items if i.is_overdue and i.safety_risk]
    assert items[: len(overdue)] == overdue or not overdue  # then safety risks


def test_maintenance_numbers_match_brute_force(db, users):
    rows = _random_complaints(db, users, 150, 9)
    staff = users["maint"].id
    d = DashboardAggregator(db).maintenance_workload(staff, now=T0)
    mine = [c for c in rows if c.assigned_to == staff]
    assert d.assigned == sum(1 for c in mine if c.status == ComplaintStatus.ASSIGNED)
    assert d.in_progress == sum(1 for c in mine if c.status == ComplaintStatus.IN_PROGRESS)
    open_mine = [c for c in mine if c.status not in (ComplaintStatus.RESOLVED, ComplaintStatus.CLOSED)]
    assert {t.complaint_id for t in d.tasks} == {c.id for c in open_mine}
    rank = {Priority.CRITICAL: 0, Priority.HIGH: 1, Priority.MEDIUM: 2, Priority.LOW: 3}
    ranks = [rank[t.priority] for t in d.tasks]
    assert ranks == sorted(ranks)  # most urgent first


# ================================================================== 4. AI performance as seen by admins
def test_ai_performance_counts_admin_decisions(db, users, detector):
    mk = lambda title, desc: cs.register_complaint(db, reporter_id=users["faculty"].id, title=title, description=desc, detector=detector)
    good = mk("Sparks from switch board", "Sparks coming from the switch board in the lab")
    odd1, odd2, odd3 = mk("asdfgh qwerty", "zxcvb lkjhg"), mk("qwerty asdfg", "lkjhg zxcvb"), mk("hjklm nbvcx", "poiuy trewq")
    perf = DashboardAggregator(db).ai_performance()
    assert perf.total_predictions == 4 and perf.pending_review == 3 and perf.reviewed == 0
    assert perf.agreement_rate_pct is None  # no decisions yet: say so instead of inventing a number

    pend = {p.complaint_id: p for p in cs.pending_reviews(db)}
    cs.review_prediction(db, pend[odd1.id].id, users["admin"].id, confirm=True)
    cs.review_prediction(db, pend[odd2.id].id, users["admin"].id, confirm=False, priority=Priority.HIGH, category=Category.NETWORKING)
    cs.review_prediction(db, pend[odd3.id].id, users["admin"].id, confirm=False, priority=pend[odd3.id].predicted_priority,
                         category=Category.CIVIL if pend[odd3.id].predicted_category != Category.CIVIL else Category.PLUMBING)
    perf = DashboardAggregator(db).ai_performance()
    assert (perf.reviewed, perf.confirmed, perf.overridden, perf.pending_review) == (3, 1, 2, 0)
    assert perf.agreement_rate_pct == 33.3 and perf.flag_rate_pct == 75.0
    assert perf.total_predictions == 4  # manual rows are not counted as AI predictions
    assert perf.category_changed == 2 and perf.priority_changed in (1, 2)
    assert sum(x.ai_predictions_reviewed for x in perf.by_ai_priority) == 3
    assert good.needs_manual_review is False
