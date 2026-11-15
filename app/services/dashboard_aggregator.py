"""Dashboard data aggregator: real queries behind the three dashboards.

    admin_overview        monitoring, emergencies, SLA breaches, AI-review backlog, resolution metrics
    maintenance_workload  one staff member's tasks and progress
    institution_analytics trends for resource allocation and preventive maintenance planning

Counting uses SQL GROUP BY; averages and SLA maths are done in Python so the same code runs on SQLite and MySQL.
"""
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import Category, ComplaintStatus, Priority
from app.core.timeutil import ensure_utc, utcnow
from app.core.enums import NotificationChannel, NotificationStatus, PredictionSource
from app.models import AIPrediction, Complaint, Notification
from app.schemas.dashboard import (
    AdminDashboard, AIPerformance, CategoryCount, CategoryTrend, ChannelDelivery, EmergencyItem, InstitutionAnalytics,
    MaintenanceDashboard, MaintenanceTask, NotificationStats, PriorityAgreement, PriorityCount, StatusCount,
)
MAX_RETRIES_DEFAULT = 3
from app.services.ai_service import pending_reviews
from app.services.common import OPEN_STATUSES

REPEAT_ISSUE_THRESHOLD = 3  # same place + same category this many times in the period -> preventive maintenance candidate
_PRIORITY_RANK = {Priority.CRITICAL: 0, Priority.HIGH: 1, Priority.MEDIUM: 2, Priority.LOW: 3}


def _hours(start: datetime, end: datetime) -> float:
    return (ensure_utc(end) - ensure_utc(start)).total_seconds() / 3600


def _avg(values: list[float]) -> Optional[float]:
    return round(sum(values) / len(values), 1) if values else None


class DashboardAggregator:
    def __init__(self, db: Session):
        self.db = db

    def _group_count(self, column, where=None) -> dict:
        q = select(column, func.count()).group_by(column)
        if where is not None:
            q = q.where(where)
        return {k: n for k, n in self.db.execute(q) if k is not None}

    def admin_overview(self, now: Optional[datetime] = None) -> AdminDashboard:
        now = now or utcnow()
        db = self.db
        by_status = self._group_count(Complaint.status)
        by_priority = self._group_count(Complaint.priority)
        by_category = self._group_count(Complaint.category)
        open_rows = db.scalars(select(Complaint).where(Complaint.status.in_(OPEN_STATUSES))).all()
        resolved = db.execute(select(Complaint.created_at, Complaint.resolved_at)
                              .where(Complaint.resolved_at.is_not(None))).all()
        return AdminDashboard(
            total_complaints=sum(by_status.values()),
            open_complaints=len(open_rows),
            overdue_complaints=sum(1 for c in open_rows if c.sla_due_at and ensure_utc(c.sla_due_at) < now),
            critical_open=sum(1 for c in open_rows if c.priority == Priority.CRITICAL),
            escalated_open=sum(1 for c in open_rows if c.escalation_level >= 1),
            unassigned_open=sum(1 for c in open_rows if c.assigned_to is None),
            pending_ai_reviews=len(pending_reviews(db)),
            avg_resolution_hours=_avg([_hours(a, b) for a, b in resolved]),
            by_status=[StatusCount(status=s, count=by_status.get(s, 0)) for s in ComplaintStatus],
            by_priority=[PriorityCount(priority=p, count=by_priority.get(p, 0)) for p in Priority],
            by_category=[CategoryCount(category=c, count=by_category.get(c, 0)) for c in Category],
            generated_at=now,
        )

    def maintenance_workload(self, staff_id: int, now: Optional[datetime] = None) -> MaintenanceDashboard:
        now = now or utcnow()
        mine = self.db.scalars(select(Complaint).where(Complaint.assigned_to == staff_id)).all()
        open_tasks = [c for c in mine if c.status in OPEN_STATUSES]
        open_tasks.sort(key=lambda c: (_PRIORITY_RANK.get(c.priority, 9), ensure_utc(c.sla_due_at) or now))
        today = now.date()
        return MaintenanceDashboard(
            staff_id=staff_id,
            assigned=sum(1 for c in open_tasks if c.status == ComplaintStatus.ASSIGNED),
            in_progress=sum(1 for c in open_tasks if c.status == ComplaintStatus.IN_PROGRESS),
            resolved_today=sum(1 for c in mine if c.resolved_at and ensure_utc(c.resolved_at).date() == today
                               and c.status in (ComplaintStatus.RESOLVED, ComplaintStatus.CLOSED)),
            tasks=[MaintenanceTask(complaint_id=c.id, title=c.label, category=c.category, priority=c.priority,
                                   status=c.status, sla_deadline=ensure_utc(c.sla_due_at)) for c in open_tasks],
            generated_at=now,
        )

    def institution_analytics(self, period_days: int = 30, now: Optional[datetime] = None) -> InstitutionAnalytics:
        now = now or utcnow()
        since = now - timedelta(days=period_days)
        rows = [c for c in self.db.scalars(select(Complaint).order_by(Complaint.id)) if ensure_utc(c.created_at) >= since]
        resolved = [c for c in rows if c.resolved_at is not None]
        within = [c for c in resolved if c.sla_due_at and ensure_utc(c.resolved_at) <= ensure_utc(c.sla_due_at)]
        per_cat_hours = defaultdict(list)
        for c in resolved:
            if c.category:
                per_cat_hours[c.category].append(_hours(c.created_at, c.resolved_at))
        counts = Counter(c.category for c in rows if c.category)
        repeats = Counter((c.location.strip().lower(), c.category) for c in rows if c.location and c.category)
        display: dict = {}
        for c in rows:  # show each place the way it was first written
            if c.location and c.category:
                display.setdefault((c.location.strip().lower(), c.category), c.location.strip())
        return InstitutionAnalytics(
            period_days=period_days,
            complaints_in_period=len(rows),
            sla_compliance_pct=round(100 * len(within) / len(resolved), 1) if resolved else None,
            category_trends=[CategoryTrend(category=cat, count=counts.get(cat, 0),
                                           avg_resolution_hours=_avg(per_cat_hours.get(cat, []))) for cat in Category],
            repeat_issue_locations=[f"{display[k]} ({k[1].value} x{n})" for k, n in repeats.most_common()
                                    if n >= REPEAT_ISSUE_THRESHOLD],
            generated_at=now,
        )

    # ------------------------------------------------------------------ emergency list
    def emergency_list(self, now: Optional[datetime] = None) -> list[EmergencyItem]:
        """Open critical/high complaints plus any open safety risk, most urgent first (overdue, then critical, then soonest due)."""
        now = now or utcnow()
        rows = self.db.scalars(select(Complaint).where(Complaint.status.in_(OPEN_STATUSES)).order_by(Complaint.id)).all()
        items = []
        for c in rows:
            if not (c.safety_risk or c.priority in (Priority.CRITICAL, Priority.HIGH)):
                continue
            due = ensure_utc(c.sla_due_at) if c.sla_due_at else None
            left = round((due - now).total_seconds() / 3600, 1) if due else None
            items.append(EmergencyItem(
                complaint_id=c.id, title=c.label, location=c.location, category=c.category,
                priority=c.priority or Priority.MEDIUM, status=c.status, safety_risk=c.safety_risk,
                assigned_to=c.assigned_to, escalation_level=c.escalation_level, sla_due_at=due,
                hours_to_deadline=left, is_overdue=left is not None and left < 0))
        items.sort(key=lambda i: (not i.is_overdue, not i.safety_risk, _PRIORITY_RANK.get(i.priority, 9),
                                  i.hours_to_deadline if i.hours_to_deadline is not None else 1e9, i.complaint_id))
        return items

    # ------------------------------------------------------------------ AI performance in real use
    def ai_performance(self, now: Optional[datetime] = None) -> AIPerformance:
        """Judge the AI by admin decisions. Only the AI's own predictions count (manual overrides are the answer key)."""
        now = now or utcnow()
        ai = [p for p in self.db.scalars(select(AIPrediction).order_by(AIPrediction.id))
              if p.source != PredictionSource.MANUAL]
        reviewed = [p for p in ai if p.reviewed_at is not None]  # review clears needs_manual_review, so count both
        pending = [p for p in ai if p.needs_manual_review and p.reviewed_at is None and p.is_applied]
        flagged = reviewed + pending
        changed_cat = [p for p in reviewed if p.reviewed_category and p.reviewed_category != p.predicted_category]
        changed_pri = [p for p in reviewed if p.reviewed_priority and p.reviewed_priority != p.predicted_priority]
        overridden = [p for p in reviewed if p in changed_cat or p in changed_pri]
        by_pri = []
        for pri in Priority:
            group = [p for p in reviewed if p.predicted_priority == pri]
            moved = sum(1 for p in group if p in overridden)
            by_pri.append(PriorityAgreement(priority=pri, ai_predictions_reviewed=len(group),
                                            kept=len(group) - moved, changed=moved))
        pct = lambda a, b: round(100 * a / b, 1) if b else None
        return AIPerformance(
            total_predictions=len(ai), flagged_for_review=len(flagged), reviewed=len(reviewed),
            pending_review=len(pending), confirmed=len(reviewed) - len(overridden),
            overridden=len(overridden), category_changed=len(changed_cat), priority_changed=len(changed_pri),
            agreement_rate_pct=pct(len(reviewed) - len(overridden), len(reviewed)),
            flag_rate_pct=pct(len(flagged), len(ai)),
            avg_category_confidence=_avg([float(p.category_confidence or 0) for p in ai]),
            avg_priority_confidence=_avg([float(p.priority_confidence or 0) for p in ai]),
            by_ai_priority=by_pri, generated_at=now)

    # ------------------------------------------------------------------ notification delivery reliability
    def notification_stats(self, max_retries: int = MAX_RETRIES_DEFAULT, now: Optional[datetime] = None) -> NotificationStats:
        """FAILED with retries left is 'retrying'; FAILED with no retries left is 'gave up' (permanent or exhausted)."""
        now = now or utcnow()
        rows = list(self.db.scalars(select(Notification).order_by(Notification.id)))

        def state(n):
            if n.status == NotificationStatus.SENT:
                return "sent"
            if n.status == NotificationStatus.FAILED:
                return "gave_up" if n.retry_count >= max_retries else "retrying"
            return "pending"

        def rate(sent, gave_up):
            return round(100 * sent / (sent + gave_up), 1) if (sent + gave_up) else None

        sent = [n for n in rows if state(n) == "sent"]
        counts = Counter(state(n) for n in rows)
        channels = []
        for ch in NotificationChannel:
            mine = [n for n in rows if n.channel == ch]
            c = Counter(state(n) for n in mine)
            channels.append(ChannelDelivery(
                channel=ch.value, total=len(mine), sent=c["sent"], pending=c["pending"], failed=c["retrying"],
                gave_up=c["gave_up"], delivery_rate_pct=round(100 * c["sent"] / len(mine), 1) if mine else None))
        delays = [(ensure_utc(n.sent_at) - ensure_utc(n.created_at)).total_seconds()
                  for n in sent if n.sent_at and n.created_at]
        errors = Counter(n.error_message for n in rows if n.error_message and state(n) in ("retrying", "gave_up"))
        return NotificationStats(
            total=len(rows), sent=counts["sent"], pending=counts["pending"], failed_retrying=counts["retrying"],
            gave_up=counts["gave_up"], delivery_rate_pct=rate(counts["sent"], counts["gave_up"]),
            avg_attempts_for_sent=_avg([n.retry_count + 1 for n in sent]),
            avg_delivery_delay_seconds=_avg(delays),
            unread_in_app=sum(1 for n in rows if n.channel == NotificationChannel.IN_APP and n.read_at is None),
            by_channel=channels, top_errors=[f"{m} (x{k})" for m, k in errors.most_common(3)], generated_at=now)
