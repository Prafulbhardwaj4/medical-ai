from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.plan_inquiry import PlanInquiry

router = APIRouter(prefix="/plan-inquiries", tags=["plan-inquiries"])


class PlanInquiryIn(BaseModel):
    requested_tier: str
    billing_period: str  # "monthly" | "yearly"
    hospital_name: str
    contact_name: str
    contact_phone: str
    contact_email: str
    message: Optional[str] = None


@router.post("")
def submit_plan_inquiry(body: PlanInquiryIn, db: Session = Depends(get_db)):
    """Fully public — no auth. Anyone browsing the marketing site can hit
    this from the pricing section's Contact Us modal, no account needed."""
    db.add(PlanInquiry(
        requested_tier=body.requested_tier,
        billing_period=body.billing_period,
        hospital_name=body.hospital_name.strip(),
        contact_name=body.contact_name.strip(),
        contact_phone=body.contact_phone.strip(),
        contact_email=body.contact_email.strip(),
        message=(body.message or "").strip() or None,
    ))
    db.commit()
    return {"message": "Thanks — our team will reach out shortly."}