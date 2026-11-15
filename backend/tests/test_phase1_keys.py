import hashlib

import pytest
from cryptography.fernet import Fernet

from app.config import settings, parse_key_list, log_startup_warnings


def test_parse_key_list_order_and_dedupe():
    assert parse_key_list("a, b", "b,c", "", None) == ["a", "b", "c"]


def test_totp_old_secret_still_readable_after_new_key(monkeypatch):
    from app.utils import totp
    monkeypatch.setattr(settings, "TOTP_ENC_KEY", "")
    old = totp.encrypt_secret("JBSWY3DPEHPK3PXP")
    new_key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "TOTP_ENC_KEY", new_key)
    assert totp.decrypt_secret(old) == "JBSWY3DPEHPK3PXP"
    fresh = totp.encrypt_secret("JBSWY3DPEHPK3PXP")
    assert Fernet(new_key.encode()).decrypt(fresh.encode()).decode() == "JBSWY3DPEHPK3PXP"
    rotated = totp.rotate_secret_token(old)
    assert Fernet(new_key.encode()).decrypt(rotated.encode()).decode() == "JBSWY3DPEHPK3PXP"


def test_totp_unset_key_behaves_as_before(monkeypatch):
    from app.utils import totp
    monkeypatch.setattr(settings, "TOTP_ENC_KEY", "")
    token = totp.encrypt_secret("ABCDEFGH")
    assert totp.decrypt_secret(token) == "ABCDEFGH"
    assert totp.decrypt_secret("not-a-token") is None


def test_qr_unset_key_equals_old_formula(monkeypatch):
    from app.utils.receipts import generate_verify_hash
    monkeypatch.setattr(settings, "QR_HASH_KEY", "")
    expected = hashlib.sha256(f"invoice-5-2-{settings.SECRET_KEY}".encode()).hexdigest()[:16].upper()
    assert generate_verify_hash(5, 2) == expected


def test_qr_new_key_and_old_hash_both_verify(monkeypatch):
    from app.utils.receipts import generate_verify_hash
    from app.utils.qr_hash import qr_hash_matches
    monkeypatch.setattr(settings, "QR_HASH_KEY", "")
    legacy = generate_verify_hash(5, 2)
    monkeypatch.setattr(settings, "QR_HASH_KEY", "q" * 40)
    new = generate_verify_hash(5, 2)
    assert new != legacy
    assert qr_hash_matches("invoice-5-2", new)
    assert qr_hash_matches("invoice-5-2", legacy)
    assert not qr_hash_matches("invoice-5-2", "0" * 16)
    assert not qr_hash_matches("invoice-5-2", "")


def test_whatsapp_key_list_reads_old_single_key(monkeypatch):
    from app.services import whatsapp_messages as wa
    old = Fernet.generate_key().decode()
    new = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "WHATSAPP_MESSAGES_KEYS", "")
    monkeypatch.setattr(settings, "WHATSAPP_MESSAGES_KEY", old)
    token = wa._fernet().encrypt(b"hello")
    monkeypatch.setattr(settings, "WHATSAPP_MESSAGES_KEYS", new)
    f = wa._fernet()
    assert f.decrypt(token) == b"hello"
    assert Fernet(new.encode()).decrypt(f.encrypt(b"x")) == b"x"


def test_invalid_key_stops_production_but_only_warns_in_dev():
    bad_prod = settings.model_copy(update={"TOTP_ENC_KEY": "not-a-key", "DATABASE_URL": "postgresql://u:p@h/db"})
    with pytest.raises(RuntimeError):
        log_startup_warnings(bad_prod)
    bad_dev = settings.model_copy(update={"TOTP_ENC_KEY": "not-a-key", "DATABASE_URL": "sqlite:///./x.db"})
    log_startup_warnings(bad_dev)