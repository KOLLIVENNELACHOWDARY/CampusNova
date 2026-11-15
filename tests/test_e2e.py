"""Error format, health checks and an end-to-end scenario through the public API only (Nakshatra)."""
import pytest

from app.core.enums import ComplaintStatus as S


@pytest.fixture(autouse=True)
def _auto_assign_on(monkeypatch):
    monkeypatch.setenv("CAMPUSNOVA_AUTO_ASSIGN", "1")


# ------------------------------------------------------------------ error format
def assert_error(r, status, code):
    assert r.status_code == status, r.text
    body = r.json()
    assert set(body) == {"error"} and body["error"]["code"] == code and isinstance(body["error"]["message"], str)


def test_every_error_family_uses_the_same_shape(client, auth, users):
    h = auth(users["faculty"])
    assert_error(client.get("/nope"), 404, "not_found")
    assert_error(client.delete("/health"), 405, "method_not_allowed")
    assert_error(client.get("/complaints"), 401, "unauthorized")
    assert_error(client.get("/users", headers=h), 403, "forbidden")
    assert_error(client.get("/complaints/999999", headers=auth(users["admin"])), 404, "not_found")
    assert_error(client.post("/complaints", json={}, headers=h), 422, "validation_error")
    assert_error(client.post("/auth/login", content=b"{not json", headers={"Content-Type": "application/json"}), 422, "validation_error")


def test_validation_errors_name_the_offending_fields(client, auth, users):
    r = client.post("/complaints", json={"block": "", "floor": "1"}, headers=auth(users["faculty"]))
    fields = {d["field"] for d in r.json()["error"]["details"]}
    assert {"block", "description"} <= fields


def test_internal_errors_do_not_leak_details(client, monkeypatch, auth, users):
    from app.services import complaints

    def boom(*a, **k):
        raise RuntimeError("secret database password is hunter2")

    monkeypatch.setattr(complaints, "search_complaints", boom)
    r = client.get("/complaints", headers=auth(users["admin"]))
    assert_error(r, 500, "internal_error")
    assert "hunter2" not in r.text


def test_database_outage_is_a_503_not_a_stack_trace(client, monkeypatch, auth, users):
    from sqlalchemy.exc import OperationalError

    from app.services import complaints

    def down(*a, **k):
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    monkeypatch.setattr(complaints, "search_complaints", down)
    assert_error(client.get("/complaints", headers=auth(users["admin"])), 503, "unavailable")


def test_health_endpoints(client):
    assert client.get("/health").json() == {"status": "healthy"}
    assert client.get("/").json()["message"] == "CampusNova API is running"


def test_openapi_documents_the_api(client):
    spec = client.get("/openapi.json").json()
    paths = set(spec["paths"])
    assert {"/auth/login", "/complaints", "/complaints/{complaint_id}/assign", "/dashboard/admin", "/routing-rules"} <= paths
    assert len(paths) >= 40


# ------------------------------------------------------------------ the whole story
def test_a_complaint_from_report_to_close_with_ai_doing_the_assigning(client, auth, users, db):
    rep = auth(users["faculty"])
    # 1. faculty reports a dangerous problem with a photo
    r = client.post("/complaints", headers=rep, json={"block": "Block A", "floor": "2", "room_number": "A-204",
                                                      "description": "Sparks and a burning smell from the switch board near the door"})
    assert r.status_code == 201
    c = r.json()
    assert c["category"] == "electrical" and c["priority"] in ("critical", "high") and c["safety_risk"] is True
    # 2. the AI already assigned it to an electrician (nobody had to)
    assert c["status"] == "assigned" and c["assigned_to"] in (users["electrician"].id, users["electrician2"].id)
    worker = users["electrician"] if c["assigned_to"] == users["electrician"].id else users["electrician2"]
    # 3. admins were alerted if it is critical
    admin_inbox = [n["title"] for n in client.get("/notifications", headers=auth(users["admin"])).json()]
    if c["priority"] == "critical":
        assert any("URGENT" in t for t in admin_inbox)
    # 4. the worker sees it on their dashboard and works it
    w = auth(worker)
    assert [x["id"] for x in client.get("/complaints", params={"open_only": "true"}, headers=w).json()["items"]] == [c["id"]]
    dash_w = client.get(f"/dashboard/maintenance/{worker.id}", headers=w).json()
    assert dash_w["assigned"] == 1 and dash_w["tasks"][0]["complaint_id"] == c["id"]
    assert client.post(f"/complaints/{c['id']}/status", json={"status": "in_progress"}, headers=w).status_code == 200
    assert client.post(f"/complaints/{c['id']}/remarks", json={"text": "Isolated the circuit"}, headers=w).status_code == 201
    assert client.post(f"/complaints/{c['id']}/status", json={"status": "resolved", "note": "Replaced the switch board"}, headers=w).status_code == 200
    # 5. the reporter signs it off
    assert client.post(f"/complaints/{c['id']}/sign-off", headers=rep).json()["status"] == "closed"
    # 6. admin dashboard numbers agree with what happened
    dash = client.get("/dashboard/admin", headers=auth(users["admin"])).json()
    assert dash["total_complaints"] == 1 and dash["open_complaints"] == 0 and dash["avg_resolution_hours"] is not None
    ev = [e["event_type"] for e in client.get(f"/complaints/{c['id']}/events", headers=rep).json()]
    assert ev[0] == "registered" and "assigned" in ev and ev.count("status_changed") == 3 and "remark" in ev
    # 7. dispatch delivers the queued notifications
    assert client.post("/admin/jobs/dispatch", headers=auth(users["admin"])).json()["result"]["sent"] > 0


def test_two_reporters_cannot_see_each_others_complaints_end_to_end(client, auth, users):
    a = client.post("/complaints", headers=auth(users["faculty"]), json={"block": "A", "floor": "1", "description": "Fan not working in room"}).json()
    assert client.get(f"/complaints/{a['id']}", headers=auth(users["staff"])).status_code == 403
    assert client.post(f"/complaints/{a['id']}/remarks", json={"text": "hi"}, headers=auth(users["staff"])).status_code == 403


def test_worker_self_service_flow_without_any_admin(client, auth, users, monkeypatch, db):
    monkeypatch.setenv("CAMPUSNOVA_AUTO_ASSIGN", "0")
    c = client.post("/complaints", headers=auth(users["faculty"]), json={"block": "B", "floor": "1", "description": "Water leaking from the pipe in the washroom"}).json()
    assert c["status"] == "registered"
    pool = client.get("/complaints/pool", headers=auth(users["plumber"])).json()
    assert [x["id"] for x in pool] == [c["id"]]
    assert client.post(f"/complaints/{c['id']}/claim", headers=auth(users["plumber"])).json()["status"] == "assigned"
    h = auth(users["plumber"])
    client.post(f"/complaints/{c['id']}/status", json={"status": "in_progress"}, headers=h)
    client.post(f"/complaints/{c['id']}/status", json={"status": "resolved", "note": "Replaced the washer"}, headers=h)
    assert client.post(f"/complaints/{c['id']}/sign-off", headers=auth(users["faculty"])).json()["status"] == "closed"


# ------------------------------------------------------------------ cron endpoints (Vercel / GitHub Actions)
def test_cron_requires_the_secret(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "cron_secret", "")
    assert_error(client.get("/cron/all"), 503, "unavailable")  # not configured: refuse rather than run open
    monkeypatch.setattr(settings, "cron_secret", "s3cret-value")
    assert_error(client.get("/cron/all"), 401, "unauthorized")
    assert_error(client.get("/cron/all", headers={"Authorization": "Bearer wrong"}), 401, "unauthorized")
    assert_error(client.get("/cron/all", headers={"Authorization": "s3cret-value"}), 401, "unauthorized")


def test_cron_runs_the_jobs(client, auth, users, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "cron_secret", "s3cret-value")
    h = {"Authorization": "Bearer s3cret-value"}
    monkeypatch.setenv("CAMPUSNOVA_AUTO_ASSIGN", "0")
    client.post("/complaints", headers=auth(users["faculty"]), json={"block": "A", "floor": "1", "description": "Fan not working in the room"})
    out = client.get("/cron/all", headers=h)
    assert out.status_code == 200 and set(out.json()) == {"sla-check", "auto-assign", "dispatch"}
    assert out.json()["auto-assign"] == {"skipped": "auto-assign is switched off"}
    assert out.json()["dispatch"]["sent"] >= 1  # the registration notification went out
    assert client.post("/cron/dispatch", headers=h).status_code == 200
    assert client.get("/cron/nonsense", headers=h).status_code == 404
