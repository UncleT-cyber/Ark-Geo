"""Durable investigation-session store.

Gives THE ARK durable ownership of the objects a restored investigation tab
needs, without duplicating the forensic record:

* **Session metadata** — investigation/conversation id, principal, case id,
  workspace, role, pinned model.
* **CAI transcript** — conversation messages, AES-256-GCM encrypted at rest.
* **Runs** — run id, status, model, timing and evidence *references*
  (execution ids / hashes), never the evidence itself.
* **Evidence references** — hashes and execution ids only. The authoritative
  evidence and audit records stay in ``evidence_recorder``; this store holds
  pointers, not copies.

Design notes
------------
* SQLite in ``settings.local_storage_path`` with WAL, encrypted field values
  via :mod:`app.core.security`, same conventions as ``settings_store``.
* **Zero-Retention Mode**: when a session is marked zero-retention, message
  *content* is never written. Only metadata, run status and evidence
  references (hashes) persist — a protected session can be listed and its run
  status reported, but its transcript is not stored and cannot be reconstructed.
* **Restart honesty**: :meth:`mark_interrupted_runs` flips any run still
  ``running`` at process start to ``interrupted``. A run is never reported as
  resumed when the execution backend that owned it is gone.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Optional

from app.core.config import settings
from app.core.security import decrypt_field, encrypt_field

logger = logging.getLogger(__name__)

_DB_PATH = os.path.join(settings.local_storage_path, "arkgeo_sessions.db")

RUN_RUNNING = "running"
RUN_COMPLETED = "completed"
RUN_FAILED = "failed"
RUN_INTERRUPTED = "interrupted"
RUN_CANCELLED = "cancelled"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionStore:
    """Thread-safe, encrypted, durable investigation-session store."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._lock = threading.Lock()
        self._db_path = db_path or _DB_PATH
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id        TEXT PRIMARY KEY,
                    principal_subject TEXT,
                    principal_org     TEXT,
                    case_id           TEXT,
                    workspace         TEXT,
                    role              TEXT,
                    model             TEXT,
                    zero_retention    INTEGER NOT NULL DEFAULT 0,
                    created_at        TEXT NOT NULL,
                    updated_at        TEXT NOT NULL,
                    last_run_id       TEXT,
                    last_run_status   TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id   TEXT NOT NULL,
                    seq          INTEGER NOT NULL,
                    role         TEXT NOT NULL,
                    content      TEXT,
                    tool_call_id TEXT,
                    created_at   TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, seq)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    run_id         TEXT PRIMARY KEY,
                    session_id     TEXT NOT NULL,
                    status         TEXT NOT NULL,
                    model          TEXT,
                    started_at     TEXT NOT NULL,
                    ended_at       TEXT,
                    error          TEXT,
                    evidence_refs  TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_session ON runs(session_id)")

    # -- session metadata ------------------------------------------------- #
    def upsert_session(
        self,
        session_id: str,
        *,
        principal_subject: Optional[str] = None,
        principal_org: Optional[str] = None,
        case_id: Optional[str] = None,
        workspace: Optional[str] = None,
        role: Optional[str] = None,
        model: Optional[str] = None,
        zero_retention: bool = False,
    ) -> None:
        now = _now_iso()
        with self._lock, self._get_conn() as conn:
            row = conn.execute(
                "SELECT session_id FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if row is None:
                conn.execute(
                    """INSERT INTO sessions
                       (session_id, principal_subject, principal_org, case_id, workspace,
                        role, model, zero_retention, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        session_id, principal_subject, principal_org, case_id, workspace,
                        role, model, 1 if zero_retention else 0, now, now,
                    ),
                )
            else:
                conn.execute(
                    """UPDATE sessions SET
                         principal_subject = COALESCE(?, principal_subject),
                         principal_org     = COALESCE(?, principal_org),
                         case_id           = COALESCE(?, case_id),
                         workspace         = COALESCE(?, workspace),
                         role              = COALESCE(?, role),
                         model             = COALESCE(?, model),
                         zero_retention    = MAX(zero_retention, ?),
                         updated_at        = ?
                       WHERE session_id = ?""",
                    (
                        principal_subject, principal_org, case_id, workspace, role, model,
                        1 if zero_retention else 0, now, session_id,
                    ),
                )

    def get_session_meta(self, session_id: str) -> Optional[dict]:
        with self._get_conn() as conn:
            row = conn.execute(
                """SELECT session_id, principal_subject, principal_org, case_id, workspace,
                          role, model, zero_retention, created_at, updated_at,
                          last_run_id, last_run_status
                   FROM sessions WHERE session_id = ?""",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        keys = (
            "session_id", "principal_subject", "principal_org", "case_id", "workspace",
            "role", "model", "zero_retention", "created_at", "updated_at",
            "last_run_id", "last_run_status",
        )
        meta = dict(zip(keys, row))
        meta["zero_retention"] = bool(meta["zero_retention"])
        return meta

    def list_sessions(
        self,
        principal_subject: Optional[str] = None,
        limit: int = 50,
        *,
        include_unowned: bool = False,
    ) -> list[dict]:
        """List sessions, newest first.

        ``principal_subject`` scopes the result to one owner. ``include_unowned``
        additionally matches rows with no recorded owner, which are the anonymous
        principal's — used only when the caller *is* the anonymous principal.
        ``None`` for ``principal_subject`` is an internal "no filter" used by
        maintenance paths, never by the HTTP surface.
        """
        with self._get_conn() as conn:
            if principal_subject is None:
                rows = conn.execute(
                    """SELECT session_id, case_id, workspace, role, model, zero_retention,
                              created_at, updated_at, last_run_id, last_run_status
                       FROM sessions ORDER BY updated_at DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
            elif include_unowned:
                rows = conn.execute(
                    """SELECT session_id, case_id, workspace, role, model, zero_retention,
                              created_at, updated_at, last_run_id, last_run_status
                       FROM sessions WHERE principal_subject = ? OR principal_subject IS NULL
                       ORDER BY updated_at DESC LIMIT ?""",
                    (principal_subject, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT session_id, case_id, workspace, role, model, zero_retention,
                              created_at, updated_at, last_run_id, last_run_status
                       FROM sessions WHERE principal_subject = ?
                       ORDER BY updated_at DESC LIMIT ?""",
                    (principal_subject, limit),
                ).fetchall()
        keys = (
            "session_id", "case_id", "workspace", "role", "model", "zero_retention",
            "created_at", "updated_at", "last_run_id", "last_run_status",
        )
        out = []
        for row in rows:
            rec = dict(zip(keys, row))
            rec["zero_retention"] = bool(rec["zero_retention"])
            out.append(rec)
        return out

    def delete_session(self, session_id: str) -> None:
        with self._lock, self._get_conn() as conn:
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM runs WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))

    # -- transcript ------------------------------------------------------- #
    def append_message(
        self,
        session_id: str,
        role: str,
        content: Optional[str],
        *,
        tool_call_id: Optional[str] = None,
        zero_retention: bool = False,
    ) -> None:
        """Persist one transcript message.

        In zero-retention mode nothing is written: the protected content never
        reaches disk and cannot be reconstructed from an ephemeral session.
        """
        if zero_retention:
            return
        now = _now_iso()
        encrypted = encrypt_field(content or "", aad=session_id.encode())
        with self._lock, self._get_conn() as conn:
            seq_row = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            seq = seq_row[0] if seq_row else 1
            conn.execute(
                """INSERT INTO messages (session_id, seq, role, content, tool_call_id, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (session_id, seq, role, encrypted, tool_call_id, now),
            )
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE session_id = ?", (now, session_id)
            )

    def load_messages(self, session_id: str) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT seq, role, content, tool_call_id FROM messages WHERE session_id = ? ORDER BY seq",
                (session_id,),
            ).fetchall()
        out = []
        for seq, role, content, tool_call_id in rows:
            try:
                text = decrypt_field(content, aad=session_id.encode()) if content else ""
            except Exception:
                logger.warning("Could not decrypt message %s/%s", session_id, seq)
                text = ""
            msg: dict[str, Any] = {"role": role, "content": text}
            if tool_call_id:
                msg["tool_call_id"] = tool_call_id
            out.append(msg)
        return out

    def message_count(self, session_id: str) -> int:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE session_id = ?", (session_id,)
            ).fetchone()
        return row[0] if row else 0

    # -- runs ------------------------------------------------------------- #
    def start_run(self, run_id: str, session_id: str, model: Optional[str] = None) -> None:
        now = _now_iso()
        with self._lock, self._get_conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO runs
                   (run_id, session_id, status, model, started_at, ended_at, error, evidence_refs)
                   VALUES (?,?,?,?,?,NULL,NULL,NULL)""",
                (run_id, session_id, RUN_RUNNING, model, now),
            )
            conn.execute(
                "UPDATE sessions SET last_run_id = ?, last_run_status = ?, updated_at = ? WHERE session_id = ?",
                (run_id, RUN_RUNNING, now, session_id),
            )

    def finish_run(
        self,
        run_id: str,
        status: str,
        *,
        error: Optional[str] = None,
        evidence_refs: Optional[list[str]] = None,
    ) -> None:
        now = _now_iso()
        refs = json.dumps(evidence_refs or [])
        with self._lock, self._get_conn() as conn:
            conn.execute(
                "UPDATE runs SET status = ?, ended_at = ?, error = ?, evidence_refs = ? WHERE run_id = ?",
                (status, now, error, refs, run_id),
            )
            row = conn.execute(
                "SELECT session_id FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE sessions SET last_run_status = ?, updated_at = ? WHERE session_id = ?",
                    (status, now, row[0]),
                )

    def get_run(self, run_id: str) -> Optional[dict]:
        with self._get_conn() as conn:
            row = conn.execute(
                """SELECT run_id, session_id, status, model, started_at, ended_at, error, evidence_refs
                   FROM runs WHERE run_id = ?""",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        keys = ("run_id", "session_id", "status", "model", "started_at", "ended_at", "error", "evidence_refs")
        rec = dict(zip(keys, row))
        rec["evidence_refs"] = json.loads(rec["evidence_refs"]) if rec["evidence_refs"] else []
        return rec

    def list_runs(self, session_id: str, limit: int = 50) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT run_id, session_id, status, model, started_at, ended_at, error, evidence_refs
                   FROM runs WHERE session_id = ? ORDER BY started_at DESC LIMIT ?""",
                (session_id, limit),
            ).fetchall()
        keys = ("run_id", "session_id", "status", "model", "started_at", "ended_at", "error", "evidence_refs")
        out = []
        for row in rows:
            rec = dict(zip(keys, row))
            rec["evidence_refs"] = json.loads(rec["evidence_refs"]) if rec["evidence_refs"] else []
            out.append(rec)
        return out

    def mark_interrupted_runs(self) -> int:
        """Flip runs still ``running`` at process start to ``interrupted``.

        Called once on startup. An active execution cannot survive a backend
        restart, so it must be reported honestly as interrupted rather than
        appearing to still be running or being silently "resumed".
        """
        now = _now_iso()
        with self._lock, self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE runs SET status = ?, ended_at = ?, error = ? WHERE status = ?",
                (RUN_INTERRUPTED, now, "backend restarted during execution", RUN_RUNNING),
            )
            conn.execute(
                "UPDATE sessions SET last_run_status = ? WHERE last_run_status = ?",
                (RUN_INTERRUPTED, RUN_RUNNING),
            )
            return cur.rowcount or 0


# Singleton
session_store = SessionStore()
