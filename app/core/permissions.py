"""Role -> permission map (Chethana). Every protected endpoint names the permission it needs; nothing checks role names
directly, so changing who may do what is a one-line edit here (and the permission-audit test shows the full table)."""
from app.core.enums import UserRole

R = UserRole
REPORTERS = {R.FLOOR_INCHARGE, R.FACULTY, R.STAFF}

PERMISSIONS: dict[str, set[UserRole]] = {
    "complaint:create": REPORTERS | {R.ADMIN},
    "complaint:view_all": {R.ADMIN},
    "complaint:upload_image": REPORTERS | {R.ADMIN},
    "complaint:assign": {R.ADMIN},
    "workflow:work": {R.MAINTENANCE},  # start / finish work on a job assigned to you, claim and hand back jobs
    "workflow:close": {R.ADMIN},
    "workflow:remark": REPORTERS | {R.ADMIN, R.MAINTENANCE},
    "routing:manage": {R.ADMIN},
    "ai:predict": REPORTERS | {R.ADMIN, R.MAINTENANCE},
    "ai:review": {R.ADMIN},  # confirm or override an AI prediction
    "dashboard:admin": {R.ADMIN},
    "dashboard:maintenance": {R.ADMIN, R.MAINTENANCE},
    "jobs:run": {R.ADMIN},
    "user:manage": {R.ADMIN},
    "notification:own": set(R),
}


def has_permission(role, permission: str) -> bool:
    try:
        role = UserRole(role)
    except ValueError:
        return False
    return role in PERMISSIONS.get(permission, set())
