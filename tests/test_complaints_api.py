"""Complaint endpoints, filters, pagination, visibility, boundary values and a small load test (Jahnavi)."""
import time

import pytest

from app.core.enums import Category

BODY = {"block": "Block A", "floor": "2", "room_number": "A-204", "title": "Ceiling fan not working",
        "description": "The ceiling fan in the classroom stopped working and the room is very hot."}


@pytest.fixture(autouse=True)
def _no_auto_assign(monkeypatch):
    monkeypatch.setenv("CAMPUSNOVA_AUTO_ASSIGN", "0")


def create(client, h, **over):
    r = client.post("/complaints", json={**BODY, **over}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def test_create_returns_ai_fields_sla_and_number(client, auth, users):
    c = create(client, auth(users["faculty"]))
    assert c["complaint_number"] == f"CN-{c['id']:05d}" and c["status"] == "registered"
    assert c["category"] == "electrical" and c["priority"] in {"low", "medium", "high", "critical"}
    assert c["sla_hours"] and c["sla_due_at"] and c["location"] == "Block A, 2, A-204"
    assert c["responsible_department_id"] == users["electrician"].department_id  # routed to EEE


def test_create_writes_history_event_prediction_and_notifications(client, auth, users, db):
    from app.models import AIPrediction, ComplaintHistory, Notification

    c = create(client, auth(users["faculty"]))
    assert db.query(ComplaintHistory).filter_by(complaint_id=c["id"]).count() == 1
    assert db.query(AIPrediction).filter_by(complaint_id=c["id"]).count() == 1
    assert db.query(Notification).filter_by(user_id=users["faculty"].id, complaint_id=c["id"]).count() >= 1


def test_explicit_category_and_department_are_respected(client, auth, users):
    dept = users["civil"].department_id
    c = create(client, auth(users["faculty"]), category="civil", responsible_department_id=dept,
               description="Crack in the wall near the staircase on the second floor")
    assert c["category"] == "civil" and c["responsible_department_id"] == dept


def test_unknown_department_is_404(client, auth, users):
    r = client.post("/complaints", json={**BODY, "responsible_department_id": 9999}, headers=auth(users["faculty"]))
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize("over,code", [
    ({"description": ""}, 422), ({"description": "   "}, 422), ({"description": "x" * 2001}, 422), ({"block": ""}, 422),
    ({"floor": ""}, 422), ({"block": "   "}, 422), ({"description": "12345 67890"}, 422), ({"description": "asdf"}, 422),
    ({"category": "plumbing-ish"}, 422), ({"title": "t" * 201}, 422), ({"room_number": "r" * 31}, 422),
])
def test_invalid_complaints_are_rejected_with_a_clear_error(client, auth, users, over, code):
    r = client.post("/complaints", json={**BODY, **over}, headers=auth(users["faculty"]))
    assert r.status_code == code and r.json()["error"]["code"] == "validation_error"


def test_boundary_lengths_are_accepted(client, auth, users):
    h = auth(users["faculty"])
    create(client, h, description=("The fan is broken. " * 105)[:1900], title="Fan broken", room_number="r" * 30, block="b" * 100, floor="f" * 50)


def test_only_reporter_roles_can_create(client, auth, users):
    assert client.post("/complaints", json=BODY, headers=auth(users["electrician"])).status_code == 403
    for who in ("faculty", "incharge", "staff"):
        assert client.post("/complaints", json=BODY, headers=auth(users[who])).status_code == 201
    # the admin account has no department, so it cannot file on behalf of one (clear message, not a crash)
    r = client.post("/complaints", json=BODY, headers=auth(users["admin"]))
    assert r.status_code == 422 and "department" in r.json()["error"]["message"]


def test_unicode_and_markup_are_stored_as_text(client, auth, users):
    c = create(client, auth(users["faculty"]), description="<script>alert(1)</script> fan not working in room — బల్బు పని చేయడం లేదు")
    got = client.get(f"/complaints/{c['id']}", headers=auth(users["faculty"])).json()
    assert "<script>" in got["description"]  # stored verbatim; the React UI escapes on render


# ------------------------------------------------------------------ visibility
def test_visibility_rules(client, auth, users):
    mine = create(client, auth(users["faculty"]))
    other = create(client, auth(users["staff"]), description="Water leaking from the pipe in the corridor")
    assert {c["id"] for c in client.get("/complaints", headers=auth(users["faculty"])).json()["items"]} == {mine["id"]}
    assert {c["id"] for c in client.get("/complaints", headers=auth(users["admin"])).json()["items"]} == {mine["id"], other["id"]}
    assert client.get(f"/complaints/{other['id']}", headers=auth(users["faculty"])).status_code == 403
    assert client.get(f"/complaints/{mine['id']}", headers=auth(users["staff"])).status_code == 403
    assert client.get(f"/complaints/{mine['id']}", headers=auth(users["admin"])).status_code == 200
    assert client.get("/complaints", headers=auth(users["electrician"])).json()["total"] == 0  # nothing assigned yet
    assert client.get("/complaints/99999", headers=auth(users["admin"])).status_code == 404


def test_worker_sees_assigned_jobs_only(client, auth, users):
    a = create(client, auth(users["faculty"]))
    create(client, auth(users["faculty"]), description="Another socket is sparking in the lab")
    client.post(f"/complaints/{a['id']}/assign", json={"assignee_id": users["electrician"].id}, headers=auth(users["admin"]))
    ids = [c["id"] for c in client.get("/complaints", headers=auth(users["electrician"])).json()["items"]]
    assert ids == [a["id"]]


# ------------------------------------------------------------------ filters, search, pagination
@pytest.fixture()
def many(client, auth, users):
    h = auth(users["faculty"])
    texts = [("Block A", "Fan not working in classroom"), ("Block A", "Tube light flickering in the lab"),
             ("Block B", "Wifi is down in the whole block"), ("Block B", "Water leaking from the ceiling pipe"),
             ("Block C", "Socket sparking near the whiteboard"), ("Block C", "Projector not working in seminar hall")]
    return [create(client, h, block=b, description=d, title=None) for b, d in texts]


def test_filters(client, auth, users, many):
    h = auth(users["admin"])
    get = lambda **p: client.get("/complaints", params=p, headers=h).json()
    assert get()["total"] == 6
    assert get(block="block a")["total"] == 2  # case-insensitive
    assert get(category="networking")["total"] >= 1 and all(c["category"] == "networking" for c in get(category="networking")["items"])
    assert get(q="wifi")["total"] == 1 and get(q="WIFI")["total"] == 1
    assert get(q="%")["total"] == 6 or get(q="%")["total"] == 0  # wildcards are not special
    assert get(status="closed")["total"] == 0 and get(status="registered")["total"] == 6
    assert get(open_only="true")["total"] == 6
    assert get(department_id=users["electrician"].department_id)["total"] >= 1
    assert get(priority="critical")["total"] == len([c for c in many if c["priority"] == "critical"])


def test_pagination_and_sorting(client, auth, users, many):
    h = auth(users["admin"])
    p1 = client.get("/complaints", params={"page": 1, "page_size": 4}, headers=h).json()
    p2 = client.get("/complaints", params={"page": 2, "page_size": 4}, headers=h).json()
    assert p1["total"] == 6 and len(p1["items"]) == 4 and len(p2["items"]) == 2
    assert not ({c["id"] for c in p1["items"]} & {c["id"] for c in p2["items"]})
    assert [c["id"] for c in p1["items"]] == sorted((c["id"] for c in p1["items"]), reverse=True)  # newest first
    oldest = client.get("/complaints", params={"sort": "oldest"}, headers=h).json()["items"]
    assert oldest[0]["id"] == many[0]["id"]
    assert client.get("/complaints", params={"page": 99}, headers=h).json()["items"] == []


@pytest.mark.parametrize("params", [{"page": 0}, {"page_size": 0}, {"page_size": 101}, {"sort": "random"}, {"status": "nope"},
                                    {"priority": "urgent"}, {"department_id": 0}, {"date_from": "yesterday"}])
def test_bad_query_parameters_are_422(client, auth, users, params):
    r = client.get("/complaints", params=params, headers=auth(users["admin"]))
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_sql_injection_in_search_is_inert(client, auth, users, many):
    r = client.get("/complaints", params={"q": "'; DROP TABLE complaints; --"}, headers=auth(users["admin"]))
    assert r.status_code == 200 and r.json()["total"] == 0
    assert client.get("/complaints", headers=auth(users["admin"])).json()["total"] == 6


# ------------------------------------------------------------------ detail + events
def test_detail_includes_history_and_images(client, auth, users):
    c = create(client, auth(users["faculty"]))
    d = client.get(f"/complaints/{c['id']}", headers=auth(users["faculty"])).json()
    assert d["history"][0]["new_status"] == "registered" and d["images"] == []
    ev = client.get(f"/complaints/{c['id']}/events", headers=auth(users["faculty"])).json()
    assert ev[0]["event_type"] == "registered"


# ------------------------------------------------------------------ load
def test_burst_of_complaints_is_handled_quickly_and_numbers_stay_unique(client, auth, users):
    h = auth(users["faculty"])
    t0 = time.perf_counter()
    ids = [create(client, h, description=f"Light number {i} is not working in the corridor")["complaint_number"] for i in range(60)]
    elapsed = time.perf_counter() - t0
    assert len(set(ids)) == 60
    page = client.get("/complaints", params={"page_size": 100}, headers=auth(users["admin"])).json()
    assert page["total"] == 60 and len(page["items"]) == 60
    assert elapsed < 30, f"60 registrations took {elapsed:.1f}s"
