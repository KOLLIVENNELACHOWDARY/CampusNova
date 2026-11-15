"""Shared test fixtures: in-memory SQLite, the real app wired to it, seeded departments/routing/users, token helpers.

Tests never need MySQL; one test module (test_migrations) proves the Alembic chain on a temporary SQLite file.
"""
import os
from datetime import datetime, timezone

os.environ.setdefault("CAMPUSNOVA_SCHEDULER", "0")
os.environ.setdefault("DATABASE_URL", "sqlite://")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  (register every table)
from app.core.enums import UserRole
from app.db.base import Base
from app.db.seed import DEMO_PASSWORD, seed_demo_users, seed_departments, seed_routing
from app.db.session import get_db
from app.main import app
from app.models import User

PASSWORD = DEMO_PASSWORD
T0 = datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc)  # a fixed "now" for time-dependent tests


@pytest.fixture()
def engine():
    url = os.getenv("TEST_DATABASE_URL")  # e.g. mysql+pymysql://user:pw@127.0.0.1/campusnova_test  (wiped for every test!)
    if url:
        eng = create_engine(url, pool_pre_ping=True)
        Base.metadata.drop_all(eng)
    else:
        eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    yield eng
    if url:
        Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture()
def Session(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture()
def db(Session):
    with Session() as s:
        depts = seed_departments(s)
        seed_routing(s, depts)
        seed_demo_users(s, depts)
        s.commit()
        yield s


class UserBook(dict):
    """Dict access (users["maint"]) and attribute access (users.maint) to the seeded demo accounts."""

    __getattr__ = dict.__getitem__


@pytest.fixture()
def users(db):
    by_email = {u.email: u for u in db.query(User).all()}
    named = {
        "admin": "admin@campusnova.edu", "incharge": "incharge.cse@campusnova.edu", "faculty": "faculty.cse@campusnova.edu",
        "staff": "staff.it@campusnova.edu", "electrician": "electrician@campusnova.edu",
        "electrician2": "electrician2@campusnova.edu", "civil": "civil@campusnova.edu", "network": "network@campusnova.edu",
        "plumber": "plumber@campusnova.edu",
    }
    book = UserBook({k: by_email[v] for k, v in named.items()})
    for k in ("faculty", "electrician", "admin"):  # device tokens (push) for the notification tests
        book[k].fcm_token = f"tok-{k}"
    book.update(maint=book["electrician"], maint2=book["electrician2"])  # names the AI/notification tests use
    extra = User(full_name="Admin Two", email="", staff_id="ADM002", role=UserRole.ADMIN,
                 department_id=None, password_hash=None)
    db.add(extra)
    db.commit()
    book["admin2"] = extra
    return book


@pytest.fixture()
def client(Session, db):
    def _get_db():
        with Session() as s:
            yield s

    app.dependency_overrides[get_db] = _get_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


def login(client, email, password=PASSWORD):
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture()
def auth(client):
    """auth(user_or_email) -> Authorization header dict."""
    cache = {}

    def _auth(user):
        email = user if isinstance(user, str) else user.email
        if email not in cache:
            cache[email] = {"Authorization": f"Bearer {login(client, email)['access_token']}"}
        return cache[email]

    return _auth


NEW_COMPLAINT = {"block": "Block A", "floor": "2", "room_number": "A-204", "title": "Ceiling fan not working",
                 "description": "The ceiling fan in the classroom stopped working and the room is very hot."}


@pytest.fixture()
def new_complaint():
    return dict(NEW_COMPLAINT)


@pytest.fixture()
def session_factory(Session):
    return Session


@pytest.fixture(scope="session")
def detector(tmp_path_factory):
    """A freshly trained detector (does not depend on the committed model files)."""
    from ml import dataset
    from ml.priority_detector import PriorityDetector
    from ml.train import train

    d = tmp_path_factory.mktemp("detector")
    csv_path = d / "complaints.csv"
    dataset.write_csv(dataset.generate(), csv_path)
    train(out_dir=d / "artifacts", data_path=csv_path, verbose=False)
    return PriorityDetector.load(d / "artifacts")
