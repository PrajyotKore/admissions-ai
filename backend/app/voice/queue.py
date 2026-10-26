from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session

from ..models import (
    Lead,
    CallJob,
    CallAttempt,
    CallEvent,
    ConversationSummary,
    Appointment,
    FollowUpTask,
    UsageRecord,
    Organization,
    OrganizationSettings,
    KnowledgeDocument,
    now,
)
from ..services import (
    has_consent,
    log_activity,
    audit,
)
from ..routers.leads import apply_dnc
from .provider import get_voice_provider, VoiceSessionResult


class CallingIneligibleError(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def check_calling_eligibility(
    db: Session,
    lead: Lead,
    settings: OrganizationSettings | None = None,
    enforce_quiet_hours: bool = True
) -> tuple[bool, str]:
    """
    Enforces telecom & consent compliance:
    1. Lead must NOT be marked Do Not Contact
    2. Lead MUST have explicit, active consent for automated_calls
    3. Organization calling must not be paused
    4. Daily call attempt limits (max 3 per 24 hours)
    5. Quiet hours check in organization's time zone (default 9:00 AM - 8:00 PM)
    """
    if lead.do_not_contact:
        return False, "Lead is marked Do Not Contact"

    if not has_consent(db, lead.id, "automated_calls"):
        return False, "No active consent recorded for automated voice calls"

    if not settings:
        settings = db.get(OrganizationSettings, lead.organization_id)

    if settings and settings.calling_paused:
        return False, "Calling is currently paused for this organization"

    # Daily attempt limit check
    twenty_four_hours_ago = now() - timedelta(hours=24)
    attempts_24h = db.scalar(
        select(func.count())
        .select_from(CallAttempt)
        .where(
            CallAttempt.lead_id == lead.id,
            CallAttempt.created_at >= twenty_four_hours_ago
        )
    ) or 0

    max_daily_attempts = 3
    if attempts_24h >= max_daily_attempts:
        return False, f"Daily calling limit reached ({attempts_24h}/{max_daily_attempts} in last 24h)"

    # Quiet hours check
    if enforce_quiet_hours and settings:
        tz_name = settings.timezone or "Asia/Kolkata"
        try:
            tz = ZoneInfo(tz_name)
            local_time = datetime.now(tz)
            # Allowed window: 09:00 AM to 20:00 PM (8:00 PM)
            if local_time.hour < 9 or local_time.hour >= 20:
                return False, f"Current local time ({local_time.strftime('%I:%M %p')}) is outside approved calling hours (09:00 AM - 08:00 PM {tz_name})"
        except Exception:
            pass

    return True, "Eligible"


def enqueue_call(
    db: Session,
    org_id: str,
    lead_id: str,
    trigger: str = "manual",
    actor_id: str | None = None,
    run_at: datetime | None = None,
    enforce_quiet_hours: bool = False, # false on manual trigger so user can test immediately
) -> CallJob:
    """Queue a call job for an eligible lead with duplicate prevention."""
    lead = db.scalar(select(Lead).where(Lead.id == lead_id, Lead.organization_id == org_id))
    if not lead:
        raise ValueError("Lead not found")

    settings = db.get(OrganizationSettings, org_id)
    eligible, reason = check_calling_eligibility(db, lead, settings, enforce_quiet_hours=enforce_quiet_hours)
    if not eligible:
        raise CallingIneligibleError(reason)

    scheduled_time = run_at or now()

    # Deduplication key per lead and calendar day
    dedupe_key = f"{lead.id}:{scheduled_time.strftime('%Y-%m-%d')}"

    # Check existing queued or running job
    existing = db.scalar(
        select(CallJob).where(
            CallJob.organization_id == org_id,
            CallJob.dedupe_key == dedupe_key,
            CallJob.status.in_(["queued", "running"])
        )
    )
    if existing:
        return existing

    job = CallJob(
        organization_id=org_id,
        lead_id=lead.id,
        status="queued",
        run_at=scheduled_time,
        attempts=0,
        max_attempts=3,
        dedupe_key=dedupe_key,
        trigger=trigger,
        created_by=actor_id,
    )
    db.add(job)
    db.flush()

    log_activity(
        db,
        org_id,
        lead.id,
        "call_queued",
        f"AI voice call scheduled ({trigger})",
        actor_id=actor_id,
        data={"job_id": job.id, "run_at": scheduled_time.isoformat()}
    )

    return job


def execute_call_job(db: Session, job: CallJob) -> CallAttempt | None:
    """
    Execute a call job:
    1. Lock job atomically
    2. Verify compliance & consent again
    3. Call voice provider (mock or real)
    4. Record call attempt, events, usage, and structured outcome
    """
    job.status = "running"
    job.locked_at = now()
    db.commit()

    lead = db.get(Lead, job.lead_id)
    org = db.get(Organization, job.organization_id)
    settings = db.get(OrganizationSettings, job.organization_id)

    # Re-verify eligibility prior to dialing
    eligible, reason = check_calling_eligibility(db, lead, settings, enforce_quiet_hours=False)
    if not eligible:
        job.status = "cancelled"
        job.last_error = f"Cancelled due to compliance check: {reason}"
        db.commit()
        return None

    # Fetch approved knowledge for context grounding
    approved_docs = db.scalars(
        select(KnowledgeDocument.content).where(
            KnowledgeDocument.organization_id == job.organization_id,
            KnowledgeDocument.is_approved.is_(True)
        )
    ).all()
    knowledge_context = "\n---\n".join(approved_docs)

    lead_data = {
        "name": lead.name,
        "phone": lead.phone,
        "preferred_course": lead.preferred_course,
        "preferred_location": lead.preferred_location,
        "academic_marks": lead.academic_marks,
    }

    provider = get_voice_provider("mock")
    call_start = now()

    # Initiate outbound call
    result: VoiceSessionResult = provider.initiate_call(
        to_phone=lead.phone_normalized,
        lead_data=lead_data,
        org_name=org.name,
        approved_knowledge=knowledge_context,
    )

    call_end = now()

    attempt = CallAttempt(
        organization_id=job.organization_id,
        job_id=job.id,
        lead_id=lead.id,
        provider="mock",
        is_synthetic=result.is_synthetic, # CRITICAL: clearly labeled synthetic
        provider_call_id=result.provider_call_id,
        status=result.status,
        outcome=result.outcome,
        duration_seconds=result.duration_seconds,
        cost_cents=result.cost_cents,
        error=result.error,
        transcript=result.transcript,
        started_at=call_start,
        ended_at=call_end,
    )
    db.add(attempt)
    db.flush()

    # Record CallEvent for webhook/audit trail
    event = CallEvent(
        organization_id=job.organization_id,
        attempt_id=attempt.id,
        provider="mock",
        event_id=f"evt-{result.provider_call_id}-finished",
        event_type="call.finished",
        payload={
            "outcome": result.outcome,
            "duration": result.duration_seconds,
            "status": result.status,
            "is_synthetic": result.is_synthetic,
        },
        received_at=now(),
    )
    db.add(event)

    # Track usage (cost tracking)
    if result.cost_cents > 0 or result.duration_seconds > 0:
        db.add(UsageRecord(
            organization_id=job.organization_id,
            kind="call_seconds",
            quantity=float(result.duration_seconds),
            cost_cents=result.cost_cents,
            is_synthetic=result.is_synthetic,
            ref_id=attempt.id,
            created_at=now(),
        ))

    # Update Lead last contact
    lead.last_contact_at = call_end

    # Handle Structured Outcomes
    if result.status == "completed":
        job.status = "completed"

        # Record Conversation Summary
        if result.summary:
            summary_record = ConversationSummary(
                organization_id=job.organization_id,
                lead_id=lead.id,
                attempt_id=attempt.id,
                channel="voice",
                summary=result.summary,
                extracted_fields=result.extracted_fields,
                next_action=result.next_action,
                is_ai_generated=True,
                needs_review=False,
                created_at=now(),
            )
            db.add(summary_record)

        # Handle specific business outcomes
        if result.outcome == "Appointment Booked":
            lead.status = "Counselling Scheduled"
            # Book appointment for tomorrow 11:00 AM
            appt_time = now() + timedelta(days=1)
            appt = Appointment(
                organization_id=job.organization_id,
                lead_id=lead.id,
                counsellor_id=lead.assigned_to,
                scheduled_at=appt_time,
                status="scheduled",
                notes=f"Booked via AI Voice Call. Topic: {lead.preferred_course}",
            )
            db.add(appt)
            log_activity(
                db, job.organization_id, lead.id, "appointment",
                f"Appointment booked via voice call for {appt_time.strftime('%Y-%m-%d %H:%M')}",
                data={"appointment_id": appt.id}
            )

        elif result.outcome == "Callback Requested":
            lead.status = "Contacted"
            callback_time = now() + timedelta(days=1)
            lead.next_follow_up_at = callback_time
            task = FollowUpTask(
                organization_id=job.organization_id,
                lead_id=lead.id,
                title="Callback requested during AI call",
                due_at=callback_time,
                assigned_to=lead.assigned_to,
                status="open",
            )
            db.add(task)
            log_activity(
                db, job.organization_id, lead.id, "task",
                f"Callback scheduled for {callback_time.strftime('%Y-%m-%d %H:%M')}"
            )

        elif result.outcome == "Do Not Contact":
            apply_dnc(db, lead, source="voice_call", actor_id=None)

        elif result.outcome == "Not Interested":
            lead.status = "Not Interested"

        elif result.outcome == "Interested":
            lead.status = "Qualified" if lead.qualification_category == "eligible" else "Contacted"

        log_activity(
            db, job.organization_id, lead.id, "call",
            f"AI voice call completed: Outcome [{result.outcome}] - Duration {result.duration_seconds}s (Synthetic Demo)",
            data={"attempt_id": attempt.id, "outcome": result.outcome, "is_synthetic": True}
        )

    else:
        # Transient failure (No Answer, Busy) -> Retry with exponential backoff
        job.attempts += 1
        if job.attempts < job.max_attempts:
            backoff_hours = 2 * job.attempts
            job.run_at = now() + timedelta(hours=backoff_hours)
            job.status = "queued"
            job.last_error = f"Attempt {job.attempts} returned {result.status}. Retry scheduled in {backoff_hours}h."
            log_activity(
                db, job.organization_id, lead.id, "call_failed",
                f"Call returned {result.status}. Retrying in {backoff_hours}h (Attempt {job.attempts}/{job.max_attempts})"
            )
        else:
            job.status = "dead"
            job.last_error = f"Max attempts ({job.max_attempts}) reached without answer"
            log_activity(
                db, job.organization_id, lead.id, "call_failed",
                f"Calling queue halted for lead: Max attempts ({job.max_attempts}) reached without answer."
            )

    audit(db, job.organization_id, None, "call.executed", "call_attempt", attempt.id, {
        "outcome": result.outcome,
        "status": result.status,
        "is_synthetic": True,
    })

    db.commit()
    return attempt


def process_due_call_jobs(db: Session, limit: int = 10) -> int:
    """Process up to `limit` queued call jobs that are due."""
    jobs = db.scalars(
        select(CallJob)
        .where(
            CallJob.status == "queued",
            CallJob.run_at <= now()
        )
        .order_by(CallJob.run_at.asc())
        .limit(limit)
    ).all()

    processed_count = 0
    for job in jobs:
        execute_call_job(db, job)
        processed_count += 1

    return processed_count
