from sqlalchemy import Column, Integer, String, Float, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from app.database import Base
from app.utils.timezone import now_ist_naive


class Admission(Base):
    """One in-patient stay, from admit to discharge."""
    __tablename__ = "admissions"

    id = Column(Integer, primary_key=True, index=True)
    public_token = Column(String, unique=True, nullable=False, index=True)  # opaque ID used in URLs — never expose the raw sequential id
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    admitting_doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)

    ward = Column(String, nullable=False)
    ward_type_id = Column(Integer, ForeignKey("admission_ward_types.id"), nullable=True)  # snapshot link for accurate current-rate lookups
    bed_number = Column(String, nullable=False)
    diagnosis = Column(Text, nullable=True)

    daily_room_charge = Column(Float, nullable=False, default=0)
    professional_fee_override = Column(Float, nullable=True)  # negotiated per-admission override of the admitting doctor's default professional_fee_per_admission; null = use the doctor's default
    admission_type = Column(String, nullable=False, default="planned")  # "planned" | "emergency" | "maternity" | "transfer_in" | "day_care" — day_care skips overnight bed-night billing entirely (see _room_charge_breakdown / _build_discharge_bill)
    discharge_type = Column(String, nullable=False, default="planned")  # "planned" | "lama_dama" | "death"
    capacity_evaluation_note = Column(Text, nullable=True)  # LAMA/DAMA only — used if there's any question of impaired decision-making behind the choice
    time_of_death = Column(DateTime, nullable=True)  # death discharge only
    certifying_doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=True)  # death discharge only
    cause_of_death = Column(Text, nullable=True)  # death discharge only
    is_mlc = Column(Boolean, nullable=True)  # death discharge only — Medico-Legal Case flag: whether police/forensic involvement is required before body release

    # Structured discharge summary (NABH-standard fields). admission_date,
    # discharge_date, diagnosis (= admitting diagnosis), and
    # admitting_doctor_id already exist above and aren't duplicated here.
    # discharge_summary above is repurposed as the free-text "additional
    # notes" field alongside these — not every field NABH lists fits neatly
    # into a box, so that catch-all stays.
    discharge_order_at = Column(DateTime, nullable=True)  # when a doctor clinically decided/ordered discharge — distinct from discharge_date below, which is when the patient actually leaves (billing finalized). The gap between these two is the discharge-delay metric.
    discharge_ordered_by = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    discharging_doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=True)  # defaults to admitting_doctor_id if not explicitly set at discharge
    course_in_hospital = Column(Text, nullable=True)
    procedures_performed = Column(Text, nullable=True)
    discharge_diagnosis = Column(Text, nullable=True)
    condition_at_discharge = Column(Text, nullable=True)
    medications_on_discharge = Column(Text, nullable=True)
    follow_up_instructions = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="admitted")  # "admitted" | "discharged"

    admission_date = Column(DateTime, default=now_ist_naive, nullable=False)
    discharge_date = Column(DateTime, nullable=True)
    discharge_summary = Column(Text, nullable=True)
    discharge_invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=True)

    balance_collected = Column(Boolean, nullable=False, default=False)  # true once reception has explicitly collected the running-bill balance, as its own step before Discharge Patient becomes available
    balance_payment_method = Column(String, nullable=True)  # "cash" | "card" | "upi"
    balance_collected_at = Column(DateTime, nullable=True)
    balance_collected_by = Column(Integer, ForeignKey("doctors.id"), nullable=True)

    created_at = Column(DateTime, default=now_ist_naive)

    medication_orders = relationship("AdmissionMedicationOrder", back_populates="admission", cascade="all, delete-orphan")
    charges = relationship("AdmissionCharge", back_populates="admission", cascade="all, delete-orphan")


class AdmissionMedicationOrder(Base):
    """A prescribed medication for this stay. Billed once, upfront, at order
    time — the full ordered quantity (in strips/packs/bottles) is deducted
    from stock and charged immediately, since that's the point a real strip
    physically leaves the pharmacy/ward stock. Stopping/resuming an order
    afterwards is a clinical status flag only and never touches the bill —
    the quantity was already paid for regardless of whether every unit in
    it ends up administered."""
    __tablename__ = "admission_medication_orders"

    id = Column(Integer, primary_key=True, index=True)
    admission_id = Column(Integer, ForeignKey("admissions.id"), nullable=False)
    medicine_id = Column(Integer, ForeignKey("hospital_medicines.id"), nullable=True)
    medicine_name = Column(String, nullable=False)  # snapshot / free-text fallback

    dosage = Column(String, nullable=False, default="")  # legacy field, no longer collected in the UI — dosage/frequency are verbal/manual, not tracked in-app
    route = Column(String, nullable=False, default="Oral")
    frequency_note = Column(String, nullable=True)    # legacy, no longer collected — kept nullable so old rows still read fine

    quantity = Column(Integer, nullable=False, default=1)  # strips/bottles/units ordered — this is what's billed and stock-deducted, all upfront

    prescribed_by = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    is_active = Column(Boolean, default=True)
    sourced_outside = Column(Boolean, default=False, nullable=False)  # patient/relatives are sourcing this themselves — no stock deduction, no bill line
    dispensed_at = Column(DateTime, nullable=True)   # last time pharmacy dispensed against this order — see AdmissionMedicationDispense for the full, billable history (an order can be re-dispensed on refill)
    dispensed_by = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    manual_unit_price = Column(Float, nullable=True)  # per-strip/unit price entered at order time — only used when medicine_id is null (not in catalog), since there's no HospitalMedicine row to price from
    is_out_of_stock = Column(Boolean, default=False, nullable=False)  # flagged by pharmacy at the counter — never touches billing/stock, those already happened at order time
    substitute_for_id = Column(Integer, ForeignKey("admission_medication_orders.id"), nullable=True)  # set on the replacement order once pharmacy substitutes an out-of-stock one
    order_batch_id = Column(String, nullable=True, index=True)  # shared across every medicine submitted in the same "Advise Medicine(s)" action — lets one notification cover the whole batch instead of one per medicine
    created_at = Column(DateTime, default=now_ist_naive)

    admission = relationship("Admission", back_populates="medication_orders")
    administrations = relationship("AdmissionMedicationAdministration", back_populates="order", cascade="all, delete-orphan")
    dispenses = relationship("AdmissionMedicationDispense", back_populates="order", cascade="all, delete-orphan")


class AdmissionMedicationAdministration(Base):
    """One real, logged instance of a dose being given at the bedside — purely
    a clinical/MAR record. No stock or billing effect: the family already
    paid pharmacy and collected the physical stock (see
    AdmissionMedicationDispense) before any dose is given from it."""
    __tablename__ = "admission_medication_administrations"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("admission_medication_orders.id"), nullable=False)
    administered_by = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    administered_at = Column(DateTime, default=now_ist_naive, nullable=False)
    notes = Column(String, nullable=True)

    order = relationship("AdmissionMedicationOrder", back_populates="administrations")


class AdmissionMedicationDispense(Base):
    """One real pharmacy-counter handover against a medication order — a
    relative collects some quantity, pharmacy deducts stock and bills the
    running admission bill for it. An order can be dispensed more than once
    over a stay (refills), so this is its own history, not a single flag."""
    __tablename__ = "admission_medication_dispenses"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("admission_medication_orders.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Float, nullable=False, default=0)
    total_amount = Column(Float, nullable=False, default=0)
    dispensed_by = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    dispensed_at = Column(DateTime, default=now_ist_naive, nullable=False)

    order = relationship("AdmissionMedicationOrder", back_populates="dispenses")

class AdmissionMedicationReturn(Base):
    """A return of already-dispensed/administered units against a specific
    order — pre-discharge only. Never a silent delete: it always produces an
    offsetting AdmissionCharge (negative amount) so the bill/audit trail
    stays intact. restocked defaults False (wastage) — stock is only put
    back on explicit confirmation at the point of return."""
    __tablename__ = "admission_medication_returns"

    id = Column(Integer, primary_key=True, index=True)
    admission_id = Column(Integer, ForeignKey("admissions.id"), nullable=False)
    order_id = Column(Integer, ForeignKey("admission_medication_orders.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    restocked = Column(Boolean, default=False, nullable=False)  # deprecated — no longer drives a stock increment, see disposition
    disposition = Column(String, nullable=True)  # "returned_to_supplier" | "sent_to_disposal" — nullable only for pre-existing rows, required going forward
    note = Column(Text, nullable=True)
    credit_charge_id = Column(Integer, ForeignKey("admission_charges.id"), nullable=True)
    returned_by = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    returned_at = Column(DateTime, default=now_ist_naive, nullable=False)


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