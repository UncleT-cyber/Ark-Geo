# ARK AI — Implementation Plan (Phases B → D)

> Status: **Phase A deliverable — plan for approval. No production code changed.**
> Depends on: `ARK_AI_ORCHESTRATION_AUDIT.md`, `IMAGE_INTELLIGENCE_TOOL_REGISTER.md`.
> Principle: **connect, classify, harden — do not rebuild.** Every phase reuses
> the existing substrate (`orchestrator`, `unified_registry`, `evidence_graph`,
> `PolicyGuard`, `EvidenceRecorder`, `session_store`, `run_control`).

---

## 0. Guiding constraints (from the directive, restated as testable rules)

1. Reuse infrastructure; never build a second engine inside `ArkControl.tsx`.
2. No mock/fabricated evidence in production paths.
3. Preserve workspace nav, tabs, sidebar, advisory panel, three-column layout.
4. Every AI action is permission-aware, scoped, audited, attributable.
5. Never execute unauthorized intrusive operations.
6. Human control: pause, cancel, review, approve.
7. Provider-agnostic; never couple the engine to one model.
8. Never silently spend paid credits.
9. Preserve working features; regression-test affected flows.
10. Long-running work: observable progress + recoverable state.
11. Works across environments, not just the dev Mac.

---

## 1. Phase B — Orchestrator hardening & connection

### B.0 — OpenRouter error-classification fix **(first, smallest, highest value)**

**Problem (proven statically):** `app/engine/provider_errors.py` classifies by
status code only; a `429` carrying a credit/quota body is mislabelled
`rate_limited`.

**Change:** in `public_error`, evaluate the credit-term check **independently of
status** (or include `429` in the credit branch when the body matches a credit
term), then fall back to `rate_limited` for a genuine 429. Order:

```
1. InvalidToolSchema / schema-400            -> invalid_tool_schema
2. credit terms present (any status)          -> insufficient_credits
3. 401/403                                    -> authentication_failed
4. 429                                        -> rate_limited
5. tool-calling unsupported                   -> unsupported_tool_calling
6. else                                       -> provider_rejected
```

**Tests:** extend `tests/test_cai_provider_tools.py::test_provider_errors_are_classified_without_raw_details`
with the matrix in the audit §7 — including the OpenRouter
*429 + "You exceeded your current quota"* → `insufficient_credits` case
(today asserted as `rate_limited`; the expectation must flip). Also add a
genuine-429 body (`"Rate limit exceeded, retry in 3s"`) → `rate_limited`.

**Risk:** low; one pure function + its table. No provider call.

### B.1 — Rate-limit metadata & bounded retry

**Problem:** no `Retry-After` / `x-ratelimit-*` reading; no bounded retry.

**Change:** in the orchestrator call sites (`_stream_completion` / `_complete`),
wrap the litellm call to:
- capture `Retry-After` and `x-ratelimit-remaining`/`-reset` from the provider
  response (sanitized — headers only, never a key), attach them to the raised
  error as attributes;
- retry **only** on a genuine 429, at most **N=2** times with exponential
  backoff honoring `Retry-After`, and only when the run has not been
  cancelled;
- never retry credit/auth failures.

**Tests:** hermetic — a stubbed litellm that 429s twice then succeeds, asserting
bounded attempts and backoff; and that a credit failure is never retried.

**Budget principle:** default disabled/off unless the operator enables it, so
no silent credit spend (directive #8).

### B.2 — Unify the two AI paths' diagnostics

**Problem:** `model_router` (litellm) and `ai_gateway` (httpx) report errors
differently; the settings surface can say "spent" while a run says
"rate-limited" for the same key.

**Change:** have `ai_gateway._cloud_call` classify its HTTP failures with the
same `public_error` taxonomy (map status+body → code+message) and surface the
code in `GenerationResult` (new optional `code` field, default `None` — no
caller breaks). Keep `detail` for human display. This makes one vocabulary
across both paths without merging their transports.

**Tests:** extend `test_ai_gateway.py` with a fabricated 403-credit and
429-rate response asserting the same codes as `public_error`.

### B.3 — Tool-registry consolidation (duplicate twins)

**Problem:** `imint.*` catalogue twins duplicate `image` substrate tools;
two ambiguous aliases (`webfetch`, `siemquery`).

**Change (minimal):** make collisions explicit in `unified_registry._add` —
log which tool id wins and which is skipped, and expose a
`unified_registry.collisions()` introspection used by a test that asserts the
set is **known and empty for image-critical ids**. Do **not** delete twins
(no working functionality removed, directive #9); just make the shadowing
auditable.

**Tests:** `tests/test_unified_registry_collisions.py`.

### B.4 — Intent recognition & plan (reuse, don't rebuild)

**Existing:** `engine/router.classify_intent`, `agent/planner.plan_builder`,
`agent/orchestrator` (Phase C already implemented:
`POST /investigate`, `/approve`, `/resume`).

**Change:** route "investigate this image …" style prompts into the existing
investigation path when a case/evidence is active, instead of the advisory
stream. Keep ordinary chat on `/cai/stream`. The distinction is the existing
`classify_intent` + presence of `session.case_id`.

**Tests:** extend `test_agent_intent_gating.py`, `test_phase_c_investigate.py`.

### B.5 — Execution lifecycle states

**Existing:** run statuses `RUN_COMPLETED/FAILED/CANCELLED`
(`session_store.py`) and `run_control` modes; orchestrator emits
`run_created/status/tool_*/result_verified/run_completed|failed|cancelled`.

**Change:** add the directive's richer vocabulary as **derived** presentation
state (do not replace the persisted enum): map existing events →
`PLANNING → RUNNING → VERIFYING → REPORTING → COMPLETED` plus
`AWAITING_APPROVAL / PAUSED / FAILED / CANCELLED / PARTIAL`. Implement as a
pure function `executionPresentation.ts` already partly exists — extend it.
This keeps persistence stable (directive #9) while giving the UI the required
states.

**Tests:** frontend has no runner; cover the mapping by a backend-equivalent
pure-function test where feasible, else a tsc-checked typed module + a Vitest
introduction deferred to Phase D (see §4).

---

## 2. Phase C — AI-controlled Image workspace

### C.1 — Shared investigation state (already partly wired)

**Existing:** `useInvestigation.tsx` holds `case/evidence/run/findings/audit`
slices; `ArkBusContext.tsx` carries run events.

**Change:** ensure every orchestrator event maps to the correct slice:
`evidence_recorded` → findings/evidence slice; `tool_started/tool` → execution
timeline (already done in `ArkControl.tsx:486-630`); `result_verified` →
findings with provenance. Manual UI edits and AI updates write the **same**
slice (single source of truth).

### C.2 — Live execution visualization

**Existing:** the ARK panel already renders a per-tool timeline. **Change:**
group the timeline under the current objective with per-stage status,
duration, and inspectable result (collapsed by default). No chain-of-thought.

### C.3 — Geospatial without fabrication

**Existing:** `MapWorkspace` + `SpatialTool` + `fuse_geolocation`. The recent
coordinate-finiteness fix (commit `fce31751`) already hardens the map boundary.

**Change:** distinguish **verified EXIF GPS** (tier 0/1) from **inferred
hypothesis** (tier 2) visually and in text; never plot a hypothesis as
confirmed; attach the supporting evidence node id to each candidate marker.
The evidence graph already encodes the tier — surface it.

### C.4 / C.5 — Metadata absence & browser/reverse-image

**Existing:** stripped-metadata path is tested
(`test_stripped_metadata_features.py`); `source_discovery` is provider-agnostic;
`browser.*` is runtime-gated.

**Change:** (a) confirm the investigation continues on absent metadata and ends
in an explicit uncertainty conclusion (already the design — add an assertion
to the lifecycle test); (b) add an explicit untrusted-content fence around
fetched web/browser text before it enters the model context (prompt-injection
resistance, directive §7 / #C5).

---

## 3. Phase D — Reporting engine

**Existing:** `CaseReportView.tsx` + report generator; the directive's 15
sections and the four epistemic labels (Verified / Analytical / Hypothesis /
Unknown) map cleanly onto the evidence graph's tiers.

**Change:** generate the report from the graph (not from prose): each
substantive conclusion cites a node hash; contradictions section is a graph
traversal; confidence uses the consensus engine's calibrated categories, never
a model-invented percentage (directive #D). Reuse existing export formats.

---

## 4. Testing & validation strategy

- **Hermetic by default.** Provider responses are fabricated; no live paid call
  in CI. (Directive §10: "Do not count mocked provider responses as proof of
  live integration" — so each phase also lists an **optional** live check,
  run only with your explicit consent and a single cheap call.)
- **Backend:** pytest. Baseline at audit: 807 passed / 13 env failures
  (exiftool, CAI) / 1 skipped. Every phase must keep that baseline and add
  cases.
- **Frontend:** `npx tsc --noEmit` + `npx vite build` (current baseline:
  clean). Introducing a JS test runner (Vitest) is proposed for Phase D only,
  because the repo currently has none and adding it is a larger change than
  the directive's "smallest coherent integration" for B/C.

---

## 5. Rollback & migration

- No migrations in Phase B.1 (pure function).
- New optional fields (`GenerationResult.code`, presentation-state mapping) are
  additive with defaults — no migration.
- Registry collision logging is additive.
- Rollback = revert the commit; nothing persists a new schema.

---

## 6. Credit-conservation commitments (your explicit instruction)

- **Phase B.0/B.1/B.2 are provable with zero model calls.** All three are
  error-classification + retry-mapping logic, testable against fabricated
  responses.
- Any live provider check is **opt-in**, uses the **cheapest** configured
  model, is **single-shot**, and is announced before it runs.
- Bounded retry is **off by default** so a run can never silently multiply
  spend.
- I will not call OpenRouter (or any paid model) to complete this work unless
  you say so.

---

## 7. Proposed execution order (smallest coherent increments)

| Step | Deliverable | Model calls | Files touched |
|---|---|---|---|
| B.0 | OpenRouter error classification + tests | 0 | `provider_errors.py`, `test_cai_provider_tools.py` |
| B.1 | Rate-limit metadata + bounded opt-in retry | 0 | `orchestrator.py`, new test |
| B.2 | Unified gateway error codes | 0 | `ai_gateway.py`, `test_ai_gateway.py` |
| B.3 | Registry collision auditability | 0 | `unified_registry.py`, new test |
| B.4 | Intent → investigation routing | 0 | `cai.py`, `test_agent_intent_gating.py` |
| C.1 | Event→slice mapping completion | 0 | `ArkControl.tsx`, `useInvestigation.tsx` |
| C.2 | Objective-grouped execution panel | 0 | `ArkControl.tsx`, `executionPresentation.ts` |
| C.3 | Verified-vs-inferred map distinction | 0 | `MapWorkspace.tsx`, `SpatialTool.tsx` |
| C.5 | Untrusted-content fence | 0 | OSINT/browser tool boundary |
| D | Graph-derived report | 0 | report generator, `CaseReportView.tsx` |

Each step: implement → add tests → run `pytest` + `tsc` + `vite build` → report
limitations → commit with a descriptive message. No PR (repo convention: work
on `main`), no push without your say-so.

---

## 8. Approval gate

Phase A is complete. **Awaiting approval before any production-code change.**
On approval I will begin with **B.0** (the OpenRouter fix), which is where the
diagnosed defect and the directive's Scenario 4 meet.
