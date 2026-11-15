"""Re-encrypts every stored 2FA secret with the newest TOTP_ENC_KEY.

    python scripts/rotate_totp_keys.py --dry-run     (shows what would change, writes nothing)
    python scripts/rotate_totp_keys.py               (does it)

Needs TOTP_ENC_KEY set (newest key first if you give a comma-separated list). The old
SECRET_KEY-derived key and any older TOTP_ENC_KEY values still in the list are used to READ.
Secrets that cannot be read with any key are listed and left untouched.
Database comes from DATABASE_URL (environment or .env).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.models  # noqa: E402,F401  (registers every model)
from app.config import parse_key_list, settings  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.models.doctor import Doctor  # noqa: E402
from app.utils import totp as totp_util  # noqa: E402


def main():
    dry = "--dry-run" in sys.argv[1:]
    if not parse_key_list(settings.TOTP_ENC_KEY):
        print("TOTP_ENC_KEY is not set. Set it first, then run this again.")
        sys.exit(1)
    print("Database:", engine.url.render_as_string(hide_password=True))
    db = SessionLocal()
    changed = 0
    unreadable = []
    try:
        rows = db.query(Doctor).filter(Doctor.totp_secret_enc.isnot(None)).all()
        for doctor in rows:
            new_token = totp_util.rotate_secret_token(doctor.totp_secret_enc)
            if new_token is None:
                unreadable.append(doctor.id)
                continue
            if not dry:
                doctor.totp_secret_enc = new_token
            changed += 1
        if dry:
            db.rollback()
        else:
            db.commit()
    finally:
        db.close()
    print(f"{'Would re-encrypt' if dry else 'Re-encrypted'} {changed} secret(s).")
    if unreadable:
        print("Could not read (left untouched), doctor ids:", ", ".join(str(i) for i in unreadable))
        sys.exit(2)


if __name__ == "__main__":
    main()