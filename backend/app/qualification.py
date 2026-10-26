from typing import Any
from sqlalchemy.orm import Session
from .models import Lead, QualificationResult, OrganizationSettings, now
from .services import log_activity

DEFAULT_RULES = {
    "required_fields": ["preferred_course", "preferred_location"],
    "min_academic_marks": 50.0,
    "course_criteria": {
        "MBBS": {"min_marks": 60.0, "weight": 25},
        "B.Tech Computer Science": {"min_marks": 55.0, "weight": 20},
        "MBA": {"min_marks": 50.0, "weight": 20},
    },
    "budget_limits": {
        "MBBS": 1500000,
        "MBA": 1000000,
    },
    "urgent_timelines": ["Immediate", "This year", "Next 1-2 months", "Fall 2026", "Spring 2027"],
    "min_score_for_eligible": 40,
}


def evaluate_qualification(lead: Lead, rules: dict[str, Any]) -> dict[str, Any]:
    """
    Deterministic qualification engine:
    Clearly distinguishes hard eligibility requirements from soft sales-priority scores.
    """
    hard_failures: list[str] = []
    reasons: list[str] = []
    missing_fields: list[str] = []
    priority_score = 0

    # 1. Check Missing Required Fields
    required = rules.get("required_fields", ["preferred_course", "preferred_location"])
    for fld in required:
        val = getattr(lead, fld, None)
        if val is None or (isinstance(val, str) and not val.strip()):
            missing_fields.append(fld)

    # 2. Hard Eligibility Check: Academic Marks
    min_marks = rules.get("min_academic_marks", 50.0)
    course_criteria = rules.get("course_criteria", {})
    if lead.preferred_course and lead.preferred_course in course_criteria:
        course_min = course_criteria[lead.preferred_course].get("min_marks", min_marks)
        if lead.academic_marks is not None:
            if lead.academic_marks < course_min:
                hard_failures.append(f"Academic marks ({lead.academic_marks}%) below minimum required for {lead.preferred_course} ({course_min}%)")
            else:
                reasons.append(f"Academic marks meet {lead.preferred_course} requirement ({lead.academic_marks}% >= {course_min}%)")
        else:
            missing_fields.append("academic_marks")
    elif lead.academic_marks is not None:
        if lead.academic_marks < min_marks:
            hard_failures.append(f"Academic marks ({lead.academic_marks}%) below minimum threshold ({min_marks}%)")
        else:
            reasons.append(f"Academic marks meet minimum requirement ({lead.academic_marks}% >= {min_marks}%)")

    # 3. Hard Eligibility Check: Budget fit
    budget_limits = rules.get("budget_limits", {})
    if lead.preferred_course and lead.preferred_course in budget_limits:
        min_course_cost = budget_limits[lead.preferred_course]
        if lead.budget_max is not None and lead.budget_max < min_course_cost:
            hard_failures.append(f"Budget maximum (₹{lead.budget_max:,}) is below estimated minimum fees for {lead.preferred_course} (₹{min_course_cost:,})")

    # 4. Soft Priority Scoring (0 - 100)
    # Profile completeness: up to 30 pts
    completeness_fields = ["email", "preferred_course", "preferred_college", "education_level", "academic_marks", "preferred_location"]
    filled_count = sum(1 for f in completeness_fields if getattr(lead, f, None) is not None)
    completeness_score = int((filled_count / len(completeness_fields)) * 30)
    priority_score += completeness_score
    if completeness_score >= 20:
        reasons.append("High profile completeness")

    # Marks excellence: up to 25 pts
    if lead.academic_marks is not None:
        if lead.academic_marks >= 85:
            priority_score += 25
            reasons.append("Excellent academic standing (85%+)")
        elif lead.academic_marks >= 70:
            priority_score += 18
            reasons.append("Good academic standing (70-84%)")
        elif lead.academic_marks >= 55:
            priority_score += 10

    # Urgency score: up to 25 pts
    urgent_timelines = rules.get("urgent_timelines", ["Immediate", "This year", "Next 1-2 months"])
    if lead.admission_timeline and any(u.lower() in lead.admission_timeline.lower() for u in urgent_timelines):
        priority_score += 25
        reasons.append(f"High admission urgency ({lead.admission_timeline})")
    elif lead.admission_timeline:
        priority_score += 10

    # Budget readiness: up to 20 pts
    if lead.budget_max is not None and lead.budget_max > 0:
        priority_score += 20
        reasons.append("Budget parameters defined")

    # Cap score at 100
    priority_score = min(100, max(0, priority_score))

    # Determine Category
    if hard_failures:
        category = "ineligible"
        next_action = "Inform student of eligibility criteria or suggest alternative courses"
    elif missing_fields:
        category = "needs_info"
        next_action = f"Collect missing fields: {', '.join(missing_fields)}"
    else:
        min_eligible_score = rules.get("min_score_for_eligible", 40)
        if priority_score >= min_eligible_score:
            category = "eligible"
            next_action = "Initiate counselling call or schedule appointment"
        else:
            category = "needs_info"
            next_action = "Follow up to assess interest and financial readiness"

    return {
        "category": category,
        "priority_score": priority_score,
        "hard_failures": hard_failures,
        "reasons": reasons,
        "missing_fields": missing_fields,
        "next_action": next_action,
    }


def qualify_lead(db: Session, lead: Lead, actor_id: str | None = None) -> QualificationResult:
    """Run deterministic qualification on a lead and store the result."""
    settings = db.get(OrganizationSettings, lead.organization_id)
    rules = (settings.qualification_rules if settings and settings.qualification_rules else None) or DEFAULT_RULES

    res = evaluate_qualification(lead, rules)

    q_result = QualificationResult(
        organization_id=lead.organization_id,
        lead_id=lead.id,
        category=res["category"],
        priority_score=res["priority_score"],
        hard_failures=res["hard_failures"],
        reasons=res["reasons"],
        missing_fields=res["missing_fields"],
        next_action=res["next_action"],
        created_at=now(),
    )
    db.add(q_result)

    # Update lead fields
    lead.qualification_score = res["priority_score"]
    lead.qualification_category = res["category"]
    
    # Store field provenance for qualification update
    prov = dict(lead.field_provenance or {})
    prov["qualification"] = {
        "source": f"qualify_engine:{actor_id or 'system'}",
        "at": now().isoformat(),
        "category": res["category"],
        "score": res["priority_score"],
    }
    lead.field_provenance = prov

    log_activity(
        db,
        lead.organization_id,
        lead.id,
        "qualification",
        f"Qualification evaluated: {res['category']} (Score: {res['priority_score']}/100) - {res['next_action']}",
        actor_id=actor_id,
        data={"category": res["category"], "score": res["priority_score"], "next_action": res["next_action"]}
    )

    return q_result
