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


def create_token(user_id: int, token_type: str, secret: str, lifetime: timedelta) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(user_id),
            "iss": "footmarks",
            "type": token_type,
            "iat": now,
            "exp": now + lifetime,
        },
        secret,
        algorithm="HS256",
    )


def read_token(token: str, expected_type: str, secret: str) -> int | None:
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
        return int(claims["sub"])
    except (jwt.InvalidTokenError, ValueError, TypeError):
        return None
