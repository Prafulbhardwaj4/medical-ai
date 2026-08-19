from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text
from app.database import Base
from app.utils.timezone import now_ist_naive

class TestOrder(Base):
    __tablename__ = "test_orders"

    id = Column(Integer, primary_key=True, index=True)
    consultation_id = Column(Integer, ForeignKey("consultations.id"), nullable=True)
    admission_id = Column(Integer, ForeignKey("admissions.id"), nullable=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    test_id = Column(Integer, ForeignKey("test_catalog_items.id"), nullable=True)
    test_name = Column(String, nullable=False)
    price = Column(Float, nullable=False, default=0)
    # Tests submitted together in one "Order Test(s)" action share the same
    # batch id, so the patient portal reports them as one report as results
    # trickle in — tests ordered separately (different actions/days) each
    # get their own batch id, even if same test name. Null = legacy order
    # from before this existed; treated as its own single-test report.
    order_batch_id = Column(String, nullable=True, index=True)
    included = Column(Boolean, default=True, nullable=False)
    status = Column(String, nullable=False, default="payment_pending")
    # payment_pending -> paid -> sample_collected -> processing -> result_entered -> verified_released

    priority = Column(String, nullable=False, default="routine")  # "routine" | "urgent" | "stat" — drives TAT clock + queue ordering (Phase 3/5)
    clinical_indication = Column(Text, nullable=True)  # e.g. "suspected DKA" — visible to the verifying pathologist (Phase 3 item 7)
    fasting_confirmed = Column(Boolean, nullable=True)  # null = not applicable (test isn't fasting-required), True/False = collector's confirmation at draw (Phase 4 item 12)
    drawn_from_iv_line = Column(Boolean, default=False, nullable=False)  # affects interpretation on certain analytes (Phase 4 item 13)

    # Sample rejection & redraw (Phase 4 item 14).
    rejection_reason = Column(String, nullable=True)   # one of the structured reasons — see REJECTION_REASONS in lab.py
    rejected_at = Column(DateTime, nullable=True)
    rejected_by = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    redraw_of_order_id = Column(Integer, ForeignKey("test_orders.id"), nullable=True)  # set on the fresh redraw clone, points back to the rejected original
    sample_condition_caveat = Column(Text, nullable=True)  # irreplaceable-sample path — annotates the report instead of hard-rejecting

    hiv_counselling_completed = Column(Boolean, default=False, nullable=False)  # manual/offline process — this just tracks that it happened (Phase 6 item 21)

    # MLC (medico-legal case) sample flag — distinct from Admission.is_mlc,
    # which is death-discharge/body-release only. This is about live-patient
    # forensic samples (assault, RTA, poisoning, sexual assault) needing a
    # chain-of-custody trail (Phase 6 item 22) — see MlcChainOfCustody.
    is_mlc_sample = Column(Boolean, default=False, nullable=False)
    mlc_case_type = Column(String, nullable=True)  # "assault" | "rta" | "poisoning" | "sexual_assault" | "other"
    mlc_reference_number = Column(String, nullable=True)  # police FIR / case reference, if known

    is_idsp_notifiable = Column(Boolean, default=False, nullable=False)  # pathologist ticks this at verification if the result is a confirmed notifiable finding (Phase 6 item 23)

    # Accession/ULR numbering (Phase 5 item 15) — assigned the moment the
    # sample is logged as received by the lab (the "processing" transition).
    # The TAT clock (Phase 5 item 17) starts from accessioned_at, not from
    # when the doctor placed the order.
    accession_number = Column(String, nullable=True, index=True)
    accessioned_at = Column(DateTime, nullable=True)

    paid_at = Column(DateTime, nullable=True)
    payment_method = Column(String, nullable=True)  # "cash" | "card" | "upi"
    queued_at = Column(DateTime, nullable=True)  # set whenever this order enters a day's active queue (payment or requeue)
    collected_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)  # now: when the raw result was entered ("result_entered"), not final release
    completed_by = Column(Integer, ForeignKey("doctors.id"), nullable=True)  # now: who entered the raw result
    result_data = Column(Text, nullable=True)  # JSON: {param_name: value}
    created_at = Column(DateTime, default=now_ist_naive)

    # Verification/release gate (Phase 2) — status flow is now
    # payment_pending -> paid -> sample_collected -> processing ->
    # result_entered -> verified_released. No result is visible to the
    # doctor or patient portal until verified_released.
    verified_by = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    self_verified_sole_staff = Column(Boolean, default=False, nullable=False)  # True when the same person entered and verified — only ever allowed when they're the only active lab-role account at the hospital; flagged so it's traceable, never silent
    verified_at = Column(DateTime, nullable=True)
    # Critical-value flagging (Phase 1, NABL-mandatory).
    is_critical = Column(Boolean, default=False, nullable=False)
    critical_note = Column(Text, nullable=True)          # human-readable breach description(s)
    critical_detected_at = Column(DateTime, nullable=True)   # when this specific breach was first flagged — reset if it clears then re-breaches
    critical_ack_at = Column(DateTime, nullable=True)        # when the ordering doctor acknowledged the alert
    critical_escalated_at = Column(DateTime, nullable=True)  # set once escalated past the doctor (Phase 1 item 3)
    sample_overdue_notified_at = Column(DateTime, nullable=True)  # set once lab staff have been pinged that an admitted patient's sample is 2+ hours uncollected — prevents re-notifying on every sweep