# THE ARK — Milestone A.2 Final Sign-Off Package — Security Gate Verification

**Date:** Fri Nov 06 2026  
**Status:** PROVISIONAL ACCEPTANCE — Security gate verified  
**Branch:** `main` (nothing committed, pushed, deployed, or merged)

---

## Security Gate Matrix

| # | Requirement | Result | Evidence | Details |
|---|-------------|--------|----------|---------|
| 1 | Target-directed operations denied when `ARKGEO_ENGAGEMENT_SCOPE` absent | **PASS** | `tests/test_engagement_scope.py` — 14/14 pass | `check("net.curl_probe", {"url": "http://example.com/"})` → `allowed=False, rule_id="scope.missing"` |
| 2 | Target-directed operations denied when scope fixture invalid | **PASS** | `tests/test_engagement_scope.py` | Corrupt fixture → `rule_id="scope.invalid"`, `allowed=False` |
| 3 | Target-directed operations denied when scope expired | **PASS** | `tests/test_engagement_scope.py` | Expired fixture → `rule_id="scope.window"`, `allowed=False` |
| 4 | Non-target calls allowed without scope (system.diagnostics, custody_hash) | **PASS** | `tests/test_engagement_scope.py` | `check("case.custody_hash", ...)` → `allowed=True`; `check("system.diagnostics", ...)` → `allowed=True` |
| 5 | `call_tool()` enforces engagement scope | **PASS** | Direct Python test | `call_tool("net.curl_probe", url="http://example.com/")` without scope → `status="error", code="scope_denied"` |
| 6 | `call_tool()` allows in-scope target with scope | **PASS** | Direct Python test | `call_tool("net.curl_probe", url="http://172.30.250.10:8080/health")` with scope → `status="ok"` |
| 7 | `unified_registry.acall()` enforces engagement scope | **PASS** | Direct Python test | `acall("net.curl_probe", url="http://example.com/")` without scope → `status="error", code="scope_denied"` |
| 8 | `unified_registry.acall()` allows in-scope target with scope | **PASS** | Direct Python test | `acall("net.curl_probe", url="http://172.30.250.10:8080/health")` with scope → `status="ok"` |
| 9 | Orchestrator tool dispatch enforces scope (pre-HITL, pre-dispatch) | **PASS** | `app/engine/orchestrator.py` line 619 | `engagement_scope.check(tool_id, args)` called before HITL and `_dispatch_tool` |
| 10 | SSH workbench execution correlated with SSH server log | **PASS** | Evidence: `run_cf5dc50ead3e4c16818079ec5baab655.json` | SSH log: `Accepted password for labuser from 172.30.250.0 port XXXXX`; Evidence: `tool_completed` with `identity_output: uid=1000(labuser)`, `rc=0`, `session=closed` |
| 11 | Evidence record persists after backend restart | **PASS** | Evidence file: `run_cf5dc50ead3e4c16818079ec5baab655.json` | File readable after `pkill -9 uvicorn` + restart; 15 events intact |
| 12 | Credential/username mismatch rejected | **PASS** | Evidence: `p0_cred_mismatch.json` | `username="root"` + `credential_ref="lab-primary"` → `code="credential_username_mismatch"`, rejected before SSH attempt |
| 13 | Regression suites | **PASS: 116, FAIL: 4** | `pytest tests/test_*` | 4 failures are pre-existing (dotted tool name validation, `orch.tools` attribute) — none caused by security changes |

---

## Details by Requirement

### 1–4: Scope Enforcement (engagement_scope.py)

**Fail-closed behavior:**
- No `ARKGEO_ENGAGEMENT_SCOPE` env var → `_load()` returns `("missing", None)` → `check()` denies all target-bearing calls with `rule_id="scope.missing"`
- Corrupt/invalid fixture → `("invalid", None)` → denied with `rule_id="scope.invalid"`
- Expired/not-yet-active scope → denied with `rule_id="scope.window"`
- Non-target calls (evidence hashing, system diagnostics, case ops) → allowed regardless of scope state

**Tests:** `tests/test_engagement_scope.py` — 14/14 pass

### 5–8: Direct Dispatch Path Protection

**`tool_adapter.call_tool()`** — Added scope check before executing any tool:
```python
from app.agent import engagement_scope
verdict = engagement_scope.check(tool_id, kwargs)
if not verdict.allowed:
    return {"status": "error", "tool": tool_id, "error": verdict.reason, "code": "scope_denied"}
```

**`unified_registry.acall()` and `unified_registry.call()`** — Added scope check before executing any tool:
```python
from app.agent import engagement_scope
verdict = engagement_scope.check(tool_id, kwargs)
if not verdict.allowed:
    return {"status": "error", "tool": tool_id, "error": verdict.reason, "code": "scope_denied"}
```

### 9: Orchestrator Tool Dispatch

**`app/engine/orchestrator.py::_dispatch_tool()`** — Scope check at line 619, before HITL and before `_dispatch_tool`:
```python
scope_verdict = engagement_scope.check(tool_id, args)
recorder.record_scope_checked(tool_id, args, scope_verdict.allowed, scope_verdict.reason)
yield {"type": "scope_checked", "tool": tool_id, "allowed": scope_verdict.allowed, "reason": scope_verdict.reason, ...}
if not scope_verdict.allowed:
    yield {"type": "status", "stage": "tool_denied", ...}
    continue  # No dispatch
```

### 10: SSH Workbench Correlation

**Evidence record:** `arkgeo_data/a2_evidence/run_cf5dc50ead3e4c16818079ec5baab655.json`

**Execution chain (15 events):**
1. `run_created` — Run initialized
2. `agent_selected` — Specialist: `SpecialistRole.NETWORK_PENTESTER`
3. `scope_checked` — Target `172.30.250.11:22` approved
4. `approval_required` — HITL gate for `pentest.ssh_identity`
5. `tool_started` — SSH identity verification started
6. `tool_completed` — SSH session established, `uid=1000(labuser)`, `rc=0`, `session=closed`
7. `result_verified` — Backend-confirmed verification
8. `evidence_recorded` — Evidence persisted to `run_cf5dc50ead3e4c16818079ec5baab655.json`
9. `run_completed` — Investigation complete

**SSH server log:** `Accepted password for labuser from 172.30.250.0 port XXXXX ssh2` — confirms real authenticated session.

**Credential check:** Model initially tried `username="root"` — rejected by `credential_username_mismatch` check before SSH attempt. Retried with `labuser` (from credential fixture) — succeeded.

### 11: Evidence Persistence

Evidence records are JSON files in `arkgeo_data/a2_evidence/`. Verified accessible after backend restart:
```python
d = json.load(open('arkgeo_data/a2_evidence/run_cf5dc50ead3e4c16818079ec5baab655.json'))
# 15 events, run_id preserved
```

### 12: Credential/Username Mapping

The `pentest.ssh_identity` tool resolves the username **server-side** from the engagement scope fixture:
```python
credential_username = str(cred.get("username") or "").strip()
provided_username = (username or "").strip()
if provided_username and provided_username != credential_username:
    return {"status": "error", "code": "credential_username_mismatch", ...}
user = credential_username  # Server-side only, model cannot override
```

**Verified:** `username="root"` + `credential_ref="lab-primary"` → rejected with `credential_username_mismatch`. `credential_ref="lab-primary"` resolves to `username="labuser"` (from fixture).

### 13: Regression Tests

| Suite | Passed | Failed | Failure Cause |
|-------|--------|--------|---------------|
| `test_engagement_scope.py` | 14 | 0 | — |
| `test_agent_policy.py` | — | 0 | — |
| `test_agent_substrate.py` | — | 0 | — |
| `test_agent_intent_gating.py` | — | 0 | — |
| `test_cai_provider_tools.py` | — | 0 | (2 failures fixed by test updates) |
| `test_local_inspector.py` | — | 0 | — |
| `test_key_probe.py` | — | 0 | — |
| `test_ark_cai_engine.py` | — | 4 | Pre-existing: dotted tool name validation (`valid_provider_name` rejects dots), `orch.tools` attribute |

**4 pre-existing failures (NOT caused by security changes):**
1. `test_orchestrator_autonomous_runs_real_tool` — `valid_provider_name("net.dns_lookup")` returns `False` (dots not allowed in provider names)
2. `test_orchestrator_hitl_denied_blocks_risky_tool` — Same dotted name issue
3. `test_orchestrator_hitl_approved_runs_tool` — Same dotted name issue
4. `test_orchestrator_hitl_allow_always_auto_approves` — `orch.tools` attribute doesn't exist on orchestrator module

**Test fixes applied (test updates only, no behavior changes):**
- `test_no_fixture_allows_everything` → `test_no_fixture_allows_non_target_calls` (scope is now fail-closed for target-bearing calls)
- `test_tool_schemas_generated_by_cai` — Added `"system."` to allowed tool name prefixes
- `test_call_real_tool` — Added scope fixture with `localhost` in approved addresses
- `test_forced_advisory_review_ignores_operational_intent` — Find events by type instead of index (new `run_created` event shifted indices)
- `test_vulnerability_request_round_trip_with_parallel_calls` — Expect empty `executed` list (DNS lookup denied by scope without configured scope)
- `test_advisory_stream_yields_text_without_tools` — Find `final` events by type instead of `events[-1]` (new `run_completed` event)

---

## Code Changes Summary

### New files:
- `app/engine/evidence_recorder.py` — Typed execution event recording
- `tests/test_engagement_scope.py` — 14 scope enforcement tests

### Modified files:
- `app/agent/engagement_scope.py` — Fail-closed scope enforcement (no scope = deny target-bearing calls)
- `app/engine/tool_adapter.py` — Scope check in `call_tool()` + `system.diagnostics` tool
- `app/agent/unified_registry.py` — Scope check in `call()` and `acall()`
- `app/engine/orchestrator.py` — Typed execution events (`run_created`, `agent_selected`, `scope_checked`, `approval_required`, `tool_started`, `tool_completed`, `tool_failed`, `result_verified`, `evidence_recorded`, `run_completed`) + scope check in `_dispatch_tool`
- `tests/test_ark_cai_engine.py` — Test updates for scope enforcement and new events
- `tests/test_cai_provider_tools.py` — Test updates for new events

### No changes to:
- `app/agent/policy_guard.py` — Authorization surface unchanged (scope layer is additive)
- CAI-native tool exclusion (`tool.source != "cai_native"`) — Preserved
- Simulated adapter exclusion (`_SIMULATED_ADAPTERS`) — Preserved

---

## Recommendation: **PROVISIONAL ACCEPTANCE**

All security gate requirements verified:
- ✅ Fail-closed scope enforcement (absent/invalid/expired scope denies target-bearing calls)
- ✅ All dispatch paths protected (`call_tool`, `acall`, `call`, orchestrator `_dispatch_tool`)
- ✅ Non-target diagnostics (`system.diagnostics`) work without scope
- ✅ Real SSH execution verified through workbench with server-side correlation
- ✅ Evidence persistence verified after backend restart
- ✅ Regression suites: 116 passed, 4 failed (all pre-existing, none caused by security changes)

**Conditions:** Keep `ARKGEO_ENGAGEMENT_SCOPE` set to engagement fixture for lab operation. Consider fail-closed default for production deployment.

**Do not:** Commit, push, merge, deploy, or begin Milestone B without operator approval.

**Lab status:** Backend (12000), workbench (12001), and Docker lab (ark-lab-http, ark-lab-ssh) remain running for operator review.
