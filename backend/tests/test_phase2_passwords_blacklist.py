import pytest
from fastapi import HTTPException

from app.utils.auth import check_password_strength, hash_token, blacklist_token, is_token_blacklisted
from app.utils.timezone import now_ist_naive


def _msg(password, **kw):
    with pytest.raises(HTTPException) as e:
        check_password_strength(password, **kw)
    assert e.value.status_code == 400
    return e.value.detail


def test_old_rule_still_enforced():
    assert "8 characters" in _msg("Ab1")
    assert "8 characters" in _msg("alllowercase1")
    assert "8 characters" in _msg("NoDigitsHere")


def test_common_passwords_rejected():
    for pw in ("Password1", "P@ssw0rd", "Welcome@123", "Summer2024", "Qwerty123", "Medscribe2026"):
        assert "too common" in _msg(pw)


def test_strong_password_accepted():
    check_password_strength("Xk9#mVq2Lp")
    check_password_strength("Tiger!Lamp#Cloud7")


def test_password_with_email_name_or_phone_rejected():
    assert "must not contain" in _msg("Zq7#praful99", email="prafulb504@gmail.com", name="Dr. Praful B")
    assert "must not contain" in _msg("Zq7#Anitha88", name="Anitha Rao")
    assert "must not contain" in _msg("Zq79876543210", extras=("98765 43210",))
    check_password_strength("Zq7#mVLp88", email="a@b.co", name="Anitha Rao", extras=("9876543210",))


def test_blacklist_stores_only_the_hash(db):
    from app.models.blacklisted_token import BlacklistedToken
    blacklist_token("tok-abc", db)
    row = db.query(BlacklistedToken).filter(BlacklistedToken.token_hash == hash_token("tok-abc")).first()
    assert row is not None and row.token is None
    assert is_token_blacklisted("tok-abc", db)
    assert not is_token_blacklisted("tok-other", db)


def test_old_raw_row_still_blocks_during_transition(db):
    from app.models.blacklisted_token import BlacklistedToken
    db.add(BlacklistedToken(token="legacy-token", blacklisted_at=now_ist_naive()))
    db.commit()
    assert is_token_blacklisted("legacy-token", db)