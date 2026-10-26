import re
import uuid
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (
    Organization,
    OrganizationSettings,
    Lead,
    KnowledgeDocument,
    ChatConversation,
    now,
)
from ..ratelimit import limiter
from ..services import (
    normalize_phone,
    PhoneError,
    record_consent,
    audit,
    log_activity,
)
from ..qualification import qualify_lead
from .leads import create_lead, DuplicateLead

router = APIRouter(prefix="/public")


def resolve_org_by_key(public_key: str, db: Session) -> Organization:
    org = db.scalar(select(Organization).where(Organization.public_key == public_key, Organization.is_active.is_(True)))
    if not org:
        raise HTTPException(404, "Invalid organization public key")
    return org


@router.get("/config")
def public_config(key: str, db: Session = Depends(get_db)):
    """Fetch public chatbot and lead capture settings for an organization."""
    org = resolve_org_by_key(key, db)
    settings = db.get(OrganizationSettings, org.id)
    chatbot_config = (settings.chatbot_config if settings else {}) or {}

    # Fetch approved knowledge document titles for suggested topics
    approved_docs = db.scalars(
        select(KnowledgeDocument.title).where(
            KnowledgeDocument.organization_id == org.id,
            KnowledgeDocument.is_approved.is_(True)
        )
    ).all()

    return {
        "organization_name": org.name,
        "is_demo": org.is_demo,
        "welcome_message": chatbot_config.get(
            "welcome_message",
            f"Hello! Welcome to {org.name}. I'm your AI admissions assistant. How can I help you with your college and course search today?"
        ),
        "available_topics": approved_docs,
        "consent_disclaimer": (
            "We collect your contact details solely to assist with your educational enquiry. "
            "Automated follow-up calls or messages are only made with your explicit consent."
        ),
        "courses_offered": [
            "MBA",
            "B.Tech Computer Science",
            "MBBS",
            "BBA",
            "B.Com",
            "MCA",
        ],
    }


# ---------- Public Web Lead Form ----------
class PublicLeadIn(BaseModel):
    public_key: str
    name: str = Field(min_length=1, max_length=200)
    phone: str = Field(min_length=5, max_length=32)
    email: EmailStr | None = None
    preferred_course: str | None = Field(default=None, max_length=200)
    preferred_college: str | None = Field(default=None, max_length=200)
    education_level: str | None = Field(default=None, max_length=100)
    academic_marks: float | None = Field(default=None, ge=0, le=100)
    preferred_location: str | None = Field(default=None, max_length=200)
    budget_max: int | None = Field(default=None, ge=0)
    admission_timeline: str | None = Field(default=None, max_length=100)
    # Distinct consent flags
    consent_automated_calls: bool = False
    consent_marketing: bool = False


@router.post("/lead", status_code=201)
def submit_public_lead(body: PublicLeadIn, request: Request, db: Session = Depends(get_db)):
    """Accessible fallback lead capture form with spam protection and consent verification."""
    client_ip = request.client.host if request.client else "unknown"
    limiter.check("public_form", client_ip, 15, 3600)

    org = resolve_org_by_key(body.public_key, db)

    try:
        phone_n = normalize_phone(body.phone)
    except PhoneError as e:
        raise HTTPException(422, str(e))

    lead_data = {
        "name": body.name,
        "phone": body.phone,
        "email": body.email,
        "preferred_course": body.preferred_course,
        "preferred_college": body.preferred_college,
        "education_level": body.education_level,
        "academic_marks": body.academic_marks,
        "preferred_location": body.preferred_location,
        "budget_max": body.budget_max,
        "admission_timeline": body.admission_timeline,
    }

    evidence = {
        "ip": client_ip,
        "user_agent": request.headers.get("user-agent", "unknown")[:255],
        "form_source": "public_web_form",
    }

    try:
        lead = create_lead(
            db,
            org.id,
            lead_data,
            source_name="Website Lead Form",
            actor_id=None,
            provenance_source="web_lead_form",
        )
    except DuplicateLead as d:
        # Respect rule: Never silently overwrite student data on duplicate!
        lead = db.get(Lead, d.lead_id)
        log_activity(db, org.id, lead.id, "form_submission", "Existing lead submitted web form enquiry", None)

    # Record consent separately
    if body.consent_automated_calls:
        record_consent(
            db,
            lead,
            purpose="automated_calls",
            status="granted",
            source="web_form",
            evidence={**evidence, "text": "Agreed to automated voice consultation calls"},
        )
    if body.consent_marketing:
        record_consent(
            db,
            lead,
            purpose="marketing",
            status="granted",
            source="web_form",
            evidence={**evidence, "text": "Agreed to admissions marketing updates"},
        )

    # Evaluate qualification
    qualify_lead(db, lead)

    audit(db, org.id, None, "public.lead_submitted", "lead", lead.id)
    db.commit()

    return {
        "success": True,
        "message": "Thank you! Your enquiry has been received. Our admissions team will review your details.",
    }


# ---------- Public Chatbot Engine ----------
class ChatMessageIn(BaseModel):
    public_key: str
    session_id: str | None = None
    message: str = Field(min_length=1, max_length=1000)


def extract_info_from_text(text: str) -> dict[str, Any]:
    """Helper extraction from visitor chat messages."""
    extracted: dict[str, Any] = {}

    # Extract phone number (e.g. 10 digits or with +91)
    phone_match = re.search(r"(?:(?:\+|0{0,2})91[\s-]*)?[6-9]\d{9}\b", text)
    if phone_match:
        extracted["phone"] = phone_match.group(0)

    # Extract name (e.g. "my name is Rohit Gupta", "I am Rohit Gupta and my phone is...")
    name_match = re.search(r"\b(?:my name is|name is|i am|this is|i'm)\s+([A-Za-z]+(?:\s+[A-Za-z]+)*?)(?=\s+(?:and|my|mobile|phone|email|\d)|[,\.]|$)", text, re.IGNORECASE)
    if name_match:
        extracted["name"] = name_match.group(1).strip()

    # Extract email
    email_match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text)
    if email_match:
        extracted["email"] = email_match.group(0)

    # Extract percentage/marks
    marks_match = re.search(r"\b(\d{2}(?:\.\d+)?)\s*(?:%|percent|marks|pct)\b", text, re.IGNORECASE)
    if marks_match:
        try:
            m = float(marks_match.group(1))
            if 30 <= m <= 100:
                extracted["academic_marks"] = m
        except ValueError:
            pass

    # Extract budget
    budget_match = re.search(r"\b(?:budget|fees?|around|max)?\s*(?:rs\.?|inr|₹)?\s*(\d+(?:,\d+)*(?:\.\d+)?)\s*(lakh|lac|k|crore)?\b", text, re.IGNORECASE)
    if budget_match:
        val_str = budget_match.group(1).replace(",", "")
        unit = (budget_match.group(2) or "").lower()
        try:
            val = float(val_str)
            if unit in ("lakh", "lac"):
                val *= 100000
            elif unit == "crore":
                val *= 10000000
            elif unit == "k":
                val *= 1000
            if val >= 10000:
                extracted["budget_max"] = int(val)
        except ValueError:
            pass

    # Extract common course keywords
    for c in ["MBA", "MBBS", "B.Tech Computer Science", "B.Tech", "BBA", "B.Com", "MCA", "BCA", "M.Tech"]:
        if re.search(rf"\b{re.escape(c)}\b", text, re.IGNORECASE):
            extracted["preferred_course"] = c
            break

    # Extract city / location
    for loc in ["Pune", "Mumbai", "Bengaluru", "Bangalore", "Delhi", "Hyderabad", "Chennai", "Kolkata"]:
        if re.search(rf"\b{re.escape(loc)}\b", text, re.IGNORECASE):
            extracted["preferred_location"] = "Bengaluru" if loc.lower() == "bangalore" else loc
            break

    return extracted


def find_knowledge_answers(query: str, org_id: str, db: Session) -> str | None:
    """
    Search approved consultancy knowledge documents only.
    NEVER invent facts not present in approved documents!
    """
    docs = db.scalars(
        select(KnowledgeDocument).where(
            KnowledgeDocument.organization_id == org_id,
            KnowledgeDocument.is_approved.is_(True)
        )
    ).all()

    if not docs:
        return None

    words = set(re.findall(r"\w{3,}", query.lower()))
    best_doc = None
    best_overlap = 0

    for doc in docs:
        doc_words = set(re.findall(r"\w{3,}", (doc.title + " " + doc.content).lower()))
        overlap = len(words.intersection(doc_words))
        if overlap > best_overlap:
            best_overlap = overlap
            best_doc = doc

    if best_doc and best_overlap >= 2:
        return best_doc.content[:600]

    return None


@router.post("/chat")
def chat_step(body: ChatMessageIn, request: Request, db: Session = Depends(get_db)):
    """Conversational enquiry flow grounded strictly in approved consultancy documents."""
    client_ip = request.client.host if request.client else "unknown"
    limiter.check("public_chat", client_ip, 60, 3600)

    org = resolve_org_by_key(body.public_key, db)

    # Retrieve or initialize session
    conv = None
    session_id = body.session_id
    if session_id:
        conv = db.scalar(select(ChatConversation).where(
            ChatConversation.id == session_id,
            ChatConversation.organization_id == org.id
        ))

    if not conv:
        session_id = str(uuid.uuid4())
        conv = ChatConversation(
            id=session_id,
            organization_id=org.id,
            state={"step": "greet", "collected": {}},
            messages=[],
            status="open",
        )
        db.add(conv)
        db.flush()

    state = dict(conv.state or {"step": "greet", "collected": {}})
    collected = dict(state.get("collected", {}))
    messages = list(conv.messages or [])

    user_text = body.message.strip()
    messages.append({"sender": "user", "text": user_text, "at": now().isoformat()})

    # Extract parameters from user text
    extracted = extract_info_from_text(user_text)
    for k, v in extracted.items():
        if k not in collected:
            collected[k] = v

    # Consent detection in user text
    lower = user_text.lower()
    consent_given = any(w in lower for w in ["yes", "agree", "sure", "ok", "proceed", "consent", "i agree"])
    consent_declined = any(w in lower for w in ["no", "don't", "dont", "refuse", "stop", "never"])

    # Grounded answer check from approved knowledge base
    knowledge_answer = find_knowledge_answers(user_text, org.id, db)

    # Conversational state progression
    bot_reply = ""
    lead_created_or_updated = False

    # Check if user is answering consent prompt
    if state.get("step") == "awaiting_consent":
        if consent_given:
            collected["consent_calls"] = True
            bot_reply = (
                "Thank you! Your consent has been recorded. Our senior counsellor will review your profile "
                f"and reach out to you at {collected.get('phone')} to guide your admission process. Is there anything else you would like to know?"
            )
            state["step"] = "completed"
        elif consent_declined:
            collected["consent_calls"] = False
            bot_reply = (
                "Understood! We respect your preference. We will not initiate automated calls. "
                "You can still reach out to us whenever you are ready."
            )
            state["step"] = "completed"
        else:
            bot_reply = (
                "To ensure we follow telecom and privacy regulations, please confirm: "
                "Do you consent to receiving an admissions consultation call? (Please reply Yes or No)"
            )

    elif knowledge_answer and not any(k in user_text.lower() for k in ["my name", "my number", "phone"]):
        bot_reply = f"{knowledge_answer}\n\nWould you like me to connect you with our counselling team to apply?"

    elif "preferred_course" not in collected:
        bot_reply = "Which course or degree program are you looking to pursue? (e.g., MBA, B.Tech Computer Science, MBBS)"
        state["step"] = "ask_course"

    elif "academic_marks" not in collected and "marks" in user_text.lower():
        bot_reply = "What was your recent percentage or academic score?"
        state["step"] = "ask_marks"

    elif "phone" not in collected:
        if "name" not in collected and len(user_text.split()) <= 3 and not any(char.isdigit() for char in user_text):
            collected["name"] = user_text
        bot_reply = f"Great! To share detailed course eligibility, fee structures, and college cutoffs, what is your phone number?"
        state["step"] = "ask_phone"

    elif "name" not in collected:
        bot_reply = "Thank you! And may I please have your full name?"
        state["step"] = "ask_name"

    elif "consent_calls" not in collected:
        bot_reply = (
            f"Thank you, {collected.get('name', 'Student')}! Before our counsellor contacts you: "
            "Do you consent to our consultancy reaching out via phone or voice consultation regarding your admission? (Yes / No)"
        )
        state["step"] = "awaiting_consent"

    else:
        if knowledge_answer:
            bot_reply = knowledge_answer
        else:
            bot_reply = (
                "I don't have verified details on that specific question in our approved admissions handbook. "
                "I have noted your enquiry and our counsellor will discuss this with you directly during your consultation."
            )

    # If we have name and phone, create or update lead
    if "phone" in collected and ("name" in collected or "preferred_course" in collected):
        try:
            phone_n = normalize_phone(collected["phone"])
            existing_lead = db.scalar(select(Lead).where(
                Lead.organization_id == org.id,
                Lead.phone_normalized == phone_n
            ))
            if not existing_lead:
                lead = create_lead(
                    db,
                    org.id,
                    {
                        "name": collected.get("name") or "Website Enquiry",
                        "phone": collected["phone"],
                        "email": collected.get("email"),
                        "preferred_course": collected.get("preferred_course"),
                        "preferred_location": collected.get("preferred_location"),
                        "academic_marks": collected.get("academic_marks"),
                        "budget_max": collected.get("budget_max"),
                    },
                    source_name="Website Chatbot",
                    actor_id=None,
                    provenance_source="website_chatbot",
                )
                conv.lead_id = lead.id
                lead_created_or_updated = True
            else:
                lead = existing_lead
                conv.lead_id = lead.id

            # If consent was granted or withdrawn, record it
            if collected.get("consent_calls") is True:
                record_consent(
                    db,
                    lead,
                    purpose="automated_calls",
                    status="granted",
                    source="chatbot",
                    evidence={"ip": client_ip, "session_id": session_id, "text": "Confirmed Yes in website chatbot"},
                )
                qualify_lead(db, lead)
            elif collected.get("consent_calls") is False:
                record_consent(
                    db,
                    lead,
                    purpose="automated_calls",
                    status="withdrawn",
                    source="chatbot",
                    evidence={"ip": client_ip, "session_id": session_id, "text": "Declined in website chatbot"},
                )

        except PhoneError:
            pass

    messages.append({"sender": "bot", "text": bot_reply, "at": now().isoformat()})
    state["collected"] = collected
    conv.state = state
    conv.messages = messages

    db.commit()

    return {
        "session_id": session_id,
        "reply": bot_reply,
        "state": state["step"],
        "collected": collected,
    }
