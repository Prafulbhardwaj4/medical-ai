from sqlalchemy import Column, Integer, String, Boolean, DateTime, Date, Text, ForeignKey
from app.database import Base
from app.utils.timezone import now_ist_naive

class RadiologyFormF(Base):
    """Statutory record under the PCPNDT Act, 1994 (Form F — see proviso to
    Section 4(3), rule 9(4) and rule 10(1A)). MedScribe only performs
    non-invasive imaging, so this covers Section A (identification, common
    to all procedures) and Section B (non-invasive procedures) of the real
    form — Section C (invasive: amniocentesis, CVS, cordocentesis, etc.)
    doesn't apply here and isn't modeled.

    Fields are split by when they're actually knowable: order-time fields
    are required before the order can be finalized (item 7); result-in-brief
    /conveyed-to/MTP-indication only exist once the scan itself happens, so
    they're nullable here and get filled in during reporting (a later piece)."""
    __tablename__ = "radiology_form_f"

    id = Column(Integer, primary_key=True, index=True)
    radiology_order_id = Column(Integer, ForeignKey("radiology_orders.id"), nullable=False, unique=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)

    # --- Section A (fields 3-8 of the real form; fields 1-2 come from the
    # hospital record itself, not stored per-order) ---
    patient_age = Column(Integer, nullable=True)
    total_living_children = Column(Integer, nullable=False, default=0)
    living_sons_ages = Column(Text, nullable=True)       # free text: e.g. "6 years, 3 months"
    living_daughters_ages = Column(Text, nullable=True)
    guardian_name = Column(String, nullable=False)         # Husband's/Wife's/Father's/Mother's name
    patient_address_contact = Column(Text, nullable=False)
    referral_type = Column(String, nullable=False)          # "referred" | "self_referral"
    referring_doctor_details = Column(Text, nullable=False)  # full name+address of referring doctor, OR the self-referral note
    lmp_or_gestational_weeks = Column(String, nullable=False)

    # --- Section B (fields 9-13; field 11 "procedure carried out" is
    # implicitly always "Ultrasound" here, so it isn't a stored field) ---
    performing_doctor_name = Column(String, nullable=False)
    indication_checklist = Column(Text, nullable=True)  # JSON list of the standard indication codes ticked (i–xxiii on the real form)
    declaration_obtained_date = Column(Date, nullable=True)  # date the pregnant woman's declaration was obtained

    # --- Section D (declaration of the doctor conducting the scan) ---
    non_sex_determination_declared = Column(Boolean, nullable=False, default=False)  # doctor's declaration of not detecting/disclosing fetal sex — must be True, this is the whole legal point (item 7)

    created_at = Column(DateTime, default=now_ist_naive)
    created_by = Column(Integer, ForeignKey("doctors.id"), nullable=True)

    # --- Filled later, once the scan is actually performed (field 13-16) ---
    procedure_date = Column(DateTime, nullable=True)
    result_brief = Column(Text, nullable=True)
    conveyed_to = Column(String, nullable=True)
    mtp_indication = Column(Text, nullable=True)  # only if an abnormality was detected — optional even at completion
    completed_at = Column(DateTime, nullable=True)
    completed_by = Column(Integer, ForeignKey("doctors.id"), nullable=True)