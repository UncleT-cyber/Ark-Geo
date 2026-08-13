"""Analyst override service — record human assessment of machine findings.

Analysts can Confirm, Reject, or mark a finding as Needs Review, and add
free-text notes.  Every override is logged to the audit trail so machine
and human assessments remain cleanly separated.

Overrides are stored in a SQLite database (evidence-grade persistence)
keyed by the image SHA-256 so they survive across sessions.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from typing import Optional

from app.core.config import settings as bootstrap_settings

logger = logging.getLogger(__name__)

_DB_PATH = os.path.join(bootstrap_settings.local_storage_path, "arkgeo_overrides.db")


class AnalystOverrideStore:
    """SQLite-backed store for analyst overrides and notes."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS overrides (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    image_sha256 TEXT NOT NULL,
                    finding_key  TEXT NOT NULL,
                    decision     TEXT NOT NULL,
                    note         TEXT,
                    analyst_id   TEXT,
                    created_at_ms INTEGER NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_overrides_sha ON overrides(image_sha256)
            """)

    def _get_conn(self) -> sqlite3.Connection:
        return sqlite3.connect(_DB_PATH)

    def record(
        self,
        image_sha256: str,
        finding_key: str,
        decision: str,
        note: str = "",
        analyst_id: str = "analyst",
    ) -> dict:
        """Persist an analyst override decision.

        ``decision`` must be one of: confirm | reject | needs_review
        """
        if decision not in ("confirm", "reject", "needs_review"):
            raise ValueError(f"Invalid decision: {decision}")
        with self._lock:
            with self._get_conn() as conn:
                conn.execute(
                    "INSERT INTO overrides "
                    "(image_sha256, finding_key, decision, note, analyst_id, created_at_ms) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (image_sha256, finding_key, decision, note, analyst_id, int(time.time() * 1000)),
                )
            logger.info("Analyst override: %s=%s for %s", finding_key, decision, image_sha256[:12])
        return {
            "image_sha256": image_sha256,
            "finding_key": finding_key,
            "decision": decision,
            "note": note,
            "analyst_id": analyst_id,
            "logged_at_ms": int(time.time() * 1000),
        }

    def list_for_image(self, image_sha256: str) -> list[dict]:
        with self._lock:
            with self._get_conn() as conn:
                rows = conn.execute(
                    "SELECT finding_key, decision, note, analyst_id, created_at_ms "
                    "FROM overrides WHERE image_sha256 = ? ORDER BY created_at_ms",
                    (image_sha256,),
                ).fetchall()
        return [
            {
                "finding_key": r[0], "decision": r[1], "note": r[2],
                "analyst_id": r[3], "created_at_ms": r[4],
            }
            for r in rows
        ]


# Singleton
analyst_override_store = AnalystOverrideStore()
