"""Default Priority Matrix and SLA targets, plus a DB seeder.

Matrix logic (severity + impact, each scored 1-3):
    safety risk                -> CRITICAL
    total 6                    -> CRITICAL
    total 5                    -> HIGH
    total 4                    -> MEDIUM
    total 2-3                  -> LOW
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import LEVEL_SCORE, Category, Level, Priority
from app.models.priority import PriorityMatrixEntry

SLA_HOURS: dict[Priority, int] = {
    Priority.CRITICAL: 4,
    Priority.HIGH: 24,
    Priority.MEDIUM: 72,
    Priority.LOW: 168,
}

MatrixKey = tuple[Level, Level, bool]  # (severity, impact, safety_risk)


def lookup_priority(severity: Level, impact: Level, safety_risk: bool) -> Priority:
    if safety_risk:
        return Priority.CRITICAL
    total = LEVEL_SCORE[severity] + LEVEL_SCORE[impact]
    if total >= 6:
        return Priority.CRITICAL
    if total == 5:
        return Priority.HIGH
    if total == 4:
        return Priority.MEDIUM
    return Priority.LOW


def build_default_matrix() -> dict[MatrixKey, Priority]:
    return {
        (sev, imp, safe): lookup_priority(sev, imp, safe)
        for sev in Level
        for imp in Level
        for safe in (False, True)
    }


def seed_priority_matrix(db: Session) -> int:
    """Insert any missing matrix cells (idempotent). Returns number of rows added."""
    existing = {
        (row.category, row.severity, row.impact, row.safety_risk)
        for row in db.execute(select(PriorityMatrixEntry)).scalars()
    }
    added = 0
    for category in Category:
        for (sev, imp, safe), priority in build_default_matrix().items():
            if (category, sev, imp, safe) in existing:
                continue
            db.add(
                PriorityMatrixEntry(
                    category=category,
                    severity=sev,
                    impact=imp,
                    safety_risk=safe,
                    priority=priority,
                    sla_hours=SLA_HOURS[priority],
                )
            )
            added += 1
    db.commit()
    return added
