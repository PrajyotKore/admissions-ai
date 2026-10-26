import re
from datetime import datetime

from sqlalchemy.orm import Session

from .models import AuditEvent, ConsentRecord, Lead, LeadActivity, now

DEFAULT_STATUSES = ["New", "Contact Pending", "Contacted", "Qualified", "Counselling Scheduled",
                    "Converted", "Not Interested", "Invalid", "Do Not Contact"]


class PhoneError(ValueError):
    pass


def normalize_phone(raw: str, default_cc: str = "91") -> str:
    """Return E.164. Raises PhoneError if it can't be validated. Indian mobiles must start 6-9."""
    s = (raw or "").strip()
    plus = s.startswith("+")
    d = re.sub(r"\D", "", s)
    if not d:
        raise PhoneError("Phone number is empty")
    if not plus:
        if d.startswith("00"):
            d, plus = d[2:], True
        elif len(d) == 11 and d.startswith("0"):
            d = d[1:]
        if not plus and len(d) == 12 and d.startswith(default_cc):
            plus = True
        elif not plus and len(d) == 10:
            d, plus = default_cc + d, True
    if not plus:
        raise PhoneError("Unrecognised phone format")
    if not 8 <= len(d) <= 15:
        raise PhoneError("Phone number has invalid length")
    if d.startswith("91") and not re.fullmatch(r"91[6-9]\d{9}", d):
        raise PhoneError("Invalid Indian mobile number")
    return "+" + d


def log_activity(db: Session, org_id: str, lead_id: str, kind: str, message: str,
                 actor_id: str | None = None, data: dict | None = None) -> None:
    db.add(LeadActivity(organization_id=org_id, lead_id=lead_id, kind=kind, message=message,
                        actor_id=actor_id, data=data or {}))


def audit(db: Session, org_id: str | None, actor_id: str | None, action: str,
          target_type: str | None = None, target_id: str | None = None, meta: dict | None = None) -> None:
    """Audit events must never contain PII (names, phones, emails)."""
    db.add(AuditEvent(organization_id=org_id, actor_id=actor_id, action=action,
                      target_type=target_type, target_id=target_id, meta=meta or {}))


def current_consent(db: Session, lead_id: str, purpose: str) -> ConsentRecord | None:
    from sqlalchemy import select
    return db.scalar(select(ConsentRecord).where(
        ConsentRecord.lead_id == lead_id, ConsentRecord.purpose == purpose)
        .order_by(ConsentRecord.created_at.desc(), ConsentRecord.id.desc()).limit(1))


def has_consent(db: Session, lead_id: str, purpose: str) -> bool:
    c = current_consent(db, lead_id, purpose)
    return bool(c and c.status == "granted")


def record_consent(db: Session, lead: Lead, purpose: str, status: str, source: str,
                   evidence: dict | None = None, actor_id: str | None = None) -> ConsentRecord:
    rec = ConsentRecord(organization_id=lead.organization_id, lead_id=lead.id, purpose=purpose,
                        status=status, source=source, evidence=evidence or {}, recorded_by=actor_id,
                        created_at=now())
    db.add(rec)
    log_activity(db, lead.organization_id, lead.id, "consent",
                 f"Consent for {purpose} {status} via {source}", actor_id)
    return rec


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None
