import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta

import pytest

from app.config import settings
from app.utils.jwt_compat import jwt, JWTError


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _old_style_token(claims: dict, key: str) -> str:
    """Builds a token byte-for-byte the way python-jose did (HS256, integer exp/iat)."""
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64(json.dumps(claims, separators=(",", ":")).encode())
    sig = _b64(hmac.new(key.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest())
    return f"{header}.{body}.{sig}"


def test_token_made_by_old_code_still_decodes():
    now = int(time.time())
    token = _old_style_token({"sub": "7", "role": "doctor", "iat": now, "exp": now + 600}, settings.SECRET_KEY)
    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    assert payload["sub"] == "7" and payload["role"] == "doctor"


def test_token_with_iat_slightly_in_future_still_decodes():
    now = int(time.time())
    token = _old_style_token({"sub": "7", "iat": now + 30, "exp": now + 600}, settings.SECRET_KEY)
    assert jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])["sub"] == "7"


def test_new_tokens_have_same_shape_and_round_trip():
    now = datetime.utcnow()
    token = jwt.encode({"sub": "9", "iat": now, "exp": now + timedelta(minutes=5)}, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    header = json.loads(base64.urlsafe_b64decode(token.split(".")[0] + "=="))
    assert header == {"alg": "HS256", "typ": "JWT"}
    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    assert isinstance(payload["exp"], int) and isinstance(payload["iat"], int)
    # a token made now is readable by the old format rules too (same signature input)
    assert _old_style_token({"sub": "9", "iat": payload["iat"], "exp": payload["exp"]}, settings.SECRET_KEY).split(".")[0] == token.split(".")[0]


def test_expired_wrong_key_and_garbage_raise_jwterror():
    now = int(time.time())
    expired = _old_style_token({"sub": "1", "exp": now - 10}, settings.SECRET_KEY)
    with pytest.raises(JWTError):
        jwt.decode(expired, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    good = _old_style_token({"sub": "1", "exp": now + 100}, settings.SECRET_KEY)
    with pytest.raises(JWTError):
        jwt.decode(good, "another-key-another-key-another-key-123", algorithms=[settings.ALGORITHM])
    for bad in ("x", "a.b.c", "", None):
        with pytest.raises(JWTError):
            jwt.decode(bad, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


def test_app_token_helpers_round_trip():
    from app.utils.auth import create_access_token, decode_access_token
    token = create_access_token({"sub": "3", "role": "admin"})
    payload = decode_access_token(token)
    assert payload["sub"] == "3" and payload["role"] == "admin" and "iat" in payload
    assert decode_access_token("garbage") is None