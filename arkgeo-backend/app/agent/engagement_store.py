"""Operator-declared engagement registry — the authoritative execution scope.

An operator declares an engagement: which targets, which ports, and for how
long. That declaration is the **source of truth** for what ARK may execute
against. Inside the declared scope ARK runs without asking; outside it,
target-bearing tool calls are denied before dispatch.

Persistence is a local SQLite file (``arkgeo_data/engagements.sqlite``).
Records are owner-isolated: an engagement resolves only for the principal that
declared it. This is the local/development adapter — a shared transactional
store is the production path for horizontal deployment.
"""
from __future__ import annotations

import ipaddress
import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from app.core.config import settings as bootstrap_settings
from .engagement_scope import _parse_ts

DEFAULT_WINDOW_HOURS = 24

# ``ports`` may be given as this sentinel (or ``all_ports=True``) to authorize
# every port on the declared addresses — the normal shape of a "scan this host"
# engagement. Port discipline still applies to explicit-port engagements.
ALL_PORTS = "*"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def default_db_path() -> str:
    return os.path.join(bootstrap_settings.local_storage_path, "engagements.sqlite")


def _validate_target(value: str) -> str:
    """Normalize a declared target (hostname, IP literal, or CIDR).

    Rejects anything carrying credentials, a path, a scheme, or a port — a
    declaration is an address grant, not a URL. Ports are declared separately.
    """
    raw = str(value).strip()
    if not raw or len(raw) > 253:
        raise ValueError("invalid target address or CIDR")
    if "/" in raw:  # CIDR is supported; validate strictly.
        try:
            return str(ipaddress.ip_network(raw, strict=False))
        except ValueError as exc:
            raise ValueError("invalid target address or CIDR") from exc
    try:  # IPv4 or IPv6 literal (IPv6 carries ':'; parse before rejecting it).
        return str(ipaddress.ip_address(raw))
    except ValueError:
        pass
    if any(c in raw for c in "\\:@?# "):
        raise ValueError("invalid target address or CIDR")
    value = raw.lower().rstrip(".")
    if not all(label and len(label) <= 63 and
               label[0].isalnum() and label[-1].isalnum() and
               all(c.isalnum() or c == "-" for c in label)
               for label in value.split(".")):
        raise ValueError("invalid DNS target")
    return value


def _normalize_ports(ports, all_ports: bool) -> tuple[list[int], bool]:
    """Return ``(ports, all_ports)``. ``all_ports`` authorizes every port."""
    if all_ports:
        return [], True
    if ports is None:
        raise ValueError("declare at least one port, or set all_ports=True")
    if isinstance(ports, (str, int)):
        ports = [ports]
    normalized: list[int] = []
    for p in ports:
        if str(p).strip() == ALL_PORTS:
            return [], True
        try:
            port = int(p)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid port: {p!r}") from exc
        if port < 1 or port > 65535:
            raise ValueError("ports must be 1..65535")
        normalized.append(port)
    if not normalized:
        raise ValueError("declare at least one port, or set all_ports=True")
    return sorted(set(normalized)), False


class EngagementStore:
    """Owner-isolated persistent engagements with explicit revocation."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = str(db_path or default_db_path())
        parent = os.path.dirname(self.db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with self._connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS engagements (
                id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL,
                label TEXT NOT NULL DEFAULT '',
                start_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                addresses_json TEXT NOT NULL,
                ports_json TEXT NOT NULL,
                all_ports INTEGER NOT NULL DEFAULT 0,
                notes TEXT NOT NULL DEFAULT '',
                revoked_at TEXT,
                created_at TEXT NOT NULL
            )""")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_engagement_owner "
                "ON engagements(owner_id, revoked_at)")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=5)

    # -- writes ---------------------------------------------------------- #
    def create(self, *, owner_id: str, addresses, ports=None, all_ports: bool = False,
               start: Optional[str] = None, expiry: Optional[str] = None,
               label: str = "", notes: str = "") -> dict:
        if not owner_id or not owner_id.strip():
            raise ValueError("authenticated owner required")
        if not addresses:
            raise ValueError("declare at least one target")
        now = _utcnow()
        starts = _parse_ts(start) if start else now
        ends = _parse_ts(expiry) if expiry else now + timedelta(hours=DEFAULT_WINDOW_HOURS)
        if starts is None or ends is None or starts >= ends:
            raise ValueError("valid engagement start and expiry required")
        normalized = sorted(set(_validate_target(a) for a in addresses))
        port_list, all_ports = _normalize_ports(ports, all_ports)
        engagement_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute("""INSERT INTO engagements
                (id, owner_id, label, start_at, expires_at, addresses_json,
                 ports_json, all_ports, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (engagement_id, owner_id, label, starts.isoformat(),
                 ends.isoformat(), json.dumps(normalized), json.dumps(port_list),
                 1 if all_ports else 0, notes, now.isoformat()))
        # Return the declaration as stored. It is not filtered by the active
        # window here: the record exists and is retrievable by id; only
        # ``get``/``get_active`` apply the window.
        return {
            "engagement_id": engagement_id,
            "label": label,
            "start": starts.isoformat(),
            "expiry": ends.isoformat(),
            "approved_addresses": normalized,
            "approved_ports": port_list,
            "all_ports": all_ports,
            "notes": notes,
        }

    def revoke(self, *, owner_id: str, engagement_id: str) -> bool:
        if not owner_id or not engagement_id:
            return False
        with self._connect() as conn:
            result = conn.execute("""UPDATE engagements SET revoked_at = ?
                WHERE id = ? AND owner_id = ? AND revoked_at IS NULL""",
                (_utcnow().isoformat(), engagement_id, owner_id))
            return result.rowcount == 1

    # -- reads ----------------------------------------------------------- #
    def _row_to_scope(self, row) -> Optional[dict]:
        (eid, label, start, expiry, addresses, ports, all_ports, notes) = row
        starts, ends = _parse_ts(start), _parse_ts(expiry)
        now = _utcnow()
        if starts is None or ends is None or not starts <= now < ends:
            return None
        return {
            "engagement_id": eid,
            "label": label,
            "start": start,
            "expiry": expiry,
            "approved_addresses": json.loads(addresses),
            "approved_ports": json.loads(ports),
            "all_ports": bool(all_ports),
            "notes": notes,
        }

    def get(self, *, owner_id: str, engagement_id: str) -> Optional[dict]:
        """Return an active, non-revoked engagement owned by ``owner_id``."""
        if not owner_id or not engagement_id:
            return None
        with self._connect() as conn:
            row = conn.execute("""SELECT id, label, start_at, expires_at,
                addresses_json, ports_json, all_ports, notes FROM engagements
                WHERE id = ? AND owner_id = ? AND revoked_at IS NULL""",
                (engagement_id, owner_id)).fetchone()
        return self._row_to_scope(row) if row else None

    def get_active(self, *, owner_id: str) -> Optional[dict]:
        """The most recently declared active engagement for ``owner_id``."""
        if not owner_id:
            return None
        with self._connect() as conn:
            rows = conn.execute("""SELECT id, label, start_at, expires_at,
                addresses_json, ports_json, all_ports, notes FROM engagements
                WHERE owner_id = ? AND revoked_at IS NULL
                ORDER BY created_at DESC""", (owner_id,)).fetchall()
        for row in rows:
            scope = self._row_to_scope(row)
            if scope:
                return scope
        return None

    def list_owners(self) -> list[str]:
        """Distinct owners with at least one non-revoked engagement."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT owner_id FROM engagements WHERE revoked_at IS NULL"
            ).fetchall()
        return [r[0] for r in rows]

    def list_active(self, *, owner_id: str) -> list[dict]:
        if not owner_id:
            return []
        with self._connect() as conn:
            rows = conn.execute("""SELECT id, label, start_at, expires_at,
                addresses_json, ports_json, all_ports, notes FROM engagements
                WHERE owner_id = ? AND revoked_at IS NULL
                ORDER BY created_at DESC""", (owner_id,)).fetchall()
        out = []
        for row in rows:
            scope = self._row_to_scope(row)
            if scope:
                out.append(scope)
        return out


__all__ = ["EngagementStore", "default_db_path", "ALL_PORTS", "DEFAULT_WINDOW_HOURS"]
