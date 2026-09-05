from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.models.doctor import Doctor
from app.models.tutorial_step import TutorialStep
from app.models.tutorial_progress import TutorialProgress
from app.schemas.tutorial import TutorialStepOut, TutorialStatusOut
from app.utils.auth import get_current_doctor
from app.utils.timezone import now_ist_naive
try:
    from app.utils.portal_auth import get_current_patient_account
except ImportError:
    get_current_patient_account = None  # swap the import above to your actual dependency name

router = APIRouter(prefix="/tutorials", tags=["tutorials"])


@router.get("/{role}/{page}", response_model=List[TutorialStepOut])
def get_tutorial_steps(role: str, page: str, db: Session = Depends(get_db)):
    """No auth requirement beyond just being logged in somewhere — tutorial
    content itself isn't hospital-scoped or sensitive, it's the same
    static walkthrough content for every account of a given role."""
    steps = (
        db.query(TutorialStep)
        .filter(TutorialStep.role == role, TutorialStep.page == page, TutorialStep.is_active == True)  # noqa: E712
        .order_by(TutorialStep.step_order.asc())
        .all()
    )
    return steps


@router.get("/status/staff", response_model=TutorialStatusOut)
def get_staff_tutorial_status(current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    role = current_doctor.role.value
    done = db.query(TutorialProgress).filter(
        TutorialProgress.subject_type == "doctor",
        TutorialProgress.subject_id == current_doctor.id,
        TutorialProgress.role == role,
    ).first()
    return {"role": role, "completed": bool(done)}


@router.post("/status/staff/complete")
def complete_staff_tutorial(current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    """Skip and finish both call this — there is no distinction between
    them once acted on. Idempotent: calling it again is a no-op, not an
    error, since a user might replay the tutorial from Settings and finish
    it again."""
    role = current_doctor.role.value
    existing = db.query(TutorialProgress).filter(
        TutorialProgress.subject_type == "doctor",
        TutorialProgress.subject_id == current_doctor.id,
        TutorialProgress.role == role,
    ).first()
    if not existing:
        db.add(TutorialProgress(subject_type="doctor", subject_id=current_doctor.id, role=role, completed_at=now_ist_naive()))
        db.commit()
    return {"message": "Tutorial marked complete"}


if get_current_patient_account:
    @router.get("/status/patient", response_model=TutorialStatusOut)
    def get_patient_tutorial_status(account=Depends(get_current_patient_account), db: Session = Depends(get_db)):
        done = db.query(TutorialProgress).filter(
            TutorialProgress.subject_type == "patient_account",
            TutorialProgress.subject_id == account.id,
            TutorialProgress.role == "patient",
        ).first()
        return {"role": "patient", "completed": bool(done)}

    @router.post("/status/patient/complete")
    def complete_patient_tutorial(account=Depends(get_current_patient_account), db: Session = Depends(get_db)):
        existing = db.query(TutorialProgress).filter(
            TutorialProgress.subject_type == "patient_account",
            TutorialProgress.subject_id == account.id,
            TutorialProgress.role == "patient",
        ).first()
        if not existing:
            db.add(TutorialProgress(subject_type="patient_account", subject_id=account.id, role="patient", completed_at=now_ist_naive()))
            db.commit()
        return {"message": "Tutorial marked complete"}