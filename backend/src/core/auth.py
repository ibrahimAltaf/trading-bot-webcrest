"""Auth helpers: password hashing and JWT."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

import jwt

from src.core.config import get_settings

try:
    # passlib 1.7.4 breaks with bcrypt>=4.1 (detect_wrap_bug / __about__).
    # Prefer direct bcrypt; fall back to passlib when available.
    import bcrypt

    def hash_password(plain: str) -> str:
        return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    def verify_password(plain: str, hashed: str) -> bool:
        try:
            return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
        except Exception:
            return False

except Exception:  # pragma: no cover
    from passlib.context import CryptContext

    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    def hash_password(plain: str) -> str:
        return pwd_context.hash(plain)

    def verify_password(plain: str, hashed: str) -> bool:
        return pwd_context.verify(plain, hashed)


def create_access_token(sub: str, payload: Optional[dict] = None) -> str:
    s = get_settings()
    expire = datetime.utcnow() + timedelta(minutes=s.jwt_expire_minutes)
    data = {"sub": str(sub), "exp": expire}
    if payload:
        data.update(payload)
    return jwt.encode(
        data,
        s.jwt_secret,
        algorithm=s.jwt_algorithm,
    )


def decode_access_token(token: str) -> Optional[dict[str, Any]]:
    try:
        s = get_settings()
        return jwt.decode(
            token,
            s.jwt_secret,
            algorithms=[s.jwt_algorithm],
        )
    except Exception:
        return None
