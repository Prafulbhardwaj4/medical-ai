import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
import app.main  # noqa: F401  (registers every model and the hospital_id stamping)
from app.models.hospital import Hospital
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.models.consultation import Consultation
from app.models.admission import Admission, AdmissionMedicationOrder, AdmissionMedicationAdministration, AdmissionCharge
from app.models.admission_vitals import AdmissionVitals
from app.utils import scoped


@pytest.fixture()
def sdb():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    yield db
    db.close()
    engine.dispose()


def _world(db, n):
    h = Hospital(name=f"H{n}", hospital_code=f"HC{n}")
    db.add(h); db.flush()
    d = Doctor(name=f"D{n}", email=f"d{n}@x.in", phone="9", specialization="GP", hashed_password="x", hospital_id=h.id)
    p = Patient(url_token=f"pt{n}", name=f"P{n}", phone="9", age=30, gender="M", hospital_id=h.id)
    db.add_all([d, p]); db.flush()
    a = Admission(public_token=f"adm{n}", patient_id=p.id, hospital_id=h.id, admitting_doctor_id=d.id, ward="W", bed_number="1")
    db.add(a); db.flush()
    o = AdmissionMedicationOrder(admission_id=a.id, medicine_name="Para", prescribed_by=d.id)
    c = AdmissionCharge(admission_id=a.id, charge_type="other", description="x", amount=1, added_by=d.id)
    v = AdmissionVitals(admission_id=a.id, recorded_by=d.id, data="{}")
    k = Consultation(token_number=f"tok{n}", patient_id=p.id, doctor_id=d.id)
    db.add_all([o, c, v, k]); db.flush()
    ad = AdmissionMedicationAdministration(order_id=o.id, administered_by=d.id)
    db.add(ad); db.commit()
    return dict(h=h, p=p, a=a, o=o, c=c, v=v, k=k, ad=ad)


def test_children_get_hospital_id_stamped(sdb):
    w = _world(sdb, 1)
    for key in ("o", "c", "v", "ad"):
        assert w[key].hospital_id == w["h"].id


def test_own_hospital_rows_are_returned(sdb):
    w = _world(sdb, 1)
    hid = w["h"].id
    assert scoped.get_admission(sdb, w["a"].id, hid).id == w["a"].id
    assert scoped.get_admission_by_token(sdb, "adm1", hid).id == w["a"].id
    assert scoped.get_medication_order(sdb, w["o"].id, hid).id == w["o"].id
    assert scoped.get_administration(sdb, w["ad"].id, hid).id == w["ad"].id
    assert scoped.get_charge(sdb, w["c"].id, hid).id == w["c"].id
    assert scoped.get_vitals(sdb, w["v"].id, hid).id == w["v"].id
    assert scoped.get_patient(sdb, w["p"].id, hid).id == w["p"].id
    assert scoped.get_consultation(sdb, w["k"].id, hid).id == w["k"].id
    assert scoped.get_consultation_by_token(sdb, "tok1", hid).id == w["k"].id


def test_other_hospital_gets_404_for_every_getter(sdb):
    w1 = _world(sdb, 1)
    w2 = _world(sdb, 2)
    other = w2["h"].id
    calls = [
        lambda: scoped.get_admission(sdb, w1["a"].id, other),
        lambda: scoped.get_admission_by_token(sdb, "adm1", other),
        lambda: scoped.get_medication_order(sdb, w1["o"].id, other),
        lambda: scoped.get_administration(sdb, w1["ad"].id, other),
        lambda: scoped.get_charge(sdb, w1["c"].id, other),
        lambda: scoped.get_vitals(sdb, w1["v"].id, other),
        lambda: scoped.get_patient(sdb, w1["p"].id, other),
        lambda: scoped.get_consultation(sdb, w1["k"].id, other),
        lambda: scoped.get_consultation_by_token(sdb, "tok1", other),
    ]
    for call in calls:
        with pytest.raises(HTTPException) as e:
            call()
        assert e.value.status_code == 404


def test_user_without_hospital_gets_404(sdb):
    w = _world(sdb, 1)
    with pytest.raises(HTTPException) as e:
        scoped.get_admission(sdb, w["a"].id, None)
    assert e.value.status_code == 404