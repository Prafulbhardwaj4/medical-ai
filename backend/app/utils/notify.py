from sqlalchemy.orm import Session
from datetime import date, timedelta
from app.models.notification import Notification
from app.models.hospital_medicine import HospitalMedicine
from app.models.medicine_batch import MedicineBatch


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


MIN_SHIFT_HOURS_BEFORE_IDLE_CHECK = 4


def sync_idle_staff_notification(db: Session, doctor):
    """
    Called exactly once, at the moment a doctor/nurse marks themselves off_duty.
    Flags them only if they were assigned real work today and completed
    literally none of it. Recomputed fresh on every off_duty transition so a
    same-day correction (present -> did the work -> off_duty again) always
    reflects the true latest state — never leaves a stale/wrong flag behind.

    Skipped entirely (no flag, nothing touched) if fewer than
    MIN_SHIFT_HOURS_BEFORE_IDLE_CHECK hours have passed since they first
    marked Present today — protects against an accidental/early Off Duty tap
    being mistaken for a full idle shift.
    """
    from datetime import date, datetime, timedelta
    from app.models.attendance import AttendanceRecord
    from app.models.checkin import Checkin
    from app.models.consultation import Consultation

    role = doctor.role.value
    if role not in ("doctor", "nurse"):
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

    hours_since_arrival = (datetime.utcnow() - attendance.shift_started_at).total_seconds() / 3600
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

    elif role == "nurse":
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
        message = f"{role_label} {doctor.name} was assigned {assigned_count} patient(s) today but completed none, and has gone off duty."
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