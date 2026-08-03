from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from app.database import Base
from app.utils.timezone import now_ist_naive


class PatientMergeRequest(Base):
    """Interim, manual duplicate-patient merge tool — reception/admin flags
    two records as a suspected duplicate, confirms identity by phone with
    the patient (confirmation_note captures what was actually confirmed —
    e.g. matching DOB/address), then an admin executes the merge. The
    duplicate record is never hard-deleted — it's soft-marked inactive with
    merged_into_id pointing at the surviving record, so clinical/billing
    history stays intact and auditable."""
    __tablename__ = "patient_merge_requests"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    primary_patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)  # the record that survives
    duplicate_patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)  # the record that gets merged away
    status = Column(String, nullable=False, default="pending_confirmation")  # "pending_confirmation" | "confirmed" | "merged" | "cancelled"
    reason = Column(Text, nullable=True)

    flagged_by = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    flagged_at = Column(DateTime, default=now_ist_naive)

    confirmation_note = Column(Text, nullable=True)  # what was confirmed on the phone call with the patient
    confirmed_by = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    confirmed_at = Column(DateTime, nullable=True)

    merged_by = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    merged_at = Column(DateTime, nullable=True)
    unmerged_profile_link_note = Column(Text, nullable=True)  # set if the duplicate's portal profile link couldn't be carried over (primary already had one) — flagged for manual follow-up