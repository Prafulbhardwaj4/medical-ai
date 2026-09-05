from sqlalchemy import Column, Integer, String, DateTime
from app.database import Base
from app.utils.timezone import now_ist_naive


class TutorialProgress(Base):
    """Whether a given account has completed a given role's tutorial —
    skip and finish are treated identically (both just mark it done, see
    role_router.py for the endpoint). Role-level granularity, not
    per-step: this is a guided one-pass walkthrough, not a resumable
    multi-session course. subject_type covers both staff (Doctor rows)
    and patients (PatientAccount rows), since the patient portal is the
    first tutorial being built, not just staff."""
    __tablename__ = "tutorial_progress"

    id = Column(Integer, primary_key=True, index=True)
    subject_type = Column(String, nullable=False)  # "doctor" | "patient_account"
    subject_id = Column(Integer, nullable=False)  # Doctor.id or PatientAccount.id, per subject_type
    role = Column(String, nullable=False)  # which tutorial — matches TutorialStep.role
    completed_at = Column(DateTime, default=now_ist_naive, nullable=False)