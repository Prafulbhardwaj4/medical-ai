"""Recovery path for a locked-out Super Admin. Needs database access, so it can run from your laptop:

    python scripts/reset_superadmin_2fa.py superadmin@example.com
    python scripts/reset_superadmin_2fa.py superadmin@example.com --database-url "postgresql://user:pass@host/db"

The database comes from --database-url, else the DATABASE_URL environment variable, else .env.
The script prints which database it is about to touch and asks you to type RESET before it changes anything.
Clears that account's 2FA. They sign in with their password and set up 2FA again. The reset is audited.
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
    print('Usage: python scripts/reset_superadmin_2fa.py <super-admin-email> [--database-url "<url>"]')
    sys.exit(1)
if _DB_URL:
    if _DB_URL.startswith("postgres://"):
        _DB_URL = "postgresql://" + _DB_URL[len("postgres://"):]
    os.environ["DATABASE_URL"] = _DB_URL  # must be set before the app modules below are imported

import app.models  # noqa: E402,F401  (registers every model)
from app.database import SessionLocal  # noqa: E402
from app.models.doctor import Doctor  # noqa: E402
from app.utils.audit import log_action  # noqa: E402


def main():
    from app.database import engine
    email = _EMAIL.strip().lower()
    target = engine.url.render_as_string(hide_password=True)
    db = SessionLocal()
    try:
        doctor = db.query(Doctor).filter(Doctor.email == email).first()
        if not doctor or doctor.role.value != "super_admin":
            print("No super admin found with that email.")
            sys.exit(1)
        print(f"Database: {target}")
        print(f"Account:  {doctor.email}")
        if input("Type RESET to clear this super admin's 2FA, anything else cancels: ").strip() != "RESET":
            print("Cancelled. Nothing was changed.")
            sys.exit(1)
        doctor.totp_secret_enc = None
        doctor.totp_enabled = False
        doctor.totp_backup_codes = None
        doctor.totp_last_step = None
        doctor.failed_login_attempts = 0
        doctor.locked_until = None
        db.commit()
        log_action(db, None, action="totp_reset_by_script", target_type="doctor", target_id=doctor.id,
                   target_label=doctor.email, details=f"2FA cleared with the recovery script; database={target}", hospital_id=None)
        print(f"2FA cleared for {email}. They must set it up again at next login.")
    finally:
        db.close()


if __name__ == "__main__":
    main()