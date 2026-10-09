import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000)
    return f"pbkdf2_sha256$600000${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt, digest = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt), int(iterations)
        )
        return hmac.compare_digest(actual, bytes.fromhex(digest))
    except (ValueError, TypeError):
        return False


def create_token(
    user_id: int, token_type: str, secret: str, lifetime: timedelta,
    *, session_id: str | None = None, token_id: str | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    claims = {
            "sub": str(user_id),
            "iss": "footmarks",
            "type": token_type,
            "iat": now,
            "exp": now + lifetime,
        }
    if session_id is not None:
        claims["sid"] = session_id
    if token_id is not None:
        claims["jti"] = token_id
    return jwt.encode(claims, secret, algorithm="HS256")


def token_claims(token: str, expected_type: str, secret: str) -> dict | None:
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            issuer="footmarks",
            options={"require": ["sub", "iss", "type", "exp", "iat"]},
        )
        if claims["type"] != expected_type:
            return None
        int(claims["sub"])
        return claims
    except (jwt.InvalidTokenError, ValueError, TypeError):
        return None


def read_token(token: str, expected_type: str, secret: str) -> int | None:
    claims = token_claims(token, expected_type, secret)
    return int(claims["sub"]) if claims is not None else None
