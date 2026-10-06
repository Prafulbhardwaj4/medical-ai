"""Recovery path for a locked-out Super Admin. Run on the server (needs database access):

    python scripts/reset_superadmin_2fa.py superadmin@example.com

Clears that account's 2FA. They sign in with their password and set up 2FA again.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.models  # noqa: E402,F401  (registers every model)
from app.database import SessionLocal  # noqa: E402
from app.models.doctor import Doctor  # noqa: E402
from app.utils.audit import log_action  # noqa: E402


def main():
    if len(sys.argv) != 2:
        print("Usage: python scripts/reset_superadmin_2fa.py <super-admin-email>")
        sys.exit(1)
    email = sys.argv[1].strip().lower()
    db = SessionLocal()
    try:
        doctor = db.query(Doctor).filter(Doctor.email == email).first()
        if not doctor or doctor.role.value != "super_admin":
            print("No super admin found with that email.")
            sys.exit(1)
        doctor.totp_secret_enc = None
        doctor.totp_enabled = False
        doctor.totp_backup_codes = None
        doctor.totp_last_step = None
        doctor.failed_login_attempts = 0
        doctor.locked_until = None
        db.commit()
        log_action(db, None, action="totp_reset_by_script", target_type="doctor", target_id=doctor.id,
                   target_label=doctor.email, details="2FA cleared with the recovery script", hospital_id=None)
        print(f"2FA cleared for {email}. They must set it up again at next login.")
    finally:
        db.close()


if __name__ == "__main__":
    main()