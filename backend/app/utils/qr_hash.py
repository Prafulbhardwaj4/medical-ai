"""QR / verification hash helpers (one place).

New hashes use QR_HASH_KEY when it is set, otherwise SECRET_KEY (today's behaviour).
Verification accepts BOTH the new-key hash and the old SECRET_KEY hash, so every printed
QR code keeps working. The hash format is unchanged: sha256("<prefix>-<key>")[:16].upper()."""
import hashlib
import hmac

from app.config import settings


def _digest(prefix: str, key: str) -> str:
    return hashlib.sha256(f"{prefix}-{key}".encode()).hexdigest()[:16].upper()


def qr_hash(prefix: str) -> str:
    """Hash for NEW QR codes."""
    key = (settings.QR_HASH_KEY or "").strip() or settings.SECRET_KEY
    return _digest(prefix, key)


def qr_hash_candidates(prefix: str) -> list:
    """Every hash that is valid for this prefix: new key first (if set), then the old SECRET_KEY one."""
    out = []
    new_key = (settings.QR_HASH_KEY or "").strip()
    if new_key:
        out.append(_digest(prefix, new_key))
    legacy = _digest(prefix, settings.SECRET_KEY)
    if legacy not in out:
        out.append(legacy)
    return out


def hash_equals(stored, supplied) -> bool:
    """Constant-time comparison of a stored verification hash with the one the caller supplied."""
    if not stored:
        return False
    return hmac.compare_digest(str(stored).encode("utf-8"), str(supplied or "").encode("utf-8"))


def qr_hash_matches(prefix: str, supplied) -> bool:
    """Constant-time check of a supplied hash against the new and the old hash."""
    given = str(supplied or "").encode("utf-8")
    ok = False
    for candidate in qr_hash_candidates(prefix):
        if hmac.compare_digest(candidate.encode("utf-8"), given):
            ok = True
    return ok