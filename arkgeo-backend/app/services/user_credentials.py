"""Per-principal user credential store (Phase 3 — BYOK).

Stores a user's own provider API keys, encrypted at rest with the platform's
existing AES-256-GCM field encryption (``app.core.security``), keyed by the
principal's server-derived namespace.  A key stored for one principal is never
readable by another — isolation is enforced by the namespace primary key.

Values are never returned to any client: reads expose only a masked preview and
a ``configured`` flag, matching the platform's existing key-hygiene contract.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
from typing import Any, Optional

from app.core.config import settings as bootstrap_settings
from app.core.security import decrypt_field, encrypt_field

logger = logging.getLogger(__name__)

_DB_PATH = os.path.join(bootstrap_settings.local_storage_path, "arkgeo_user_creds.db")

# Providers a user may bring their own key for (model providers only).
USER_KEY_PROVIDERS = ("openai", "anthropic", "gemini", "openrouter", "huggingface")


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 12:
        return value[:2] + "…"
    return f"{value[:6]}…{value[-4:]}"


class UserCredentialStore:
    """Thread-safe encrypted per-principal credential store."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(_DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_credentials (
                    namespace TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    encrypted TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (namespace, provider)
                )
                """
            )

    def get_key(self, namespace: str, provider: str) -> Optional[str]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT encrypted FROM user_credentials WHERE namespace = ? AND provider = ?",
                (namespace, provider),
            ).fetchone()
        if not row:
            return None
        try:
            return decrypt_field(row["encrypted"])
        except Exception:
            logger.warning("Could not decrypt user credential for provider '%s'", provider)
            return None

    def set_key(self, namespace: str, provider: str, value: Optional[str]) -> None:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._lock, self._conn() as conn:
            if not value:
                conn.execute(
                    "DELETE FROM user_credentials WHERE namespace = ? AND provider = ?",
                    (namespace, provider),
                )
                return
            conn.execute(
                "INSERT OR REPLACE INTO user_credentials (namespace, provider, encrypted, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (namespace, provider, encrypt_field(value), now),
            )

    def status(self, namespace: str) -> dict[str, dict[str, Any]]:
        """Return provider → {configured, preview} for a principal."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT provider, encrypted FROM user_credentials WHERE namespace = ?",
                (namespace,),
            ).fetchall()
        out: dict[str, dict[str, Any]] = {}
        for provider in USER_KEY_PROVIDERS:
            out[provider] = {"configured": False, "preview": ""}
        for row in rows:
            try:
                plain = decrypt_field(row["encrypted"])
            except Exception:
                continue
            out[row["provider"]] = {"configured": True, "preview": _mask(plain)}
        return out

    def delete_all(self, namespace: str) -> int:
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM user_credentials WHERE namespace = ?", (namespace,)
            )
            return cur.rowcount


user_credentials = UserCredentialStore()
