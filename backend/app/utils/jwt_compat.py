"""JWT encode/decode on PyJWT with the SAME token format, algorithm, claims and expiry as the
old python-jose code, so every token already issued stays valid.

Same as jose: datetime exp/iat are written as integer seconds, and "iat" is not
checked against the clock on decode (PyJWT would reject a token whose iat is a moment in the future).
JWTError is the one exception callers catch for any bad, expired or tampered token."""
import jwt as _pyjwt

JWTError = _pyjwt.PyJWTError


class _Jwt:
    @staticmethod
    def encode(claims: dict, key: str, algorithm: str = "HS256") -> str:
        return _pyjwt.encode(claims, key, algorithm=algorithm)

    @staticmethod
    def decode(token, key: str, algorithms=None, **kwargs) -> dict:
        if not isinstance(token, (str, bytes)):
            raise _pyjwt.DecodeError("Not a token")
        return _pyjwt.decode(token, key, algorithms=algorithms, options={"verify_iat": False})


jwt = _Jwt()