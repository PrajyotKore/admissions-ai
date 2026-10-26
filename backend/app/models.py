"""All tables. IDs are UUID strings (non-guessable). Every tenant table carries organization_id."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer,
                        String, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def uid() -> str:
    return str(uuid.uuid4())


def now() -> datetime:
    return datetime.now(timezone.utc)


class Stamped:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


def pk():
    return mapped_column(String(36), primary_key=True, default=uid)


def org_fk():
    return mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), index=True)


class User(Base, Stamped):
    __tablename__ = "users"
    id: Mapped[str] = pk()
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(200))
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # incremented on password change/reset to invalidate old tokens
    token_version: Mapped[int] = mapped_column(Integer, default=0)


class Organization(Base, Stamped):
    __tablename__ = "organizations"
    id: Mapped[str] = pk()
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    # public key used by embeddable chatbot/lead form (not a secret)
    public_key: Mapped[str] = mapped_column(String(36), unique=True, default=uid)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class OrganizationMembership(Base, Stamped):
    __tablename__ = "organization_memberships"
    __table_args__ = (UniqueConstraint("organization_id", "user_id"),)
    id: Mapped[str] = pk()
    organization_id: Mapped[str] = org_fk()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # owner | manager | counsellor
    user: Mapped[User] = relationship()


class OrganizationSettings(Base, Stamped):
    __tablename__ = "organization_settings"
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    lead_statuses: Mapped[list] = mapped_column(JSON, default=list)
    qualification_rules: Mapped[dict] = mapped_column(JSON, default=dict)
    chatbot_config: Mapped[dict] = mapped_column(JSON, default=dict)
    calling_config: Mapped[dict] = mapped_column(JSON, default=dict)
    retention_days: Mapped[int] = mapped_column(Integer, default=365)
    calling_paused: Mapped[bool] = mapped_column(Boolean, default=False)


class LeadSource(Base, Stamped):
    __tablename__ = "lead_sources"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)
    id: Mapped[str] = pk()
    organization_id: Mapped[str] = org_fk()
    name: Mapped[str] = mapped_column(String(100))


class Lead(Base, Stamped):
    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint("organization_id", "phone_normalized", name="uq_lead_org_phone"),
        Index("ix_leads_org_status", "organization_id", "status"),
    )
    id: Mapped[str] = pk()
    organization_id: Mapped[str] = org_fk()
    name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str] = mapped_column(String(32))
    phone_normalized: Mapped[str] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    preferred_course: Mapped[str | None] = mapped_column(String(200), nullable=True)
    preferred_college: Mapped[str | None] = mapped_column(String(200), nullable=True)
    education_level: Mapped[str | None] = mapped_column(String(100), nullable=True)
    academic_marks: Mapped[float | None] = mapped_column(Float, nullable=True)
    preferred_location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    budget_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    budget_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    admission_timeline: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_id: Mapped[str | None] = mapped_column(ForeignKey("lead_sources.id"), nullable=True)
    source_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    assigned_to: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    qualification_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    qualification_category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="New")
    last_contact_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_follow_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    do_not_contact: Mapped[bool] = mapped_column(Boolean, default=False)
    # field -> {"source": str, "at": iso} for important qualification updates
    field_provenance: Mapped[dict] = mapped_column(JSON, default=dict)


class ConsentRecord(Base):
    """Append-only. Current consent = latest record per (lead, purpose)."""
    __tablename__ = "consent_records"
    __table_args__ = (Index("ix_consent_lead_purpose", "lead_id", "purpose", "created_at"),)
    id: Mapped[str] = pk()
    organization_id: Mapped[str] = org_fk()
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[str] = mapped_column(String(40))  # automated_calls | marketing | data_processing
    status: Mapped[str] = mapped_column(String(20))  # granted | withdrawn
    source: Mapped[str] = mapped_column(String(60))  # chatbot | web_form | manual | import | call
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)  # consent text shown, ip hash, etc.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    recorded_by: Mapped[str | None] = mapped_column(String(36), nullable=True)


class LeadActivity(Base):
    __tablename__ = "lead_activities"
    id: Mapped[str] = pk()
    organization_id: Mapped[str] = org_fk()
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(40))  # created|updated|note|status|assigned|call|consent|task
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class QualificationResult(Base):
    __tablename__ = "qualification_results"
    id: Mapped[str] = pk()
    organization_id: Mapped[str] = org_fk()
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(40))  # eligible|ineligible|needs_info
    priority_score: Mapped[int] = mapped_column(Integer)  # soft score 0-100
    hard_failures: Mapped[list] = mapped_column(JSON, default=list)
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    missing_fields: Mapped[list] = mapped_column(JSON, default=list)
    next_action: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class FollowUpTask(Base, Stamped):
    __tablename__ = "follow_up_tasks"
    id: Mapped[str] = pk()
    organization_id: Mapped[str] = org_fk()
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    assigned_to: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(300))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open|done|cancelled
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)


class CallJob(Base, Stamped):
    __tablename__ = "call_jobs"
    __table_args__ = (
        UniqueConstraint("organization_id", "dedupe_key", name="uq_calljob_dedupe"),
        Index("ix_calljob_due", "status", "run_at"),
    )
    id: Mapped[str] = pk()
    organization_id: Mapped[str] = org_fk()
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    # queued|running|completed|failed|cancelled|dead
    status: Mapped[str] = mapped_column(String(20), default="queued")
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    dedupe_key: Mapped[str] = mapped_column(String(120))
    trigger: Mapped[str] = mapped_column(String(20), default="manual")  # manual|scheduled|sequence
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)


class CallAttempt(Base, Stamped):
    __tablename__ = "call_attempts"
    id: Mapped[str] = pk()
    organization_id: Mapped[str] = org_fk()
    job_id: Mapped[str] = mapped_column(ForeignKey("call_jobs.id", ondelete="CASCADE"), index=True)
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(40))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    provider_call_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    # initiated|ringing|in_progress|completed|failed|no_answer|busy|cancelled
    status: Mapped[str] = mapped_column(String(20), default="initiated")
    outcome: Mapped[str | None] = mapped_column(String(40), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CallEvent(Base):
    """Raw provider events; unique (provider, event_id) gives webhook idempotency."""
    __tablename__ = "call_events"
    __table_args__ = (UniqueConstraint("provider", "event_id", name="uq_callevent_provider_event"),)
    id: Mapped[str] = pk()
    organization_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    attempt_id: Mapped[str | None] = mapped_column(ForeignKey("call_attempts.id", ondelete="CASCADE"),
                                                   nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(40))
    event_id: Mapped[str] = mapped_column(String(120))
    event_type: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)  # restricted: managers only
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ConversationSummary(Base):
    __tablename__ = "conversation_summaries"
    id: Mapped[str] = pk()
    organization_id: Mapped[str] = org_fk()
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    attempt_id: Mapped[str | None] = mapped_column(ForeignKey("call_attempts.id", ondelete="CASCADE"),
                                                   nullable=True)
    channel: Mapped[str] = mapped_column(String(20))  # voice | chatbot
    summary: Mapped[str] = mapped_column(Text)
    extracted_fields: Mapped[dict] = mapped_column(JSON, default=dict)
    next_action: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_ai_generated: Mapped[bool] = mapped_column(Boolean, default=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Appointment(Base, Stamped):
    __tablename__ = "appointments"
    id: Mapped[str] = pk()
    organization_id: Mapped[str] = org_fk()
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    counsellor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(20), default="scheduled")  # scheduled|completed|cancelled|no_show
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class KnowledgeDocument(Base, Stamped):
    __tablename__ = "knowledge_documents"
    id: Mapped[str] = pk()
    organization_id: Mapped[str] = org_fk()
    title: Mapped[str] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(Text)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)


class UsageRecord(Base):
    __tablename__ = "usage_records"
    id: Mapped[str] = pk()
    organization_id: Mapped[str] = org_fk()
    kind: Mapped[str] = mapped_column(String(40))  # call_seconds | llm_tokens | ...
    quantity: Mapped[float] = mapped_column(Float)
    cost_cents: Mapped[int] = mapped_column(Integer, default=0)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    ref_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = pk()
    organization_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(80))
    target_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)  # never put PII here
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class ChatConversation(Base, Stamped):
    __tablename__ = "chat_conversations"
    id: Mapped[str] = pk()
    organization_id: Mapped[str] = org_fk()
    lead_id: Mapped[str | None] = mapped_column(ForeignKey("leads.id"), nullable=True)
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    messages: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="open")
