from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.doctor import Doctor
from app.models.suggestion import Suggestion
from app.schemas.suggestion import SuggestionIn, SuggestionStatusIn, VALID_SUGGESTION_STATUSES
from app.utils.auth import get_current_doctor

router = APIRouter(prefix="/suggestions", tags=["suggestions"])


@router.post("", status_code=201)
def create_suggestion(
    body: SuggestionIn,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Any staff member (any role, including admin) can submit a suggestion.
    hospital_name/submitted_by_name/submitted_by_role are snapshotted at
    submission time so the record stays correct even if the person's name,
    role, or hospital's name later changes."""
    if not body.message or not body.message.strip():
        raise HTTPException(status_code=400, detail="Please enter a suggestion")

    from app.models.hospital import Hospital
    hospital = db.query(Hospital).filter(Hospital.id == current_doctor.hospital_id).first()

    suggestion = Suggestion(
        hospital_id=current_doctor.hospital_id,
        hospital_name=hospital.name if hospital else "—",
        submitted_by=current_doctor.id,
        submitted_by_name=current_doctor.name,
        submitted_by_role=current_doctor.role.value,
        message=body.message.strip(),
        status="sent",
    )
    db.add(suggestion)
    db.commit()
    db.refresh(suggestion)
    return {"message": "Suggestion sent", "id": suggestion.id, "status": suggestion.status}


@router.get("/mine")
def list_my_suggestions(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Staff-facing, read-only — status only, they never get a way to set it."""
    rows = db.query(Suggestion).filter(
        Suggestion.submitted_by == current_doctor.id
    ).order_by(Suggestion.created_at.desc()).all()
    return [
        {
            "id": s.id,
            "message": s.message,
            "status": s.status,
            "rejection_reason": s.rejection_reason,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        }
        for s in rows
    ]


@router.get("")
def list_all_suggestions(
    status: str = None,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Super Admin's dashboard tab — every suggestion across every hospital,
    optionally filtered by status."""
    if current_doctor.role.value != "super_admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    query = db.query(Suggestion)
    if status:
        if status not in VALID_SUGGESTION_STATUSES:
            raise HTTPException(status_code=400, detail=f"status must be one of {sorted(VALID_SUGGESTION_STATUSES)}")
        query = query.filter(Suggestion.status == status)

    rows = query.order_by(Suggestion.created_at.desc()).all()
    return [
        {
            "id": s.id,
            "hospital_name": s.hospital_name,
            "submitted_by_name": s.submitted_by_name,
            "submitted_by_role": s.submitted_by_role,
            "message": s.message,
            "status": s.status,
            "rejection_reason": s.rejection_reason,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        }
        for s in rows
    ]


@router.patch("/{suggestion_id}/status")
def update_suggestion_status(
    suggestion_id: int,
    body: SuggestionStatusIn,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Super Admin only — staff never set status themselves."""
    if current_doctor.role.value != "super_admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    if body.status not in VALID_SUGGESTION_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {sorted(VALID_SUGGESTION_STATUSES)}")
    if body.status == "rejected" and not (body.rejection_reason and body.rejection_reason.strip()):
        raise HTTPException(status_code=400, detail="rejection_reason is required when rejecting")

    suggestion = db.query(Suggestion).filter(Suggestion.id == suggestion_id).first()
    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    suggestion.status = body.status
    # The model's own comment says resolved_by isn't a doctors.id — that's
    # incorrect, super_admin authenticates through the exact same Doctor/
    # get_current_doctor path as every other role (see app/utils/auth.py).
    suggestion.resolved_by = current_doctor.id
    suggestion.rejection_reason = body.rejection_reason.strip() if body.status == "rejected" and body.rejection_reason else None
    db.commit()
    db.refresh(suggestion)
    return {"message": "Status updated", "id": suggestion.id, "status": suggestion.status}