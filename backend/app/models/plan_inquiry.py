from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean
from app.database import Base
from app.utils.timezone import now_ist_naive


class PlanInquiry(Base):
    """A prospective hospital's submission from the public marketing site's
    (home.html) pricing "Contact Us" modal — nobody is logged in at this
    point, this is a fully public/unauthenticated lead. Deliberately
    separate from UpgradeRequest (an existing paying hospital's admin
    asking to move up a tier) and HospitalLead (a patient saying their
    hospital isn't on MedScribe yet) — three different sources feeding
    three different super admin tabs."""
    __tablename__ = "plan_inquiries"

    id = Column(Integer, primary_key=True, index=True)
    requested_tier = Column(String, nullable=False)   # tier key, e.g. "growth"
    billing_period = Column(String, nullable=False)    # "monthly" | "yearly"
    hospital_name = Column(String, nullable=False)
    contact_name = Column(String, nullable=False)
    contact_phone = Column(String, nullable=False)
    contact_email = Column(String, nullable=False)
    state = Column(String, nullable=False)
    city = Column(String, nullable=False)
    preferred_language = Column(String, nullable=False)
    message = Column(Text, nullable=True)
    status = Column(String, default="new", nullable=False)  # new | contacted
    created_at = Column(DateTime, default=now_ist_naive, nullable=False)