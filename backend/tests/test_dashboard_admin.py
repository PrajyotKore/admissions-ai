from tests.conftest import Actor, mk_lead, signup
from app.models import User


def test_dashboard_scoped_and_defined(client, owner_a, owner_b, counsellor_a):
    mk_lead(owner_a, "9876543210", source_name="Walk-in", assigned_to=counsellor_a.user_id)
    mk_lead(owner_a, "9876543211", source_name="Walk-in")
    mk_lead(owner_b, "9876543212")
    d = owner_a.get("/api/dashboard").json()
    assert d["total_leads"] == 2 and d["leads_by_source"] == {"Walk-in": 2}
    assert d["leads_by_status"] == {"New": 2}
    assert d["qualification_rate"]["value"] is None  # no denominator -> not fabricated
    assert d["contact_rate"]["denominator"] == 0
    assert "definition" in d["conversion_rate"]
    assert owner_b.get("/api/dashboard").json()["total_leads"] == 1
    assert counsellor_a.get("/api/dashboard").json()["total_leads"] == 1


def test_conversion_rate_uses_closed_outcomes(owner_a):
    ids = [mk_lead(owner_a, f"98765432{i}0").json()["id"] for i in range(3)]
    for lid, st in zip(ids, ["Converted", "Converted", "Not Interested"]):
        owner_a.patch(f"/api/leads/{lid}", json={"status": st})
    c = owner_a.get("/api/dashboard").json()["conversion_rate"]
    assert (c["numerator"], c["denominator"]) == (2, 3)


def test_platform_admin_endpoints(client, owner_a, Session):
    assert owner_a.get("/api/admin/organizations").status_code == 403
    with Session() as db:
        db.query(User).filter(User.id == owner_a.user_id).one().is_platform_admin = True
        db.commit()
    mk_lead(owner_a)
    orgs = owner_a.get("/api/admin/organizations").json()
    assert orgs[0]["leads"] == 1 and "name" in orgs[0]
    # aggregate only: no lead-level fields exposed
    assert "phone" not in str(orgs)
    assert owner_a.post(f"/api/admin/organizations/{owner_a.org_id}/active?active=false").status_code == 200
    assert owner_a.get("/api/leads").status_code == 403  # deactivated org is blocked
