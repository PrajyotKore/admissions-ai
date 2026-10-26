from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select, func

from ..deps import Ctx, get_ctx, require_manager
from ..models import (
    Lead,
    CallJob,
    CallAttempt,
    CallEvent,
    ConversationSummary,
    OrganizationSettings,
    now,
)
from ..services import audit, iso
from ..voice.queue import (
    enqueue_call,
    execute_call_job,
    process_due_call_jobs,
    CallingIneligibleError,
)

router = APIRouter(prefix="/calls")


def attempt_out(a: CallAttempt, lead_name: str | None = None) -> dict[str, Any]:
    return {
        "id": a.id,
        "lead_id": a.lead_id,
        "lead_name": lead_name,
        "job_id": a.job_id,
        "provider": a.provider,
        "is_synthetic": a.is_synthetic, # Clear label: synthetic mock call vs real call
        "provider_call_id": a.provider_call_id,
        "status": a.status,
        "outcome": a.outcome,
        "duration_seconds": a.duration_seconds,
        "cost_cents": a.cost_cents,
        "error": a.error,
        "started_at": iso(a.started_at),
        "ended_at": iso(a.ended_at),
        "created_at": iso(a.created_at),
    }


def job_out(j: CallJob, lead_name: str | None = None) -> dict[str, Any]:
    return {
        "id": j.id,
        "lead_id": j.lead_id,
        "lead_name": lead_name,
        "status": j.status,
        "run_at": iso(j.run_at),
        "attempts": j.attempts,
        "max_attempts": j.max_attempts,
        "trigger": j.trigger,
        "last_error": j.last_error,
        "created_at": iso(j.created_at),
    }


# ---------- Triggering & Queue Operations ----------

@router.post("/trigger/{lead_id}", status_code=201)
def trigger_call(
    lead_id: str,
    execute_now: bool = True,
    ctx: Ctx = Depends(get_ctx)
):
    """Initiate or queue a call to an eligible student lead."""
    lead = ctx.db.scalar(select(Lead).where(Lead.id == lead_id, Lead.organization_id == ctx.org_id))
    if not lead:
        raise HTTPException(404, "Lead not found")

    try:
        job = enqueue_call(
            ctx.db,
            ctx.org_id,
            lead.id,
            trigger="manual",
            actor_id=ctx.user.id,
            enforce_quiet_hours=False, # allow manual immediate testing
        )
    except CallingIneligibleError as e:
        raise HTTPException(409, f"Lead cannot be called: {e.reason}")

    attempt_data = None
    if execute_now:
        attempt = execute_call_job(ctx.db, job)
        if attempt:
            attempt_data = attempt_out(attempt, lead.name)

    ctx.db.commit()
    return {
        "job": job_out(job, lead.name),
        "attempt": attempt_data,
    }


@router.get("/queue")
def list_queue(
    status: str | None = None,
    ctx: Ctx = Depends(get_ctx),
):
    """List jobs currently in calling queue."""
    q = (
        select(CallJob, Lead.name)
        .join(Lead, Lead.id == CallJob.lead_id)
        .where(CallJob.organization_id == ctx.org_id)
    )
    if status:
        q = q.where(CallJob.status == status)

    rows = ctx.db.execute(q.order_by(CallJob.run_at.asc())).all()
    return [job_out(j, lead_name) for j, lead_name in rows]


@router.post("/queue/{job_id}/cancel")
def cancel_job(job_id: str, ctx: Ctx = Depends(require_manager)):
    job = ctx.db.scalar(select(CallJob).where(CallJob.id == job_id, CallJob.organization_id == ctx.org_id))
    if not job:
        raise HTTPException(404, "Call job not found")
    if job.status not in ("queued", "running"):
        raise HTTPException(409, f"Cannot cancel job with status '{job.status}'")

    job.status = "cancelled"
    job.last_error = f"Cancelled by {ctx.user.full_name}"
    audit(ctx.db, ctx.org_id, ctx.user.id, "call_job.cancelled", "call_job", job.id)
    ctx.db.commit()
    return {"id": job.id, "status": "cancelled"}


@router.post("/queue/pause")
def toggle_pause_calling(paused: bool, ctx: Ctx = Depends(require_manager)):
    settings = ctx.db.get(OrganizationSettings, ctx.org_id)
    settings.calling_paused = paused
    audit(ctx.db, ctx.org_id, ctx.user.id, "calling.paused_changed", "organization", ctx.org_id, {"paused": paused})
    ctx.db.commit()
    return {"calling_paused": paused}


@router.post("/queue/process")
def process_queue_worker(ctx: Ctx = Depends(require_manager)):
    """Run a worker cycle to execute due calling jobs."""
    count = process_due_call_jobs(ctx.db, limit=10)
    return {"processed": count}


# ---------- History & Individual Call Intelligence ----------

@router.get("/history")
def call_history(
    lead_id: str | None = None,
    outcome: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    ctx: Ctx = Depends(get_ctx)
):
    """List historical call attempts with outcomes, duration, and synthetic label."""
    q = (
        select(CallAttempt, Lead.name)
        .join(Lead, Lead.id == CallAttempt.lead_id)
        .where(CallAttempt.organization_id == ctx.org_id)
    )
    if not ctx.is_manager:
        q = q.where(Lead.assigned_to == ctx.user.id)
    if lead_id:
        q = q.where(CallAttempt.lead_id == lead_id)
    if outcome:
        q = q.where(CallAttempt.outcome == outcome)

    total = ctx.db.scalar(select(func.count()).select_from(q.subquery()))
    rows = ctx.db.execute(
        q.order_by(CallAttempt.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    return {
        "items": [attempt_out(a, lead_name) for a, lead_name in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/attempts/{attempt_id}")
def call_attempt_detail(attempt_id: str, ctx: Ctx = Depends(get_ctx)):
    """Retrieve full conversation intelligence, transcript, and summary."""
    attempt = ctx.db.scalar(
        select(CallAttempt)
        .where(CallAttempt.id == attempt_id, CallAttempt.organization_id == ctx.org_id)
    )
    if not attempt:
        raise HTTPException(404, "Call attempt not found")

    lead = ctx.db.get(Lead, attempt.lead_id)
    if not ctx.is_manager and lead.assigned_to != ctx.user.id:
        raise HTTPException(403, "Access to this call record is restricted")

    # Fetch summary
    summary = ctx.db.scalar(
        select(ConversationSummary)
        .where(ConversationSummary.attempt_id == attempt.id)
    )

    return {
        **attempt_out(attempt, lead.name),
        "transcript": attempt.transcript,
        "summary": {
            "summary": summary.summary if summary else None,
            "extracted_fields": summary.extracted_fields if summary else {},
            "next_action": summary.next_action if summary else None,
            "is_ai_generated": summary.is_ai_generated if summary else True,
        } if summary else None,
    }


# ---------- Webhook Ingestion with Idempotency ----------

class WebhookPayload(BaseModel):
    event_id: str
    event_type: str
    call_id: str
    outcome: str | None = None
    duration_seconds: int | None = None


@router.post("/webhooks/{provider}")
def handle_provider_webhook(provider: str, payload: WebhookPayload, request: Request, ctx: Ctx = Depends(get_ctx)):
    """
    Idempotent webhook processor for telephony & voice events.
    Unique constraint on (provider, event_id) guarantees duplicate events are safely ignored.
    """
    # Check if event already processed
    existing_evt = ctx.db.scalar(
        select(CallEvent)
        .where(
            CallEvent.provider == provider,
            CallEvent.event_id == payload.event_id
        )
    )
    if existing_evt:
        return {"status": "ignored", "reason": "duplicate_event_already_processed"}

    attempt = ctx.db.scalar(
        select(CallAttempt)
        .where(
            CallAttempt.provider == provider,
            CallAttempt.provider_call_id == payload.call_id
        )
    )

    evt = CallEvent(
        organization_id=attempt.organization_id if attempt else ctx.org_id,
        attempt_id=attempt.id if attempt else None,
        provider=provider,
        event_id=payload.event_id,
        event_type=payload.event_type,
        payload=payload.model_dump(),
        received_at=now(),
    )
    ctx.db.add(evt)

    if attempt and payload.outcome:
        attempt.outcome = payload.outcome
        if payload.duration_seconds is not None:
            attempt.duration_seconds = payload.duration_seconds

    ctx.db.commit()
    return {"status": "processed", "event_id": payload.event_id}
