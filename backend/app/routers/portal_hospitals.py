from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException, Request
from app.utils.rate_limit import limiter
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.hospital import Hospital
from app.models.doctor import Doctor, UserRole
from app.models.admission import Admission
from app.models.admission_ward_type import AdmissionWardType
from app.models.hospital_lead import HospitalLead
from app.models.portal import PatientAccount
from app.schemas.portal import HospitalOut
from app.utils.portal_auth import get_current_patient_account
from pydantic import BaseModel

router = APIRouter(prefix="/portal/hospitals", tags=["portal-hospitals"])


class HospitalLeadIn(BaseModel):
    state: str
    city: str
    hospital_name: str
    location: str | None = None
    note: str | None = None


@router.get("/states")
@limiter.limit("60/minute")
def list_states(request: Request, db: Session = Depends(get_db)):
    rows = db.query(Hospital.state).filter(Hospital.is_active == True, Hospital.state.isnot(None)).distinct().all()  # noqa: E712
    return sorted({r[0] for r in rows if r[0]})


@router.get("/cities")
@limiter.limit("60/minute")
def list_cities(request: Request, state: Optional[str] = Query(None), db: Session = Depends(get_db)):
    q = db.query(Hospital.city).filter(Hospital.is_active == True, Hospital.city.isnot(None))  # noqa: E712
    if state:
        q = q.filter(Hospital.state == state)
    rows = q.distinct().all()
    return sorted({r[0] for r in rows if r[0]})


@router.get("", response_model=list[HospitalOut])
@limiter.limit("60/minute")
def list_hospitals(request: Request, city: Optional[str] = Query(None), state: Optional[str] = Query(None), db: Session = Depends(get_db)):
    q = db.query(Hospital).filter(Hospital.is_active == True)  # noqa: E712
    if state:
        q = q.filter(Hospital.state == state)
    if city:
        q = q.filter(Hospital.city.ilike(f"%{city}%"))
    return q.order_by(Hospital.name).all()


@router.post("/lead")
@limiter.limit("5/hour")
def submit_hospital_lead(
    request: Request,
    body: HospitalLeadIn,
    db: Session = Depends(get_db),
    account: PatientAccount = Depends(get_current_patient_account),
):
    if not body.hospital_name.strip():
        raise HTTPException(status_code=400, detail="Hospital name is required")
    for _v, _max in ((body.state, 80), (body.city, 80), (body.hospital_name, 150),
                     (body.location or "", 200), (body.note or "", 500)):
        if len(_v) > _max:
            raise HTTPException(status_code=400, detail="One of the fields is too long")
    if not body.state.strip() or not body.city.strip():
        raise HTTPException(status_code=400, detail="State and city are required")

    lead = HospitalLead(
        patient_account_id=account.id,
        contact_phone=account.phone,
        state=body.state.strip(),
        city=body.city.strip(),
        hospital_name=body.hospital_name.strip(),
        location=(body.location or "").strip() or None,
        note=(body.note or "").strip() or None,
    )
    db.add(lead)
    db.commit()
    return {"submitted": True}


@router.get("/{hospital_id}/doctors")
@limiter.limit("60/minute")
def list_hospital_doctors(request: Request, hospital_id: int, db: Session = Depends(get_db)):
    if not db.query(Hospital.id).filter(Hospital.id == hospital_id, Hospital.is_active == True).first():  # noqa: E712
        raise HTTPException(status_code=404, detail="Hospital not found")
    doctors = db.query(Doctor).filter(
        Doctor.hospital_id == hospital_id,
        Doctor.role == UserRole.doctor,
        Doctor.is_active == True  # noqa: E712
    ).all()
    return [
        {
            "id": d.id, "name": f"{d.title} {d.name}", "specialization": d.specialization,
            "room_number": d.room_number, "consultation_fee": d.consultation_fee,
            "registration_number": d.registration_number,
        }
        for d in doctors
    ]


@router.get("/{hospital_id}/doctors/{doctor_id}/slots")
@limiter.limit("60/minute")
def list_doctor_slots(request: Request, hospital_id: int, doctor_id: int, date: str, db: Session = Depends(get_db)):
    from datetime import datetime as dt
    from app.models.doctor_slot import DoctorSlot
    from app.models.doctor_availability import DoctorUnavailability
    from app.utils.timezone import now_ist_naive

    if not db.query(Hospital.id).filter(Hospital.id == hospital_id, Hospital.is_active == True).first():  # noqa: E712
        raise HTTPException(status_code=404, detail="Hospital not found")
    try:
        slot_date = dt.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format, expected YYYY-MM-DD")

    is_unavailable = db.query(DoctorUnavailability).filter(
        DoctorUnavailability.doctor_id == doctor_id, DoctorUnavailability.date == slot_date
    ).first() is not None
    if is_unavailable:
        return {"morning": [], "afternoon": [], "evening": [], "doctor_unavailable": True}

    slots = db.query(DoctorSlot).filter(
        DoctorSlot.hospital_id == hospital_id, DoctorSlot.doctor_id == doctor_id,
        DoctorSlot.slot_date == slot_date
    ).order_by(DoctorSlot.slot_time).all()

    now = now_ist_naive()
    is_today = slot_date == now.date()

    def _parse_slot_time(time_str):
        for fmt in ("%H:%M", "%I:%M %p"):
            try:
                return dt.strptime(time_str.strip(), fmt).time()
            except ValueError:
                continue
        return None  # unrecognised format — skip the past-time check rather than wrongly hide it

    if is_today:
        filtered = []
        for s in slots:
            parsed = _parse_slot_time(s.slot_time)
            if parsed is not None and parsed <= now.time():
                continue  # already passed today — never bookable
            filtered.append(s)
        slots = filtered

    def _level(s):
        if s.booked_count >= s.capacity:
            return "red"
        ratio = s.booked_count / s.capacity if s.capacity else 0
        return "yellow" if ratio >= 0.5 else "green"

    grouped = {"morning": [], "afternoon": [], "evening": []}
    for s in slots:
        grouped[s.period].append({
            "id": s.id, "time": s.slot_time,
            "capacity": s.capacity, "booked_count": s.booked_count,
            "level": _level(s), "full": s.booked_count >= s.capacity,
        })
    return grouped


@router.get("/{hospital_id}/bed-availability")
@limiter.limit("60/minute")
def bed_availability(request: Request, hospital_id: int, db: Session = Depends(get_db)):
    """Returns the actual vacant bed count, shown by default on the booking flow
    (item 49) — no longer coarsened to available/full/unknown only."""
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id, Hospital.is_active == True).first()  # noqa: E712
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")
    if hospital.tier == "foundation":
        # Foundation hospitals never have ward/admissions access at all — this
        # isn't a "not configured yet" gap, the feature just doesn't apply to
        # this tier, so the frontend hides the row entirely rather than
        # showing a message that implies something's missing.
        return {"status": "not_applicable", "vacant_beds": None, "total_beds": 0}

    ward_types = db.query(AdmissionWardType).filter(AdmissionWardType.hospital_id == hospital_id).all()
    total_beds = sum(w.total_beds for w in ward_types)
    if total_beds == 0:
        return {"status": "unknown", "vacant_beds": None, "total_beds": 0}

    occupied = db.query(Admission).filter(
        Admission.hospital_id == hospital_id, Admission.status == "admitted"
    ).count()
    vacant = max(total_beds - occupied, 0)

    status = "full" if vacant == 0 else "available"
    return {"status": status, "vacant_beds": vacant, "total_beds": total_beds}


@router.get("/{hospital_id}", response_model=HospitalOut)
@limiter.limit("60/minute")
def get_hospital(request: Request, hospital_id: int, db: Session = Depends(get_db)):
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id, Hospital.is_active == True).first()  # noqa: E712
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")
    return hospital