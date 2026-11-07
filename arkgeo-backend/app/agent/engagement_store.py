"""Server-owned engagement registry for multi-user authorization.

This store is an internal backend primitive. Callers must derive owner_id from
verified authentication, never from a request body. No public API is exposed.
SQLite is a development/local persistence adapter; use shared transactional
storage before horizontal deployment.
"""
from __future__ import annotations

import ipaddress
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .engagement_scope import _parse_ts


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _validate_target(value: str) -> str:
    value = value.strip().lower()
    if not value or len(value) > 253 or any(c in value for c in "/\\:@?# "):
        # CIDR is explicitly supported, but not arbitrary URL/credentials.
        try:
            return str(ipaddress.ip_network(value, strict=False))
        except ValueError as exc:
            raise ValueError("invalid target address or CIDR") from exc
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        pass
    if not all(label and len(label) <= 63 and
               label[0].isalnum() and label[-1].isalnum() and
               all(c.isalnum() or c == "-" for c in label)
               for label in value.split(".")):
        raise ValueError("invalid DNS target")
    return value


class EngagementStore:
    """Owner-isolated persistent engagements with explicit revocation."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        with self._connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS engagements (
                id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL,
                start_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                addresses_json TEXT NOT NULL,
                ports_json TEXT NOT NULL,
                revoked_at TEXT,
                created_at TEXT NOT NULL
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_engagement_owner ON engagements(owner_id)")

    def _connect(self):
        return sqlite3.connect(self.db_path, timeout=5)

    def create(self, *, owner_id: str, start: str, expiry: str,
               addresses: list[str], ports: list[int]) -> str:
        if not owner_id or not owner_id.strip():
            raise ValueError("authenticated owner required")
        starts, ends = _parse_ts(start), _parse_ts(expiry)
        if starts is None or ends is None or starts >= ends:
            raise ValueError("valid engagement start and expiry required")
        if not addresses or not ports:
            raise ValueError("at least one target and port required")
        normalized = sorted(set(_validate_target(a) for a in addresses))
        normalized_ports = sorted(set(int(p) for p in ports))
        if any(p < 1 or p > 65535 for p in normalized_ports):
            raise ValueError("ports must be 1..65535")
        engagement_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute("""INSERT INTO engagements
                (id, owner_id, start_at, expires_at, addresses_json,
                 ports_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (engagement_id, owner_id, starts.isoformat(), ends.isoformat(),
                 json.dumps(normalized), json.dumps(normalized_ports),
                 _utcnow().isoformat()))
        return engagement_id

    def resolve(self, *, owner_id: str, engagement_id: str) -> Optional[dict]:
        """Return only an active, nonrevoked engagement belonging to owner."""
        if not owner_id or not engagement_id:
            return None
        with self._connect() as conn:
            row = conn.execute("""SELECT id, start_at, expires_at,
                addresses_json, ports_json FROM engagements
                WHERE id = ? AND owner_id = ? AND revoked_at IS NULL""",
                (engagement_id, owner_id)).fetchone()
        if row is None:
            return None
        eid, start, expiry, addresses, ports = row
        now = _utcnow()
        starts, ends = _parse_ts(start), _parse_ts(expiry)
        if starts is None or ends is None or not starts <= now < ends:
            return None
        return {"engagement_id": eid, "start": start, "expiry": expiry,
                "approved_addresses": json.loads(addresses),
                "approved_ports": json.loads(ports)}

    def revoke(self, *, owner_id: str, engagement_id: str) -> bool:
        if not owner_id or not engagement_id:
            return False
        with self._connect() as conn:
            result = conn.execute("""UPDATE engagements SET revoked_at = ?
                WHERE id = ? AND owner_id = ? AND revoked_at IS NULL""",
                (_utcnow().isoformat(), engagement_id, owner_id))
            return result.rowcount == 1
