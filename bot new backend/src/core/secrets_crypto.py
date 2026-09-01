"""AES-256-GCM for optional encryption of persisted API secrets (env master key)."""
from __future__ import annotations

import base64
import hashlib
import os
from typing import Optional

_PREFIX = "enc:v1:"


def _key_256(key_material: str) -> bytes:
    return hashlib.sha256(key_material.encode("utf-8")).digest()


def encrypt_optional(plaintext: str, key_material: Optional[str]) -> str:
    if not plaintext:
        return ""
    km = key_material or os.getenv("SECRETS_ENCRYPTION_KEY", "").strip()
    if not km:
        return plaintext
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        return plaintext

    aesgcm = AESGCM(_key_256(km))
    nonce = os.urandom(12)
    ct = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    blob = base64.urlsafe_b64encode(nonce + ct).decode("ascii")
    return f"{_PREFIX}{blob}"


def decrypt_optional(ciphertext: str, key_material: Optional[str]) -> str:
    if not ciphertext:
        return ""
    if not ciphertext.startswith(_PREFIX):
        return ciphertext
    km = key_material or os.getenv("SECRETS_ENCRYPTION_KEY", "").strip()
    if not km:
        return ciphertext
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        return ciphertext

    raw = base64.urlsafe_b64decode(ciphertext[len(_PREFIX) :].encode("ascii"))
    nonce, ct = raw[:12], raw[12:]
    aesgcm = AESGCM(_key_256(km))
    return aesgcm.decrypt(nonce, ct, None).decode("utf-8")
