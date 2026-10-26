from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import Organization, OrganizationMembership, User
from .security import decode_token

MANAGER_ROLES = ("owner", "manager")
ALL_ROLES = ("owner", "manager", "counsellor")


def get_current_user(authorization: str | None = Header(default=None),
                     db: Session = Depends(get_db)) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Not authenticated")
    data = decode_token(authorization[7:], "access")
    if not data:
        raise HTTPException(401, "Invalid or expired token")
    user = db.get(User, data["sub"])
    if not user or not user.is_active or user.token_version != data.get("ver"):
        raise HTTPException(401, "Invalid or expired token")
    return user


@dataclass
class Ctx:
    """Resolved per-request context: who, in which organization, with which role."""
    db: Session
    user: User
    org: Organization
    role: str

    @property
    def org_id(self) -> str:
        return self.org.id

    @property
    def is_manager(self) -> bool:
        return self.role in MANAGER_ROLES


def get_ctx(x_organization_id: str | None = Header(default=None),
            user: User = Depends(get_current_user),
            db: Session = Depends(get_db)) -> Ctx:
    if not x_organization_id:
        raise HTTPException(400, "X-Organization-Id header required")
    m = db.scalar(select(OrganizationMembership).where(
        OrganizationMembership.organization_id == x_organization_id,
        OrganizationMembership.user_id == user.id))
    org = db.get(Organization, x_organization_id) if m else None
    # Same error whether the org doesn't exist or the user isn't a member: no tenant enumeration.
    if not m or not org or not org.is_active:
        raise HTTPException(403, "No access to this organization")
    return Ctx(db=db, user=user, org=org, role=m.role)


def require_manager(ctx: Ctx = Depends(get_ctx)) -> Ctx:
    if not ctx.is_manager:
        raise HTTPException(403, "Manager role required")
    return ctx


def require_owner(ctx: Ctx = Depends(get_ctx)) -> Ctx:
    if ctx.role != "owner":
        raise HTTPException(403, "Owner role required")
    return ctx


def require_platform_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_platform_admin:
        raise HTTPException(403, "Platform administrator required")
    return user
