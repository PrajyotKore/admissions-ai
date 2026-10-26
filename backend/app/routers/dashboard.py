from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from ..deps import Ctx, get_ctx
from ..models import (Appointment, CallAttempt, CallJob, FollowUpTask, Lead, UsageRecord, now)

router = APIRouter()


def ratio(num: int, den: int) -> dict:
    return {"numerator": num, "denominator": den, "value": round(num / den, 4) if den else None}


@router.get("/dashboard")
def dashboard(ctx: Ctx = Depends(get_ctx), days: int = Query(30, ge=1, le=365)):
    """All figures are computed from the active organization's stored data only.
    Counsellors see figures for their assigned leads. `value` is null when the denominator is 0."""
    db, org = ctx.db, ctx.org_id
    lead_filter = [Lead.organization_id == org]
    if not ctx.is_manager:
        lead_filter.append(Lead.assigned_to == ctx.user.id)
    since = now() - timedelta(days=days)

    total = db.scalar(select(func.count()).select_from(Lead).where(*lead_filter))
    by_status = dict(db.execute(select(Lead.status, func.count()).where(*lead_filter).group_by(Lead.status)).all())
    by_source = dict(db.execute(select(func.coalesce(Lead.source_name, "Unknown"), func.count())
                                .where(*lead_filter).group_by(func.coalesce(Lead.source_name, "Unknown"))).all())
    day_col = func.date(Lead.created_at)
    over_time = [{"date": str(d), "count": c} for d, c in db.execute(
        select(day_col, func.count()).where(*lead_filter, Lead.created_at >= since)
        .group_by(day_col).order_by(day_col)).all()]
    qualified = db.scalar(select(func.count()).select_from(Lead).where(*lead_filter, Lead.qualification_category == "eligible"))
    assessed = db.scalar(select(func.count()).select_from(Lead).where(*lead_filter, Lead.qualification_category.is_not(None)))
    converted = by_status.get("Converted", 0)
    terminal = converted + by_status.get("Not Interested", 0)

    # Calls (manager-level data; counsellors get their leads' calls only)
    call_q = [CallAttempt.organization_id == org, CallAttempt.created_at >= since]
    if not ctx.is_manager:
        call_q.append(CallAttempt.lead_id.in_(select(Lead.id).where(*lead_filter)))
    attempted = db.scalar(select(func.count()).select_from(CallAttempt).where(*call_q))
    completed = db.scalar(select(func.count()).select_from(CallAttempt).where(*call_q, CallAttempt.status == "completed"))
    connected = db.scalar(select(func.count()).select_from(CallAttempt).where(
        *call_q, CallAttempt.outcome.in_(["Interested", "Not Interested", "Callback Requested",
                                          "Appointment Booked", "Escalation Required", "Do Not Contact"])))
    failed = db.scalar(select(func.count()).select_from(CallAttempt).where(*call_q, CallAttempt.status == "failed"))
    real_cost = db.scalar(select(func.coalesce(func.sum(UsageRecord.cost_cents), 0)).where(
        UsageRecord.organization_id == org, UsageRecord.created_at >= since, UsageRecord.is_synthetic.is_(False)))
    synth_cost = db.scalar(select(func.coalesce(func.sum(UsageRecord.cost_cents), 0)).where(
        UsageRecord.organization_id == org, UsageRecord.created_at >= since, UsageRecord.is_synthetic.is_(True)))
    appts = db.scalar(select(func.count()).select_from(Appointment).where(
        Appointment.organization_id == org, Appointment.created_at >= since))

    task_q = [FollowUpTask.organization_id == org, FollowUpTask.status == "open", FollowUpTask.due_at <= now()]
    if not ctx.is_manager:
        task_q.append(FollowUpTask.assigned_to == ctx.user.id)
    due = db.scalar(select(func.count()).select_from(FollowUpTask).where(*task_q))

    return {
        "window_days": days,
        "total_leads": total,
        "leads_by_status": by_status,
        "leads_by_source": by_source,
        "new_leads_over_time": over_time,
        "qualified_leads": qualified,
        "qualification_rate": {**ratio(qualified, assessed),
                               "definition": "leads categorised eligible / leads that have been qualification-assessed"},
        "calls_attempted": attempted,
        "calls_completed": completed,
        "contact_rate": {**ratio(connected, attempted),
                         "definition": "call attempts reaching a conversation outcome / call attempts in window"},
        "appointments_booked": appts,
        "conversion_rate": {**ratio(converted, terminal),
                            "definition": "leads Converted / leads Converted or Not Interested (closed outcomes only)"},
        "estimated_cost_cents": real_cost,
        "synthetic_cost_cents_excluded": synth_cost,
        "follow_ups_due": due,
        "failed_calls_needing_attention": failed + (db.scalar(select(func.count()).select_from(CallJob).where(
            CallJob.organization_id == org, CallJob.status == "dead")) if ctx.is_manager else 0),
    }
