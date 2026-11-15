
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.department import Department


DEPARTMENTS = [
    "Electronics and Communication Engineering",
    "Computer Science and Engineering",
    "Computer Science and Engineering-AIML",
    "Computer Science and Engineering-CSBS",
    "Computer Science and Engineering-DS",
    "Civil Engineering",
    "Mechanical Engineering",
    "Electrical and Electronics Engineering",
    "Information Technology",
    "Humanities and Sciences",
]


def seed_departments():
    with SessionLocal() as db:
        for name in DEPARTMENTS:
            existing = db.scalar(
                select(Department).where(Department.name == name)
            )
            if existing is None:
                db.add(Department(name=name))

        db.commit()
        print("Department seeding completed.")


if __name__ == "__main__":
    seed_departments()
