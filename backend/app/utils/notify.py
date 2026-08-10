from sqlalchemy.orm import Session
from datetime import date, timedelta
from app.models.notification import Notification
from app.models.hospital_medicine import HospitalMedicine
from app.models.medicine_batch import MedicineBatch
from app.utils.timezone import now_ist_naive


def _upsert(db: Session, hospital_id: int, source_key: str, type_: str, severity: str, title: str, message: str, link_type: str, link_id: int):
    existing = db.query(Notification).filter(
        Notification.hospital_id == hospital_id,
        Notification.source_key == source_key
    ).first()
    if existing:
        # Update content but leave is_read alone — don't re-flag something the admin already saw as unread again
        existing.title = title
        existing.message = message
        existing.severity = severity
    else:
        db.add(Notification(
            hospital_id=hospital_id, source_key=source_key, type=type_, severity=severity,
            title=title, message=message, link_type=link_type, link_id=link_id, is_read=False
        ))


def notify_emergency_alert(db: Session, hospital_id: int, admission_id: int, patient_name: str,
                            doctor_id: int, raised_by_name: str, ward: str, bed_number: str, message: str = None):
    """Urgent ping for an existing IPD patient — NOT a queue entry. Fires two
    notifications: one targeted at the assigned doctor (so it can be pulled
    into a banner instead of a list) and one hospital-wide for admin
    visibility. Always a fresh timestamped row — every alert is its own
    event, never deduped/overwritten."""
    key = f"emergency_alert:{admission_id}:{now_ist_naive().isoformat()}"
    base_message = f"{raised_by_name} raised an emergency alert for {patient_name} — {ward}, Bed {bed_number}."
    if message:
        base_message += f" {message}"

    if doctor_id:
        db.add(Notification(
            hospital_id=hospital_id, source_key=key + ":doctor", type="emergency_alert", severity="critical",
            title=f"🚨 Emergency — {patient_name}", message=base_message,
            link_type="admission", link_id=admission_id, is_read=False, target_doctor_id=doctor_id,
        ))
    db.add(Notification(
        hospital_id=hospital_id, source_key=key + ":admin", type="emergency_alert", severity="critical",
        title=f"🚨 Emergency — {patient_name}", message=base_message,
        link_type="admission", link_id=admission_id, is_read=False,
    ))


def notify_emergency_ward_intake(db: Session, hospital_id: int, checkin_id: int, patient_name: str,
                                  doctor_id: int, token_number: str, reason: str = None, destination: str = "ward"):
    """Emergency walk-in assigned to a doctor — a fresh timestamped ping every
    time (never deduped), targeted only at the assigned doctor. The doctor's
    dashboard defers showing it while they're mid-consultation and surfaces
    it the moment they're free. destination="ward" means the patient is
    holding in the Emergency Ward until accepted; destination="cabin" means
    they've already been placed at the front of the doctor's queue."""
    key = f"emergency_ward_intake:{checkin_id}:{now_ist_naive().isoformat()}"
    reason_part = f" Reason: {reason}." if reason else ""
    if destination == "cabin":
        message = f"{patient_name} (Token {token_number}) came in as an emergency and is on their way to your cabin.{reason_part}"
    else:
        message = f"{patient_name} (Token {token_number}) came in as an emergency and has been assigned to you.{reason_part}"
    db.add(Notification(
        hospital_id=hospital_id, source_key=key, type="emergency_ward_intake", severity="critical",
        title=f"🚨 Emergency — {patient_name}",
        message=message,
        link_type="checkin", link_id=checkin_id, is_read=False, target_doctor_id=doctor_id,
    ))


def notify_emergency_admission(db: Session, hospital_id: int, admission_id: int, patient_name: str,
                                doctor_id: int, bed_number: str, is_overflow: bool = False):
    """Emergency Ward admission created — targets only the admitting doctor.
    link_id carries the admission's internal id (Notification.link_id is an
    Integer column); the frontend resolves id→public_token via the existing
    GET /admissions/token-for/{admission_id} before navigating, same pattern
    already used elsewhere for this link_type. Never deduped, same as the
    walk-in version this replaces."""
    key = f"emergency_admission:{admission_id}:{now_ist_naive().isoformat()}"
    overflow_part = " (overflow bed — ward is at capacity)" if is_overflow else ""
    db.add(Notification(
        hospital_id=hospital_id, source_key=key, type="emergency_admission", severity="critical",
        title="🚨 Emergency admission",
        message=f"{patient_name} has been admitted to the Emergency Ward, bed {bed_number}{overflow_part}. See them now.",
        link_type="admission", link_id=admission_id, is_read=False, target_doctor_id=doctor_id,
    ))


def notify_emergency_assistant_hold(db: Session, hospital_id: int, admission_id: int, patient_name: str,
                                     doctor_id: int, assistant_id: int, bed_number: str):
    """Tells an assistant covering this doctor to hold off sending the
    doctor's regular queue patients in until this emergency admission has
    been seen. One row per covering assistant, targeted. link_id carries the
    admission's internal id (Notification.link_id is an Integer column); the
    frontend resolves id->public token the same way notify_emergency_admission
    already does before navigating."""
    key = f"emergency_assistant_hold:{admission_id}:{assistant_id}:{now_ist_naive().isoformat()}"
    db.add(Notification(
        hospital_id=hospital_id, source_key=key, type="emergency_assistant_hold", severity="critical",
        title=f"🚨 Emergency — hold the queue",
        message=f"{patient_name} (Bed {bed_number}) is an emergency admission for their doctor. Hold off sending regular queue patients in until this one's been seen.",
        link_type="admission", link_id=admission_id, is_read=False, target_doctor_id=assistant_id,
    ))


def notify_critical_result(db: Session, hospital_id: int, order_id: int, patient_name: str,
                            doctor_id: int, test_name: str, critical_note: str,
                            ward: str = None, bed_number: str = None):
    """Critical lab value crossed threshold — same dual-target primitive as
    notify_emergency_alert (targeted doctor ping + hospital-wide admin
    visibility), new entry point. Always a fresh timestamped row, same as
    the emergency alert, since every critical result is its own event."""
    key = f"critical_result:{order_id}:{now_ist_naive().isoformat()}"
    location = f" — {ward}, Bed {bed_number}" if ward else ""
    base_message = f"Critical result for {patient_name}{location}: {test_name} — {critical_note}"

    if doctor_id:
        db.add(Notification(
            hospital_id=hospital_id, source_key=key + ":doctor", type="critical_result", severity="critical",
            title=f"🚨 Critical result — {patient_name}", message=base_message,
            link_type="test_order", link_id=order_id, is_read=False, target_doctor_id=doctor_id,
        ))
    db.add(Notification(
        hospital_id=hospital_id, source_key=key + ":admin", type="critical_result", severity="critical",
        title=f"🚨 Critical result — {patient_name}", message=base_message,
        link_type="test_order", link_id=order_id, is_read=False,
    ))


def notify_critical_result_escalation(db: Session, hospital_id: int, order_id: int, patient_name: str,
                                       test_name: str, critical_note: str, stage: str,
                                       ward: str = None, bed_number: str = None):
    """Escalation step when the ordering doctor hasn't acknowledged in time.
    stage is "nurse_ward" (first escalation) or "admin" (final escalation) —
    always hospital-wide (no single target_doctor_id), since at this point
    the point is broad visibility, not a single recipient."""
    key = f"critical_result_escalation:{order_id}:{stage}:{now_ist_naive().isoformat()}"
    location = f" — {ward}, Bed {bed_number}" if ward else ""
    if stage == "nurse_ward":
        title = f"🚨 Unacknowledged critical result — {patient_name}"
        message = f"No doctor acknowledgment yet for {patient_name}{location}: {test_name} — {critical_note}. Escalating to ward coverage."
    else:
        title = f"🚨 Critical result still unacknowledged — {patient_name}"
        message = f"Still unacknowledged after escalation for {patient_name}{location}: {test_name} — {critical_note}. Needs immediate admin attention."

    db.add(Notification(
        hospital_id=hospital_id, source_key=key, type="critical_result_escalation", severity="critical",
        title=title, message=message, link_type="test_order", link_id=order_id, is_read=False,
    ))


def notify_ward_change_request(db: Session, hospital_id: int, admission_id: int, patient_name: str,
                                requested_ward_name: str, requested_by_name: str, note: str = None):
    """Raised when a doctor/nurse asks reception to move a patient to a
    different ward/bed. source_key includes a timestamp so repeated requests
    for the same admission each surface as their own notification rather than
    silently overwriting one another."""
    key = f"ward_change_request:{admission_id}:{now_ist_naive().isoformat()}"
    message = f"{requested_by_name} requested moving {patient_name} to {requested_ward_name}."
    if note:
        message += f" Note: {note}"
    db.add(Notification(
        hospital_id=hospital_id, source_key=key, type="ward_change_request", severity="warning",
        title=f"Ward change requested — {patient_name}", message=message,
        link_type="ward_change_request", link_id=admission_id, is_read=False
    ))


MIN_SHIFT_HOURS_BEFORE_IDLE_CHECK = 3


def sync_idle_staff_notification(db: Session, doctor):
    """
    Flags a doctor/nurse/assistant if they were assigned real work today and
    completed literally none of it, so far. Safe to call repeatedly at any
    point in their shift, not just at off_duty — the check and the
    create/update/clear of the notification are both keyed to today's date,
    so re-running it mid-shift just refreshes the same flag (self-heals the
    same way a same-day correction already does: present -> did the work ->
    checked again -> flag clears).

    Two call sites today:
    - mark_attendance(), once, at the moment they go off_duty (immediate signal).
    - sync_idle_staff_notifications_for_hospital(), lazily, whenever attendance
      is read for the hospital while they're still present/on_break (catches
      someone idling mid-shift without needing a background job).

    Skipped entirely (no flag, nothing touched) if fewer than
    MIN_SHIFT_HOURS_BEFORE_IDLE_CHECK hours have passed since they first
    marked Present today — protects against an accidental/early Off Duty tap,
    or a lazy mid-shift check firing too early, being mistaken for a full
    idle shift.
    """
    from datetime import date, datetime, timedelta
    from app.models.attendance import AttendanceRecord
    from app.models.checkin import Checkin
    from app.models.consultation import Consultation

    role = doctor.role.value
    if role not in ("doctor", "nurse", "assistant"):
        return

    hospital_id = doctor.hospital_id
    today = date.today()

    attendance = db.query(AttendanceRecord).filter(
        AttendanceRecord.doctor_id == doctor.id,
        AttendanceRecord.date == today
    ).first()

    if not attendance or not attendance.shift_started_at:
        # No known arrival time today — don't guess, skip the check entirely
        return

    hours_since_arrival = (now_ist_naive() - attendance.shift_started_at).total_seconds() / 3600
    if hours_since_arrival < MIN_SHIFT_HOURS_BEFORE_IDLE_CHECK:
        return

    key = f"idle_staff:{doctor.id}:{today.isoformat()}"

    is_idle = False
    assigned_count = 0

    if role == "doctor":
        assigned_count = db.query(Checkin).filter(
            Checkin.doctor_id == doctor.id,
            Checkin.hospital_id == hospital_id,
            Checkin.visit_date == today
        ).count()

        if assigned_count > 0:
            day_start = datetime.combine(today, datetime.min.time())
            day_end = datetime.combine(today, datetime.max.time())
            completed_count = db.query(Consultation).filter(
                Consultation.doctor_id == doctor.id,
                Consultation.token_number != None,
                Consultation.created_at >= day_start,
                Consultation.created_at <= day_end
            ).count()
            is_idle = completed_count == 0

    elif role in ("nurse", "assistant"):
        assigned_count = db.query(Checkin).filter(
            Checkin.nurse_id == doctor.id,
            Checkin.hospital_id == hospital_id,
            Checkin.visit_date == today
        ).count()

        if assigned_count > 0:
            completed_count = db.query(Checkin).filter(
                Checkin.nurse_id == doctor.id,
                Checkin.hospital_id == hospital_id,
                Checkin.visit_date == today,
                Checkin.vitals_status == "done",
                Checkin.vitals_recorded_by == doctor.id
            ).count()
            is_idle = completed_count == 0

    existing = db.query(Notification).filter(
        Notification.hospital_id == hospital_id,
        Notification.source_key == key
    ).first()

    if is_idle:
        role_label = "Doctor" if role == "doctor" else "Nurse"
        still_on_shift = attendance.status in ("present", "on_break")
        tail = "and has gone off duty." if not still_on_shift else "and hasn't started yet."
        message = f"{role_label} {doctor.name} was assigned {assigned_count} patient(s) today but completed none, {tail}"
        if existing:
            existing.title = "Staff inactivity"
            existing.message = message
            existing.severity = "warning"
        else:
            db.add(Notification(
                hospital_id=hospital_id, source_key=key, type="idle_staff", severity="warning",
                title="Staff inactivity", message=message, link_type="staff", link_id=doctor.id, is_read=False
            ))
    else:
        if existing:
            db.delete(existing)

    db.commit()


def sync_idle_staff_notifications_for_hospital(db: Session, hospital_id: int):
    """Lazy mid-shift sweep — runs the same idle check above across every
    doctor/nurse/assistant who marked attendance today, regardless of their
    current status. Called opportunistically whenever attendance is read for
    the hospital (same self-healing-on-read pattern as auto_close_stale_shifts),
    so an idle staff member gets flagged the next time anyone loads an
    attendance view, without needing a background job."""
    from datetime import date
    from app.models.attendance import AttendanceRecord
    from app.models.doctor import Doctor

    today = date.today()
    staff_ids = [
        r[0] for r in db.query(AttendanceRecord.doctor_id).filter(
            AttendanceRecord.hospital_id == hospital_id,
            AttendanceRecord.date == today,
            AttendanceRecord.status.in_(["present", "on_break"])
        ).all()
    ]
    if not staff_ids:
        return
    staff = db.query(Doctor).filter(Doctor.id.in_(staff_ids)).all()
    for member in staff:
        sync_idle_staff_notification(db, member)


def sync_room_classification_notifications(db: Session, hospital_id: int):
    """Flags rooms whose type hasn't been explicitly confirmed by an admin yet
    (legacy rooms auto-defaulted to General during migration). Clears the moment
    admin saves any type for that room — even General again, since that's now a
    deliberate choice, not a default."""
    from app.models.room import Room

    rooms = db.query(Room).filter(
        Room.hospital_id == hospital_id,
        Room.is_active == True,
        Room.type_confirmed == False
    ).all()

    live_keys = set()
    for r in rooms:
        key = f"unclassified_room:{r.id}"
        live_keys.add(key)
        label = r.name or (f"Room {r.room_number}" if r.room_number else f"Room #{r.id}")
        _upsert(
            db, hospital_id, key, "unclassified_room", "warning",
            "Room needs a type",
            f"{label} was auto-set to General during migration and hasn't been classified yet. Set its type in Rooms so doctor/nurse pickers work correctly.",
            "room", r.id
        )

    stale = db.query(Notification).filter(
        Notification.hospital_id == hospital_id,
        Notification.type == "unclassified_room"
    ).all()
    for n in stale:
        if n.source_key not in live_keys:
            db.delete(n)

    db.commit()


def sync_stock_notifications(db: Session, hospital_id: int):
    """Call this after anything that changes medicine stock or batch expiry data.
    Creates/updates notifications for conditions still true, removes ones that resolved."""

    medicines = db.query(HospitalMedicine).filter(
        HospitalMedicine.hospital_id == hospital_id,
        HospitalMedicine.is_active == True
    ).all()

    live_low_stock_keys = set()
    for m in medicines:
        stock = m.stock_quantity or 0
        if stock <= m.low_stock_threshold:
            key = f"low_stock:{m.id}"
            live_low_stock_keys.add(key)
            label = f"{m.generic_name}{' ' + m.strength if m.strength else ''}"
            if stock == 0:
                _upsert(db, hospital_id, key, "low_stock", "critical", "Out of stock", f"{label} is out of stock.", "medicine", m.id)
            else:
                _upsert(db, hospital_id, key, "low_stock", "warning", "Low stock", f"{label} has {stock} unit(s) left (alert at {m.low_stock_threshold}).", "medicine", m.id)

    cutoff = date.today() + timedelta(days=30)
    batches = db.query(MedicineBatch).filter(
        MedicineBatch.hospital_id == hospital_id,
        MedicineBatch.expiry_date != None,
        MedicineBatch.expiry_date <= cutoff,
        MedicineBatch.quantity > 0
    ).all()

    live_expiry_keys = set()
    for b in batches:
        medicine = db.query(HospitalMedicine).filter(HospitalMedicine.id == b.medicine_id, HospitalMedicine.is_active == True).first()
        if not medicine:
            continue
        key = f"expiring:{b.id}"
        live_expiry_keys.add(key)
        days_left = (b.expiry_date - date.today()).days
        label = f"{medicine.generic_name}{' ' + medicine.strength if medicine.strength else ''}"
        if days_left < 0:
            _upsert(db, hospital_id, key, "expiring_stock", "critical", "Stock expired", f"{label} (Lot {b.batch_number or '—'}, {b.quantity} units) expired.", "medicine", medicine.id)
        else:
            _upsert(db, hospital_id, key, "expiring_stock", "warning", "Expiring soon", f"{label} (Lot {b.batch_number or '—'}, {b.quantity} units) expires in {days_left} day(s).", "medicine", medicine.id)

    # Remove notifications whose underlying condition is no longer true (restocked / batch consumed or removed)
    stale = db.query(Notification).filter(
        Notification.hospital_id == hospital_id,
        Notification.type.in_(["low_stock", "expiring_stock"])
    ).all()
    for n in stale:
        if n.type == "low_stock" and n.source_key not in live_low_stock_keys:
            db.delete(n)
        elif n.type == "expiring_stock" and n.source_key not in live_expiry_keys:
            db.delete(n)

    db.commit()


def notify_suggestion_reply(db: Session, hospital_id: int, suggestion_id: int, staff_id: int):
    """Super Admin asked the submitting staff member something on their
    suggestion. Targets only that staff member. link_id carries the
    suggestion's id — the frontend's suggestion widget opens straight to
    that suggestion's conversation thread rather than navigating pages."""
    key = f"suggestion_reply:{suggestion_id}:{now_ist_naive().isoformat()}"
    db.add(Notification(
        hospital_id=hospital_id, source_key=key, type="suggestion_reply", severity="info",
        title="💬 Question on your suggestion",
        message="Super Admin asked you something about a suggestion you sent in.",
        link_type="suggestion", link_id=suggestion_id, is_read=False, target_doctor_id=staff_id,
    ))