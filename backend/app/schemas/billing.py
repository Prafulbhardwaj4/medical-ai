from pydantic import BaseModel
from typing import Optional


class RefundIn(BaseModel):
    patient_id: int
    source_type: str  # "appointment" | "pharmacy" | "ipd_deposit" | "opd_charge" | "tpa" | "other"
    source_id: Optional[int] = None
    amount: float
    channel: str  # "cash" | "card" | "upi" | "online"
    reason: Optional[str] = None


class DayEndCloseIn(BaseModel):
    date: Optional[str] = None  # YYYY-MM-DD, defaults to today
    counted_cash: float
    counted_card: float
    counted_upi: float
    notes: Optional[str] = None