from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.db.base import Base

BACKEND = Path(__file__).resolve().parent.parent


def _cfg() -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    return cfg


def test_migration_creates_every_model_table_and_matches_the_models(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'mig.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(_cfg(), "head")
    tables = set(inspect(create_engine(url)).get_table_names())
    assert set(Base.metadata.tables) <= tables
    command.check(_cfg())  # raises if the models drifted from the migration: re-run `alembic revision --autogenerate`


def test_migration_downgrades_cleanly(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'mig.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(_cfg(), "head")
    command.downgrade(_cfg(), "base")
    assert set(inspect(create_engine(url)).get_table_names()) <= {"alembic_version"}


def test_migration_upgrades_a_database_that_already_has_the_teams_rows(tmp_path, monkeypatch):
    """The team's first schema (revision 209354ec1d11) already holds data; 0003 must keep it and normalise it."""
    import sqlite3

    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(_cfg(), "209354ec1d11")
    con = sqlite3.connect(tmp_path / "legacy.db")
    con.execute("insert into departments(name) values('EEE')")
    con.execute("insert into users(firebase_uid,full_name,email,staff_id,role,department_id,is_active) values('u1','A','a@x.t','S1','Admin',1,1)")
    con.execute("insert into complaints(complaint_number,reported_by,reporter_department_id,block,floor,category,description,"
                "responsible_department_id,priority,status) values('CN-OLD',1,1,'B','1','Electrical','old row',1,'medium','registered')")
    con.execute("insert into notifications(user_id,complaint_id,message,is_read) values(1,1,'old msg',0)")
    con.commit()
    con.close()

    command.upgrade(_cfg(), "head")
    command.check(_cfg())
    con = sqlite3.connect(tmp_path / "legacy.db")
    assert con.execute("select category,status,escalation_level from complaints").fetchall() == [("electrical", "registered", 0)]
    n = con.execute("select message,status,type,channel from notifications").fetchall()
    assert n[0][0] == "old msg" and all(n[0][1:])  # new NOT NULL columns were filled in
    con.close()
    command.downgrade(_cfg(), "209354ec1d11")
    command.upgrade(_cfg(), "head")
