"""Tests for the durable investigation-session store (Phase 1).

Covers: metadata round-trip, encrypted transcript, run lifecycle, restart
recovery (running → interrupted), zero-retention non-persistence, and
evidence-reference (not evidence-copy) behaviour.
"""
from __future__ import annotations

import pytest

from app.services.session_store import (
    SessionStore,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_INTERRUPTED,
    RUN_RUNNING,
)


@pytest.fixture()
def store(tmp_path):
    return SessionStore(db_path=str(tmp_path / "sessions.db"))


def test_session_metadata_round_trip(store):
    store.upsert_session(
        "s1", principal_subject="alice", case_id="CASE-1",
        workspace="image", role="operator", model="qwen2.5-coder:3b",
    )
    meta = store.get_session_meta("s1")
    assert meta is not None
    assert meta["principal_subject"] == "alice"
    assert meta["case_id"] == "CASE-1"
    assert meta["workspace"] == "image"
    assert meta["model"] == "qwen2.5-coder:3b"
    assert meta["zero_retention"] is False


def test_upsert_updates_without_clobbering(store):
    store.upsert_session("s1", case_id="CASE-1", workspace="image")
    store.upsert_session("s1", model="gpt-4o-mini")  # case_id/workspace omitted
    meta = store.get_session_meta("s1")
    assert meta["case_id"] == "CASE-1"
    assert meta["workspace"] == "image"
    assert meta["model"] == "gpt-4o-mini"


def test_transcript_is_encrypted_at_rest(store, tmp_path):
    store.upsert_session("s1")
    store.append_message("s1", "user", "find the location of this photo")
    store.append_message("s1", "assistant", "analyzing EXIF metadata")

    # Ciphertext on disk must not contain the plaintext.
    raw = (tmp_path / "sessions.db").read_bytes()
    assert b"find the location" not in raw
    assert b"analyzing EXIF" not in raw

    msgs = store.load_messages("s1")
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[0]["content"] == "find the location of this photo"
    assert msgs[1]["content"] == "analyzing EXIF metadata"


def test_message_order_and_tool_call_id(store):
    store.upsert_session("s1")
    store.append_message("s1", "user", "one")
    store.append_message("s1", "tool", '{"status":"ok"}', tool_call_id="tc-9")
    store.append_message("s1", "assistant", "three")
    msgs = store.load_messages("s1")
    assert [m["content"] for m in msgs] == ["one", '{"status":"ok"}', "three"]
    assert msgs[1]["tool_call_id"] == "tc-9"


def test_zero_retention_never_writes_transcript(store, tmp_path):
    store.upsert_session("zr", zero_retention=True)
    store.append_message("zr", "user", "TOP SECRET protected content", zero_retention=True)

    assert store.message_count("zr") == 0
    assert store.load_messages("zr") == []
    raw = (tmp_path / "sessions.db").read_bytes()
    assert b"TOP SECRET" not in raw
    # Metadata still persists so the session can be listed and its status shown.
    assert store.get_session_meta("zr")["zero_retention"] is True


def test_zero_retention_flag_is_sticky(store):
    store.upsert_session("zr", zero_retention=True)
    store.upsert_session("zr", zero_retention=False)  # cannot downgrade
    assert store.get_session_meta("zr")["zero_retention"] is True


def test_run_lifecycle_and_evidence_refs(store):
    store.upsert_session("s1")
    store.start_run("run-1", "s1", model="m1")
    running = store.get_run("run-1")
    assert running["status"] == RUN_RUNNING
    assert store.get_session_meta("s1")["last_run_status"] == RUN_RUNNING

    store.finish_run("run-1", RUN_COMPLETED, evidence_refs=["exec-abc", "sha256:deadbeef"])
    done = store.get_run("run-1")
    assert done["status"] == RUN_COMPLETED
    assert done["ended_at"] is not None
    assert done["evidence_refs"] == ["exec-abc", "sha256:deadbeef"]
    assert store.get_session_meta("s1")["last_run_status"] == RUN_COMPLETED


def test_failed_run_records_error(store):
    store.upsert_session("s1")
    store.start_run("run-1", "s1")
    store.finish_run("run-1", RUN_FAILED, error="model unavailable")
    run = store.get_run("run-1")
    assert run["status"] == RUN_FAILED
    assert run["error"] == "model unavailable"


def test_restart_marks_running_as_interrupted(store):
    store.upsert_session("s1")
    store.upsert_session("s2")
    store.start_run("run-a", "s1")
    store.start_run("run-b", "s2")
    store.start_run("run-done", "s1")
    store.finish_run("run-done", RUN_COMPLETED)

    interrupted = store.mark_interrupted_runs()
    assert interrupted == 2
    assert store.get_run("run-a")["status"] == RUN_INTERRUPTED
    assert store.get_run("run-b")["status"] == RUN_INTERRUPTED
    # A completed run's history must survive the restart untouched.
    assert store.get_run("run-done")["status"] == RUN_COMPLETED
    # s1's most recent run (run-done) completed, so its session status stays
    # completed; s2's only run was interrupted.
    assert store.get_session_meta("s1")["last_run_status"] == RUN_COMPLETED
    assert store.get_session_meta("s2")["last_run_status"] == RUN_INTERRUPTED


def test_completed_history_survives_restart(store, tmp_path):
    """A backend restart (fresh store over the same file) keeps transcripts."""
    store.upsert_session("s1", case_id="CASE-1")
    store.append_message("s1", "user", "durable question")
    store.start_run("run-1", "s1")
    store.finish_run("run-1", RUN_COMPLETED)

    reopened = SessionStore(db_path=str(tmp_path / "sessions.db"))
    assert reopened.get_session_meta("s1")["case_id"] == "CASE-1"
    assert reopened.load_messages("s1")[0]["content"] == "durable question"
    assert reopened.get_run("run-1")["status"] == RUN_COMPLETED


def test_list_sessions_scoped_by_principal(store):
    store.upsert_session("a", principal_subject="alice")
    store.upsert_session("b", principal_subject="bob")
    alice = store.list_sessions(principal_subject="alice")
    assert [s["session_id"] for s in alice] == ["a"]


def test_delete_session_removes_transcript_and_runs(store):
    store.upsert_session("s1")
    store.append_message("s1", "user", "hello")
    store.start_run("run-1", "s1")
    store.delete_session("s1")
    assert store.get_session_meta("s1") is None
    assert store.load_messages("s1") == []
    assert store.get_run("run-1") is None
