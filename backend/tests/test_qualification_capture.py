from tests.conftest import mk_lead
from app.models import Organization, KnowledgeDocument, Lead, ConsentRecord
from app.qualification import evaluate_qualification, DEFAULT_RULES


def test_deterministic_qualification_rules():
    # Hard failure: Marks below required
    l1 = Lead(
        organization_id="org1",
        name="Student Low Marks",
        phone="+919876543210",
        phone_normalized="+919876543210",
        preferred_course="MBBS",
        preferred_location="Pune",
        academic_marks=45.0, # MBBS requires 60%
        budget_max=2000000,
    )
    res1 = evaluate_qualification(l1, DEFAULT_RULES)
    assert res1["category"] == "ineligible"
    assert any("below minimum required" in f for f in res1["hard_failures"])

    # Hard failure: Budget below threshold
    l2 = Lead(
        organization_id="org1",
        name="Student Low Budget",
        phone="+919876543211",
        phone_normalized="+919876543211",
        preferred_course="MBA",
        preferred_location="Bengaluru",
        academic_marks=75.0,
        budget_max=400000, # MBA budget limit in rules is 1,000,000
    )
    res2 = evaluate_qualification(l2, DEFAULT_RULES)
    assert res2["category"] == "ineligible"
    assert any("below estimated minimum" in f for f in res2["hard_failures"])

    # Missing required fields -> needs_info
    l3 = Lead(
        organization_id="org1",
        name="Student Incomplete",
        phone="+919876543212",
        phone_normalized="+919876543212",
        preferred_course=None,
        preferred_location=None,
    )
    res3 = evaluate_qualification(l3, DEFAULT_RULES)
    assert res3["category"] == "needs_info"
    assert "preferred_course" in res3["missing_fields"]
    assert "preferred_location" in res3["missing_fields"]

    # High marks & urgency -> eligible with high score
    l4 = Lead(
        organization_id="org1",
        name="Top Student",
        phone="+919876543213",
        phone_normalized="+919876543213",
        email="top@example.com",
        preferred_course="B.Tech Computer Science",
        preferred_college="COEP",
        education_level="12th",
        academic_marks=92.0,
        preferred_location="Pune",
        budget_max=800000,
        admission_timeline="Immediate",
    )
    res4 = evaluate_qualification(l4, DEFAULT_RULES)
    assert res4["category"] == "eligible"
    assert res4["priority_score"] >= 80
    assert len(res4["hard_failures"]) == 0
    assert "High profile completeness" in res4["reasons"]


def test_qualification_endpoint_and_provenance(owner_a):
    r = mk_lead(
        owner_a,
        "9876500001",
        name="Priya Sharma",
        preferred_course="MBA",
        preferred_location="Pune",
        academic_marks=80.0,
        budget_max=1200000,
        admission_timeline="This year",
    )
    lid = r.json()["id"]

    q = owner_a.post(f"/api/leads/{lid}/qualify")
    assert q.status_code == 200
    data = q.json()
    assert data["category"] == "eligible"
    assert data["priority_score"] >= 70

    # Verify provenance was saved
    updated_lead = owner_a.get(f"/api/leads/{lid}").json()
    assert updated_lead["qualification_category"] == "eligible"
    assert updated_lead["qualification_score"] == data["priority_score"]
    assert "qualification" in updated_lead["field_provenance"]
    assert updated_lead["field_provenance"]["qualification"]["source"].startswith("qualify_engine:")

    # Verify history list
    hist = owner_a.get(f"/api/leads/{lid}/qualification").json()
    assert len(hist) >= 1
    assert hist[0]["category"] == "eligible"


def test_knowledge_base_crud_and_permissions(owner_a, counsellor_a):
    # Counsellor cannot create or approve
    bad = counsellor_a.post("/api/knowledge", json={"title": "Hostel Fees", "content": "1 Lakh per year"})
    assert bad.status_code == 403

    # Owner creates
    doc = owner_a.post("/api/knowledge", json={
        "title": "MBA Admission 2026 Eligibility and Fees",
        "content": "Tuition fees for the 2-year MBA are ₹6,50,000. Minimum marks required: 50% in graduation.",
        "is_approved": True,
    }).json()
    assert doc["is_approved"] is True
    assert doc["title"].startswith("MBA")

    # Read docs
    docs = counsellor_a.get("/api/knowledge").json()
    assert len(docs) == 1
    assert docs[0]["id"] == doc["id"]

    # Update doc
    up = owner_a.patch(f"/api/knowledge/{doc['id']}", json={"content": "Updated fee is ₹7,00,000."})
    assert up.status_code == 200
    assert "₹7,00,000" in up.json()["content"]


def test_public_web_lead_form_with_consent(client, owner_a, Session):
    with Session() as db:
        org = db.query(Organization).filter(Organization.id == owner_a.org_id).one()
        pub_key = org.public_key

    # Config endpoint
    cfg = client.get(f"/api/public/config?key={pub_key}").json()
    assert cfg["organization_name"] == "Alpha Admissions"
    assert len(cfg["courses_offered"]) > 0

    # Submit lead form
    res = client.post("/api/public/lead", json={
        "public_key": pub_key,
        "name": "Web Visitor",
        "phone": "+91 91234 56789",
        "email": "visitor@example.com",
        "preferred_course": "MBA",
        "preferred_location": "Pune",
        "academic_marks": 72.0,
        "budget_max": 1200000,
        "admission_timeline": "Next 1-2 months",
        "consent_automated_calls": True,
        "consent_marketing": False,
    })
    assert res.status_code == 201
    assert res.json()["success"] is True

    # Check lead was created in CRM with consent and qualified
    leads = owner_a.get("/api/leads", params={"q": "9123456789"}).json()["items"]
    assert len(leads) == 1
    l = leads[0]
    assert l["name"] == "Web Visitor"
    assert l["qualification_category"] == "eligible"

    # Consent checked
    detail = owner_a.get(f"/api/leads/{l['id']}").json()
    assert detail["consent"]["automated_calls"] == "granted"
    assert detail["consent"]["marketing"] == "none"


def test_public_chatbot_grounded_conversation_and_consent(client, owner_a, Session):
    with Session() as db:
        org = db.query(Organization).filter(Organization.id == owner_a.org_id).one()
        pub_key = org.public_key

    # 1. Add approved document for knowledge grounding
    owner_a.post("/api/knowledge", json={
        "title": "Scholarship Guidelines 2026",
        "content": "Merit scholarships of 25% fee waiver are granted to students with marks above 85% in entrance tests.",
        "is_approved": True,
    })

    # Step 1: Initial user greeting asking question about scholarship
    m1 = client.post("/api/public/chat", json={
        "public_key": pub_key,
        "message": "Hi, what are the scholarship guidelines?",
    }).json()
    sess_id = m1["session_id"]
    # Verified ground knowledge included in reply
    assert "fee waiver" in m1["reply"]

    # Step 2: User provides course
    m2 = client.post("/api/public/chat", json={
        "public_key": pub_key,
        "session_id": sess_id,
        "message": "I want to apply for MBA in Pune",
    }).json()
    assert "phone" in m2["reply"].lower()

    # Step 3: User provides phone number and name
    m3 = client.post("/api/public/chat", json={
        "public_key": pub_key,
        "session_id": sess_id,
        "message": "My name is Rohit Gupta and mobile is 9822012345",
    }).json()
    assert "consent" in m3["reply"].lower()

    # Step 4: User grants consent explicitly
    m4 = client.post("/api/public/chat", json={
        "public_key": pub_key,
        "session_id": sess_id,
        "message": "Yes, I agree and give consent",
    }).json()
    assert "consent has been recorded" in m4["reply"].lower()

    # Verify lead created and consent recorded in CRM
    leads = owner_a.get("/api/leads", params={"q": "9822012345"}).json()["items"]
    assert len(leads) == 1
    lead = leads[0]
    assert lead["name"] == "Rohit Gupta"
    assert lead["preferred_course"] == "MBA"

    lead_detail = owner_a.get(f"/api/leads/{lead['id']}").json()
    assert lead_detail["consent"]["automated_calls"] == "granted"


def test_chatbot_unsupported_question_does_not_hallucinate(client, owner_a, Session):
    with Session() as db:
        org = db.query(Organization).filter(Organization.id == owner_a.org_id).one()
        pub_key = org.public_key

    # Query with facts not in approved docs (e.g. fake placement guarantee)
    m = client.post("/api/public/chat", json={
        "public_key": pub_key,
        "message": "Do you offer 100% Google placement guarantee with 50 LPA salary?",
    }).json()

    # Does not fabricate promises
    assert "100%" not in m["reply"]
    # Directs to counsellor or admits no verified details
    assert any(term in m["reply"].lower() for term in ["course", "counsellor", "approved", "admissions handbook", "degree"])
