from sqlalchemy import Column, Integer, String, Float, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from app.database import Base
from app.utils.timezone import now_ist_naive


class Admission(Base):
    """One in-patient stay, from admit to discharge."""
    __tablename__ = "admissions"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    admitting_doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)

    ward = Column(String, nullable=False)
    bed_number = Column(String, nullable=False)
    diagnosis = Column(Text, nullable=True)

    daily_room_charge = Column(Float, nullable=False, default=0)
    status = Column(String, nullable=False, default="admitted")  # "admitted" | "discharged"

    admission_date = Column(DateTime, default=now_ist_naive, nullable=False)
    discharge_date = Column(DateTime, nullable=True)
    discharge_summary = Column(Text, nullable=True)
    discharge_invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=True)

    created_at = Column(DateTime, default=now_ist_naive)

    medication_orders = relationship("AdmissionMedicationOrder", back_populates="admission", cascade="all, delete-orphan")
    charges = relationship("AdmissionCharge", back_populates="admission", cascade="all, delete-orphan")


class AdmissionMedicationOrder(Base):
    """A prescribed medication for this stay — the MAR logs actual doses
    given against this order."""
    __tablename__ = "admission_medication_orders"

    id = Column(Integer, primary_key=True, index=True)
    admission_id = Column(Integer, ForeignKey("admissions.id"), nullable=False)
    medicine_id = Column(Integer, ForeignKey("hospital_medicines.id"), nullable=True)
    medicine_name = Column(String, nullable=False)  # snapshot / free-text fallback

    dosage = Column(String, nullable=False)          # e.g. "500mg"
    route = Column(String, nullable=False, default="Oral")
    frequency_note = Column(String, nullable=True)    # human-readable, e.g. "Every 8 hours"

    prescribed_by = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=now_ist_naive)

    admission = relationship("Admission", back_populates="medication_orders")
    administrations = relationship("AdmissionMedicationAdministration", back_populates="order", cascade="all, delete-orphan")


class AdmissionMedicationAdministration(Base):
    """One real, logged instance of a dose being given."""
    __tablename__ = "admission_medication_administrations"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("admission_medication_orders.id"), nullable=False)
    administered_by = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    administered_at = Column(DateTime, default=now_ist_naive, nullable=False)
    notes = Column(String, nullable=True)

    order = relationship("AdmissionMedicationOrder", back_populates="administrations")


class AdmissionCharge(Base):
    """A discrete billable line item added during the stay (medicine given,
    test ordered, procedure, misc). Room charges are NOT stored here — they're
    calculated on demand from days admitted × daily_room_charge."""
    __tablename__ = "admission_charges"

    id = Column(Integer, primary_key=True, index=True)
    admission_id = Column(Integer, ForeignKey("admissions.id"), nullable=False)
    charge_type = Column(String, nullable=False)  # "medicine" | "test" | "procedure" | "other"
    description = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    quantity = Column(Integer, nullable=False, default=1)
    added_by = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    charged_at = Column(DateTime, default=now_ist_naive)

    admission = relationship("Admission", back_populates="charges")