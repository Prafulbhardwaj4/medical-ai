from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey
from app.database import Base
from app.utils.timezone import now_ist_naive


class CrossHospitalReferral(Base):
    """One hop of a cross-hospital emergency referral. Deliberately NOT
    related to AdmissionReferral/OpdReferral (those are same-hospital
    doctor-facing referrals, unrelated concept). Every hop is a
    self-contained, functionally independent record — clinical data is
    snapshotted at creation time rather than linked live, since the
    receiving hospital's session has no auth to query another hospital's
    patient/test/vitals rows. `chain_id` groups hops of the same patient
    journey together purely for the Records view; it carries no
    functional coupling between hops."""
    __tablename__ = "cross_hospital_referrals"

    id = Column(Integer, primary_key=True, index=True)
    chain_id = Column(Integer, nullable=False, index=True)  # = own id on the first hop of a journey; propagated to every later hop

    from_hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    to_hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)

    # Null only for initiation_type="reject_forward", where the forwarding
    # hospital never admitted the patient and has no admission of its own.
    source_admission_id = Column(Integer, ForeignKey("admissions.id"), nullable=True)
    origin_patient_id = Column(Integer, ForeignKey("patients.id"), nullable=True)  # the from_hospital's local patient row — patient portal reads rejection notes off this

    initiation_type = Column(String, nullable=False, default="referral")  # "referral" | "reject_forward"
    initiated_by = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    superseded_referral_id = Column(Integer, ForeignKey("cross_hospital_referrals.id"), nullable=True)  # the prior hop this one supersedes (re-refer after reject, or reject-and-forward)

    # --- Snapshot of the referred patient's clinical record, captured once at creation ---
    patient_name = Column(String, nullable=False)
    patient_age = Column(Integer, nullable=True)
    patient_gender = Column(String, nullable=True)
    clinical_note = Column(Text, nullable=False)  # mandatory diagnosis/reason/urgency note from the Refer modal
    diagnosis_snapshot = Column(Text, nullable=True)
    vitals_snapshot_json = Column(Text, nullable=True)
    medicines_snapshot_json = Column(Text, nullable=True)
    tests_snapshot_json = Column(Text, nullable=True)  # shaped like /lab/patient-reports/{id}'s response so the Reports modal can render it directly
    progress_notes_snapshot_json = Column(Text, nullable=True)

    status = Column(String, nullable=False, default="pending")  # pending | rejected | departed | admitted | expired
    acknowledged_at = Column(DateTime, nullable=True)  # Foundation-tier "Acknowledge" only — informational, doesn't change status

    rejected_at = Column(DateTime, nullable=True)
    rejected_by = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    rejection_note = Column(Text, nullable=True)  # mandatory on reject — visible on the patient's own portal at from_hospital

    departed_at = Column(DateTime, nullable=True)  # set the moment the source admission is discharged as a transfer-out

    admitted_at = Column(DateTime, nullable=True)
    admitted_admission_id = Column(Integer, ForeignKey("admissions.id"), nullable=True)  # the new admission created at to_hospital via the Emergency Intake handoff

    expires_at = Column(DateTime, nullable=False)  # created_at + 24h; scheduler flips unactioned referrals to "expired"
    created_at = Column(DateTime, default=now_ist_naive)