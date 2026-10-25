"""WhatsApp messages: the ONE place that builds message text, stores it, and (later) sends it.

Until Meta business verification is finished the system sends nothing. Every message is built
here from the eight templates, stored in the `whatsapp_messages` table, and shown in the staff
"WhatsApp messages" list, where a person copies it and sends it by hand.

No other file may write WhatsApp text. Callers use the build_* functions and enqueue_message().
All times are naive IST (the app-wide convention).
"""
import base64
import hashlib
import json
import logging
import re
from datetime import timedelta

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.config import settings, _is_production
from app.models.whatsapp_message import WhatsappMessage
from app.utils.phone import normalize_phone
from app.utils.timezone import now_ist_naive

logger = logging.getLogger("whatsapp")

# ---------------------------------------------------------------------------
# Template keys, labels, visibility
# ---------------------------------------------------------------------------
T_WELCOME = "welcome_account_created"
T_TEMP_PASSWORD = "temporary_password_code"
T_VISIT_TOKEN = "visit_token_details"
T_APPT_CONFIRMED = "appointment_confirmed"
T_APPT_REMINDER = "appointment_reminder_24h"
T_APPT_CANCELLED = "appointment_cancelled_rescheduled"
T_FORGOT_OTP = "forgot_password_otp"

TYPE_LABELS = {
    T_WELCOME: "Welcome",
    T_TEMP_PASSWORD: "Temporary password",
    T_VISIT_TOKEN: "Visit token",
    T_APPT_CONFIRMED: "Appointment confirmed",
    T_APPT_REMINDER: "Appointment reminder",
    T_APPT_CANCELLED: "Appointment cancelled/rescheduled",
    T_FORGOT_OTP: "Password reset code",
}

# visibility level -> roles that may see the message (the hospital scope is applied separately)
VIS_ALL = "all"                  # super_admin, admin, receptionist
VIS_ADMIN_SUPER = "admin_super"  # super_admin, admin
VIS_SUPER_ONLY = "super_only"    # super_admin
VISIBLE_LEVELS_FOR_ROLE = {
    "super_admin": {VIS_ALL, VIS_ADMIN_SUPER, VIS_SUPER_ONLY},
    "admin": {VIS_ALL, VIS_ADMIN_SUPER},
    "receptionist": {VIS_ALL},
}

OPEN_STATUSES = ("scheduled", "due", "pending")
CLOSED_STATUSES = ("sent", "cancelled", "expired")

SECRET_MASK = "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022"
EXPIRED_TEXT = "[expired]"

TEMP_PASSWORD_VALID_DAYS = 7
OTP_VALID_MINUTES = 10
DEFAULT_EXPIRY_DAYS = 7

# ---------------------------------------------------------------------------
# The templates (exact text). {{n}} are filled in ONE pass by _fill().
# ---------------------------------------------------------------------------
_DIV = "\u2501" * 14

TEMPLATE_BODIES = {
    T_WELCOME: (
        "*Welcome to MedScribe*\n"
        "\n"
        "Hello {{1}},\n"
        "\n"
        "{{2}} \u2705\n"
        "\n"
        f"{_DIV}\n"
        "\U0001F194 *Login ID:* {{4}}\n"
        f"{_DIV}\n"
        "\n"
        "{{5}}\n"
        "\n"
        "Your temporary password is valid for 7 days and will be sent shortly.\n"
        "\n"
        "*NOTE:* Please log in and set a new password. Do not share it with anyone.\n"
        "\n"
        "Log in: {{6}}"
    ),
    T_TEMP_PASSWORD: "{{1}} is your verification code. For your security, do not share this code.",
    T_VISIT_TOKEN: (
        "Hello {{1}},\n"
        "\n"
        "*TOKEN NUMBER: {{3}}*\n"
        "\n"
        "*Doctor:* {{4}}\n"
        "*Room:* {{6}}\n"
        "*Date & time:* {{7}}\n"
        "*Hospital:* {{2}}\n"
        "\n"
        "*NOTE:* Your bills, reports and prescriptions will be available on the patient portal once they are generated.\n"
        "\n"
        "Need help? Call {{9}} anytime.\n"
        "\n"
        "Open patient portal: {{10}}"
    ),
    T_APPT_CONFIRMED: (
        "Hello {{1}},\n"
        "\n"
        "Your appointment at *{{2}}* is confirmed.\n"
        "\n"
        "*Date & time:* {{3}}\n"
        "*Doctor:* {{4}}\n"
        "\n"
        "Please arrive at least *10 minutes* before your appointment time.\n"
        "\n"
        "*NOTE:* Your token number will be sent to you 30 minutes before the appointment. You can also ask at the reception."
    ),
    T_APPT_REMINDER: (
        "Hello {{1}} \U0001F44B\n"
        "\n"
        "*REMINDER:* You have an appointment at *{{2}}*.\n"
        "\n"
        f"{_DIV}\n"
        "\U0001F4C5 *Date & time:* {{3}}\n"
        "\U0001F468\u200D\u2695\uFE0F *Doctor:* {{4}}\n"
        f"{_DIV}\n"
        "\n"
        "Please arrive at least *10 minutes* before your appointment time.\n"
        "\n"
        "*NOTE:* Your token number will be sent to you 30 minutes before the appointment. You can also ask at the reception."
    ),
    T_APPT_CANCELLED: (
        "Hello {{1}} \U0001F44B\n"
        "\n"
        "\u26A0\uFE0F *APPOINTMENT UPDATE*\n"
        "\n"
        "Due to unavoidable reasons, your appointment has been *cancelled* by *{{2}}*.\n"
        "\n"
        f"{_DIV}\n"
        "\U0001F4C5 *Date & time:* {{3}}\n"
        "\U0001F468\u200D\u2695\uFE0F *Doctor:* {{4}}\n"
        f"{_DIV}\n"
        "\n"
        "{{5}}\n"
        "\n"
        "For further details, contact the hospital on {{6}} anytime."
    ),
    T_FORGOT_OTP: "{{1}} is your verification code. For your security, do not share this code.",
}

ROLE_WORDS = {
    "admin": "admin", "sub_admin": "sub-admin", "doctor": "doctor", "receptionist": "receptionist",
    "nurse": "nurse", "pharmacy": "pharmacy", "lab": "lab", "assistant": "assistant",
    "radiology": "radiology", "patient": "patient",
}

ROLE_LINES = {
    "admin": "You can manage staff, rooms, billing and reports for your hospital from your dashboard.",
    "sub_admin": "You can help manage staff, patients and daily hospital work from your dashboard.",
    "doctor": "You can see your patients, record consultations with the AI scribe and review their history from your dashboard.",
    "receptionist": "You can register patients, issue tokens and manage appointments and billing from your dashboard.",
    "nurse": "You can record vitals, manage ward duties and give medicines from your dashboard.",
    "pharmacy": "You can manage medicine stock, dispense prescriptions and handle pharmacy billing from your dashboard.",
    "lab": "You can receive test orders, enter results and prepare lab reports from your dashboard.",
    "assistant": "You can record patient vitals and get patients ready for the doctor from your dashboard.",
    "radiology": "You can manage radiology orders and reports from your dashboard.",
    "patient": "You can view your visits, prescriptions, bills and reports and book appointments on the patient portal.",
}
DEFAULT_ROLE_LINE = "You can do your daily work from your MedScribe dashboard."

CANCEL_LINE_RESCHEDULED = "Details of your new appointment will be provided shortly through another message."
CANCEL_LINE_CANCELLED = "We are sorry for the inconvenience."


# ---------------------------------------------------------------------------
# Sanitizing and filling
# ---------------------------------------------------------------------------
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\u2028\u2029]")
_SPACES = re.compile(r"[ \u00a0]{2,}")
_PLACEHOLDER = re.compile(r"\{\{(\d+)\}\}")


def clean_line(value, max_len: int = 160) -> str:
    """Untrusted value -> ONE line: no line breaks, tabs, control characters, bold marks or runs of spaces."""
    s = "" if value is None else str(value)
    s = s.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    s = _CTRL.sub("", s)
    s = s.replace("*", "").replace("{{", "").replace("}}", "")
    s = _SPACES.sub(" ", s).strip()
    return s[:max_len].strip()


def _fill(template: str, values: dict) -> str:
    """Single pass: a value that happens to contain {{n}} is never substituted again."""
    return _PLACEHOLDER.sub(lambda m: values.get(int(m.group(1)), ""), template)


def format_ist_datetime(dt) -> str:
    """'24 Oct 2026, 10:30 AM'. Stored datetimes are naive IST already."""
    if dt is None:
        return ""
    return f"{dt.day} {dt.strftime('%b %Y, %I:%M %p')}"


def staff_login_link() -> str:
    return settings.PUBLIC_FRONTEND_URL.rstrip("/")


def portal_login_link() -> str:
    return settings.PORTAL_FRONTEND_URL.rstrip("/")


def hospital_mobile(hospital) -> str:
    """First mobile number saved in the hospital's contact numbers (legacy phone as fallback)."""
    if hospital is None:
        return "the reception"
    try:
        for item in json.loads(hospital.contact_numbers or "[]"):
            if isinstance(item, dict) and item.get("type") == "mobile" and item.get("number"):
                return clean_line(item["number"], 30)
    except (ValueError, TypeError):
        pass
    return clean_line(hospital.phone, 30) or "the reception"


# ---------------------------------------------------------------------------
# Message builders. Each returns the exact text to send.
# ---------------------------------------------------------------------------
def build_welcome(*, name, role, hospital_name, login_id) -> str:
    role = role or "patient"
    link = portal_login_link() if role == "patient" else staff_login_link()
    if role == "patient":
        intro = "Your patient portal is ready"  # one portal for every hospital, so no hospital name here
    else:
        word = ROLE_WORDS.get(role, clean_line(role.replace("_", "-"), 30))
        intro = f"Your {word} portal at *{clean_line(hospital_name)}* is ready"
    return _fill(TEMPLATE_BODIES[T_WELCOME], {
        1: clean_line(name), 2: intro, 4: clean_line(login_id),
        5: ROLE_LINES.get(role, DEFAULT_ROLE_LINE), 6: link,
    })


def build_temp_password(password) -> tuple:
    """Returns (full_text, masked_text). The full text holds the secret."""
    pw = clean_line(password, 30)
    body = TEMPLATE_BODIES[T_TEMP_PASSWORD]
    return _fill(body, {1: pw}), _fill(body, {1: SECRET_MASK})


def build_forgot_otp(code) -> tuple:
    """Returns (full_text, masked_text). The full text holds the 6-digit code."""
    c = clean_line(code, 10)
    body = TEMPLATE_BODIES[T_FORGOT_OTP]
    return _fill(body, {1: c}), _fill(body, {1: SECRET_MASK})


def build_visit_token(*, patient_name, hospital_name, token_number, doctor_name, speciality,
                      room, visit_datetime, patient_uid, hospital_mobile_number) -> str:
    doctor = clean_line(doctor_name)
    if clean_line(speciality):
        doctor = f"{doctor} ({clean_line(speciality)})"
    return _fill(TEMPLATE_BODIES[T_VISIT_TOKEN], {
        1: clean_line(patient_name), 2: clean_line(hospital_name), 3: clean_line(token_number, 30),
        4: doctor, 6: clean_line(room, 40) or "-", 7: format_ist_datetime(visit_datetime),
        9: clean_line(hospital_mobile_number, 30) or "the reception", 10: portal_login_link(),
    })


def build_appointment_confirmed(*, patient_name, hospital_name, appt_datetime, doctor_name, speciality=None) -> str:
    doctor = clean_line(doctor_name)
    if clean_line(speciality):
        doctor = f"{doctor} ({clean_line(speciality)})"
    return _fill(TEMPLATE_BODIES[T_APPT_CONFIRMED], {
        1: clean_line(patient_name), 2: clean_line(hospital_name),
        3: format_ist_datetime(appt_datetime), 4: doctor,
    })


def build_appointment_reminder(*, patient_name, hospital_name, appt_datetime, doctor_name) -> str:
    return _fill(TEMPLATE_BODIES[T_APPT_REMINDER], {
        1: clean_line(patient_name), 2: clean_line(hospital_name),
        3: format_ist_datetime(appt_datetime), 4: clean_line(doctor_name),
    })


def build_appointment_cancelled(*, patient_name, hospital_name, old_datetime, doctor_name,
                                rescheduled: bool, hospital_mobile_number) -> str:
    return _fill(TEMPLATE_BODIES[T_APPT_CANCELLED], {
        1: clean_line(patient_name), 2: clean_line(hospital_name),
        3: format_ist_datetime(old_datetime), 4: clean_line(doctor_name),
        5: CANCEL_LINE_RESCHEDULED if rescheduled else CANCEL_LINE_CANCELLED,
        6: clean_line(hospital_mobile_number, 30) or "the reception",
    })


# ---------------------------------------------------------------------------
# Secret storage (encrypted column)
# ---------------------------------------------------------------------------
class SecretKeyMissing(RuntimeError):
    pass


def _fernet() -> Fernet:
    key = (settings.WHATSAPP_MESSAGES_KEY or "").strip()
    if key:
        try:
            return Fernet(key.encode())
        except (ValueError, TypeError):
            raise SecretKeyMissing("WHATSAPP_MESSAGES_KEY is not a valid Fernet key")
    if _is_production(settings):
        raise SecretKeyMissing("WHATSAPP_MESSAGES_KEY is not set")
    # LOCAL DEV ONLY (never reached in production): derive a key from SECRET_KEY.
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(f"wa-msgs-dev:{settings.SECRET_KEY}".encode()).digest()))


def _encrypt(text: str) -> str:
    return _fernet().encrypt(text.encode("utf-8")).decode()


def decrypt_secret_text(row: WhatsappMessage):
    """Full text of a secret message, or None if it was wiped / cannot be read."""
    if not row.secret_enc:
        return None
    try:
        return _fernet().decrypt(row.secret_enc.encode()).decode("utf-8")
    except (InvalidToken, ValueError, SecretKeyMissing):
        logger.error("Could not decrypt secret of whatsapp message %s", row.id)
        return None


# ---------------------------------------------------------------------------
# Storing messages
# ---------------------------------------------------------------------------
def enqueue_message(db: Session, *, template_key: str, text: str, hospital_id, recipient_name: str,
                    recipient_role: str, recipient_phone: str, recipient_kind: str = "patient",
                    recipient_id=None, masked_text: str = None, secret: bool = False,
                    visibility: str = VIS_ALL, due_at=None, expires_at=None, created_by=None,
                    appointment_id=None, checkin_id=None, token_number=None,
                    is_sample: bool = False) -> WhatsappMessage:
    """Adds one message to the list inside the CALLER's transaction (flush only; the caller commits).
    A secret message needs WHATSAPP_MESSAGES_KEY: without it nothing is created and SecretKeyMissing is raised."""
    now = now_ist_naive()
    due = due_at or now
    row = WhatsappMessage(
        hospital_id=hospital_id, recipient_kind=recipient_kind, recipient_id=recipient_id,
        recipient_name=clean_line(recipient_name, 120) or "-", recipient_role=clean_line(recipient_role, 30) or "-",
        recipient_phone=normalize_phone(recipient_phone) or clean_line(recipient_phone, 20),
        template_key=template_key, is_secret=bool(secret), visibility=visibility,
        status="scheduled" if due > now else "pending", status_changed_at=now, due_at=due,
        expires_at=expires_at, is_sample=is_sample, created_by=created_by,
        appointment_id=appointment_id, checkin_id=checkin_id, token_number=token_number,
    )
    if row.expires_at is None and not is_sample:
        row.expires_at = now + (timedelta(minutes=OTP_VALID_MINUTES) if template_key == T_FORGOT_OTP
                                else timedelta(days=DEFAULT_EXPIRY_DAYS))
    if secret:
        row.secret_enc = _encrypt(text)  # raises SecretKeyMissing before anything is added
        row.message_text = masked_text if masked_text is not None else text
    else:
        row.message_text = text
    db.add(row)
    db.flush()
    return row


def cancel_unsent(db: Session, *, appointment_id=None, checkin_id=None, template_keys=None) -> int:
    """Cancels every not-yet-sent message of an appointment / check-in (used when it is cancelled or rescheduled)."""
    if appointment_id is None and checkin_id is None:
        return 0
    q = db.query(WhatsappMessage).filter(WhatsappMessage.status.in_(OPEN_STATUSES), WhatsappMessage.is_sample == False)  # noqa: E712
    if appointment_id is not None:
        q = q.filter(WhatsappMessage.appointment_id == appointment_id)
    if checkin_id is not None:
        q = q.filter(WhatsappMessage.checkin_id == checkin_id)
    if template_keys:
        q = q.filter(WhatsappMessage.template_key.in_(list(template_keys)))
    now = now_ist_naive()
    count = 0
    for row in q.all():
        row.prev_status, row.status, row.status_changed_at = row.status, "cancelled", now
        row.secret_enc = None
        count += 1
    return count


def wipe_secrets_for_recipient(db: Session, *, recipient_kind: str, recipient_id: int, template_keys=None) -> int:
    """Used when a password is changed or a code is used: the plaintext is deleted at once and the message closes."""
    q = db.query(WhatsappMessage).filter(
        WhatsappMessage.is_secret == True, WhatsappMessage.secret_enc.isnot(None),  # noqa: E712
        WhatsappMessage.recipient_kind == recipient_kind, WhatsappMessage.recipient_id == recipient_id,
    )
    if template_keys:
        q = q.filter(WhatsappMessage.template_key.in_(list(template_keys)))
    now = now_ist_naive()
    count = 0
    for row in q.all():
        row.secret_enc = None
        if row.status in OPEN_STATUSES:
            row.prev_status, row.status, row.status_changed_at = None, "expired", now
        count += 1
    return count


# ---------------------------------------------------------------------------
# Scheduler job (called from app/scheduler.py)
# ---------------------------------------------------------------------------
def run_message_maintenance(db: Session) -> dict:
    """1) scheduled -> due when their time arrives; 2) open messages past expires_at -> expired;
    3) delete the plaintext of every secret that is closed (after the short Undo window) or expired."""
    now = now_ist_naive()
    base = db.query(WhatsappMessage).filter(WhatsappMessage.is_sample == False)  # noqa: E712

    try:  # appointment token messages are rebuilt with the real token and room just before they become due
        from app.services.whatsapp_appointments import refresh_due_token_messages
        refresh_due_token_messages(db, now)
    except Exception:
        logger.exception("Token message refresh failed")

    moved = base.filter(WhatsappMessage.status == "scheduled", WhatsappMessage.due_at <= now).update(
        {WhatsappMessage.status: "due", WhatsappMessage.status_changed_at: now}, synchronize_session=False)

    expired = 0
    for row in base.filter(WhatsappMessage.status.in_(OPEN_STATUSES), WhatsappMessage.expires_at.isnot(None),
                           WhatsappMessage.expires_at <= now).all():
        row.prev_status, row.status, row.status_changed_at = None, "expired", now
        row.secret_enc = None
        expired += 1

    undo_cutoff = now - timedelta(seconds=max(0, settings.WHATSAPP_UNDO_WINDOW_SECONDS))
    wiped = base.filter(
        WhatsappMessage.secret_enc.isnot(None), WhatsappMessage.status.in_(CLOSED_STATUSES),
        (WhatsappMessage.status_changed_at.is_(None)) | (WhatsappMessage.status_changed_at <= undo_cutoff),
    ).update({WhatsappMessage.secret_enc: None}, synchronize_session=False)
    db.commit()
    return {"due": moved, "expired": expired, "wiped": wiped}


# ---------------------------------------------------------------------------
# >>> AUTOMATIC SENDER PLUGS IN HERE <<<
# After Meta approval (via a third-party provider), take the rows with status "due" or "pending"
# (is_sample == False), send each one by API, then mark it sent with sent_marked_by = NULL.
# Nothing is sent today; this function is deliberately empty and is not called anywhere.
# ---------------------------------------------------------------------------
def dispatch_due_messages(db: Session) -> None:
    return None