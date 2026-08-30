from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float, Text
from app.database import Base
from app.utils.timezone import now_ist_naive

class Hospital(Base):
    __tablename__ = "hospitals"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    address = Column(String, nullable=True)
    city = Column(String, nullable=True)
    state = Column(String, nullable=True)
    hospital_code = Column(String, unique=True, index=True, nullable=False)
    hospital_type = Column(String, default="private", nullable=False)
    billing_enabled = Column(Boolean, default=True, nullable=False)
    default_consultation_fee = Column(Float, nullable=True)
    gstin = Column(String, nullable=True)  # optional — hospital adds this later if/when they need GST on invoices
    consultation_gst_percent = Column(Float, nullable=True)  # blank = no GST on consultation fee
    test_gst_percent = Column(Float, nullable=True)  # blank = no GST on lab tests
    room_gst_percent = Column(Float, nullable=True)  # blank = no GST on the taxable-excess portion of room charges
    charge_gst_percent = Column(Float, nullable=True)  # blank = no GST on ad-hoc OPD/IPD charges (consumable/procedure/other)
    room_gst_threshold_per_day = Column(Float, nullable=False, default=5000.0)  # only the daily room rate above this is taxable
    waiver_auto_approve_cap = Column(Float, nullable=True)  # ₹ — waivers at or below this OR the percent cap below can be applied directly, no approval needed
    waiver_auto_approve_percent = Column(Float, nullable=True)  # % of the current bill — same auto-approve logic as the cap, whichever is looser wins
    hsn_consultation = Column(String, nullable=True)  # SAC code for consultation line items — GST-mandatory per invoice line
    hsn_room = Column(String, nullable=True)  # SAC code for room/facility charges
    hsn_test = Column(String, nullable=True)  # SAC code for diagnostic tests
    hsn_charge = Column(String, nullable=True)  # SAC code for procedures/consumables/other/professional-fee charges (same catch-all bucket charge_gst_percent already uses)
    default_service_hsn_sac = Column(String, nullable=True, default="999311")  # SAC code applied to service-type invoice lines (consultation, room, professional fee, tests, procedures) — medicines use their own catalog hsn_code instead
    phone = Column(String, nullable=True)  # optional — shown on PDF letterheads if set
    logo_base64 = Column(Text, nullable=True)  # optional — full data URI; stored in-DB since Render's disk is ephemeral
    tier = Column(String, nullable=False, default="growth")  # "foundation" | "growth" | "scale" | "enterprise" — manually set by super admin, gates feature access
    pcpndt_registration_number = Column(String, nullable=True)  # Registration No. under PC&PNDT Act, 1994 — required on every Form F (item 2 of the statutory form); only relevant to hospitals doing ultrasound

    # --- Billing cycle / AI Scribe usage ---
    billing_cycle_start = Column(DateTime, nullable=True)  # anchor date for the current cycle — set on the hospital's first login, then re-anchored on renewal (rolls +1mo) or reactivation (resets to reactivation date)
    ai_scribe_consultations_used = Column(Integer, default=0, nullable=False)  # resets to 0 every cycle roll (renewal or reactivation)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=now_ist_naive)