"""Prints every super_admin account whose 2FA is not enabled (totp_enabled is false or empty).

    python scripts/list_superadmins_without_2fa.py
    python scripts/list_superadmins_without_2fa.py --database-url "postgresql://user:pass@host/db"

Read only. Exit code 1 if any account is listed, 0 if every super admin has 2FA.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _db_url(argv):
    rest = list(argv[1:])
    while rest:
        a = rest.pop(0)
        if a == "--database-url":
            return rest.pop(0) if rest else None
        if a.startswith("--database-url="):
            return a.split("=", 1)[1]
    return None


_URL = _db_url(sys.argv)
if _URL:
    if _URL.startswith("postgres://"):
        _URL = "postgresql://" + _URL[len("postgres://"):]
    os.environ["DATABASE_URL"] = _URL  # must be set before the app modules below are imported

import app.models  # noqa: E402,F401  (registers every model)
from app.database import SessionLocal, engine  # noqa: E402
from app.models.doctor import Doctor, UserRole  # noqa: E402


def main():
    print("Database:", engine.url.render_as_string(hide_password=True))
    db = SessionLocal()
    try:
        rows = db.query(Doctor).filter(Doctor.role == UserRole.super_admin, Doctor.totp_enabled.isnot(True)).all()
        if not rows:
            print("OK: every super admin has 2FA enabled.")
            return 0
        print("Super admins WITHOUT 2FA:")
        for d in rows:
            print(f"  id={d.id}  email={d.email}  name={d.name}  active={d.is_active}")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())