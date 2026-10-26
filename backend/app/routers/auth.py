import re
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import Ctx, get_ctx, get_current_user, require_manager, require_owner, ALL_ROLES
from ..models import Organization, OrganizationMembership, OrganizationSettings, User
from ..security import (decode_token, hash_password, make_access_token, make_reset_token,
                        verify_password)
from ..services import DEFAULT_STATUSES, audit
from ..ratelimit import limiter

log = logging.getLogger("app.auth")
router = APIRouter()


def _slugify(name: str, db: Session) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "org"
    slug, i = base, 1
    while db.scalar(select(Organization.id).where(Organization.slug == slug)):
        i += 1
        slug = f"{base}-{i}"
    return slug


def create_organization(db: Session, name: str, owner: User) -> Organization:
    org = Organization(name=name, slug=_slugify(name, db))
    db.add(org)
    db.flush()
    db.add(OrganizationSettings(organization_id=org.id, lead_statuses=DEFAULT_STATUSES))
    db.add(OrganizationMembership(organization_id=org.id, user_id=owner.id, role="owner"))
    audit(db, org.id, owner.id, "organization.created", "organization", org.id)
    return org


class SignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    full_name: str = Field(min_length=1, max_length=200)
    organization_name: str | None = Field(default=None, max_length=200)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


def _memberships(db: Session, user: User) -> list[dict]:
    rows = db.execute(select(OrganizationMembership, Organization).join(
        Organization, Organization.id == OrganizationMembership.organization_id)
        .where(OrganizationMembership.user_id == user.id, Organization.is_active.is_(True))).all()
    return [{"organization_id": o.id, "name": o.name, "slug": o.slug, "role": m.role, "is_demo": o.is_demo}
            for m, o in rows]


def _session(db: Session, user: User) -> dict:
    return {"access_token": make_access_token(user.id, user.token_version), "token_type": "bearer",
            "user": {"id": user.id, "email": user.email, "full_name": user.full_name,
                     "is_platform_admin": user.is_platform_admin},
            "organizations": _memberships(db, user)}


@router.post("/auth/signup", status_code=201)
def signup(body: SignupIn, db: Session = Depends(get_db)):
    limiter.check("signup", "global", 20, 3600)
    email = body.email.lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(409, "An account with this email already exists")
    user = User(email=email, password_hash=hash_password(body.password), full_name=body.full_name)
    db.add(user)
    db.flush()
    if body.organization_name:
        create_organization(db, body.organization_name, user)
    db.commit()
    return _session(db, user)


@router.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    email = body.email.lower()
    limiter.check("login", email, 10, 900)
    user = db.scalar(select(User).where(User.email == email))
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    return _session(db, user)


@router.post("/auth/logout", status_code=204)
def logout(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Server-side logout: bumps token_version so all existing tokens are revoked."""
    user.token_version += 1
    db.commit()


@router.get("/auth/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = _session(db, user)
    s.pop("access_token")
    return s


class OrgIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


@router.post("/organizations", status_code=201)
def new_org(body: OrgIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    org = create_organization(db, body.name, user)
    db.commit()
    return {"organization_id": org.id, "name": org.name, "slug": org.slug, "role": "owner"}


class ForgotIn(BaseModel):
    email: EmailStr


@router.post("/auth/forgot-password")
def forgot(body: ForgotIn, db: Session = Depends(get_db)):
    email = body.email.lower()
    limiter.check("forgot", email, 5, 3600)
    user = db.scalar(select(User).where(User.email == email))
    resp: dict = {"detail": "If the account exists, a reset link has been sent."}
    if user:
        token = make_reset_token(user.id, user.token_version)
        # No email provider is wired up yet: see README known limitations.
        log.info("password reset requested for user_id=%s", user.id)
        if settings.environment == "development":
            resp["dev_reset_token"] = token
    return resp


class ResetIn(BaseModel):
    token: str
    new_password: str = Field(min_length=10, max_length=128)


@router.post("/auth/reset-password")
def reset(body: ResetIn, db: Session = Depends(get_db)):
    data = decode_token(body.token, "reset")
    user = db.get(User, data["sub"]) if data else None
    if not user or user.token_version != data.get("ver"):
        raise HTTPException(400, "Invalid or expired reset token")
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1  # single-use + revokes sessions
    audit(db, None, user.id, "auth.password_reset", "user", user.id)
    db.commit()
    return {"detail": "Password updated"}


# ---- team ----
class MemberIn(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    role: str
    password: str | None = Field(default=None, min_length=10, max_length=128)


@router.get("/team")
def team(ctx: Ctx = Depends(get_ctx)):
    rows = ctx.db.scalars(select(OrganizationMembership).where(
        OrganizationMembership.organization_id == ctx.org_id)).all()
    return [{"user_id": m.user_id, "email": m.user.email, "full_name": m.user.full_name, "role": m.role}
            for m in rows]


@router.post("/team", status_code=201)
def add_member(body: MemberIn, ctx: Ctx = Depends(require_manager)):
    if body.role not in ALL_ROLES or (body.role == "owner" and ctx.role != "owner"):
        raise HTTPException(403 if body.role == "owner" else 422, "Invalid or forbidden role")
    db = ctx.db
    email = body.email.lower()
    user = db.scalar(select(User).where(User.email == email))
    if not user:
        if not body.password:
            raise HTTPException(422, "password required to create a new user")
        user = User(email=email, password_hash=hash_password(body.password), full_name=body.full_name)
        db.add(user)
        db.flush()
    if db.scalar(select(OrganizationMembership.id).where(
            OrganizationMembership.organization_id == ctx.org_id,
            OrganizationMembership.user_id == user.id)):
        raise HTTPException(409, "Already a member")
    db.add(OrganizationMembership(organization_id=ctx.org_id, user_id=user.id, role=body.role))
    audit(db, ctx.org_id, ctx.user.id, "member.added", "user", user.id, {"role": body.role})
    db.commit()
    return {"user_id": user.id, "role": body.role}


class RoleIn(BaseModel):
    role: str


@router.patch("/team/{user_id}")
def change_role(user_id: str, body: RoleIn, ctx: Ctx = Depends(require_owner)):
    if body.role not in ALL_ROLES:
        raise HTTPException(422, "Invalid role")
    m = ctx.db.scalar(select(OrganizationMembership).where(
        OrganizationMembership.organization_id == ctx.org_id, OrganizationMembership.user_id == user_id))
    if not m:
        raise HTTPException(404, "Member not found")
    if m.role == "owner" and body.role != "owner":
        owners = ctx.db.scalars(select(OrganizationMembership.id).where(
            OrganizationMembership.organization_id == ctx.org_id,
            OrganizationMembership.role == "owner")).all()
        if len(owners) <= 1:
            raise HTTPException(409, "Organization must keep at least one owner")
    m.role = body.role
    audit(ctx.db, ctx.org_id, ctx.user.id, "member.role_changed", "user", user_id, {"role": body.role})
    ctx.db.commit()
    return {"user_id": user_id, "role": m.role}


@router.delete("/team/{user_id}", status_code=204)
def remove_member(user_id: str, ctx: Ctx = Depends(require_owner)):
    m = ctx.db.scalar(select(OrganizationMembership).where(
        OrganizationMembership.organization_id == ctx.org_id, OrganizationMembership.user_id == user_id))
    if not m:
        raise HTTPException(404, "Member not found")
    if m.role == "owner":
        raise HTTPException(409, "Change owner role before removing")
    ctx.db.delete(m)
    audit(ctx.db, ctx.org_id, ctx.user.id, "member.removed", "user", user_id)
    ctx.db.commit()


# ---- settings ----
class SettingsIn(BaseModel):
    timezone: str | None = None
    lead_statuses: list[str] | None = None
    qualification_rules: dict | None = None
    chatbot_config: dict | None = None
    calling_config: dict | None = None
    retention_days: int | None = Field(default=None, ge=1, le=3650)


def _settings_out(s: OrganizationSettings, org: Organization) -> dict:
    return {"organization": {"id": org.id, "name": org.name, "public_key": org.public_key},
            "timezone": s.timezone, "lead_statuses": s.lead_statuses,
            "qualification_rules": s.qualification_rules, "chatbot_config": s.chatbot_config,
            "calling_config": s.calling_config, "retention_days": s.retention_days,
            "calling_paused": s.calling_paused}


@router.get("/settings")
def get_settings(ctx: Ctx = Depends(get_ctx)):
    return _settings_out(ctx.db.get(OrganizationSettings, ctx.org_id), ctx.org)


@router.patch("/settings")
def update_settings(body: SettingsIn, ctx: Ctx = Depends(require_manager)):
    s = ctx.db.get(OrganizationSettings, ctx.org_id)
    changed = []
    for k, v in body.model_dump(exclude_none=True).items():
        if k == "timezone":
            from zoneinfo import ZoneInfo
            try:
                ZoneInfo(v)
            except Exception:
                raise HTTPException(422, "Unknown timezone")
        if k == "lead_statuses":
            required = {"New", "Do Not Contact", "Invalid"}
            if not required.issubset(v):
                raise HTTPException(422, "Statuses New, Invalid and Do Not Contact are required")
        setattr(s, k, v)
        changed.append(k)
    audit(ctx.db, ctx.org_id, ctx.user.id, "settings.updated", "organization", ctx.org_id,
          {"fields": changed})
    ctx.db.commit()
    return _settings_out(s, ctx.org)
