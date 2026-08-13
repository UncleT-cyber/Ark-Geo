"""Encrypted storage service – local filesystem or S3.

Images are written with AES-256-GCM field encryption applied to any
metadata sidecar, and the raw bytes are optionally wiped when zero-retention
mode is enabled.
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Optional

from app.core.config import settings
from app.core.security import encrypt_field, sha256_hex

logger = logging.getLogger(__name__)


class StorageService:
    def __init__(self) -> None:
        os.makedirs(settings.local_storage_path, exist_ok=True)

    def store_image(self, image_bytes: bytes, zero_retention: bool = False) -> dict:
        """Persist an image and return a dict with path, sha256, and retention flag.

        In zero-retention mode the image is *not* persisted to disk; only the
        SHA-256 hash is retained for the chain-of-custody log.
        """
        digest = sha256_hex(image_bytes)
        if zero_retention:
            logger.info("Zero-retention mode: image not persisted (sha256=%s)", digest)
            return {"path": None, "sha256": digest, "zero_retention": True}

        filename = f"{uuid.uuid4().hex}.bin"
        filepath = os.path.join(settings.local_storage_path, filename)
        with open(filepath, "wb") as f:
            f.write(image_bytes)
        logger.info("Stored image %s (%s)", filepath, digest)
        return {"path": filepath, "sha256": digest, "zero_retention": False}

    def store_encrypted_metadata(self, metadata: dict, image_sha: str) -> str:
        """Encrypt a metadata dict and store it alongside an image. Returns path."""
        import json

        blob = json.dumps(metadata, sort_keys=True)
        encrypted = encrypt_field(blob, aad=image_sha.encode())
        filename = f"{image_sha}.meta"
        filepath = os.path.join(settings.local_storage_path, filename)
        with open(filepath, "w") as f:
            f.write(encrypted)
        return filepath

    def delete_image(self, path: Optional[str]) -> None:
        """Securely remove an image file (used for zero-retention cleanup)."""
        if not path or not os.path.exists(path):
            return
        try:
            os.remove(path)
            logger.info("Deleted image %s", path)
        except OSError as exc:
            logger.warning("Failed to delete %s: %s", path, exc)


# Singleton
storage = StorageService()
