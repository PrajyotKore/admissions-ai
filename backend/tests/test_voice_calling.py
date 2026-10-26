from tests.conftest import mk_lead
from app.models import Lead, CallJob, CallAttempt, ConsentRecord, Appointment, FollowUpTask


def test_consent_enforcement_prevents_calling(owner_a):
    r = mk_lead(owner_a, "9876599991", name="No Consent Student")
    lid = r.json()["id"]

    # No consent granted yet
    call_req = owner_a.post(f"/api/calls/trigger/{lid}")
    assert call_req.status_code == 409
    assert "consent" in call_req.json()["detail"].lower()


def test_dnc_prevents_calling(owner_a):
    r = mk_lead(owner_a, "9876599992", name="DNC Student")
    lid = r.json()["id"]

    # Grant consent
    owner_a.post(f"/api/leads/{lid}/consent", json={
        "purpose": "automated_calls",
        "status": "granted",
        "evidence": {"note": "phone agreement"},
    })

    # Mark Do Not Contact
    owner_a.patch(f"/api/leads/{lid}", json={"status": "Do Not Contact"})

    # Attempt call
    call_req = owner_a.post(f"/api/calls/trigger/{lid}")
    assert call_req.status_code == 409
    assert "do not contact" in call_req.json()["detail"].lower()


def test_mock_voice_call_execution_and_synthetic_flag(owner_a):
    r = mk_lead(owner_a, "9876599993", name="Eligible Voice Student", preferred_course="MBA")
    lid = r.json()["id"]

    # Grant consent
    owner_a.post(f"/api/leads/{lid}/consent", json={
        "purpose": "automated_calls",
        "status": "granted",
        "evidence": {"note": "web agreement"},
    })

    # Trigger call immediately
    call_res = owner_a.post(f"/api/calls/trigger/{lid}?execute_now=true")
    assert call_res.status_code == 201
    data = call_res.json()

    attempt = data["attempt"]
    assert attempt is not None
    # CRITICAL VERIFICATION: Mock calls must be explicitly labeled synthetic
    assert attempt["is_synthetic"] is True
    assert attempt["provider"] == "mock"
    assert attempt["status"] in ("completed", "no_answer", "busy")

    # Verify attempt detail endpoint with transcript and AI summary
    att_detail = owner_a.get(f"/api/calls/attempts/{attempt['id']}").json()
    assert att_detail["is_synthetic"] is True
    if attempt["status"] == "completed":
        assert att_detail["transcript"] is not None
        assert "AI Assistant:" in att_detail["transcript"]
        assert att_detail["summary"] is not None
        assert "MBA" in att_detail["transcript"] or "Student" in att_detail["transcript"]


def test_calling_queue_and_cancellation(owner_a):
    r = mk_lead(owner_a, "9876599994", name="Queue Student")
    lid = r.json()["id"]

    owner_a.post(f"/api/leads/{lid}/consent", json={
        "purpose": "automated_calls",
        "status": "granted",
        "evidence": {"note": "verbal agreement"},
    })

    # Enqueue without immediate execution
    q_res = owner_a.post(f"/api/calls/trigger/{lid}?execute_now=false").json()
    job = q_res["job"]
    assert job["status"] == "queued"

    # View in queue
    queue = owner_a.get("/api/calls/queue?status=queued").json()
    assert any(j["id"] == job["id"] for j in queue)

    # Cancel job
    c_res = owner_a.post(f"/api/calls/queue/{job['id']}/cancel")
    assert c_res.status_code == 200
    assert c_res.json()["status"] == "cancelled"


def test_queue_background_processing(owner_a):
    r = mk_lead(owner_a, "9876599995", name="Batch Call Student")
    lid = r.json()["id"]

    owner_a.post(f"/api/leads/{lid}/consent", json={
        "purpose": "automated_calls",
        "status": "granted",
        "evidence": {"note": "consent agreement"},
    })

    # Enqueue
    owner_a.post(f"/api/calls/trigger/{lid}?execute_now=false")

    # Run queue processor
    proc_res = owner_a.post("/api/calls/queue/process")
    assert proc_res.status_code == 200
    assert proc_res.json()["processed"] >= 1


def test_webhook_idempotency(owner_a):
    # Send webhook event
    evt_payload = {
        "event_id": "evt-unique-12345",
        "event_type": "call.completed",
        "call_id": "mock-call-ext-1",
        "outcome": "Interested",
        "duration_seconds": 120,
    }
    r1 = owner_a.post("/api/calls/webhooks/mock", json=evt_payload)
    assert r1.status_code == 200
    assert r1.json()["status"] == "processed"

    # Send exact duplicate event -> idempotently ignored
    r2 = owner_a.post("/api/calls/webhooks/mock", json=evt_payload)
    assert r2.status_code == 200
    assert r2.json()["status"] == "ignored"


def test_calls_tenant_isolation(owner_a, owner_b):
    r = mk_lead(owner_a, "9876599996", name="Tenant A Student")
    lid = r.json()["id"]
    owner_a.post(f"/api/leads/{lid}/consent", json={
        "purpose": "automated_calls",
        "status": "granted",
        "evidence": {"note": "test"},
    })
    c = owner_a.post(f"/api/calls/trigger/{lid}?execute_now=true").json()
    attempt_id = c["attempt"]["id"]

    # Tenant B cannot access attempt detail
    bad = owner_b.get(f"/api/calls/attempts/{attempt_id}")
    assert bad.status_code == 404

    # Tenant B cannot see Tenant A calls in history
    b_history = owner_b.get("/api/calls/history").json()
    assert all(item["id"] != attempt_id for item in b_history["items"])
