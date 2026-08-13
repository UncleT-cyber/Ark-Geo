"""Dynamic settings store — encrypted API key persistence.

Stores API keys and engine thresholds in a local SQLite database with
AES-256-GCM field-level encryption.  The settings manager is the single
source of truth at runtime; the :class:`Settings` object in ``config.py``
is used only for initial bootstrap defaults.

Keys are never returned in API responses — only a boolean ``configured``
flag per key is exposed.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from typing import Any, Optional

from app.core.config import settings as bootstrap_settings
from app.core.security import encrypt_field, decrypt_field

logger = logging.getLogger(__name__)

_DB_PATH = os.path.join(bootstrap_settings.local_storage_path, "arkgeo_settings.db")

# Runtime mutable thresholds (separate from API keys)
_RUNTIME_THRESHOLDS = {
    "min_confidence_threshold": 0.5,
    "default_uncertainty_radius": 500.0,
}

# Key fields that can be stored / retrieved
_KEY_FIELDS = (
    "geospy_api_key",
    "geoinfer_api_key",
    "llm_api_key",
    "twilio_account_sid",
    "twilio_auth_token",
    "twilio_from_number",
    "reverse_search_api_key",
    "ocr_api_key",
    "c2pa_api_key",
    "satellite_api_key",
)


class SettingsStore:
    """Thread-safe encrypted settings store backed by SQLite."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: dict[str, str] = {}  # plaintext cache in memory
        self._thresholds: dict[str, float] = dict(_RUNTIME_THRESHOLDS)
        os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
        self._init_db()
        self._load_all()

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS api_keys (
                    key_name   TEXT PRIMARY KEY,
                    encrypted  TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS thresholds (
                    name   TEXT PRIMARY KEY,
                    value  REAL NOT NULL
                )
            """)

    def _get_conn(self) -> sqlite3.Connection:
        return sqlite3.connect(_DB_PATH)

    def _load_all(self) -> None:
        """Load all stored keys and thresholds into memory at startup."""
        with self._lock:
            try:
                with self._get_conn() as conn:
                    # Load keys
                    rows = conn.execute("SELECT key_name, encrypted FROM api_keys").fetchall()
                    for name, encrypted in rows:
                        try:
                            self._cache[name] = decrypt_field(encrypted)
                        except Exception:
                            logger.warning("Could not decrypt key '%s'", name)
                    # Load thresholds
                    trows = conn.execute("SELECT name, value FROM thresholds").fetchall()
                    for name, value in trows:
                        self._thresholds[name] = float(value)
            except Exception as exc:
                logger.warning("Settings load failed: %s", exc)

            # Seed from environment / config defaults if not in DB
            for field in _KEY_FIELDS:
                if field not in self._cache:
                    env_val = getattr(bootstrap_settings, field, None)
                    if env_val:
                        self._cache[field] = env_val

    def get_key(self, key_name: str) -> Optional[str]:
        """Return the plaintext API key, or None."""
        return self._cache.get(key_name)

    def set_key(self, key_name: str, value: str | None) -> None:
        """Set (or clear) an API key.  Persists encrypted to SQLite."""
        with self._lock:
            if value is None or value == "":
                self._cache.pop(key_name, None)
                with self._get_conn() as conn:
                    conn.execute("DELETE FROM api_keys WHERE key_name = ?", (key_name,))
                return
            self._cache[key_name] = value
            encrypted = encrypt_field(value)
            with self._get_conn() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO api_keys (key_name, encrypted) VALUES (?, ?)",
                    (key_name, encrypted),
                )
            conn.commit()
            logger.info("Settings: updated key '%s'", key_name)

    def get_threshold(self, name: str) -> float:
        return self._thresholds.get(name, _RUNTIME_THRESHOLDS.get(name, 0.0))

    def set_threshold(self, name: str, value: float) -> None:
        with self._lock:
            self._thresholds[name] = value
            with self._get_conn() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO thresholds (name, value) VALUES (?, ?)",
                    (name, value),
                )
            conn.commit()
            logger.info("Settings: updated threshold '%s' = %s", name, value)

    def get_keys_configured(self) -> dict[str, bool]:
        """Return a map of key name → configured (bool)."""
        return {name: bool(self._cache.get(name)) for name in _KEY_FIELDS}

    def get_keys_masked(self) -> dict[str, dict]:
        """Return a map of key name → {configured, key_preview}.

        The preview is a truncated representation (first 8 chars + last 4 chars)
        that NEVER exposes the full key value to the frontend.
        """
        result = {}
        for name in _KEY_FIELDS:
            value = self._cache.get(name)
            if value:
                if len(value) <= 12:
                    preview = f"{value[:4]}...{value[-2:]}" if len(value) > 6 else "••••"
                else:
                    preview = f"{value[:8]}...{value[-4:]}"
                result[name] = {"configured": True, "key_preview": preview}
            else:
                result[name] = {"configured": False, "key_preview": None}
        return result

    def get_thresholds(self) -> dict[str, float]:
        return dict(self._thresholds)

    def update_api_keys(self, keys: dict[str, str | None]) -> None:
        for name, value in keys.items():
            if name in _KEY_FIELDS:
                self.set_key(name, value)

    def update_thresholds(self, thresholds: dict[str, float]) -> None:
        for name, value in thresholds.items():
            if name in _RUNTIME_THRESHOLDS:
                self.set_threshold(name, value)


# Singleton
settings_store = SettingsStore()
