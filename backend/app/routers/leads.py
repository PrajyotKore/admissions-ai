import csv
import io
import json
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, or_, select
from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session

from ..deps import Ctx, get_ctx, require_manager
from ..models import (CallJob, ConsentRecord, FollowUpTask, Lead, LeadActivity, LeadSource,
                      OrganizationMembership, OrganizationSettings, QualificationResult, now)
from ..qualification import qualify_lead, DEFAULT_RULES
from ..services import (PhoneError, audit, current_consent, log_activity, normalize_phone,
                        record_consent)

router = APIRouter()

MAX_CSV_BYTES = 2_000_000
MAX_CSV_ROWS = 5000
IMPORT_FIELDS = ["name", "phone", "email", "preferred_course", "preferred_college", "education_level",
                 "academic_marks", "preferred_location", "budget_min", "budget_max",
                 "admission_timeline", "source_name"]
EDITABLE = ["name", "email", "preferred_course", "preferred_college", "education_level",
            "academic_marks", "preferred_location", "budget_min", "budget_max",
            "admission_timeline", "status", "next_follow_up_at"]
SORTABLE = {"created_at", "updated_at", "name", "status", "qualification_score", "next_follow_up_at",
            "last_contact_at"}


# ---------- helpers ----------
def lead_out(l: Lead) -> dict:
    return {
        "id": l.id, "organization_id": l.organization_id, "name": l.name, "phone": l.phone_normalized,
        "email": l.email, "preferred_course": l.preferred_course, "preferred_college": l.preferred_college,
        "education_level": l.education_level, "academic_marks": l.academic_marks,
        "preferred_location": l.preferred_location, "budget_min": l.budget_min, "budget_max": l.budget_max,
        "admission_timeline": l.admission_timeline, "source_name": l.source_name,
        "assigned_to": l.assigned_to, "qualification_score": l.qualification_score,
        "qualification_category": l.qualification_category, "status": l.status,
        "last_contact_at": l.last_contact_at, "next_follow_up_at": l.next_follow_up_at,
        "do_not_contact": l.do_not_contact, "field_provenance": l.field_provenance,
        "created_at": l.created_at, "updated_at": l.updated_at,
    }


def scoped(ctx: Ctx):
    q = select(Lead).where(Lead.organization_id == ctx.org_id)
    if not ctx.is_manager:  # counsellors only see assigned leads
        q = q.where(Lead.assigned_to == ctx.user.id)
    return q


def get_lead(ctx: Ctx, lead_id: str) -> Lead:
    lead = ctx.db.scalar(scoped(ctx).where(Lead.id == lead_id))
    if not lead:
        raise HTTPException(404, "Lead not found")  # also hides cross-tenant leads
    return lead


def valid_statuses(ctx: Ctx) -> list[str]:
    return ctx.db.get(OrganizationSettings, ctx.org_id).lead_statuses


def ensure_assignee(ctx: Ctx, user_id: str | None):
    if user_id is None:
        return
    ok = ctx.db.scalar(select(OrganizationMembership.id).where(
        OrganizationMembership.organization_id == ctx.org_id, OrganizationMembership.user_id == user_id))
    if not ok:
        raise HTTPException(422, "Assignee is not a member of this organization")


def apply_dnc(db: Session, lead: Lead, source: str, actor_id: str | None) -> None:
    """Do Not Contact: set flag, withdraw all consents, cancel pending call jobs."""
    lead.do_not_contact = True
    lead.status = "Do Not Contact"
    for purpose in ("automated_calls", "marketing"):
        c = current_consent(db, lead.id, purpose)
        if c and c.status == "granted":
            record_consent(db, lead, purpose, "withdrawn", source, actor_id=actor_id)
    cancel_pending_jobs(db, lead.id, "Do Not Contact")


def cancel_pending_jobs(db: Session, lead_id: str, reason: str) -> int:
    res = db.execute(sa_update(CallJob).where(
        CallJob.lead_id == lead_id, CallJob.status.in_(["queued"]))
        .values(status="cancelled", last_error=f"Cancelled: {reason}"))
    return res.rowcount or 0


def get_or_create_source(db: Session, org_id: str, name: str | None) -> LeadSource | None:
    if not name:
        return None
    name = name.strip()[:100]
    src = db.scalar(select(LeadSource).where(LeadSource.organization_id == org_id, LeadSource.name == name))
    if not src:
        src = LeadSource(organization_id=org_id, name=name)
        db.add(src)
        db.flush()
    return src


def create_lead(db: Session, org_id: str, data: dict, *, source_name: str | None, actor_id: str | None,
                assigned_to: str | None = None, provenance_source: str = "manual") -> Lead:
    """Raises PhoneError for bad phone, DuplicateLead if the normalized phone exists in the org."""
    phone_n = normalize_phone(data["phone"])
    existing = db.scalar(select(Lead).where(Lead.organization_id == org_id, Lead.phone_normalized == phone_n))
    if existing:
        raise DuplicateLead(existing.id)
    src = get_or_create_source(db, org_id, source_name)
    fields = {k: v for k, v in data.items() if k in IMPORT_FIELDS and k not in ("phone", "source_name")}
    stamp = {"source": provenance_source, "at": now().isoformat()}
    lead = Lead(organization_id=org_id, phone=data["phone"].strip()[:32], phone_normalized=phone_n,
                source_id=src.id if src else None, source_name=src.name if src else None,
                assigned_to=assigned_to, field_provenance={k: stamp for k, v in fields.items() if v is not None},
                **fields)
    db.add(lead)
    db.flush()
    log_activity(db, org_id, lead.id, "created", f"Lead created via {provenance_source}", actor_id)
    return lead


class DuplicateLead(Exception):
    def __init__(self, lead_id: str):
        self.lead_id = lead_id


# ---------- schemas ----------
class LeadIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    phone: str = Field(min_length=5, max_length=32)
    email: EmailStr | None = None
    preferred_course: str | None = Field(default=None, max_length=200)
    preferred_college: str | None = Field(default=None, max_length=200)
    education_level: str | None = Field(default=None, max_length=100)
    academic_marks: float | None = Field(default=None, ge=0, le=100000)
    preferred_location: str | None = Field(default=None, max_length=200)
    budget_min: int | None = Field(default=None, ge=0)
    budget_max: int | None = Field(default=None, ge=0)
    admission_timeline: str | None = Field(default=None, max_length=100)
    source_name: str | None = Field(default=None, max_length=100)
    assigned_to: str | None = None


class LeadPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    email: EmailStr | None = None
    preferred_course: str | None = Field(default=None, max_length=200)
    preferred_college: str | None = Field(default=None, max_length=200)
    education_level: str | None = Field(default=None, max_length=100)
    academic_marks: float | None = Field(default=None, ge=0, le=100000)
    preferred_location: str | None = Field(default=None, max_length=200)
    budget_min: int | None = Field(default=None, ge=0)
    budget_max: int | None = Field(default=None, ge=0)
    admission_timeline: str | None = Field(default=None, max_length=100)
    status: str | None = None
    next_follow_up_at: datetime | None = None


# ---------- list / create ----------
@router.get("/leads")
def list_leads(ctx: Ctx = Depends(get_ctx), q: str | None = None, status: str | None = None,
               source: str | None = None, assigned_to: str | None = None,
               category: str | None = None, sort: str = "created_at", order: str = "desc",
               page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100)):
    query = scoped(ctx)
    if q:
        like = f"%{q.strip().lower()}%"
        query = query.where(or_(func.lower(Lead.name).like(like), Lead.phone_normalized.like(f"%{q.strip()}%"),
                                func.lower(func.coalesce(Lead.email, "")).like(like),
                                func.lower(func.coalesce(Lead.preferred_course, "")).like(like)))
    if status:
        query = query.where(Lead.status == status)
    if source:
        query = query.where(Lead.source_name == source)
    if category:
        query = query.where(Lead.qualification_category == category)
    if assigned_to:
        query = query.where(Lead.assigned_to == (None if assigned_to == "unassigned" else assigned_to))
    if sort not in SORTABLE:
        raise HTTPException(422, "Invalid sort field")
    col = getattr(Lead, sort)
    query = query.order_by(col.asc() if order == "asc" else col.desc(), Lead.id)
    total = ctx.db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    rows = ctx.db.scalars(query.offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [lead_out(l) for l in rows], "total": total, "page": page, "page_size": page_size}


@router.post("/leads", status_code=201)
def create(body: LeadIn, ctx: Ctx = Depends(get_ctx)):
    assignee = body.assigned_to if ctx.is_manager else ctx.user.id
    ensure_assignee(ctx, assignee)
    try:
        lead = create_lead(ctx.db, ctx.org_id, body.model_dump(), source_name=body.source_name,
                           actor_id=ctx.user.id, assigned_to=assignee)
    except PhoneError as e:
        raise HTTPException(422, str(e))
    except DuplicateLead as d:
        ctx.db.rollback()
        # Never merge or overwrite silently: report and let the user decide.
        existing = ctx.db.get(Lead, d.lead_id)
        if not ctx.is_manager and existing.assigned_to != ctx.user.id:
            raise HTTPException(409, {"message": "A lead with this phone number already exists"})
        raise HTTPException(409, {"message": "A lead with this phone number already exists",
                                  "existing_lead_id": d.lead_id})
    audit(ctx.db, ctx.org_id, ctx.user.id, "lead.created", "lead", lead.id)
    ctx.db.commit()
    return lead_out(lead)


# ---------- import / export / bulk (declared before /leads/{id}) ----------
def _num(v: str, cast):
    v = (v or "").strip().replace(",", "")
    return cast(v) if v else None


@router.post("/leads/import")
async def import_leads(file: UploadFile = File(...), mapping: str = Form(...),
                       dry_run: bool = Form(False), ctx: Ctx = Depends(require_manager)):
    """mapping: JSON {lead_field: csv_column}. Valid rows are imported; invalid rows and duplicates are
    reported (never merged/overwritten)."""
    raw = await file.read(MAX_CSV_BYTES + 1)
    if len(raw) > MAX_CSV_BYTES:
        raise HTTPException(413, "CSV too large (max 2 MB)")
    try:
        mp = json.loads(mapping)
        assert isinstance(mp, dict)
    except Exception:
        raise HTTPException(422, "mapping must be a JSON object")
    bad = [k for k in mp if k not in IMPORT_FIELDS]
    if bad or "name" not in mp or "phone" not in mp:
        raise HTTPException(422, "mapping must include name and phone and only known fields")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(422, "CSV must be UTF-8 encoded")
    reader = csv.DictReader(io.StringIO(text))
    cols = reader.fieldnames or []
    missing_cols = [c for c in mp.values() if c not in cols]
    if missing_cols:
        raise HTTPException(422, f"Mapped columns not found in CSV: {missing_cols}")

    created, errors, duplicates = 0, [], []
    seen: set[str] = set()
    for i, row in enumerate(reader, start=2):  # row 1 is header
        if i - 1 > MAX_CSV_ROWS:
            errors.append({"row": i, "error": f"Row limit {MAX_CSV_ROWS} exceeded; remaining rows skipped"})
            break
        try:
            data = {f: (row.get(c) or "").strip() or None for f, c in mp.items()}
            if not data.get("name"):
                raise ValueError("Name is required")
            if not data.get("phone"):
                raise ValueError("Phone is required")
            if data.get("email"):
                LeadIn(name="x", phone="00000", email=data["email"])  # reuse email validation
            for f, cast in (("academic_marks", float), ("budget_min", int), ("budget_max", int)):
                if data.get(f) is not None:
                    try:
                        data[f] = _num(data[f], cast)
                    except ValueError:
                        raise ValueError(f"{f} must be a number")
            phone_n = normalize_phone(data["phone"])
            if phone_n in seen:
                duplicates.append({"row": i, "phone": phone_n, "reason": "Duplicate within file"})
                continue
            seen.add(phone_n)
            if dry_run:
                if ctx.db.scalar(select(Lead.id).where(Lead.organization_id == ctx.org_id,
                                                       Lead.phone_normalized == phone_n)):
                    duplicates.append({"row": i, "phone": phone_n, "reason": "Already exists in CRM"})
                else:
                    created += 1
                continue
            with ctx.db.begin_nested():
                create_lead(ctx.db, ctx.org_id, data, source_name=data.get("source_name") or "CSV Import",
                            actor_id=ctx.user.id, provenance_source="csv_import")
            created += 1
        except DuplicateLead as d:
            duplicates.append({"row": i, "phone": phone_n, "reason": "Already exists in CRM",
                               "existing_lead_id": d.lead_id})
        except (ValueError, PhoneError) as e:
            errors.append({"row": i, "error": str(e)})
    if not dry_run:
        audit(ctx.db, ctx.org_id, ctx.user.id, "lead.import", "lead", None,
              {"created": created, "errors": len(errors), "duplicates": len(duplicates)})
        ctx.db.commit()
    return {"dry_run": dry_run, "created": created, "error_count": len(errors),
            "duplicate_count": len(duplicates), "errors": errors, "duplicates": duplicates}


def _csv_safe(v) -> str:
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s  # CSV formula injection guard


@router.get("/leads/export")
def export_leads(ctx: Ctx = Depends(require_manager)):
    rows = ctx.db.scalars(scoped(ctx).order_by(Lead.created_at)).all()
    cols = ["id", "name", "phone", "email", "preferred_course", "preferred_college", "education_level",
            "academic_marks", "preferred_location", "budget_min", "budget_max", "admission_timeline",
            "source_name", "status", "qualification_category", "qualification_score", "created_at"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for l in rows:
        o = lead_out(l)
        w.writerow([_csv_safe(o[c]) for c in cols])
    audit(ctx.db, ctx.org_id, ctx.user.id, "lead.export", "lead", None, {"count": len(rows)})
    ctx.db.commit()
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=leads.csv"})


class BulkIn(BaseModel):
    lead_ids: list[str] = Field(min_length=1, max_length=500)
    action: str  # assign | status | delete
    assigned_to: str | None = None
    status: str | None = None
    confirm: bool = False


@router.post("/leads/bulk")
def bulk(body: BulkIn, ctx: Ctx = Depends(require_manager)):
    if not body.confirm:
        raise HTTPException(422, "Bulk operations require confirm=true")
    leads = ctx.db.scalars(select(Lead).where(Lead.organization_id == ctx.org_id,
                                              Lead.id.in_(body.lead_ids))).all()
    if len(leads) != len(set(body.lead_ids)):
        raise HTTPException(404, "One or more leads not found")
    if body.action == "assign":
        ensure_assignee(ctx, body.assigned_to)
        for l in leads:
            l.assigned_to = body.assigned_to
            log_activity(ctx.db, ctx.org_id, l.id, "assigned", "Lead assigned (bulk)", ctx.user.id)
    elif body.action == "status":
        if body.status not in valid_statuses(ctx):
            raise HTTPException(422, "Unknown status")
        for l in leads:
            set_status(ctx, l, body.status)
    elif body.action == "delete":
        for l in leads:
            ctx.db.delete(l)
    else:
        raise HTTPException(422, "Unknown action")
    audit(ctx.db, ctx.org_id, ctx.user.id, f"lead.bulk_{body.action}", "lead", None, {"count": len(leads)})
    ctx.db.commit()
    return {"affected": len(leads)}


def set_status(ctx: Ctx, lead: Lead, status: str) -> None:
    if lead.status == status:
        return
    old = lead.status
    if status == "Do Not Contact":
        apply_dnc(ctx.db, lead, "manual", ctx.user.id)
    elif lead.do_not_contact and status != "Do Not Contact":
        # Leaving DNC never re-grants consent; it needs a fresh, recorded consent.
        lead.do_not_contact = False
    lead.status = status
    if status == "Invalid":
        cancel_pending_jobs(ctx.db, lead.id, "Invalid lead")
    log_activity(ctx.db, ctx.org_id, lead.id, "status", f"Status changed from {old} to {status}", ctx.user.id)


# ---------- detail ----------
@router.get("/leads/{lead_id}")
def detail(lead_id: str, ctx: Ctx = Depends(get_ctx)):
    lead = get_lead(ctx, lead_id)
    consents = {p: (current_consent(ctx.db, lead.id, p).status if current_consent(ctx.db, lead.id, p) else "none")
                for p in ("automated_calls", "marketing", "data_processing")}
    return {**lead_out(lead), "consent": consents}


@router.patch("/leads/{lead_id}")
def update(lead_id: str, body: LeadPatch, ctx: Ctx = Depends(get_ctx)):
    lead = get_lead(ctx, lead_id)
    changes = body.model_dump(exclude_unset=True)
    if "status" in changes:
        if changes["status"] not in valid_statuses(ctx):
            raise HTTPException(422, "Unknown status")
    changed = []
    stamp = {"source": f"user:{ctx.user.id}", "at": now().isoformat()}
    for k, v in changes.items():
        if k == "status":
            if v != lead.status:
                set_status(ctx, lead, v)
                changed.append(k)
            continue
        if k == "name" and v is None:
            continue
        if getattr(lead, k) != v:
            setattr(lead, k, v)
            changed.append(k)
            if k not in ("name", "status", "next_follow_up_at"):
                prov = dict(lead.field_provenance or {})
                prov[k] = stamp
                lead.field_provenance = prov
    if lead.budget_min is not None and lead.budget_max is not None and lead.budget_min > lead.budget_max:
        raise HTTPException(422, "budget_min cannot exceed budget_max")
    if changed:
        fields = [c for c in changed if c != "status"]
        if fields:
            log_activity(ctx.db, ctx.org_id, lead.id, "updated", f"Updated: {', '.join(fields)}", ctx.user.id,
                         {"fields": fields})
        audit(ctx.db, ctx.org_id, ctx.user.id, "lead.updated", "lead", lead.id, {"fields": changed})
    ctx.db.commit()
    return lead_out(lead)


class AssignIn(BaseModel):
    assigned_to: str | None


@router.post("/leads/{lead_id}/assign")
def assign(lead_id: str, body: AssignIn, ctx: Ctx = Depends(require_manager)):
    lead = get_lead(ctx, lead_id)
    ensure_assignee(ctx, body.assigned_to)
    lead.assigned_to = body.assigned_to
    log_activity(ctx.db, ctx.org_id, lead.id, "assigned",
                 "Lead unassigned" if not body.assigned_to else "Lead assigned", ctx.user.id,
                 {"assigned_to": body.assigned_to})
    audit(ctx.db, ctx.org_id, ctx.user.id, "lead.assigned", "lead", lead.id)
    ctx.db.commit()
    return lead_out(lead)


@router.delete("/leads/{lead_id}", status_code=204)
def delete_lead(lead_id: str, ctx: Ctx = Depends(require_manager)):
    lead = get_lead(ctx, lead_id)
    ctx.db.delete(lead)
    audit(ctx.db, ctx.org_id, ctx.user.id, "lead.deleted", "lead", lead_id)
    ctx.db.commit()


# ---------- activity, notes, tasks, consent ----------
@router.get("/leads/{lead_id}/activities")
def activities(lead_id: str, ctx: Ctx = Depends(get_ctx)):
    lead = get_lead(ctx, lead_id)
    rows = ctx.db.scalars(select(LeadActivity).where(
        LeadActivity.lead_id == lead.id, LeadActivity.organization_id == ctx.org_id)
        .order_by(LeadActivity.created_at.desc())).all()
    return [{"id": a.id, "kind": a.kind, "message": a.message, "data": a.data, "actor_id": a.actor_id,
             "created_at": a.created_at} for a in rows]


class NoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=5000)


@router.post("/leads/{lead_id}/notes", status_code=201)
def add_note(lead_id: str, body: NoteIn, ctx: Ctx = Depends(get_ctx)):
    lead = get_lead(ctx, lead_id)
    log_activity(ctx.db, ctx.org_id, lead.id, "note", body.text, ctx.user.id)
    ctx.db.commit()
    return {"detail": "Note added"}


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    due_at: datetime
    assigned_to: str | None = None


def task_out(t: FollowUpTask) -> dict:
    return {"id": t.id, "lead_id": t.lead_id, "title": t.title, "due_at": t.due_at, "status": t.status,
            "assigned_to": t.assigned_to}


@router.post("/leads/{lead_id}/tasks", status_code=201)
def add_task(lead_id: str, body: TaskIn, ctx: Ctx = Depends(get_ctx)):
    lead = get_lead(ctx, lead_id)
    assignee = body.assigned_to or lead.assigned_to or ctx.user.id
    ensure_assignee(ctx, assignee)
    t = FollowUpTask(organization_id=ctx.org_id, lead_id=lead.id, title=body.title, due_at=body.due_at,
                     assigned_to=assignee, created_by=ctx.user.id)
    ctx.db.add(t)
    if not lead.next_follow_up_at or body.due_at < lead.next_follow_up_at:
        lead.next_follow_up_at = body.due_at
    log_activity(ctx.db, ctx.org_id, lead.id, "task", f"Follow-up created: {body.title}", ctx.user.id)
    ctx.db.commit()
    return task_out(t)


@router.get("/tasks")
def list_tasks(ctx: Ctx = Depends(get_ctx), status: str = "open", mine: bool = False):
    q = select(FollowUpTask).where(FollowUpTask.organization_id == ctx.org_id, FollowUpTask.status == status)
    if not ctx.is_manager or mine:
        q = q.where(FollowUpTask.assigned_to == ctx.user.id)
    return [task_out(t) for t in ctx.db.scalars(q.order_by(FollowUpTask.due_at)).all()]


class TaskPatch(BaseModel):
    status: str | None = None
    due_at: datetime | None = None


@router.patch("/tasks/{task_id}")
def patch_task(task_id: str, body: TaskPatch, ctx: Ctx = Depends(get_ctx)):
    t = ctx.db.scalar(select(FollowUpTask).where(FollowUpTask.id == task_id,
                                                 FollowUpTask.organization_id == ctx.org_id))
    if not t or (not ctx.is_manager and t.assigned_to != ctx.user.id):
        raise HTTPException(404, "Task not found")
    if body.status:
        if body.status not in ("open", "done", "cancelled"):
            raise HTTPException(422, "Invalid status")
        t.status = body.status
    if body.due_at:
        t.due_at = body.due_at
    ctx.db.commit()
    return task_out(t)


class ConsentIn(BaseModel):
    purpose: str
    status: str
    source: str = "manual"
    evidence: dict = {}


@router.post("/leads/{lead_id}/consent", status_code=201)
def set_consent(lead_id: str, body: ConsentIn, ctx: Ctx = Depends(get_ctx)):
    lead = get_lead(ctx, lead_id)
    if body.purpose not in ("automated_calls", "marketing", "data_processing") or \
            body.status not in ("granted", "withdrawn"):
        raise HTTPException(422, "Invalid purpose or status")
    if body.status == "granted" and lead.do_not_contact:
        raise HTTPException(409, "Lead is marked Do Not Contact; clear the status first")
    if body.status == "granted" and not body.evidence.get("note") and body.source == "manual":
        raise HTTPException(422, "Manual consent requires evidence.note describing how consent was obtained")
    record_consent(ctx.db, lead, body.purpose, body.status, body.source, body.evidence, ctx.user.id)
    if body.status == "withdrawn" and body.purpose == "automated_calls":
        cancel_pending_jobs(ctx.db, lead.id, "Consent withdrawn")
    audit(ctx.db, ctx.org_id, ctx.user.id, f"consent.{body.status}", "lead", lead.id, {"purpose": body.purpose})
    ctx.db.commit()
    return {"purpose": body.purpose, "status": body.status}


@router.get("/leads/{lead_id}/consent")
def consent_history(lead_id: str, ctx: Ctx = Depends(get_ctx)):
    lead = get_lead(ctx, lead_id)
    rows = ctx.db.scalars(select(ConsentRecord).where(ConsentRecord.lead_id == lead.id)
                          .order_by(ConsentRecord.created_at.desc())).all()
    return [{"id": c.id, "purpose": c.purpose, "status": c.status, "source": c.source,
             "evidence": c.evidence, "created_at": c.created_at} for c in rows]


@router.post("/leads/{lead_id}/qualify")
def trigger_qualification(lead_id: str, ctx: Ctx = Depends(get_ctx)):
    lead = get_lead(ctx, lead_id)
    res = qualify_lead(ctx.db, lead, actor_id=ctx.user.id)
    audit(ctx.db, ctx.org_id, ctx.user.id, "lead.qualified", "lead", lead.id, {"category": res.category, "score": res.priority_score})
    ctx.db.commit()
    return {
        "lead_id": lead.id,
        "category": res.category,
        "priority_score": res.priority_score,
        "hard_failures": res.hard_failures,
        "reasons": res.reasons,
        "missing_fields": res.missing_fields,
        "next_action": res.next_action,
        "created_at": res.created_at,
    }


@router.get("/leads/{lead_id}/qualification")
def get_lead_qualification(lead_id: str, ctx: Ctx = Depends(get_ctx)):
    lead = get_lead(ctx, lead_id)
    results = ctx.db.scalars(
        select(QualificationResult)
        .where(QualificationResult.lead_id == lead.id)
        .order_by(QualificationResult.created_at.desc())
    ).all()
    return [
        {
            "id": r.id,
            "category": r.category,
            "priority_score": r.priority_score,
            "hard_failures": r.hard_failures,
            "reasons": r.reasons,
            "missing_fields": r.missing_fields,
            "next_action": r.next_action,
            "created_at": r.created_at,
        }
        for r in results
    ]


@router.get("/qualification/rules")
def get_qualification_rules(ctx: Ctx = Depends(get_ctx)):
    settings = ctx.db.get(OrganizationSettings, ctx.org_id)
    return (settings.qualification_rules if settings and settings.qualification_rules else None) or DEFAULT_RULES


class RulesIn(BaseModel):
    rules: dict


@router.patch("/qualification/rules")
def update_qualification_rules(body: RulesIn, ctx: Ctx = Depends(require_manager)):
    settings = ctx.db.get(OrganizationSettings, ctx.org_id)
    settings.qualification_rules = body.rules
    audit(ctx.db, ctx.org_id, ctx.user.id, "qualification_rules.updated", "organization", ctx.org_id)
    ctx.db.commit()
    return settings.qualification_rules
