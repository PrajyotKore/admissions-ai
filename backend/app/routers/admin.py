from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require_platform_admin
from ..models import CallAttempt, Lead, Organization, OrganizationMembership, User
from ..services import audit

router = APIRouter(prefix="/admin")


@router.get("/organizations")
def orgs(admin: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    """Aggregate usage only: platform admins do not get lead-level (PII) access."""
    out = []
    for o in db.scalars(select(Organization).order_by(Organization.created_at)).all():
        out.append({"id": o.id, "name": o.name, "is_active": o.is_active, "is_demo": o.is_demo,
                    "members": db.scalar(select(func.count()).select_from(OrganizationMembership)
                                         .where(OrganizationMembership.organization_id == o.id)),
                    "leads": db.scalar(select(func.count()).select_from(Lead).where(Lead.organization_id == o.id)),
                    "call_attempts": db.scalar(select(func.count()).select_from(CallAttempt)
                                               .where(CallAttempt.organization_id == o.id))})
    return out


@router.post("/organizations/{org_id}/active")
def set_active(org_id: str, active: bool, admin: User = Depends(require_platform_admin),
               db: Session = Depends(get_db)):
    org = db.get(Organization, org_id)
    if not org:
        raise HTTPException(404, "Organization not found")
    org.is_active = active
    audit(db, org_id, admin.id, "admin.org_active_changed", "organization", org_id, {"active": active})
    db.commit()
    return {"id": org_id, "is_active": active}


@router.get("/health")
def health(admin: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    return {"database": "ok" if db.scalar(select(1)) == 1 else "error",
            "organizations": db.scalar(select(func.count()).select_from(Organization)),
            "users": db.scalar(select(func.count()).select_from(User))}
