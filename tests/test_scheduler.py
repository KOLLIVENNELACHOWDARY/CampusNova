import time
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.enums import NotificationStatus as St
from app.jobs import scheduler as jobs
from app.models import Notification
from tests import compat as cs
from app.services.notification_service import build_senders
from tests.conftest import T0


def test_scheduler_has_both_jobs_and_is_not_started(session_factory):
    s = jobs.build_scheduler(session_factory, build_senders("log"))
    assert {j.id for j in s.get_jobs()} == {"sla_check", "auto_assign", "dispatch"}
    assert s.running is False
    by_id = {j.id: j for j in s.get_jobs()}
    assert by_id["sla_check"].trigger.interval == timedelta(minutes=5)
    assert by_id["dispatch"].trigger.interval == timedelta(seconds=60)
    assert all(j.max_instances == 1 and j.coalesce for j in s.get_jobs())  # never overlap, never pile up


def test_intervals_come_from_env_or_arguments(session_factory, monkeypatch):
    monkeypatch.setenv("CAMPUSNOVA_SLA_CHECK_MINUTES", "2")
    monkeypatch.setenv("CAMPUSNOVA_DISPATCH_SECONDS", "15")
    by_id = {j.id: j for j in jobs.build_scheduler(session_factory, {}).get_jobs()}
    assert by_id["sla_check"].trigger.interval == timedelta(minutes=2)
    assert by_id["dispatch"].trigger.interval == timedelta(seconds=15)
    by_id = {j.id: j for j in jobs.build_scheduler(session_factory, {}, sla_check_minutes=9, dispatch_seconds=7).get_jobs()}
    assert by_id["sla_check"].trigger.interval == timedelta(minutes=9)


def test_jobs_commit_their_work(session_factory, db, users, detector):
    c = cs.register_complaint(db, reporter_id=users["faculty"].id, title="Wifi down",
                              description="wifi is down in the entire CSE block", detector=detector, now=T0)
    cs.assign_complaint(db, c.id, users["maint"].id, now=T0)
    res = jobs.sla_check_job(session_factory, now=T0 + timedelta(hours=30))
    assert res.escalated == {c.id: 1}
    sent = jobs.dispatch_job(session_factory, build_senders("log"), now=T0 + timedelta(hours=30))
    assert sent.sent > 0
    assert sent.gave_up == sent.failed  # only undeliverable ones (admin2 has no email / device token) fail
    with session_factory() as other:  # a different session sees the committed data
        rows = other.scalars(select(Notification)).all()
        assert all(n.status == St.SENT for n in rows if n.user_id != users["admin2"].id)
        assert any(n.status == St.SENT and n.user_id == users["admin"].id for n in rows)


def test_a_crashing_job_does_not_kill_the_schedule(caplog):
    def bad(**_):
        raise RuntimeError("database is gone")

    assert jobs._safe(bad, "demo") is None
    assert "background job demo failed" in caplog.text


def test_scheduler_really_runs_the_jobs_in_the_background(session_factory, db, users, detector):
    c = cs.register_complaint(db, reporter_id=users["faculty"].id, title="Wifi down",
                              description="wifi is down in the entire CSE block", detector=detector)
    s = jobs.build_scheduler(session_factory, build_senders("log"), sla_check_minutes=1, dispatch_seconds=1)
    s.start()
    try:
        deadline = time.time() + 5
        while time.time() < deadline:
            with session_factory() as other:
                rows = other.scalars(select(Notification)).all()
            if rows and all(n.status == St.SENT for n in rows):
                break
            time.sleep(0.1)
    finally:
        s.shutdown(wait=True)
    assert rows and all(n.status == St.SENT for n in rows)  # queued by registration, delivered by the job


def test_run_once_cli_prints_results(monkeypatch, capsys, session_factory):
    from app.jobs import run_once

    monkeypatch.setattr(jobs, "SessionLocal", session_factory)
    monkeypatch.setattr(run_once, "sla_check_job", lambda **kw: jobs.sla_check_job(session_factory, **kw))
    monkeypatch.setattr(run_once, "dispatch_job", lambda **kw: jobs.dispatch_job(session_factory, **kw))
    monkeypatch.setattr("sys.argv", ["run_once", "--hours-ahead", "3"])
    run_once.main()
    out = capsys.readouterr().out
    assert "SLA check" in out and "Dispatch" in out
