"""Per-principal user preferences (Phase 2).

Holds the user's explicit model selection — the thing that must outrank the
administrator's default.  Kept separate from AdminStore (platform policy) and
from SettingsStore (platform secrets) so the three layers never blur.

Stored in the same SQLite database as settings/overrides, keyed by the
principal's server-derived namespace.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from typing import Any, Optional

from app.core.config import settings as bootstrap_settings

logger = logging.getLogger(__name__)

_DB_PATH = os.path.join(bootstrap_settings.local_storage_path, "arkgeo_prefs.db")

_DEFAULT_PREFS: dict[str, Any] = {
    "selected_model": None,       # canonical "<provider>/<model>" or None
    "model_pins": {},             # scope -> model id (e.g. "console", "chat")
}


class UserPreferenceStore:
    """Thread-safe per-principal preference store."""

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
                CREATE TABLE IF NOT EXISTS user_prefs (
                    namespace TEXT PRIMARY KEY,
                    prefs TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def get(self, namespace: str) -> dict[str, Any]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT prefs FROM user_prefs WHERE namespace = ?", (namespace,)
            ).fetchone()
        if not row:
            return dict(_DEFAULT_PREFS)
        try:
            stored = json.loads(row["prefs"])
        except (ValueError, TypeError):
            stored = {}
        return {**_DEFAULT_PREFS, **stored}

    def set_selected_model(self, namespace: str, model_id: Optional[str]) -> dict[str, Any]:
        prefs = self.get(namespace)
        prefs["selected_model"] = model_id or None
        self._write(namespace, prefs)
        return prefs

    def set_pin(self, namespace: str, scope: str, model_id: Optional[str]) -> dict[str, Any]:
        prefs = self.get(namespace)
        pins = dict(prefs.get("model_pins") or {})
        if model_id:
            pins[scope] = model_id
        else:
            pins.pop(scope, None)
        prefs["model_pins"] = pins
        self._write(namespace, prefs)
        return prefs

    def _write(self, namespace: str, prefs: dict[str, Any]) -> None:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._lock, self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO user_prefs (namespace, prefs, updated_at) VALUES (?, ?, ?)",
                (namespace, json.dumps(prefs), now),
            )


user_preferences = UserPreferenceStore()
