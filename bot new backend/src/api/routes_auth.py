"""
Auth & Exchange config API.
- Register, Login (JWT), Me
- Exchange config: get/put (per user, CCXT-style: exchange_id, testnet, api_key, api_secret)
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from src.core.auth import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from src.db.session import SessionLocal
from src.db.models import User, ExchangeConfig

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------- DTOs ----------
class RegisterIn(BaseModel):
    email: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=6, max_length=128)
    name: Optional[str] = Field(None, max_length=128)


class LoginIn(BaseModel):
    email: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class ExchangeConfigIn(BaseModel):
    exchange_id: str = Field(default="binance", max_length=32)
    testnet: bool = Field(default=True)
    api_key: str = Field(default="", max_length=512)
    api_secret: str = Field(default="", max_length=512)


# ---------- Dependency: get current user from Authorization header ----------
def get_current_user_id(authorization: Optional[str] = Header(None, alias="Authorization")) -> int:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.replace("Bearer ", "").strip()
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    try:
        return int(payload["sub"])
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid token")


# ---------- Endpoints ----------
@router.post("/register")
def register(body: RegisterIn):
    """Create a new user account."""
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == body.email.strip().lower()).first()
        if existing:
            raise HTTPException(status_code=400, detail="Email already registered")
        user = User(
            email=body.email.strip().lower(),
            password_hash=hash_password(body.password),
            name=(body.name or "").strip() or None,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        token = create_access_token(str(user.id))
        return {
            "ok": True,
            "user": {
                "id": user.id,
                "email": user.email,
                "name": user.name,
            },
            "token": token,
        }
    finally:
        db.close()


@router.post("/login")
def login(body: LoginIn):
    """Login and return JWT."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == body.email.strip().lower()).first()
        if not user or not verify_password(body.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid email or password")
        token = create_access_token(str(user.id))
        return {
            "ok": True,
            "user": {
                "id": user.id,
                "email": user.email,
                "name": user.name,
            },
            "token": token,
        }
    finally:
        db.close()


@router.get("/me")
def me(authorization: Optional[str] = Header(None, alias="Authorization")):
    """Return current user (requires Authorization: Bearer <token>)."""
    user_id = get_current_user_id(authorization)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return {
            "ok": True,
            "user": {
                "id": user.id,
                "email": user.email,
                "name": user.name,
            },
        }
    finally:
        db.close()


def _get_exchange_config(authorization: Optional[str]) -> tuple[int, Optional[ExchangeConfig]]:
    user_id = get_current_user_id(authorization)
    db = SessionLocal()
    try:
        config = db.query(ExchangeConfig).filter(ExchangeConfig.user_id == user_id).first()
        return user_id, config
    finally:
        db.close()


@router.get("/exchange-config")
def get_exchange_config(authorization: Optional[str] = Header(None, alias="Authorization")):
    """Get current user's exchange config (keys masked)."""
    user_id, config = _get_exchange_config(authorization)
    if not config:
        return {
            "ok": True,
            "exchange_id": "binance",
            "testnet": True,
            "api_key_set": False,
            "api_secret_set": False,
        }
    return {
        "ok": True,
        "exchange_id": config.exchange_id,
        "testnet": config.testnet,
        "api_key_set": bool(config.api_key),
        "api_secret_set": bool(config.api_secret),
    }


@router.put("/exchange-config")
def put_exchange_config(body: ExchangeConfigIn, authorization: Optional[str] = Header(None, alias="Authorization")):
    """Save exchange connection (CCXT-style): exchange_id, testnet, api_key, api_secret."""
    user_id = get_current_user_id(authorization)
    db = SessionLocal()
    try:
        config = db.query(ExchangeConfig).filter(ExchangeConfig.user_id == user_id).first()
        if not config:
            config = ExchangeConfig(user_id=user_id)
            db.add(config)
        config.exchange_id = (body.exchange_id or "binance").strip().lower()
        config.testnet = body.testnet
        if body.api_key and body.api_key.strip():
            config.api_key = body.api_key.strip()
        if body.api_secret and body.api_secret.strip():
            from src.core.config import get_settings as _gs
            from src.core.secrets_crypto import encrypt_optional

            _s = _gs()
            config.api_secret = encrypt_optional(
                body.api_secret.strip(), _s.secrets_encryption_key
            )
        db.commit()
        return {
            "ok": True,
            "exchange_id": config.exchange_id,
            "testnet": config.testnet,
            "api_key_set": bool(config.api_key),
            "api_secret_set": bool(config.api_secret),
        }
    finally:
        db.close()
