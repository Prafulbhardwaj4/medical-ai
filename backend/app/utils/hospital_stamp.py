"""Stamps hospital_id on new admission-child rows (copied from the parent admission).

The column is an extra guard and an index for reports. The parent admission stays the source of truth:
every getter in app.utils.scoped joins the parent. If the parent cannot be found the column is left
empty (it is nullable) and the insert still goes through, exactly as before."""
from sqlalchemy import event as _event, text as _text

from app.models.admission import (
    AdmissionMedicationOrder, AdmissionMedicationAdministration,
    AdmissionMedicationDispense, AdmissionMedicationReturn, AdmissionCharge,
)
from app.models.admission_consent import AdmissionConsent
from app.models.admission_deposit import AdmissionDeposit, AdmissionDepositTopupRequest
from app.models.admission_progress_note import AdmissionProgressNote
from app.models.admission_vitals import AdmissionVitals
from app.models.admission_ward_stay import AdmissionWardStay

_BY_ADMISSION = (
    AdmissionMedicationOrder, AdmissionMedicationReturn, AdmissionCharge, AdmissionConsent,
    AdmissionDeposit, AdmissionDepositTopupRequest, AdmissionProgressNote, AdmissionVitals,
    AdmissionWardStay,
)
_BY_ORDER = (AdmissionMedicationAdministration, AdmissionMedicationDispense)


def _stamp_from_admission(mapper, connection, target):
    if getattr(target, "hospital_id", None) is not None or not getattr(target, "admission_id", None):
        return
    try:
        target.hospital_id = connection.execute(
            _text("SELECT hospital_id FROM admissions WHERE id = :i"), {"i": target.admission_id}
        ).scalar()
    except Exception:
        pass


def _stamp_from_order(mapper, connection, target):
    if getattr(target, "hospital_id", None) is not None or not getattr(target, "order_id", None):
        return
    try:
        target.hospital_id = connection.execute(
            _text(
                "SELECT a.hospital_id FROM admission_medication_orders o "
                "JOIN admissions a ON a.id = o.admission_id WHERE o.id = :i"
            ),
            {"i": target.order_id},
        ).scalar()
    except Exception:
        pass


for _m in _BY_ADMISSION:
    _event.listen(_m, "before_insert", _stamp_from_admission)
for _m in _BY_ORDER:
    _event.listen(_m, "before_insert", _stamp_from_order)