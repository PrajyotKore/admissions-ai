# Admissions AI: Multi-Tenant Lead Management & AI Telephony Platform

A production-minded, multi-tenant SaaS platform built for **educational admissions consultancies** to automate student lead capture, eligibility qualification, voice-based outreach, and CRM follow-ups with strict regulatory compliance and zero-hallucination knowledge grounding.

---

## 1. System Architecture

```
                                  +---------------------------------------+
                                  |   Public Students / Visitors          |
                                  | - Embeddable Chatbot (/widget/chat)   |
                                  | - Fallback Lead Form (/widget/form)   |
                                  +-------------------+-------------------+
                                                      |
                                                      | HTTPS REST (Rate-limited)
                                                      v
+-----------------------------+        +-----------------------------------+
| Next.js 16 Web Dashboard    |        | FastAPI Backend Service (:8000)   |
| - App Router / React 19     |------->| - Multi-Tenant Scoping (Header)   |
| - Tailwind CSS v4           | Bearer | - JWT Auth + Session Revocation   |
| - Counsellor / Manager CRM  | Auth   | - Deterministic Qualification     |
| - Voice Queue & Transcripts |        | - Telephony Queue & Compliance    |
+-----------------------------+        +-----------------+-----------------+
                                                         |
                                 +-----------------------+-----------------------+
                                 |                       |                       |
                                 v                       v                       v
                      +--------------------+  +--------------------+  +--------------------+
                      | SQLite / Postgres  |  | Approved Knowledge |  | Mock Telephony     |
                      | SQLAlchemy 2.0 ORM |  | Document Store     |  | Engine             |
                      | 19 Relational Tbls |  | (Grounded Facts)   |  | (is_synthetic=True)|
                      +--------------------+  +--------------------+  +--------------------+
```

---

## 2. Core Capabilities & Workflows

### 2.1 Multi-Tenant Organization Isolation
- **Organization Hierarchy:** Supports multiple consultancies with isolated student databases, team members, knowledge bases, and calling queues.
- **Role-Based Access Control (RBAC):**
  - `owner`: Full organizational control, billing, settings, deletion, team provisioning.
  - `manager`: Lead assignment, knowledge base document approvals, call queue toggling, CRM analytics.
  - `counsellor`: Access to assigned student leads, personal follow-up tasks, call notes, manual call triggers.
- **Tenant Context:** Securely scoped via `X-Organization-Id` HTTP header and verified against authenticated user memberships in database queries.

### 2.2 Student Lead Management & Normalized Deduplication
- **E.164 Phone Normalization:** Automatically standardizes Indian numbers to `+91[6-9]\d{9}`.
- **Conflict Prevention:** Never silently overwrites or merges conflicting leads on duplicate entry. Flags duplicates and increments contact logs.
- **CSV Import / Export:**
  - Import supports column mapping, dry-run validation, and line-by-line error reports.
  - Export sanitizes all strings against formula injection attacks (prefixes `=`, `+`, `-`, `@` with a tab).
- **Field Provenance:** Tracks the originating source and timestamp for every student profile attribute (e.g. `website_chatbot`, `counsellor_edit`, `csv_import`).

### 2.3 Deterministic Qualification Engine
- **Transparent Logic:** Separates hard eligibility criteria (academic marks cutoff, minimum budget) from soft prioritisation scoring (0–100).
- **Provenance & Next Actions:** Generates structured records documenting hard failures, missing data fields, supporting criteria, and recommended next actions (e.g. `"Schedule counsellor callback"`).

### 2.4 Grounded Knowledge Base (Zero Hallucination)
- **Document Ingestion:** Consultancies upload course catalogs, fee structures, eligibility guidelines, and seat matrices.
- **Manager Approval Gate:** Documents must be explicitly approved by a `manager` before the AI assistant or voice agent can cite facts from them.
- **Fact Retrieval:** AI queries search strictly approved knowledge documents; never invents cutoffs, costs, or seat guarantees.

### 2.5 Compliant AI Voice Telephony Engine
- **Synthetic Call Labeling:** Every simulated call and usage record is explicitly tagged `is_synthetic = True` for auditability and compliance.
- **Pre-Dial Verification Checklist:**
  1. Lead must have explicit `automated_calls: granted` consent recorded in the append-only ledger.
  2. Lead must not be marked `Do Not Contact`.
  3. Lead must not exceed the daily call attempt threshold (default: 2 per day).
  4. Local time must be within legal calling hours (09:00 to 21:00 in tenant timezone).
  5. Organization calling queue must not be paused.
- **Call Outcomes & Sync:** Automatically transcribes dialogue, summarizes conversation intent, extracts structured fields, and schedules follow-up tasks or appointments in the CRM.

---

## 3. Technology Stack

| Layer | Technologies |
|---|---|
| **Backend** | Python 3.12, FastAPI, SQLAlchemy 2.0, Pydantic v2, Uvicorn, Passlib (Argon2 / Bcrypt) |
| **Database** | SQLite (development/testing) / PostgreSQL (production), Alembic migrations |
| **Frontend** | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS v4 |
| **Telephony** | Extensible Telephony Provider Interface with `MockVoiceProvider` implementation |
| **Testing** | Pytest, HTTPX, Playwright / Browser Agent |

---

## 4. Quick Start & Running Locally

### 4.1 Prerequisites
- Python 3.11+
- Node.js 18+ and npm
- Git

### 4.2 Backend Setup

```bash
# 1. Navigate to backend directory
cd backend

# 2. Activate virtual environment (Windows PowerShell)
.\.venv\Scripts\Activate.ps1
# Or on Linux/macOS: source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Seed the database with demo consultancy, counsellors, and student leads
python -m app.seed

# 5. Start the FastAPI development server with auto-reload
python -m uvicorn app.main:app --reload --port 8000
```

The backend API will be available at `http://localhost:8000`.
- Interactive Swagger API docs: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/api/health`

### 4.3 Frontend Setup

```bash
# 1. In a new terminal, navigate to frontend directory
cd frontend

# 2. Install dependencies
npm install

# 3. Start the Next.js development server
npm run dev -- -p 3000
```

Open `http://localhost:3000` in your web browser.

### 4.4 Default Demo Credentials

| Role | Email | Password | Organization |
|---|---|---|---|
| **Owner** | `owner@demo.example` | `demo-password-123` | Demo Admissions (DEMO) |
| **Counsellor** | `counsellor@demo.example` | `demo-password-123` | Demo Admissions (DEMO) |

---

## 5. API Reference Catalog

All endpoints require authentication (Bearer JWT token) except `/api/auth/*` and public endpoints `/api/public/*`.

### 5.1 Authentication & Tenancy
- `POST /api/auth/signup` — Register new user account.
- `POST /api/auth/login` — Authenticate and receive access token + user organizations.
- `POST /api/auth/logout` — Revoke token session.
- `GET /api/auth/me` — Current user profile and memberships.
- `POST /api/organizations` — Create new admissions consultancy organization.
- `GET /api/team` — List organization staff members (Owner, Manager, Counsellor).
- `POST /api/team` — Invite or provision a new team member.

### 5.2 Student Leads CRM
- `GET /api/leads` — List leads with search, filters (status, qualification, source, counsellor), sorting, and pagination.
- `POST /api/leads` — Create new student lead with E.164 normalization and duplicate detection.
- `GET /api/leads/{id}` — Get complete student lead profile.
- `PATCH /api/leads/{id}` — Update student academic and preference details with provenance.
- `POST /api/leads/{id}/notes` — Add internal counsellor note.
- `POST /api/leads/{id}/consent` — Record append-only consent grant or withdrawal.
- `POST /api/leads/{id}/tasks` — Schedule follow-up task.
- `POST /api/leads/import/preview` — Dry-run CSV import with field mapping.
- `POST /api/leads/import/commit` — Execute bulk lead import with conflict checks.
- `GET /api/leads/export/csv` — Export leads with formula-injection sanitization.

### 5.3 Deterministic Qualification
- `POST /api/leads/{id}/qualify` — Execute deterministic qualification check against course criteria and budget ranges.
- `GET /api/leads/{id}/qualification` — Retrieve qualification history and factors.

### 5.4 Grounded Knowledge Base
- `GET /api/knowledge` — List uploaded knowledge documents.
- `POST /api/knowledge` — Upload new guidelines / fee structures / course catalogs.
- `POST /api/knowledge/{id}/approve` — Approve document for public and voice AI citation (Manager/Owner only).
- `DELETE /api/knowledge/{id}` — Archive or delete outdated document.

### 5.5 AI Voice Telephony & Queue
- `POST /api/calls/trigger/{lead_id}?execute_now=true` — Trigger an immediate AI voice outreach call.
- `GET /api/calls/queue` — Inspect live pending calling jobs.
- `POST /api/calls/queue/{job_id}/cancel` — Cancel scheduled call attempt.
- `POST /api/calls/queue/pause?paused=true` — Global kill-switch to pause all automated dialing.
- `POST /api/calls/queue/process` — Process next batch of due calls.
- `GET /api/calls/history` — Historical call logs with outcome filters and duration.
- `GET /api/calls/attempts/{id}` — Full conversation intelligence, verbatim transcript, and next action recommendations.
- `POST /api/calls/webhooks/{provider}` — Idempotent webhook receiver for telephony carriers.

### 5.6 Public Widgets & Lead Capture
- `POST /api/public/chat` — Rate-limited, knowledge-grounded student admissions chatbot.
- `POST /api/public/lead` — Standalone website lead capture form endpoint.
- `GET /api/public/settings` — Public brand name and course list for widget rendering.

---

## 6. Public Website Widget Integration

Admissions consultancies can embed the Admissions AI assistant directly onto their marketing websites using lightweight iframes or JavaScript snippets.

### 6.1 Embeddable Floating Chatbot

Add the following iframe snippet to any webpage:

```html
<iframe
  src="https://your-admissions-domain.com/widget/chat?org=YOUR_ORG_ID"
  style="position: fixed; bottom: 20px; right: 20px; width: 380px; height: 560px; border: none; z-index: 9999; border-radius: 16px; box-shadow: 0 10px 30px rgba(0,0,0,0.15);"
  title="Admissions AI Assistant"
  allow="microphone"
></iframe>
```

### 6.2 Standalone Lead Capture Form

For landing pages and admissions enquiry sections:

```html
<iframe
  src="https://your-admissions-domain.com/widget/form?org=YOUR_ORG_ID"
  style="width: 100%; max-width: 600px; height: 620px; border: none;"
  title="Enquiry Form"
></iframe>
```

*(You can copy personalized snippets with your organization ID directly from the **Settings** page in the dashboard).*

---

## 7. Extending the Telephony Engine

The platform defines a clean abstract interface in `backend/app/voice/provider.py`:

```python
class VoiceProvider(ABC):
    @abstractmethod
    def initiate_call(self, to_phone: str, lead_context: dict[str, Any]) -> ProviderCallResponse:
        pass

    @abstractmethod
    def parse_webhook_event(self, raw_payload: dict[str, Any]) -> NormalizedCallEvent:
        pass
```

To connect a live telephony carrier (e.g. Twilio, Exotel, Plivo, or Bland AI):
1. Subclass `VoiceProvider` and implement `initiate_call` and `parse_webhook_event`.
2. Configure provider API credentials in `backend/app/config.py`.
3. Set `is_synthetic = False` on production call records and link carrier webhooks to `/api/calls/webhooks/<provider_name>`.

---

## 8. Compliance & Security Highlights

1. **Explicit Consent & DNC Propagation:**
   - Dialing without explicit `automated_calls: granted` consent is strictly prohibited and rejected at both the service and database levels.
   - When a student requests Do Not Contact (`DNC`), all future calling is blocked immediately and pending scheduled queue jobs are canceled.
2. **Quiet Hours Enforcement:**
   - Automated outreach is legally restricted to `09:00 - 21:00` in the consultancy's local timezone.
3. **Audit Trails:**
   - All significant operations (lead modifications, assignments, qualification runs, consent grants/revocations, and settings changes) are recorded in the immutable `audit_events` ledger.
4. **Formula Injection Defense:**
   - CSV exports sanitize formula trigger characters (`=`, `+`, `-`, `@`) preventing spreadsheet code execution vulnerabilities.

---

## 9. Running Tests

The test suite covers multi-tenancy, authentication, deduplication, CSV operations, deterministic qualification, public chatbot rate-limiting, and voice queueing.

```bash
cd backend
.\.venv\Scripts\python -m pytest -v
```

**Test Status:** 43 passed (100% test pass rate).
