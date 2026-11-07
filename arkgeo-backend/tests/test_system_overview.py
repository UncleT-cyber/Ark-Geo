"""System Overview aggregate — honesty + principal-scoping contract.

Covers ``GET /api/v1/overview`` (``app/services/overview_service.py``). The
dashboard's core promise is that it never claims a tool ran when it did not:
values the backend did not measure must render as ``None`` (the UI shows ``—``),
never a fabricated ``0``. These tests exercise the real route through the ASGI
app and the real session store, so principal resolution and run derivation are
what is verified.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from main import app
from app.services import session_store as session_store_module

SESS = "sess-overview-t1"
RUN_OK = "run-overview-t1-ok"
RUN_BAD = "run-overview-t1-bad"


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def seeded():
    """One principal owning one completed and one failed run."""
    store = session_store_module.session_store
    store.upsert_session(SESS, principal_subject="ov-alice", case_id="CASE-OV")
    store.start_run(RUN_OK, SESS, model="ollama/qwen2.5-coder:3b")
    store.finish_run(RUN_OK, "completed")
    store.start_run(RUN_BAD, SESS, model="openrouter/example:free")
    store.finish_run(RUN_BAD, "failed", error="boom")
    yield store
    store.delete_session(SESS)


def test_fresh_principal_reports_measured_zeros_not_fabricated(client):
    """A principal with no history gets real zeros where a count is knowable."""
    r = client.get("/api/v1/overview", headers={"X-ARK-Principal": "ov-empty"})
    assert r.status_code == 200
    body = r.json()
    assert body["kpis"]["investigations"]["total"] == 0
    assert body["kpis"]["tool_executions"]["total"] == 0
    # No completed/failed runs → success rate is unknown, not 0%.
    assert body["kpis"]["tool_executions"]["success_rate"] is None
    assert body["evidence"]["runs_recorded"] == 0


def test_unmeasured_cost_is_null_with_explicit_basis(client):
    r = client.get("/api/v1/overview", headers={"X-ARK-Principal": "ov-empty"})
    usage = r.json()["usage"]
    assert usage["input_tokens"] is None
    assert usage["output_tokens"] is None
    assert usage["cost_usd"] is None
    assert usage["cost_basis"] == "unavailable"


def test_owner_sees_own_runs_and_derived_metrics(client, seeded):
    r = client.get("/api/v1/overview", headers={"X-ARK-Principal": "ov-alice"})
    assert r.status_code == 200
    body = r.json()
    assert body["kpis"]["investigations"]["total"] == 1
    assert body["kpis"]["tool_executions"]["total"] == 2
    assert body["kpis"]["tool_executions"]["completed"] == 1
    assert body["kpis"]["tool_executions"]["failed"] == 1
    assert body["kpis"]["tool_executions"]["success_rate"] == 0.5
    assert body["evidence"]["runs_recorded"] == 2
    run_ids = {t["run_id"] for t in body["traces"]}
    assert {RUN_OK, RUN_BAD} <= run_ids


def test_other_principal_cannot_see_runs(client, seeded):
    r = client.get("/api/v1/overview", headers={"X-ARK-Principal": "ov-bob"})
    assert r.status_code == 200
    body = r.json()
    assert body["kpis"]["tool_executions"]["total"] == 0
    assert all(t["run_id"] not in {RUN_OK, RUN_BAD} for t in body["traces"])


def test_trace_surfaces_recorded_failure_detail(client, seeded):
    r = client.get("/api/v1/overview?traces=25", headers={"X-ARK-Principal": "ov-alice"})
    traces = {t["run_id"]: t for t in r.json()["traces"]}
    assert traces[RUN_BAD]["status"] == "failed"
    assert traces[RUN_BAD]["error"] == "boom"
    # No evidence file was written for these synthetic runs → not guessed.
    assert traces[RUN_OK]["event_count"] is None
    assert traces[RUN_OK]["verified"] is None


def test_unknown_period_falls_back_to_24h(client):
    r = client.get("/api/v1/overview?period=bogus", headers={"X-ARK-Principal": "ov-empty"})
    assert r.status_code == 200
    assert r.json()["period_hours"] == 24


def test_local_vs_cloud_split_is_derived_from_model(client, seeded):
    r = client.get("/api/v1/overview", headers={"X-ARK-Principal": "ov-alice"})
    usage = r.json()["usage"]
    assert usage["local_inference_runs"] == 1
    assert usage["cloud_inference_runs"] == 1
