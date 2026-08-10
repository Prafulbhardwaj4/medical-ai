from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.doctor import Doctor
from app.models.suggestion import Suggestion
from app.models.suggestion_reply import SuggestionReply
from app.schemas.suggestion import SuggestionIn, SuggestionEditIn, SuggestionStatusIn, SuggestionReplyIn, VALID_SUGGESTION_STATUSES
from app.utils.auth import get_current_doctor
from app.utils.timezone import now_ist_naive
from datetime import timedelta

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

    unread_ids = {
        r.suggestion_id for r in db.query(SuggestionReply).join(
            Suggestion, Suggestion.id == SuggestionReply.suggestion_id
        ).filter(
            Suggestion.submitted_by == current_doctor.id,
            SuggestionReply.sender == "super_admin",
            SuggestionReply.is_read_by_staff == False
        ).all()
    }

    return [
        {
            "id": s.id,
            "message": s.message,
            "status": s.status,
            "rejection_reason": s.rejection_reason,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
            "can_edit": s.status in ("sent", "seen"),
            "can_follow_up": s.status not in ("completed", "rejected") and (now_ist_naive() - s.updated_at) >= timedelta(days=3),
            "follow_up_requested_at": s.follow_up_requested_at.isoformat() if s.follow_up_requested_at else None,
            "has_unread_reply": s.id in unread_ids,
        }
        for s in rows
    ]


@router.get("/unread-count")
def suggestions_unread_count(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Staff-side badge count — questions from Super Admin the staff member
    hasn't opened yet, across all their own suggestions. Registered ahead of
    the /{suggestion_id} routes below so "unread-count" is never swallowed
    as a suggestion_id path param."""
    count = db.query(SuggestionReply).join(
        Suggestion, Suggestion.id == SuggestionReply.suggestion_id
    ).filter(
        Suggestion.submitted_by == current_doctor.id,
        SuggestionReply.sender == "super_admin",
        SuggestionReply.is_read_by_staff == False
    ).count()
    return {"unread_count": count}


@router.patch("/{suggestion_id}")
def edit_suggestion(
    suggestion_id: int,
    body: SuggestionEditIn,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Staff can edit their own suggestion's text, but only while it's still
    sitting in "sent" or "seen" — once Super Admin has started acting on it
    ("in_progress" or beyond), the text is locked and they're told to send a
    fresh suggestion instead."""
    suggestion = db.query(Suggestion).filter(
        Suggestion.id == suggestion_id, Suggestion.submitted_by == current_doctor.id
    ).first()
    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    if suggestion.status not in ("sent", "seen"):
        raise HTTPException(status_code=400, detail="This one is already in progress and cannot be changed — you can send another suggestion.")
    if not body.message or not body.message.strip():
        raise HTTPException(status_code=400, detail="Please enter a suggestion")

    suggestion.message = body.message.strip()
    suggestion.follow_up_requested_at = None
    db.commit()
    return {"message": "Suggestion updated", "id": suggestion.id}


@router.post("/{suggestion_id}/follow-up")
def follow_up_suggestion(
    suggestion_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Staff nudge when a suggestion has sat unchanged for 3+ days. Flags it
    for Super Admin — surfaced prominently in their suggestions tab rather
    than through the Doctor-scoped notification bell, since Super Admin
    isn't on that system."""
    suggestion = db.query(Suggestion).filter(
        Suggestion.id == suggestion_id, Suggestion.submitted_by == current_doctor.id
    ).first()
    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    if suggestion.status in ("completed", "rejected"):
        raise HTTPException(status_code=400, detail="This suggestion has already been resolved")
    if (now_ist_naive() - suggestion.updated_at) < timedelta(days=3):
        raise HTTPException(status_code=400, detail="Follow-up is only available once a suggestion has sat unchanged for 3 days")

    suggestion.follow_up_requested_at = now_ist_naive()
    db.commit()
    return {"message": "Follow-up sent"}


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

    rows = query.order_by(Suggestion.follow_up_requested_at.isnot(None).desc(), Suggestion.created_at.desc()).all()
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
            "follow_up_requested_at": s.follow_up_requested_at.isoformat() if s.follow_up_requested_at else None,
        }
        for s in rows
    ]


@router.get("/{suggestion_id}")
def get_suggestion(
    suggestion_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Super Admin's detail modal fetches through here — opening it is what
    auto-transitions a fresh "sent" suggestion to "seen"; staff also use this
    to load their own suggestion when opening its reply thread."""
    is_super_admin = current_doctor.role.value == "super_admin"
    suggestion = db.query(Suggestion).filter(Suggestion.id == suggestion_id).first()
    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    if not is_super_admin and suggestion.submitted_by != current_doctor.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    if is_super_admin and suggestion.status == "sent":
        suggestion.status = "seen"
        suggestion.follow_up_requested_at = None
        db.commit()
        db.refresh(suggestion)

    return {
        "id": suggestion.id,
        "hospital_name": suggestion.hospital_name,
        "submitted_by_name": suggestion.submitted_by_name,
        "submitted_by_role": suggestion.submitted_by_role,
        "message": suggestion.message,
        "status": suggestion.status,
        "rejection_reason": suggestion.rejection_reason,
        "created_at": suggestion.created_at.isoformat() if suggestion.created_at else None,
        "updated_at": suggestion.updated_at.isoformat() if suggestion.updated_at else None,
        "follow_up_requested_at": suggestion.follow_up_requested_at.isoformat() if suggestion.follow_up_requested_at else None,
    }


@router.get("/{suggestion_id}/replies")
def list_suggestion_replies(
    suggestion_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    is_super_admin = current_doctor.role.value == "super_admin"
    suggestion = db.query(Suggestion).filter(Suggestion.id == suggestion_id).first()
    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    if not is_super_admin and suggestion.submitted_by != current_doctor.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    rows = db.query(SuggestionReply).filter(
        SuggestionReply.suggestion_id == suggestion_id
    ).order_by(SuggestionReply.created_at.asc()).all()

    if not is_super_admin:
        db.query(SuggestionReply).filter(
            SuggestionReply.suggestion_id == suggestion_id,
            SuggestionReply.sender == "super_admin",
            SuggestionReply.is_read_by_staff == False
        ).update({"is_read_by_staff": True})
        db.commit()

    return [{"id": r.id, "sender": r.sender, "message": r.message, "created_at": r.created_at.isoformat()} for r in rows]


@router.post("/{suggestion_id}/replies", status_code=201)
def add_suggestion_reply(
    suggestion_id: int,
    body: SuggestionReplyIn,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    is_super_admin = current_doctor.role.value == "super_admin"
    suggestion = db.query(Suggestion).filter(Suggestion.id == suggestion_id).first()
    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    if not is_super_admin and suggestion.submitted_by != current_doctor.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    if not body.message or not body.message.strip():
        raise HTTPException(status_code=400, detail="Message can't be empty")

    reply = SuggestionReply(
        suggestion_id=suggestion_id,
        sender="super_admin" if is_super_admin else "staff",
        message=body.message.strip(),
        is_read_by_staff=not is_super_admin,  # staff's own replies don't need to notify themselves
    )
    db.add(reply)

    if is_super_admin:
        from app.utils.notify import notify_suggestion_reply
        notify_suggestion_reply(db, suggestion.hospital_id, suggestion.id, suggestion.submitted_by)

    db.commit()
    return {"message": "Reply sent"}


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
    suggestion.follow_up_requested_at = None
    db.commit()
    db.refresh(suggestion)
    return {"message": "Status updated", "id": suggestion.id, "status": suggestion.status}