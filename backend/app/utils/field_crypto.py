"""Field-level encryption for a few sensitive columns (Phase 7).

Values are stored as  enc:v1:<fernet token>  using DATA_ENC_KEYS (comma-separated, newest first).
- DATA_ENC_KEYS empty: new values are stored as plain text (nothing changes).
- A plain old value (no prefix) is returned unchanged, so existing rows keep working.
- Any key in the list can read; the first key writes.
"""
import logging
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from sqlalchemy.types import Text, TypeDecorator

from app.config import parse_key_list, settings

log = logging.getLogger(__name__)

PREFIX = "enc:v1:"
UNREADABLE = "[encrypted - key missing]"


def _multi() -> Optional[MultiFernet]:
    fernets = []
    for key in parse_key_list(settings.DATA_ENC_KEYS):
        try:
            fernets.append(Fernet(key.encode()))
        except Exception:
            log.error("A DATA_ENC_KEYS entry is not a valid Fernet key and is ignored.")
    return MultiFernet(fernets) if fernets else None


def is_encrypted(value) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


def encrypt_value(value):
    """Plain text in, stored form out. None, empty text and already-encrypted values pass through."""
    if value is None or value == "" or is_encrypted(value):
        return value
    multi = _multi()
    if multi is None:
        return value
    return PREFIX + multi.encrypt(str(value).encode("utf-8")).decode("ascii")


def decrypt_value(value):
    """Stored form in, plain text out. A plain old value is returned unchanged."""
    if not is_encrypted(value):
        return value
    multi = _multi()
    if multi is None:
        log.error("An encrypted value was read but DATA_ENC_KEYS is not set.")
        return UNREADABLE
    try:
        return multi.decrypt(value[len(PREFIX):].encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        log.error("An encrypted value could not be read with any key in DATA_ENC_KEYS.")
        return UNREADABLE


def rotate_value(value):
    """Re-encrypts an encrypted value with the newest key. Returns None if it is not encrypted or cannot be read."""
    if not is_encrypted(value):
        return None
    multi = _multi()
    if multi is None:
        return None
    try:
        return PREFIX + multi.rotate(value[len(PREFIX):].encode("ascii")).decode("ascii")
    except (InvalidToken, ValueError):
        return None


class EncryptedText(TypeDecorator):
    """A Text column that encrypts on write and decrypts on read."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return encrypt_value(value)

    def process_result_value(self, value, dialect):
        return decrypt_value(value)