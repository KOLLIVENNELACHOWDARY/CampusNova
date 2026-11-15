"""Seed data: departments, routing rules, and demo accounts (one per role plus a worker per department).

    python -m app.db.seed                 # departments + routing rules only (safe for production)
    python -m app.db.seed --demo          # + demo users, password printed below  (NEVER in production)

Routing: electrical -> EEE, civil -> Civil Engineering, networking -> Information Technology,
sanitation -> Mechanical Engineering (no plumbing department exists; change it in /routing-rules), laboratory and
general -> the reporter's own department.
"""
import sys
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import Category, UserRole
from app.db.seed_departments import DEPARTMENTS
from app.db.session import SessionLocal
from app.models import Department, RoutingRule, User
from app.core.security import hash_password

DEFAULT_ROUTING = {
    Category.ELECTRICAL: "Electrical and Electronics Engineering",
    Category.CIVIL: "Civil Engineering",
    Category.NETWORKING: "Information Technology",
    Category.SANITATION: "Mechanical Engineering",
    Category.LABORATORY: None,
    Category.GENERAL: None,
}
DEMO_PASSWORD = "Campus@123"


def seed_departments(db: Session) -> dict[str, int]:
    out = {}
    for name in DEPARTMENTS:
        d = db.scalar(select(Department).where(Department.name == name))
        if d is None:
            d = Department(name=name)
            db.add(d)
            db.flush()
        out[name] = d.id
    return out


def seed_routing(db: Session, depts: dict[str, int]) -> None:
    for cat, dept in DEFAULT_ROUTING.items():
        if db.scalar(select(RoutingRule).where(RoutingRule.category == cat)) is None:
            db.add(RoutingRule(category=cat, department_id=depts.get(dept) if dept else None))


def _user(db: Session, email: str, name: str, staff_id: str, role: UserRole, dept_id: Optional[int]) -> User:
    u = db.scalar(select(User).where(User.email == email))
    if u is None:
        u = User(email=email, full_name=name, staff_id=staff_id, role=role, department_id=dept_id,
                 password_hash=hash_password(DEMO_PASSWORD), is_active=True)
        db.add(u)
    return u


def seed_demo_users(db: Session, depts: dict[str, int]) -> None:
    cse, eee, civil = depts["Computer Science and Engineering"], depts["Electrical and Electronics Engineering"], depts["Civil Engineering"]
    it, mech = depts["Information Technology"], depts["Mechanical Engineering"]
    _user(db, "admin@campusnova.edu", "Admin Office", "ADM001", UserRole.ADMIN, None)
    _user(db, "incharge.cse@campusnova.edu", "CSE Floor In-charge", "FIC001", UserRole.FLOOR_INCHARGE, cse)
    _user(db, "faculty.cse@campusnova.edu", "Dr. Faculty (CSE)", "FAC001", UserRole.FACULTY, cse)
    _user(db, "staff.it@campusnova.edu", "IT Staff", "STF001", UserRole.STAFF, it)
    _user(db, "electrician@campusnova.edu", "Ravi (Electrician)", "MNT001", UserRole.MAINTENANCE, eee)
    _user(db, "electrician2@campusnova.edu", "Suresh (Electrician)", "MNT002", UserRole.MAINTENANCE, eee)
    _user(db, "civil@campusnova.edu", "Kiran (Civil)", "MNT003", UserRole.MAINTENANCE, civil)
    _user(db, "network@campusnova.edu", "Anil (Network)", "MNT004", UserRole.MAINTENANCE, it)
    _user(db, "plumber@campusnova.edu", "Mohan (Plumber)", "MNT005", UserRole.MAINTENANCE, mech)


def seed(demo: bool = False) -> None:
    with SessionLocal() as db:
        depts = seed_departments(db)
        seed_routing(db, depts)
        if demo:
            seed_demo_users(db, depts)
        db.commit()
    print("Seeded departments and routing rules." + (f" Demo users created (password: {DEMO_PASSWORD})." if demo else ""))


if __name__ == "__main__":
    seed(demo="--demo" in sys.argv)
