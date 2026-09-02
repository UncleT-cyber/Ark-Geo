"""Tests for the sandboxed local-path inspector + agent task loop.

Covers:
  * Sandbox confinement — safe_resolve blocks escapes outside the sandbox root
  * Recursive indexing — entries, MIME, SHA-256, size
  * High-entropy detection — packed/encrypted/embedded payload flagging
  * observations_from_result → CaseObservation-shaped dicts
  * AgentLoop with the model down → deterministic FALLBACK inspection
  * POST /agent/task → the same fallback over HTTP
"""
import os
import struct

from fastapi.testclient import TestClient

from app.agent import local_inspector as li
from app.agent import schemas as S
from main import app


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
class _OfflineGateway:
    """Stand-in for the Ollama gateway that reports the model unavailable."""

    default_model = "offline-test"

    def available(self):
        return False

    async def chat(self, *args, **kwargs):
        raise AssertionError("chat must not be called when the model is down")


def _make_sandbox(root, case="case-001"):
    """Sandbox with one plaintext file + one high-entropy payload file."""
    sub = os.path.join(root, case, "evidence")
    os.makedirs(sub)
    with open(os.path.join(sub, "notes.txt"), "w") as fh:
        fh.write("plaintext notes " * 20)
    with open(os.path.join(sub, "payload.bin"), "wb") as fh:
        fh.write(os.urandom(1024 * 1024 + 1024))
    return root


def _patch_sandbox(monkeypatch, tmp_path):
    root = tmp_path / "sandbox"
    root.mkdir()
    monkeypatch.setattr(li, "sandbox_root", lambda: root)
    return root


# --------------------------------------------------------------------------- #
# Sandbox confinement
# --------------------------------------------------------------------------- #
def test_safe_resolve_blocks_escape(monkeypatch, tmp_path):
    _patch_sandbox(monkeypatch, tmp_path)
    for evil in ("/etc/passwd", "../escape", "..", "../../../../etc/shadow"):
        try:
            li.safe_resolve(evil, create=False)
        except ValueError:
            pass
        else:
            raise AssertionError(f"escape path not blocked: {evil!r}")


def test_safe_resolve_creates_and_stays_in_sandbox(monkeypatch, tmp_path):
    root = _patch_sandbox(monkeypatch, tmp_path)
    resolved = li.safe_resolve("case-099", create=True)
    assert resolved.is_dir()
    assert os.path.realpath(resolved).startswith(os.path.realpath(root) + os.sep)


# --------------------------------------------------------------------------- #
# Indexing
# --------------------------------------------------------------------------- #
def test_inspect_path_indexes_entries(monkeypatch, tmp_path):
    root = _make_sandbox(_patch_sandbox(monkeypatch, tmp_path))
    result = li.inspect_path("case-001")
    assert result["sandbox_root"] == str(root)
    assert len(result["entries"]) == 3  # notes.txt, payload.bin, evidence/
    assert result["file_count"] == 2 and result["dir_count"] == 1
    assert result["total_bytes"] > 0
    by_name = {e["name"] for e in result["entries"]}
    assert {"notes.txt", "payload.bin"} <= by_name


def test_inspect_path_reports_mime_and_sha256(monkeypatch, tmp_path):
    _make_sandbox(_patch_sandbox(monkeypatch, tmp_path))
    result = li.inspect_path("case-001")
    notes = next(e for e in result["entries"] if e["name"] == "notes.txt")
    assert notes["mime"].startswith("text/plain")
    assert len(notes["sha256"]) == 64
    payload = next(e for e in result["entries"] if e["name"] == "payload.bin")
    assert payload["size"] == 1024 * 1024 + 1024
    assert payload["high_entropy"] is True
    assert result["high_entropy_files"] == ["evidence/payload.bin"]


def test_observations_from_result_shapes(monkeypatch, tmp_path):
    _make_sandbox(_patch_sandbox(monkeypatch, tmp_path))
    result = li.inspect_path("case-001")
    obs = li.observations_from_result(result)
    kinds = {o["type"] for o in obs}
    assert "FILESYSTEM" in kinds
    assert "STEGO" in kinds
    for o in obs:
        assert 0.0 <= o["confidence"] <= 1.0
    stego = next(o for o in obs if o["type"] == "STEGO")
    assert "payload.bin" in stego["label"]


# --------------------------------------------------------------------------- #
# Agent loop — deterministic fallback when the model is down
# --------------------------------------------------------------------------- #
def test_agent_loop_fallback_asserts(monkeypatch, tmp_path):
    import asyncio

    from app.agent import agent_loop as al

    _make_sandbox(_patch_sandbox(monkeypatch, tmp_path))
    monkeypatch.setattr(al, "gateway", _OfflineGateway())
    result = asyncio.run(
        al.agent_loop.run(prompt="inspect case-001", target_path="case-001")
    )
    assert result["status"] == "done"
    assert result["model_calls"] == 0
    assert result["tool_calls"][0]["tool_id"] == "inspect_local_path"
    assert result["tool_calls"][0]["status"] == "ran"
    assert result["observations"]
    assert any(
        f["severity"] == S.FindingSeverity.HIGH.value for f in result["findings"]
    )
    assert "payload.bin" in result["answer"]
    assert result["target_path"].endswith("case-001")


# --------------------------------------------------------------------------- #
# HTTP endpoint
# --------------------------------------------------------------------------- #
def test_agent_task_endpoint_fallback_over_http(monkeypatch, tmp_path):
    from app.agent import agent_loop as al

    _make_sandbox(_patch_sandbox(monkeypatch, tmp_path))
    monkeypatch.setattr(al, "gateway", _OfflineGateway())
    client = TestClient(app)
    resp = client.post(
        "/api/v1/agent/task",
        json={"prompt": "inspect case-001", "target_path": "case-001"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "done"
    assert body["model_calls"] == 0
    assert body["tool_calls"][0]["tool_id"] == "inspect_local_path"
    assert body["observations"]
