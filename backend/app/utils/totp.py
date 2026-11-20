"""TOTP (RFC 6238) for Super Admin 2FA, with no extra dependency.
Secrets are stored encrypted with TOTP_ENC_KEY (MultiFernet, newest first). Values written
before TOTP_ENC_KEY existed use a key derived from SECRET_KEY; that key is always tried on read,
so nothing breaks. If TOTP_ENC_KEY is unset, new writes use the SECRET_KEY-derived key as before.
Run scripts/rotate_totp_keys.py to move every stored secret to the newest key.
This is separate from, and does not touch, the QR verification hash derivation."""
import base64
import hashlib
import hmac
import io
import os
import secrets
import struct
import time
from urllib.parse import quote

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.config import settings

TOTP_ISSUER = settings.BRAND_NAME
_STEP_SECONDS = 30
_BACKUP_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _legacy_fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(f"totp-secret-v1:{settings.SECRET_KEY}".encode()).digest())
    return Fernet(key)


def _fernet() -> MultiFernet:
    """Encrypts with the first key (TOTP_ENC_KEY if set, else the old SECRET_KEY-derived key).
    Decrypts with any of them."""
    from app.config import parse_key_list
    fernets = [Fernet(k.encode()) for k in parse_key_list(settings.TOTP_ENC_KEY)]
    fernets.append(_legacy_fernet())
    return MultiFernet(fernets)


def generate_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode()


def encrypt_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def decrypt_secret(token):
    if not token:
        return None
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return None


def rotate_secret_token(token):
    """Re-encrypts a stored token with the newest key. Returns the new token, or None if it cannot be read."""
    if not token:
        return None
    try:
        return _fernet().rotate(token.encode()).decode()
    except (InvalidToken, ValueError):
        return None


def _hotp(secret: str, counter: int) -> str:
    key = base64.b32decode(secret.upper() + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{number:06d}"


def verify_code(secret: str, code: str, last_step=None):
    """Returns the matched time-step (store it as last_step to block replay), or None."""
    code = (code or "").strip().replace(" ", "")
    if len(code) != 6 or not code.isdigit():
        return None
    now_step = int(time.time() // _STEP_SECONDS)
    for step in (now_step - 1, now_step, now_step + 1):
        if last_step is not None and step <= last_step:
            continue
        if hmac.compare_digest(_hotp(secret, step), code):
            return step
    return None


def provisioning_uri(secret: str, email: str) -> str:
    label = quote(f"{TOTP_ISSUER}:{email}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(TOTP_ISSUER)}&algorithm=SHA1&digits=6&period=30"


def qr_data_uri(uri: str) -> str:
    import qrcode
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _norm(code: str) -> str:
    return (code or "").strip().upper().replace("-", "").replace(" ", "")


def _hash_backup(code: str) -> str:
    return hashlib.sha256(f"totp-backup-v1:{_norm(code)}".encode()).hexdigest()


def make_backup_codes(n: int = 8):
    """Returns (plain codes to show once, hashes to store)."""
    codes = []
    for _ in range(n):
        raw = "".join(secrets.choice(_BACKUP_ALPHABET) for _ in range(10))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes, [_hash_backup(c) for c in codes]


def consume_backup_code(code: str, hashes: list):
    """Returns the remaining hashes if the code was valid (it is now spent), else None."""
    h = _hash_backup(code)
    for existing in hashes:
        if hmac.compare_digest(existing, h):
            return [x for x in hashes if x != existing]
    return None