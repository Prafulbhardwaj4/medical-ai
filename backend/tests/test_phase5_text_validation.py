import pytest
from pydantic import ValidationError

from app.utils.text_safety import SafeTextModel, ensure_safe_text, ensure_safe_text_or_400
from app.schemas.patient import PatientCreate, NurseNoteCreate, ReasonIn
from app.schemas.doctor import DoctorCreate, EditMeIn
from fastapi import HTTPException


def _patient(**over):
    base = dict(name="Ravi Kumar", phone="9876543210", age=30, gender="male")
    base.update(over)
    return base


def test_plain_names_are_accepted():
    for name in ("Ravi Kumar", "रवि कुमार", "O'Brien-Smith Jr.", "Anne-Marie D’Souza"):
        assert PatientCreate(**_patient(name=name)).name == name


@pytest.mark.parametrize("bad", ["<b>x</b>", "Ravi <img src=x>", "a>b", "<script>alert(1)</script>"])
def test_patient_name_rejects_angle_brackets(bad):
    with pytest.raises(ValidationError) as e:
        PatientCreate(**_patient(name=bad))
    assert "can't contain the < or > characters" in str(e.value)


@pytest.mark.parametrize("bad", ["Ravi\x00Kumar", "Ravi\nKumar", "Ravi\tKumar", "Ravi\u202eKumar", "Ravi\x7fKumar"])
def test_patient_name_rejects_control_characters(bad):
    with pytest.raises(ValidationError):
        PatientCreate(**_patient(name=bad))


def test_address_allows_new_lines_but_not_angle_brackets():
    assert PatientCreate(**_patient(address="House 4\nSector 7, Ambala")).address.startswith("House 4")
    with pytest.raises(ValidationError):
        PatientCreate(**_patient(address="House <4>"))
    with pytest.raises(ValidationError):
        PatientCreate(**_patient(address="House\x00 4"))


def test_notes_and_reasons_are_checked():
    with pytest.raises(ValidationError):
        NurseNoteCreate(note="BP <script>")
    with pytest.raises(ValidationError):
        ReasonIn(reason="reason with <b>markup</b>")
    assert NurseNoteCreate(note="Patient comfortable.\nVitals stable.").note.startswith("Patient")


def test_doctor_inputs_checked():
    with pytest.raises(ValidationError):
        DoctorCreate(name="<b>Dr</b>", email="a@b.co", phone="9999999999", specialization="x", clinic_name="c", password="x")
    with pytest.raises(ValidationError):
        EditMeIn(name="Dr <i>X</i>", phone="9999999999")
    assert EditMeIn(name="Dr Sharma", phone="9999999999").name == "Dr Sharma"


def test_passwords_and_other_fields_are_not_touched():
    d = DoctorCreate(name="Dr Sharma", email="a@b.co", phone="9999999999", specialization="x", clinic_name="c", password="p<a>ss")
    assert d.password == "p<a>ss"


def test_nested_lists_are_scanned():
    class Inner(SafeTextModel):
        label: str

    class Outer(SafeTextModel):
        items: list[Inner]

    with pytest.raises(ValidationError):
        Outer(items=[{"label": "ok"}, {"label": "<b>"}])


def test_model_objects_with_old_stored_data_still_load():
    from app.schemas.patient import PatientOut
    from types import SimpleNamespace
    from datetime import datetime
    obj = SimpleNamespace(id=1, patient_uid="P1", url_token="t", name="<old stored>", phone="1", age=1, date_of_birth=None,
                          blood_group=None, gender="Male", abha_number=None, address=None, hospital_id=1, created_by=1,
                          created_at=datetime(2026, 1, 1), auto_checked_in_token=None)
    assert PatientOut.model_validate(obj).name == "<old stored>"


def test_ensure_helpers():
    assert ensure_safe_text("fine") == "fine"
    assert ensure_safe_text(None) is None
    with pytest.raises(ValueError):
        ensure_safe_text("a<b", "Hospital name")
    with pytest.raises(HTTPException) as e:
        ensure_safe_text_or_400("a>b", "City")
    assert e.value.status_code == 400 and "City" in e.value.detail


def test_admin_models_use_the_check():
    from app.routers.admin import CreateDoctorIn, CreateAdminIn, UpdateAccountIn, LeadToHospitalIn
    with pytest.raises(ValidationError):
        CreateDoctorIn(hospital_id=1, name="<b>x</b>", email="a@b.co", phone="9999999999")
    with pytest.raises(ValidationError):
        CreateAdminIn(hospital_id=1, name="x", email="a@b.co", phone="9999999999", specialization="<i>")
    with pytest.raises(ValidationError):
        UpdateAccountIn(name="<x>", email="a@b.co", phone="9999999999")
    with pytest.raises(ValidationError):
        LeadToHospitalIn(name="<x>")