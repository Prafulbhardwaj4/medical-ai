"""Issues a one-time 2FA enrolment code for ONE super admin account.

    python scripts/issue_totp_enrolment_code.py superadmin@example.com
    python scripts/issue_totp_enrolment_code.py superadmin@example.com --database-url "postgresql://user:pass@host/db"

The code is shown once, stored only as a hash, works once, and expires in 24 hours. Issuing a new code
cancels any earlier unused one. The database comes from --database-url, else DATABASE_URL, else .env.
The issue is audited.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _parse_args(argv):
    email, url, rest = None, None, list(argv[1:])
    while rest:
        a = rest.pop(0)
        if a == "--database-url":
            url = rest.pop(0) if rest else None
        elif a.startswith("--database-url="):
            url = a.split("=", 1)[1]
        elif email is None:
            email = a
    return email, url


_EMAIL, _DB_URL = _parse_args(sys.argv)
if not _EMAIL:
    print('Usage: python scripts/issue_totp_enrolment_code.py <super-admin-email> [--database-url "<url>"]')
    sys.exit(1)
if _DB_URL:
    if _DB_URL.startswith("postgres://"):
        _DB_URL = "postgresql://" + _DB_URL[len("postgres://"):]
    os.environ["DATABASE_URL"] = _DB_URL  # must be set before the app modules below are imported

import app.models  # noqa: E402,F401  (registers every model)
from app.database import SessionLocal, engine  # noqa: E402
from app.models.doctor import Doctor  # noqa: E402
from app.services.totp_enrolment import issue_enrolment_code, CODE_VALID_HOURS  # noqa: E402
from app.utils.audit import log_action  # noqa: E402


def main():
    email = _EMAIL.strip().lower()
    target = engine.url.render_as_string(hide_password=True)
    db = SessionLocal()
    try:
        doctor = db.query(Doctor).filter(Doctor.email == email).first()
        if not doctor or doctor.role.value != "super_admin":
            print("No super admin found with that email.")
            sys.exit(1)
        if doctor.totp_enabled:
            print("This account already has 2FA. To redo it, run scripts/reset_superadmin_2fa.py first.")
            sys.exit(1)
        code = issue_enrolment_code(db, doctor)
        log_action(db, None, action="totp_enrolment_code_issued", target_type="doctor", target_id=doctor.id,
                   target_label=doctor.email, details=f"one-time code issued by script; database={target}", hospital_id=None)
        print(f"Database: {target}")
        print(f"Account:  {doctor.email}")
        print(f"Enrolment code (shown once, valid {CODE_VALID_HOURS} hours, single use): {code}")
    finally:
        db.close()


if __name__ == "__main__":
    main()