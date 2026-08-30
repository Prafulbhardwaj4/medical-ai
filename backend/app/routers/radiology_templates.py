from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from pydantic import BaseModel

from app.database import get_db
from app.models.doctor import Doctor
from app.models.radiology_template import RadiologyTemplate
from app.models.radiology_template_section import RadiologyTemplateSection
from app.utils.auth import get_current_doctor
from app.utils.audit import log_action

router = APIRouter(prefix="/admin/radiology-templates", tags=["radiology-templates"])

VALID_STUDY_TYPES = ["xray", "ct", "mri", "ultrasound"]


def require_admin(current_doctor: Doctor):
    if current_doctor.role.value not in ["admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")


class SectionIn(BaseModel):
    name: str
    default_finding_text: Optional[str] = ""


class TemplateIn(BaseModel):
    name: str
    study_type: str
    fee: Optional[float] = None
    sections: list[SectionIn]


def serialize_section(s: RadiologyTemplateSection):
    return {
        "id": s.id,
        "name": s.name,
        "default_finding_text": s.default_finding_text or "",
        "display_order": s.display_order,
    }


def serialize(t: RadiologyTemplate, db: Session):
    rows = db.query(RadiologyTemplateSection).filter(
        RadiologyTemplateSection.radiology_template_id == t.id,
        RadiologyTemplateSection.is_active == True
    ).order_by(RadiologyTemplateSection.display_order).all()

    return {
        "id": t.id,
        "name": t.name,
        "study_type": t.study_type,
        "fee": t.fee,
        "is_active": t.is_active,
        "sections": [serialize_section(s) for s in rows],
    }


@router.get("")
def list_templates(
    study_type: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_admin(current_doctor)

    query = db.query(RadiologyTemplate).filter(
        RadiologyTemplate.hospital_id == current_doctor.hospital_id,
        RadiologyTemplate.is_active == True
    )
    if study_type:
        query = query.filter(RadiologyTemplate.study_type == study_type)
    if search:
        query = query.filter(RadiologyTemplate.name.ilike(f"%{search}%"))

    items = query.order_by(RadiologyTemplate.name).all()
    return [serialize(t, db) for t in items]


@router.post("", status_code=201)
def create_template(
    payload: TemplateIn,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_admin(current_doctor)

    if payload.fee is None:
        raise HTTPException(status_code=400, detail="Fee is required")
    if payload.study_type not in VALID_STUDY_TYPES:
        raise HTTPException(status_code=400, detail="Invalid study type")
    if not payload.sections or len(payload.sections) == 0:
        raise HTTPException(status_code=400, detail="A template needs at least one section")

    template = RadiologyTemplate(
        hospital_id=current_doctor.hospital_id,
        name=payload.name.strip(),
        study_type=payload.study_type,
        fee=payload.fee,
        is_active=True
    )
    db.add(template)
    db.commit()
    db.refresh(template)

    for i, s in enumerate(payload.sections):
        if not s.name or not s.name.strip():
            continue
        db.add(RadiologyTemplateSection(
            radiology_template_id=template.id,
            hospital_id=current_doctor.hospital_id,
            name=s.name.strip(),
            default_finding_text=(s.default_finding_text or "").strip(),
            display_order=i,
            is_active=True,
        ))
    db.commit()

    log_action(
        db, current_doctor,
        action="radiology_template_created",
        target_type="radiology_template",
        target_id=template.id,
        target_label=template.name,
        hospital_id=current_doctor.hospital_id
    )
    return serialize(template, db)


@router.patch("/{template_id}")
def update_template(
    template_id: int,
    payload: TemplateIn,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_admin(current_doctor)

    template = db.query(RadiologyTemplate).filter(
        RadiologyTemplate.id == template_id,
        RadiologyTemplate.hospital_id == current_doctor.hospital_id
    ).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    if payload.fee is None:
        raise HTTPException(status_code=400, detail="Fee is required")
    if payload.study_type not in VALID_STUDY_TYPES:
        raise HTTPException(status_code=400, detail="Invalid study type")
    if not payload.sections or len(payload.sections) == 0:
        raise HTTPException(status_code=400, detail="A template needs at least one section")

    template.name = payload.name.strip()
    template.study_type = payload.study_type
    template.fee = payload.fee

    # Replace-all: same convention as tests.py — existing section rows are
    # wiped and rebuilt from the payload every save.
    db.query(RadiologyTemplateSection).filter(
        RadiologyTemplateSection.radiology_template_id == template.id
    ).delete()

    for i, s in enumerate(payload.sections):
        if not s.name or not s.name.strip():
            continue
        db.add(RadiologyTemplateSection(
            radiology_template_id=template.id,
            hospital_id=current_doctor.hospital_id,
            name=s.name.strip(),
            default_finding_text=(s.default_finding_text or "").strip(),
            display_order=i,
            is_active=True,
        ))

    db.commit()

    log_action(
        db, current_doctor,
        action="radiology_template_updated",
        target_type="radiology_template",
        target_id=template.id,
        target_label=template.name,
        hospital_id=current_doctor.hospital_id
    )
    return serialize(template, db)


@router.delete("/{template_id}")
def deactivate_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_admin(current_doctor)

    template = db.query(RadiologyTemplate).filter(
        RadiologyTemplate.id == template_id,
        RadiologyTemplate.hospital_id == current_doctor.hospital_id
    ).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    template.is_active = False
    db.commit()

    log_action(
        db, current_doctor,
        action="radiology_template_deactivated",
        target_type="radiology_template",
        target_id=template.id,
        target_label=template.name,
        hospital_id=current_doctor.hospital_id
    )
    return {"id": template.id, "is_active": template.is_active}