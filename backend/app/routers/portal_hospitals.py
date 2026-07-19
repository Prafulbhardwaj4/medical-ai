from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.hospital import Hospital
from app.schemas.portal import HospitalOut

router = APIRouter(prefix="/portal/hospitals", tags=["portal-hospitals"])


@router.get("", response_model=list[HospitalOut])
def list_hospitals(city: Optional[str] = Query(None), db: Session = Depends(get_db)):
    q = db.query(Hospital).filter(Hospital.is_active == True)  # noqa: E712
    if city:
        q = q.filter(Hospital.city.ilike(f"%{city}%"))
    return q.all()