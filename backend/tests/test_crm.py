import io
import json

from tests.conftest import mk_lead, signup
from app.services import PhoneError, normalize_phone
import pytest


# ---------- auth ----------
def test_signup_login_me_logout(client):
    a = signup(client, "x@example.com", "X Org")
    assert a.get("/api/auth/me").json()["organizations"][0]["role"] == "owner"
    assert client.post("/api/auth/login", json={"email": "x@example.com", "password": "bad-password-1"}).status_code == 401
    assert client.post("/api/auth/logout", headers=a.h()).status_code == 204
    assert a.get("/api/auth/me").status_code == 401  # token revoked


def test_unauthenticated_and_weak_password(client):
    assert client.get("/api/leads").status_code == 401
    r = client.post("/api/auth/signup", json={"email": "a@example.com", "password": "short", "full_name": "A"})
    assert r.status_code == 422


def test_duplicate_signup(client):
    signup(client, "d@example.com")
    r = client.post("/api/auth/signup", json={"email": "D@example.com", "password": "correct-horse-1", "full_name": "D"})
    assert r.status_code == 409


def test_login_rate_limited(client):
    for _ in range(10):
        client.post("/api/auth/login", json={"email": "no@example.com", "password": "wrong-password"})
    assert client.post("/api/auth/login", json={"email": "no@example.com", "password": "wrong-password"}).status_code == 429


def test_password_reset_flow(client):
    signup(client, "r@example.com", "R")
    tok = client.post("/api/auth/forgot-password", json={"email": "r@example.com"}).json()["dev_reset_token"]
    assert client.post("/api/auth/reset-password", json={"token": tok, "new_password": "brand-new-pass-1"}).status_code == 200
    # token is single-use
    assert client.post("/api/auth/reset-password", json={"token": tok, "new_password": "another-pass-12"}).status_code == 400
    assert client.post("/api/auth/login", json={"email": "r@example.com", "password": "brand-new-pass-1"}).status_code == 200
    # unknown email gives same shape and no token
    assert "dev_reset_token" not in client.post("/api/auth/forgot-password", json={"email": "zz@example.com"}).json()


def test_active_org_required_and_membership_enforced(client, owner_a, owner_b):
    assert client.get("/api/leads", headers={"Authorization": f"Bearer {owner_a.token}"}).status_code == 400
    bad = client.get("/api/leads", headers={"Authorization": f"Bearer {owner_a.token}",
                                            "X-Organization-Id": owner_b.org_id})
    assert bad.status_code == 403


# ---------- roles ----------
def test_counsellor_cannot_manage(client, owner_a, counsellor_a):
    assert counsellor_a.post("/api/team", json={"email": "n@example.com", "full_name": "N", "role": "counsellor",
                                                "password": "correct-horse-1"}).status_code == 403
    assert counsellor_a.patch("/api/settings", json={"timezone": "Asia/Kolkata"}).status_code == 403
    assert counsellor_a.get("/api/leads/export").status_code == 403
    assert counsellor_a.post("/api/leads/bulk", json={"lead_ids": ["x"], "action": "delete", "confirm": True}).status_code == 403


def test_manager_cannot_grant_owner_or_change_roles(client, owner_a):
    r = owner_a.post("/api/team", json={"email": "m@example.com", "full_name": "M", "role": "manager",
                                        "password": "correct-horse-1"})
    mgr_login = client.post("/api/auth/login", json={"email": "m@example.com", "password": "correct-horse-1"}).json()
    from tests.conftest import Actor
    mgr = Actor(client, mgr_login["access_token"], owner_a.org_id)
    assert mgr.post("/api/team", json={"email": "o2@example.com", "full_name": "O", "role": "owner",
                                       "password": "correct-horse-1"}).status_code == 403
    assert mgr.patch(f"/api/team/{r.json()['user_id']}", json={"role": "owner"}).status_code == 403


def test_last_owner_protected(owner_a):
    assert owner_a.patch(f"/api/team/{owner_a.user_id}", json={"role": "manager"}).status_code == 409


def test_counsellor_sees_only_assigned(client, owner_a, counsellor_a):
    l1 = mk_lead(owner_a, "9876543210", assigned_to=counsellor_a.user_id).json()
    l2 = mk_lead(owner_a, "9876543211").json()
    ids = [l["id"] for l in counsellor_a.get("/api/leads").json()["items"]]
    assert ids == [l1["id"]]
    assert counsellor_a.get(f"/api/leads/{l2['id']}").status_code == 404
    assert counsellor_a.patch(f"/api/leads/{l1['id']}", json={"status": "Contacted"}).status_code == 200
    assert counsellor_a.post(f"/api/leads/{l1['id']}/assign", json={"assigned_to": None}).status_code == 403


# ---------- tenant isolation ----------
def test_tenant_isolation(client, owner_a, owner_b):
    la = mk_lead(owner_a).json()
    lid = la["id"]
    assert owner_b.get(f"/api/leads/{lid}").status_code == 404
    assert owner_b.patch(f"/api/leads/{lid}", json={"name": "hax"}).status_code == 404
    assert owner_b.delete(f"/api/leads/{lid}").status_code == 404
    assert owner_b.get(f"/api/leads/{lid}/activities").status_code == 404
    assert owner_b.post(f"/api/leads/{lid}/notes", json={"text": "x"}).status_code == 404
    assert owner_b.post(f"/api/leads/{lid}/consent", json={"purpose": "marketing", "status": "withdrawn"}).status_code == 404
    assert owner_b.get("/api/leads").json()["total"] == 0
    assert owner_b.post("/api/leads/bulk", json={"lead_ids": [lid], "action": "delete", "confirm": True}).status_code == 404
    # same phone in another org is allowed (uniqueness is per-org)
    assert mk_lead(owner_b).status_code == 201
    # cannot assign to a user from another org
    assert owner_a.post(f"/api/leads/{lid}/assign", json={"assigned_to": owner_b.user_id}).status_code == 422
    assert owner_a.get("/api/leads").json()["total"] == 1


# ---------- leads ----------
def test_create_update_activity_provenance(owner_a):
    r = mk_lead(owner_a, "+91 98765-43210", email="a@example.com", preferred_course="MBA")
    assert r.status_code == 201
    lead = r.json()
    assert lead["phone"] == "+919876543210"
    assert lead["status"] == "New"
    u = owner_a.patch(f"/api/leads/{lead['id']}", json={"budget_min": 100, "budget_max": 50})
    assert u.status_code == 422
    u = owner_a.patch(f"/api/leads/{lead['id']}", json={"preferred_location": "Pune", "status": "Contacted"})
    assert u.json()["field_provenance"]["preferred_location"]["source"].startswith("user:")
    kinds = [a["kind"] for a in owner_a.get(f"/api/leads/{lead['id']}/activities").json()]
    assert {"created", "updated", "status"} <= set(kinds)
    assert owner_a.patch(f"/api/leads/{lead['id']}", json={"status": "Bogus"}).status_code == 422


def test_duplicate_detection_normalized(owner_a):
    assert mk_lead(owner_a, "9876543210").status_code == 201
    for variant in ("+91 98765 43210", "09876543210", "919876543210"):
        r = mk_lead(owner_a, variant, name="Other")
        assert r.status_code == 409, variant
        assert "existing_lead_id" in r.json()["detail"]
    assert owner_a.get("/api/leads").json()["total"] == 1  # nothing overwritten
    assert owner_a.get("/api/leads").json()["items"][0]["name"] == "Asha"


def test_invalid_phone(owner_a):
    assert mk_lead(owner_a, "12345").status_code == 422
    assert mk_lead(owner_a, "5876543210").status_code == 422  # Indian mobiles start 6-9


@pytest.mark.parametrize("raw,expected", [("98765 43210", "+919876543210"), ("+14155552671", "+14155552671"),
                                          ("0091 9876543210", "+919876543210")])
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


def test_normalize_phone_errors():
    for bad in ("", "abc", "123"):
        with pytest.raises(PhoneError):
            normalize_phone(bad)


def test_search_filter_sort_paginate(owner_a):
    for i in range(30):
        mk_lead(owner_a, f"98765432{i:02d}", name=f"Student {i:02d}", preferred_course="MBA" if i % 2 else "BTech")
    p = owner_a.get("/api/leads", params={"page_size": 10, "page": 2, "sort": "name", "order": "asc"}).json()
    assert p["total"] == 30 and len(p["items"]) == 10 and p["items"][0]["name"] == "Student 10"
    assert owner_a.get("/api/leads", params={"q": "btech"}).json()["total"] == 15
    assert owner_a.get("/api/leads", params={"q": "student 07"}).json()["total"] == 1
    assert owner_a.get("/api/leads", params={"sort": "password"}).status_code == 422
    assert owner_a.get("/api/leads", params={"status": "Converted"}).json()["total"] == 0


# ---------- CSV ----------
def _csv(owner, content, mapping, dry=False):
    return owner.post("/api/leads/import", files={"file": ("l.csv", io.BytesIO(content.encode()), "text/csv")},
                      data={"mapping": json.dumps(mapping), "dry_run": str(dry).lower()})


MAP = {"name": "Name", "phone": "Mobile", "email": "Email", "budget_max": "Budget"}


def test_csv_import_validation_and_duplicates(owner_a):
    mk_lead(owner_a, "9000000001", name="Existing")
    content = ("Name,Mobile,Email,Budget\n"
               "Good One,9000000002,g@example.com,500000\n"
               "Dup Existing,9000000001,,\n"
               "Dup In File,90000 00002,,\n"
               ",9000000003,,\n"
               "Bad Phone,123,,\n"
               "Bad Email,9000000004,notanemail,\n"
               "Bad Budget,9000000005,,lots\n"
               "Fine Two,9000000006,,\n")
    dry = _csv(owner_a, content, MAP, dry=True).json()
    assert dry["created"] == 2 and dry["error_count"] == 4 and dry["duplicate_count"] == 2
    assert owner_a.get("/api/leads").json()["total"] == 1  # dry run wrote nothing
    res = _csv(owner_a, content, MAP).json()
    assert res["created"] == 2 and res["error_count"] == 4 and res["duplicate_count"] == 2
    assert {e["row"] for e in res["errors"]} == {5, 6, 7, 8}
    leads = owner_a.get("/api/leads").json()["items"]
    assert len(leads) == 3
    assert next(l for l in leads if l["phone"] == "+919000000001")["name"] == "Existing"
    assert all(l["source_name"] == "CSV Import" for l in leads if l["name"] != "Existing")


def test_csv_import_rejects_bad_mapping_and_files(owner_a, counsellor_a):
    assert _csv(owner_a, "Name,Mobile\nA,9000000002\n", {"name": "Name"}).status_code == 422
    assert _csv(owner_a, "Name,Mobile\nA,9000000002\n", {"name": "Name", "phone": "Nope"}).status_code == 422
    assert _csv(owner_a, "Name,Mobile\nA,9000000002\n", {"name": "Name", "phone": "Mobile", "is_admin": "x"}).status_code == 422
    assert _csv(counsellor_a, "Name,Mobile\nA,9000000002\n", {"name": "Name", "phone": "Mobile"}).status_code == 403


def test_csv_export_escapes_formulas_and_is_scoped(owner_a, owner_b, counsellor_a):
    mk_lead(owner_a, "9000000001", name="=cmd|' /C calc'!A0")
    mk_lead(owner_b, "9000000002", name="Other tenant")
    csv_text = owner_a.get("/api/leads/export").text
    assert "'=cmd" in csv_text and "Other tenant" not in csv_text
    assert counsellor_a.get("/api/leads/export").status_code == 403


# ---------- bulk ----------
def test_bulk_requires_confirm(owner_a):
    lid = mk_lead(owner_a).json()["id"]
    body = {"lead_ids": [lid], "action": "status", "status": "Contacted"}
    assert owner_a.post("/api/leads/bulk", json=body).status_code == 422
    assert owner_a.post("/api/leads/bulk", json={**body, "confirm": True}).json()["affected"] == 1
    assert owner_a.get(f"/api/leads/{lid}").json()["status"] == "Contacted"


# ---------- consent / DNC ----------
def test_consent_append_only_and_manual_needs_evidence(owner_a):
    lid = mk_lead(owner_a).json()["id"]
    url = f"/api/leads/{lid}/consent"
    assert owner_a.post(url, json={"purpose": "automated_calls", "status": "granted"}).status_code == 422
    assert owner_a.post(url, json={"purpose": "automated_calls", "status": "granted",
                                   "evidence": {"note": "verbal on walk-in"}}).status_code == 201
    assert owner_a.get(f"/api/leads/{lid}").json()["consent"]["automated_calls"] == "granted"
    owner_a.post(url, json={"purpose": "automated_calls", "status": "withdrawn"})
    assert owner_a.get(f"/api/leads/{lid}").json()["consent"]["automated_calls"] == "withdrawn"
    assert len(owner_a.get(url).json()) == 2  # history retained


def test_dnc_status_withdraws_consent_and_cancels_jobs(owner_a, Session):
    from app.models import CallJob
    lid = mk_lead(owner_a).json()["id"]
    owner_a.post(f"/api/leads/{lid}/consent", json={"purpose": "automated_calls", "status": "granted",
                                                    "evidence": {"note": "form"}})
    with Session() as db:
        db.add(CallJob(organization_id=owner_a.org_id, lead_id=lid, dedupe_key="k1"))
        db.commit()
    assert owner_a.patch(f"/api/leads/{lid}", json={"status": "Do Not Contact"}).status_code == 200
    d = owner_a.get(f"/api/leads/{lid}").json()
    assert d["do_not_contact"] and d["consent"]["automated_calls"] == "withdrawn"
    with Session() as db:
        assert db.query(CallJob).one().status == "cancelled"
    # cannot re-grant consent while DNC
    assert owner_a.post(f"/api/leads/{lid}/consent", json={"purpose": "automated_calls", "status": "granted",
                                                           "evidence": {"note": "x"}}).status_code == 409


# ---------- tasks / notes / settings ----------
def test_tasks_and_notes(owner_a, counsellor_a):
    lid = mk_lead(owner_a, assigned_to=counsellor_a.user_id).json()["id"]
    t = counsellor_a.post(f"/api/leads/{lid}/tasks", json={"title": "Call back", "due_at": "2030-01-01T10:00:00Z"})
    assert t.status_code == 201
    assert len(counsellor_a.get("/api/tasks").json()) == 1
    assert counsellor_a.patch(f"/api/tasks/{t.json()['id']}", json={"status": "done"}).json()["status"] == "done"
    assert counsellor_a.post(f"/api/leads/{lid}/notes", json={"text": "Parent prefers evenings"}).status_code == 201


def test_settings_validation(owner_a):
    assert owner_a.patch("/api/settings", json={"timezone": "Mars/Base"}).status_code == 422
    assert owner_a.patch("/api/settings", json={"lead_statuses": ["Foo"]}).status_code == 422
    assert owner_a.patch("/api/settings", json={"timezone": "Asia/Kolkata"}).status_code == 200
