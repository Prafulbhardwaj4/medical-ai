"""Checks the strength of the secrets in the environment. Prints PASS / FAIL / SKIP per name.
It NEVER prints a secret value.

    python scripts/check_secrets_strength.py

Reads the environment (and backend/.env if python-dotenv is installed). Exit code 1 if any FAIL.
"""
import hashlib
import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
except Exception:
    pass

MIN_LEN = 32
WEAK = {"", "changeme", "changeme-invite-secret", "your_secret_key_here", "secret", "password"}

failures = 0
seen = {}  # sha256 of value -> first name that used it


def _split(value):
    return [p.strip() for p in (value or "").split(",") if p.strip()]


def _report(name, ok, reason=""):
    global failures
    if ok:
        print(f"PASS  {name}")
    else:
        failures += 1
        print(f"FAIL  {name}: {reason}")


def _strong(value):
    lowered = value.lower()
    if lowered in WEAK or "changeme" in lowered or "your_secret" in lowered:
        return "is a default or placeholder value"
    if len(value) < MIN_LEN:
        return f"is shorter than {MIN_LEN} characters"
    if len(set(value)) < 10:
        return "has too few different characters"
    return ""


def _note_unique(name, values):
    """Two different settings must not share a value."""
    for v in values:
        h = hashlib.sha256(v.encode()).hexdigest()
        if h in seen and seen[h] != name:
            _report(name, False, f"has the same value as {seen[h]}")
            return False
        seen.setdefault(h, name)
    return True


def check_secret(name, required=True):
    value = os.environ.get(name, "")
    if not value:
        if required:
            _report(name, False, "is not set")
        else:
            print(f"SKIP  {name} (not set)")
        return
    problem = _strong(value)
    if problem:
        _report(name, False, problem)
    elif _note_unique(name, [value]):
        _report(name, True)


def check_fernet(name, required=False):
    try:
        from cryptography.fernet import Fernet
    except Exception:
        print(f"SKIP  {name} (cryptography is not installed)")
        return
    keys = _split(os.environ.get(name, ""))
    if not keys:
        if required:
            _report(name, False, "is not set")
        else:
            print(f"SKIP  {name} (not set)")
        return
    for k in keys:
        try:
            Fernet(k.encode())
        except Exception:
            _report(name, False, "contains a value that is not a valid Fernet key")
            return
    if _note_unique(name, keys):
        _report(name, True)


def main():
    check_secret("SECRET_KEY")
    check_secret("PORTAL_INVITE_SECRET")
    check_secret("QR_HASH_KEY", required=False)

    sa = os.environ.get("SUPER_ADMIN_KEY", "")
    if not sa:
        print("PASS  SUPER_ADMIN_KEY (empty: create-superadmin is disabled)")
    else:
        problem = _strong(sa)
        if problem:
            _report("SUPER_ADMIN_KEY", False, problem)
        elif _note_unique("SUPER_ADMIN_KEY", [sa]):
            _report("SUPER_ADMIN_KEY", True)

    wa_single = _split(os.environ.get("WHATSAPP_MESSAGES_KEY", ""))
    wa_list = _split(os.environ.get("WHATSAPP_MESSAGES_KEYS", ""))
    if not wa_single and not wa_list:
        _report("WHATSAPP_MESSAGES_KEY(S)", False, "neither is set")
    else:
        check_fernet("WHATSAPP_MESSAGES_KEY")
        check_fernet("WHATSAPP_MESSAGES_KEYS")
    check_fernet("TOTP_ENC_KEY")
    check_fernet("DATA_ENC_KEYS")

    print("Result:", "FAIL" if failures else "PASS")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()