from pydantic import BaseModel
from typing import Optional


class RefundIn(BaseModel):
    patient_id: int
    source_type: str  # "appointment" | "pharmacy" | "ipd_deposit" | "opd_charge" | "tpa" | "other"
    source_id: Optional[int] = None
    amount: float
    channel: str  # "cash" | "card" | "upi" | "online"
    reason: Optional[str] = None
    invoice_id: Optional[int] = None  # link to the invoice this refund corrects — auto-generates a credit note


class CreditDebitNoteIn(BaseModel):
    note_type: str  # "credit" | "debit"
    amount: float
    reason: str


class WaiverIn(BaseModel):
    checkin_id: Optional[int] = None  # OPD visit — set exactly one of these two
    admission_token: Optional[str] = None  # IPD admission's public_token, same identifier the frontend already uses in /admissions/{id} URLs
    amount: float
    reason: str


class DayEndCloseIn(BaseModel):
    date: Optional[str] = None  # YYYY-MM-DD, defaults to today
    counted_cash: float
    counted_card: float
    counted_upi: float
    notes: Optional[str] = None