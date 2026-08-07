from sqlalchemy import Column, Integer, String, Date, DateTime, ForeignKey, Text, Float, Boolean
from app.database import Base
from app.utils.timezone import now_ist_naive

class Checkin(Base):
    __tablename__ = "checkins"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    token_number = Column(String, unique=True, nullable=False, index=True)  # DB-level unique constraint — already the real hard backstop against the generate_token_number race (see checkin_patient / convert_appointment_to_checkin, which now retry on the IntegrityError this raises). Global uniqueness rather than a (hospital_id, visit_date, token_number) composite is equivalent here since the token string itself already embeds the hospital prefix and date.
    issue_category = Column(String, nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    created_by = Column(Integer, ForeignKey("doctors.id"), nullable=True)  # null = system-generated (online booking handoff), no staff actor
    visit_date = Column(Date, nullable=False, index=True)
    created_at = Column(DateTime, default=now_ist_naive)

    source = Column(String, nullable=False, default="walk_in")  # "walk_in" | "online" — see Phase 2 item 5
    portal_appointment_id = Column(Integer, ForeignKey("portal_appointments.id"), nullable=True)
    booked_time = Column(DateTime, nullable=True)  # the online-booked slot time, for dashboards to show "booked for HH:MM"
    queue_priority_time = Column(DateTime, nullable=True)  # if set, queue sort uses this instead of created_at (Phase 2 item 7)

    nurse_id = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    vitals_status = Column(String, default="none", nullable=False)  # none / pending / sent_back / done
    vitals_data = Column(Text, nullable=True)
    vitals_recorded_by = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    vitals_recorded_at = Column(DateTime, nullable=True)
    vitals_recheck_request = Column(Text, nullable=True)  # what the doctor asked to be rechecked, while vitals_status == "sent_back"

    post_consult_status = Column(String, default="none", nullable=False)
    post_consult_note = Column(Text, nullable=True)
    post_consult_data = Column(Text, nullable=True)
    post_consult_recorded_by = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    post_consult_recorded_at = Column(DateTime, nullable=True)

    consultation_fee = Column(Float, nullable=True)
    test_fee = Column(Float, nullable=True)
    is_paid = Column(Boolean, default=False, nullable=False)
    paid_at = Column(DateTime, nullable=True)

    is_finalized = Column(Boolean, default=False, nullable=False)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=True)
    payment_method = Column(String, nullable=True)  # "cash" | "card" | "upi" — how the consultation fee was collected
    is_emergency = Column(Boolean, default=False, nullable=False)  # Emergency Intake — skipped payment/registration gate

    is_returned = Column(Boolean, default=False, nullable=False)  # Same-Day Return Queue — sent back to doctor without new token/payment
    returned_at = Column(DateTime, nullable=True)

    emergency_status = Column(String, nullable=True)  # "holding" = in the Emergency Ward, not yet in the doctor's queue; "released" = sent to queue; null = not an emergency
    emergency_reason = Column(Text, nullable=True)  # what reception typed/picked, shown to the assigned doctor
    emergency_destination = Column(String, nullable=True)  # "ward" | "cabin" — where reception sent the patient

    visit_group_id = Column(Integer, nullable=True)  # set to the primary checkin's own id when a visit covers 2+ doctors in one go (item 7) — links siblings for combined billing/display, never used to change queue/consult behavior, each doctor's queue entry works exactly like any normal checkin