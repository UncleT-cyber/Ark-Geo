"""Security primitives for ArkGeo.

Provides:
* AES-256-GCM symmetric encryption for field-level data protection.
* JWT creation / verification for API authentication.
* Password hashing helpers (bcrypt via passlib).
* Chain-of-custody SHA-256 hashing for forensic integrity.
"""
from __future__ import annotations

import hashlib
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import bcrypt
import jwt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings

# --------------------------------------------------------------------------- #
# Password hashing (bcrypt directly — avoids passlib/bcrypt version conflicts)
# --------------------------------------------------------------------------- #


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# --------------------------------------------------------------------------- #
# AES-256-GCM field encryption
# --------------------------------------------------------------------------- #
def encrypt_field(plaintext: str, aad: Optional[bytes] = None) -> str:
    """Encrypt a string with AES-256-GCM.

    Returns a hex string ``nonce:ciphertext``.
    """
    aesgcm = AESGCM(settings.aes_key_bytes)
    nonce = os.urandom(12)
    ct = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), aad)
    return f"{nonce.hex()}:{ct.hex()}"


def decrypt_field(token: str, aad: Optional[bytes] = None) -> str:
    """Reverse of :func:`encrypt_field`."""
    nonce_hex, ct_hex = token.split(":", 1)
    aesgcm = AESGCM(settings.aes_key_bytes)
    pt = aesgcm.decrypt(bytes.fromhex(nonce_hex), bytes.fromhex(ct_hex), aad)
    return pt.decode("utf-8")


# --------------------------------------------------------------------------- #
# JWT
# --------------------------------------------------------------------------- #
def create_access_token(
    subject: str,
    extra_claims: Optional[dict[str, Any]] = None,
    expires_minutes: Optional[int] = None,
) -> str:
    now = datetime.now(timezone.utc)
    exp_minutes = expires_minutes if expires_minutes is not None else settings.jwt_expiry_minutes
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=exp_minutes)).timestamp()),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode + verify a JWT.  Raises ``jwt.PyJWTError`` on failure."""
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


# --------------------------------------------------------------------------- #
# Chain-of-custody hashing
# --------------------------------------------------------------------------- #
def sha256_hex(data: bytes | str) -> str:
    """Return the SHA-256 hex digest of *data*."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def custody_hash(image_bytes: bytes, metadata: Optional[dict] = None) -> str:
    """Produce a forensic chain-of-custody digest for an uploaded image.

    Combines the image SHA-256 with a stable JSON serialisation of optional
    metadata and a UTC timestamp so every entry in the audit log is unique
    yet verifiable.
    """
    import json

    image_digest = sha256_hex(image_bytes)
    stamp = time.time()
    meta_str = json.dumps(metadata or {}, sort_keys=True)
    return sha256_hex(f"{image_digest}:{meta_str}:{stamp}")
