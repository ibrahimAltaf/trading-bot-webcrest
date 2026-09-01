"""Auth helpers: password hashing and JWT."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

import jwt
from passlib.context import CryptContext

from src.core.config import get_settings

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
