"""Server-side tier enforcement. The frontend lock (upgrade-gate.js) is UX only;
this is the real gate. Same rule as referrals._require_scale_or_above, packaged
as a FastAPI dependency so a whole router can be gated in one line:

    router = APIRouter(..., dependencies=[Depends(require_tier("growth", "IPD / Admissions"))])
"""
from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.doctor import Doctor
from app.models.hospital import Hospital
from app.utils.auth import get_current_doctor

TIER_ORDER = {"foundation": 0, "growth": 1, "scale": 2, "enterprise": 3}


def tier_at_least(tier: str, minimum: str) -> bool:
    # Unknown/garbage tier values fail CLOSED (treated as foundation).
    return TIER_ORDER.get(tier, 0) >= TIER_ORDER[minimum]


def hospital_has_tier(db: Session, hospital_id: int, minimum: str) -> bool:
    """Non-raising check for places that must silently skip a feature instead of 403."""
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    return bool(hospital) and tier_at_least(hospital.tier, minimum)


def require_tier(minimum: str, feature: str):
    def _dependency(
        current_doctor: Doctor = Depends(get_current_doctor),
        db: Session = Depends(get_db),
    ):
        hospital = db.query(Hospital).filter(Hospital.id == current_doctor.hospital_id).first()
        if not hospital or not tier_at_least(hospital.tier, minimum):
            raise HTTPException(
                status_code=403,
                detail=f"{feature} is not included in your plan. It requires the {minimum.title()} plan or above.",
            )
    return _dependency