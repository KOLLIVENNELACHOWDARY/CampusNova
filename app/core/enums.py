"""Shared enums for CampusNova.

Kept in one place so models, schemas, the priority engine and the dashboards all
agree on the same vocabulary.
"""
from enum import Enum


class UserRole(str, Enum):
    """Roles. The team's schema draft names three (Admin, Floor In-charge, Maintenance Staff); faculty and staff
    are kept as extra reporter roles so existing accounts and the AI demo data keep working."""

    ADMIN = "admin"
    FLOOR_INCHARGE = "floor_incharge"
    MAINTENANCE = "maintenance"
    FACULTY = "faculty"
    STAFF = "staff"


REPORTER_ROLES = (UserRole.FLOOR_INCHARGE, UserRole.FACULTY, UserRole.STAFF)


class Category(str, Enum):
    ELECTRICAL = "electrical"
    CIVIL = "civil"
    NETWORKING = "networking"
    SANITATION = "sanitation"
    LABORATORY = "laboratory"
    GENERAL = "general"


class ComplaintStatus(str, Enum):
    REGISTERED = "registered"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Level(str, Enum):
    """Three-step scale used for the severity and impact axes of the matrix."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


LEVEL_SCORE = {Level.LOW: 1, Level.MEDIUM: 2, Level.HIGH: 3}


class NotificationType(str, Enum):
    STATUS_UPDATE = "status_update"
    ASSIGNMENT = "assignment"
    URGENT_ALERT = "urgent_alert"
    SLA_WARNING = "sla_warning"
    ESCALATION = "escalation"


class NotificationChannel(str, Enum):
    EMAIL = "email"  # SMTP
    PUSH = "push"  # Firebase Cloud Messaging
    IN_APP = "in_app"


class NotificationStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    READ = "read"


class PredictionSource(str, Enum):
    ML = "ml"  # Scikit-learn / spaCy model
    RULE_BASED = "rule_based"  # fallback engine
    MANUAL = "manual"  # human override


class RuleSignal(str, Enum):
    SEVERITY = "severity"
    IMPACT = "impact"
    SAFETY = "safety"
