"""Seed a clearly-labelled DEMO organization. Refuses to run in production.

Usage:  python -m app.seed
        python -m app.seed --platform-admin you@example.com   (promote an existing user)
"""
import argparse
import random

from sqlalchemy import select

from .config import settings
from .db import SessionLocal
from .models import Lead, Organization, OrganizationMembership, User
from .routers.auth import create_organization
from .routers.leads import create_lead
from .security import hash_password
from .services import record_consent

DEMO_PASSWORD = "demo-password-123"
COURSES = ["MBA", "B.Tech Computer Science", "MBBS", "BBA", "B.Com", "MCA"]
CITIES = ["Pune", "Mumbai", "Bengaluru", "Delhi", "Hyderabad"]
SOURCES = ["Website Chatbot", "Instagram Ad", "Walk-in", "Referral"]
NAMES = ["Aarav Sharma", "Diya Patel", "Vihaan Rao", "Ananya Iyer", "Kabir Singh", "Ishita Nair",
         "Rohan Mehta", "Saanvi Reddy", "Arjun Kulkarni", "Meera Joshi", "Dev Malhotra", "Tara Das"]


def get_or_create_user(db, email, name):
    u = db.scalar(select(User).where(User.email == email))
    if not u:
        u = User(email=email, full_name=name, password_hash=hash_password(DEMO_PASSWORD))
        db.add(u)
        db.flush()
    return u


def seed():
    if settings.environment == "production":
        raise SystemExit("Refusing to seed demo data in production.")
    random.seed(7)
    with SessionLocal() as db:
        if db.scalar(select(Organization).where(Organization.slug == "demo-admissions")):
            print("Demo organization already exists.")
            return
        owner = get_or_create_user(db, "owner@demo.example", "Demo Owner")
        org = create_organization(db, "Demo Admissions", owner)
        org.is_demo = True
        counsellor = get_or_create_user(db, "counsellor@demo.example", "Demo Counsellor")
        db.add(OrganizationMembership(organization_id=org.id, user_id=counsellor.id, role="counsellor"))
        for i, name in enumerate(NAMES):
            lead = create_lead(db, org.id, {
                "name": f"[DEMO] {name}", "phone": f"98{random.randint(10000000, 99999999)}",
                "preferred_course": random.choice(COURSES), "preferred_location": random.choice(CITIES),
                "budget_max": random.choice([300000, 500000, 800000]), "admission_timeline": "This year",
                "education_level": "12th", "academic_marks": random.randint(55, 95)},
                source_name=random.choice(SOURCES), actor_id=owner.id,
                assigned_to=counsellor.id if i % 2 else None, provenance_source="demo_seed")
            if i % 3 == 0:
                record_consent(db, lead, "automated_calls", "granted", "manual",
                               {"note": "DEMO seed data"}, owner.id)
        db.commit()
        print(f"Seeded DEMO org. Login: owner@demo.example / {DEMO_PASSWORD} "
              f"(counsellor@demo.example, same password)")


def promote(email: str):
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == email.lower()))
        if not u:
            raise SystemExit("No such user. Sign up first.")
        u.is_platform_admin = True
        db.commit()
        print(f"{email} is now a platform administrator.")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--platform-admin")
    a = p.parse_args()
    promote(a.platform_admin) if a.platform_admin else seed()
