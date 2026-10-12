from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, event, func
from sqlalchemy.orm import Session as _OrmSession
from app.database import Base
from app.utils.timezone import now_ist_naive


class Refund(Base):
    """Refund record — cash/QR refunds are recorded complete immediately;
    online/portal refunds settle automatically through the gateway (48-72h)
    and are tracked as 'pending' until confirmed. Covers every refund
    scenario (appointment, pharmacy, IPD deposit balance, TPA overpayment)
    uniformly, per Receptionist Flow §8."""
    __tablename__ = "refunds"

    id = Column(Integer, primary_key=True, index=True)
    # Nullable: a system-generated refund (patient self-cancel, auto-decline)
    # has no staff actor and may predate the patient ever getting a real
    # Patient row created by reception.
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    source_type = Column(String, nullable=False)  # appointment | pharmacy | ipd_deposit | opd_charge | other
    source_id = Column(Integer, nullable=True)
    amount = Column(Float, nullable=False)
    channel = Column(String, nullable=False)  # cash | card | upi | online
    status = Column(String, nullable=False, default="completed")  # pending (owed, not paid yet) | completed (paid out by reception) | dismissed (reception closed it without paying)
    reason = Column(String, nullable=True)
    processed_by = Column(Integer, ForeignKey("doctors.id"), nullable=True)  # null = system-generated, no staff actor
    processed_at = Column(DateTime, default=now_ist_naive)  # when the refund was raised
    collected_at = Column(DateTime, nullable=True)  # when the ORIGINAL money came in — refunds net against this day in Collected/revenue history (falls back to processed_at when empty)
    settled_at = Column(DateTime, nullable=True)  # when reception actually paid it out (or dismissed it)
    settled_by = Column(Integer, ForeignKey("doctors.id"), nullable=True)


def _original_collected_at(session, refund):
    st, sid = refund.source_type, refund.source_id
    if not sid:
        return None
    try:
        if st == "appointment":
            from app.models.portal import Appointment
            row = session.query(Appointment.paid_at).filter(Appointment.id == sid).first()
        elif st == "test":
            from app.models.test_order import TestOrder
            row = session.query(TestOrder.paid_at).filter(TestOrder.id == sid).first()
        elif st == "pharmacy":
            from app.models.medicine_order import MedicineOrder
            row = session.query(MedicineOrder.paid_at).filter(MedicineOrder.id == sid).first()
        elif st == "opd_charge":
            from app.models.opd_charge import OpdCharge
            row = session.query(OpdCharge.paid_at).filter(OpdCharge.id == sid).first()
        elif st == "ipd_deposit":
            from app.models.admission_deposit import AdmissionDeposit
            row = session.query(func.max(AdmissionDeposit.collected_at)).filter(AdmissionDeposit.admission_id == sid).first()
        else:
            return None
        return row[0] if row else None
    except Exception:
        return None


@event.listens_for(_OrmSession, "before_flush")
def _stamp_refund_collected_at(session, flush_context, instances):
    # Every place that creates a Refund gets its original-collection date
    # stamped here, so none of them need to remember to set it.
    for obj in list(session.new):
        if isinstance(obj, Refund) and obj.collected_at is None:
            with session.no_autoflush:
                obj.collected_at = _original_collected_at(session, obj)