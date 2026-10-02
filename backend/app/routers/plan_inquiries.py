from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.plan_inquiry import PlanInquiry
from app.utils.rate_limit import limiter

router = APIRouter(prefix="/plan-inquiries", tags=["plan-inquiries"])


class PlanInquiryIn(BaseModel):
    requested_tier: str
    billing_period: str  # "monthly" | "yearly"
    hospital_name: str
    contact_name: str
    contact_phone: str
    contact_email: str
    state: str
    city: str
    preferred_language: str
    message: Optional[str] = None

@router.post("")
@limiter.limit("5/hour")
def submit_plan_inquiry(request: Request, body: PlanInquiryIn, db: Session = Depends(get_db)):
    """Fully public — no auth. Anyone browsing the marketing site can hit
    this from the pricing section's Contact Us modal, no account needed."""
    if body.requested_tier not in ("foundation", "growth", "scale", "enterprise"):
        raise HTTPException(status_code=400, detail="Invalid plan")
    if body.billing_period not in ("monthly", "yearly"):
        raise HTTPException(status_code=400, detail="Invalid billing period")
    for _v, _max in ((body.hospital_name, 150), (body.contact_name, 100), (body.contact_phone, 20),
                     (body.contact_email, 150), (body.state, 80), (body.city, 80),
                     (body.preferred_language, 40), (body.message or "", 1000)):
        if len(_v) > _max:
            raise HTTPException(status_code=400, detail="One of the fields is too long")
    import re
    _digits = re.sub(r"\D", "", body.contact_phone)
    if not (10 <= len(_digits) <= 13):
        raise HTTPException(status_code=400, detail="Please enter a valid phone number")
    if body.contact_email.strip() and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", body.contact_email.strip()):
        raise HTTPException(status_code=400, detail="Please enter a valid email address")
    if not body.hospital_name.strip() or not body.contact_name.strip() or not body.contact_phone.strip():
        raise HTTPException(status_code=400, detail="Hospital, contact name and phone are required")
    db.add(PlanInquiry(
        requested_tier=body.requested_tier,
        billing_period=body.billing_period,
        hospital_name=body.hospital_name.strip(),
        contact_name=body.contact_name.strip(),
        contact_phone=body.contact_phone.strip(),
        contact_email=body.contact_email.strip(),
        state=body.state.strip(),
        city=body.city.strip(),
        preferred_language=body.preferred_language.strip(),
        message=(body.message or "").strip() or None,
    ))
    db.commit()
    return {"message": "Thanks — our team will reach out shortly."}