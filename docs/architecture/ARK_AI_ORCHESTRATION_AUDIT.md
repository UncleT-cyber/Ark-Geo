# ARK AI Orchestration — Phase A Architecture Audit

> Status: **Phase A — read-only audit. No production code was modified.**
> Branch: `main` @ `0548d2de`
> Scope: AI/OpenRouter pathway, existing orchestration substrate, Image
> Intelligence capability surface, and investigation-state identity.
> Method: source inspection + the full backend test suite (no live paid model
> calls were made; see §7).

This document is the first of three Phase A deliverables. Companions:

- `IMAGE_INTELLIGENCE_TOOL_REGISTER.md` — verified per-tool inventory.
- `ARK_AI_IMPLEMENTATION_PLAN.md` — phased integration plan and stop gate.

---

## 0. Executive summary

The directive assumed ARK is "a conversational assistant" that must be
*evolved* into an orchestrator. **The audit disproves that premise.** A large,
genuinely wired orchestration substrate already exists:

- A unified tool registry with **98 registered tools** across 12 domains
  (image 22, network 15, web 15, imint 12, pentest 10, osint 6, case 6, …).
- A real autonomous ReAct loop (`app/engine/orchestrator.py`) that calls the
  model through `litellm`, receives **structured tool calls**, dispatches them
  through the registry, gates them behind a `PolicyGuard`, and streams
  `tool_call / tool_started / tool / result_verified / evidence_recorded`
  events over SSE.
- A frontend (`ArkControl.tsx`) that **consumes those events and renders live
  execution** — it is not a mock chat panel.
- An evidence graph, a policy guard, an evidence recorder, a run-control plane
  (pause / stop / steer / queue), and a persistent session/run store.

So the real work is **connection and hardening, not construction**. The
highest-value findings are:

1. **The "rate-limited" message is almost certainly a misclassification of an
   OpenRouter *credit/quota* condition — not a true HTTP 429.** The classifier
   at `app/engine/provider_errors.py:27` maps any `429` to `rate_limited`, but
   it does **not** inspect OpenRouter's body when the status is 429. OpenRouter
   returns credit-exhaustion as `402`/`403` with a body such as *"You
   exceeded your current quota"*; that phrase is in the classifier's credit
   list but is only consulted for statuses `401/402/403`. A 429 whose body is a
   quota message therefore falls through to the rate-limit branch. This exactly
   matches the observed symptom: *"the model provider is rate-limited"* while a
   **different framework succeeded with a different model** (a model the
   account still had credit/eligibility for).
2. **There are two separate AI paths and they are not unified.** The
   *orchestrator* (`app/services/model_router.py` → `litellm`) and the *gateway*
   (`app/services/ai_gateway.py` → raw `httpx`) resolve models independently.
   Diagnostics, fallback, and error classification differ between them.
3. **No rate-limit/retry-after handling exists** anywhere on the model path
   (no `Retry-After`, no `x-ratelimit-*`, no bounded retry in the call sites).
4. **No live provider call is needed to prove #1.** A hermetic test against a
   fabricated 429-with-quota-body reproduces the misclassification.

---

## 1. A1 — AI and OpenRouter investigation

### 1.1 Where the message comes from

The exact string:

```
app/engine/provider_errors.py:28
code, message = "rate_limited", "The model provider is rate-limited. Try again later."
```

It is produced only by `public_error(exc)` and is emitted by the SSE error
boundary in `app/api/v1/endpoints/cai.py` (lines 619 and 643) when the run
loop raises. `public_error` derives its branch **only** from
`getattr(exc, "status_code", None)` plus lowercased `str(exc)`.

### 1.2 The classifier, verbatim logic

```
401/402/403 AND body contains a credit term  -> insufficient_credits
401/403                                      -> authentication_failed
402                                          -> insufficient_credits
429                                          -> rate_limited          <-- here
body mentions "support tool use"/"tool calling" -> unsupported_tool_calling
else                                         -> provider_rejected
```

Credit terms are: `insufficient, credit, billing, payment required,
out of funds, limit exceeded, exceeded your current`.

**Defect:** the credit-term check is confined to `401/402/403`. OpenRouter's
quota message (`"You exceeded your current quota"`) is a *credit* condition,
but when it arrives with a `429` status the body is never examined — the code
short-circuits to `rate_limited`. (The existing parametrised test at
`tests/test_cai_provider_tools.py:168` even asserts this: a 429 body of
*"You exceeded your current quota"* is *expected* to classify as `rate_limited`.)

### 1.3 Request formatting (OpenRouter)

`app/engine/orchestrator.py:_litellm_kwargs` (line ~288):

- `model` comes from `model_router.resolve()` as a **canonical** string such as
  `openrouter/openai/gpt-4o-mini`. `parse_model_id` splits only the **first**
  slash, so `provider="openrouter"`, `model="openai/gpt-4o-mini"` — correct.
- `api_base` = `https://openrouter.ai/api/v1`, `api_key` = the resolved key.
- With tools, `tool_choice="auto"` and, for OpenRouter only,
  `extra_body={"provider": {"require_parameters": True}}`. That flag tells
  OpenRouter to only route to providers that support **all** request
  parameters (tools included). On a free or thinly-provisioned model, that can
  yield *"No endpoints found that support tool use"* (404) — which the
  classifier correctly maps to `unsupported_tool_calling`.

### 1.4 The two independent AI paths (a structural finding)

| Concern | Orchestrator path | Gateway path |
|---|---|---|
| Entry | `/cai/stream`, `/cai/terminal/stream` | brain extractors, vision ensemble, OSINT |
| Model resolution | `app/services/model_router.resolve()` | `AIGateway._resolve_model()` |
| Transport | `litellm.acompletion` | raw `httpx` |
| Error surfacing | `public_error()` → typed codes | `GenerationResult.detail` (a string) |
| Fallback | entitlement-gated chain, off by default | always-on cloud→Ollama cascade |
| Retry / backoff | none | none |

A provider outage handled well by one path can be handled differently (or
mis-reported) by the other. The directive's requirement to "separate inference
/ tool-execution / state layers and survive a provider outage" is **partly
met** (state is separate and durable; see §4) but the *diagnostics* are
inconsistent.

### 1.5 Credential resolution and ownership

- Precedence (`model_router._resolve_credential`): **user BYOK → platform →
  none**. Organization-managed keys are declared but unwired.
- `key_probe.live_probe("openrouter", key)` calls `/api/v1/auth/key` and, at
  `key_probe.py:246`, **already handles the spent-key case**: it reads
  `data.limit`/`data.usage` and reports `Key limit exceeded ($x of $y used)`.
  So the *settings* surface can correctly say "spent", while the *run* path can
  simultaneously say "rate-limited" for the same key. That divergence is itself
  a defect worth fixing.
- Keys are read from the encrypted `SettingsStore` at call time (no restart),
  never logged, and the tests assert no raw secret leaks into messages.

### 1.6 Hypothesis ranking (no live call needed)

| # | Hypothesis | Likelihood | Evidence |
|---|---|---|---|
| H1 | 429 + quota body misclassified as rate-limit | **High** | `provider_errors.py` branch order; matches "other framework worked with a different model" |
| H2 | Free-model capacity limit (true 429) | Medium | `:free` models are capacity-throttled upstream; would also 429 |
| H3 | `require_parameters` routed tools to a 404 | Low-Med | would read *unsupported_tool_calling*, not rate-limited |
| H4 | Spent key (403 "Key limit exceeded") | Low | would read *insufficient_credits*; but *settings* would say spent |
| H5 | Invalid/mismatched credential | Very low | would read *authentication_failed* |
| H6 | Account-level quota restriction | High (overlaps H1) | OpenRouter distinguishes credit from rate in the body, not the status |

**Required outcome met (statically):** the actual failure mechanism is the
status-only classification in `provider_errors.py`. §7 gives the hermetic test
that proves it without spending credit.

---

## 2. A2 — Existing AI orchestration capabilities

Classification per area: **Implemented / Partial / Disconnected / Placeholder**.

| Capability | Status | Source | Notes |
|---|---|---|---|
| Conversation processing | Implemented | `orchestrator.run`, `cai.py:/cai/stream` | streaming SSE |
| Model tool-call **execution** | Implemented | `orchestrator._complete` → `unified_registry.acall` | structured calls parsed, dispatched |
| Tool registration | Implemented | `app/agent/unified_registry.py` | 98 tools, 3 sources merged |
| Tool **selection** | Implemented | `orchestrator._select_provider_tools` | domain + availability + policy filter |
| Execution events streamed | Implemented | `ArkControl.tsx:486-630` | session/run_created/tool_call/tool/result_verified/… |
| Investigation state persisted | Implemented | `app/services/session_store.py` (SQLite) | sessions, messages, runs |
| Resume after refresh/reconnect | Partial | `cai.py:/cai/session/{id}`, `mark_interrupted_runs` | transcript rehydrates; an *in-flight* run is marked interrupted, not resumed |
| Approval gates | Implemented | `run_control.py`, `orchestrator._await_approval` | auto/manual modes, HITL timeout |
| Tools access case evidence | Partial | `agent/evidence_graph.py` has `case_id`; `cai.py` sets `session.case_id` | graph is case-bound; the *provider-tool* loop reasons from prompt+graph, not from a hydrated evidence object per call |
| AI results reach central workspace | Partial | `ArkBusContext.tsx`, `useInvestigation.tsx` slices | run events update the panel; mapping event→specific tool views is not 1:1 |
| Cost/token budgets | Partial | `policy_guard.BudgetUsage`, `CostEstimate` per spec | declared on tools; not enforced end-to-end in the loop shown |
| Prompt-injection resistance | Partial | system prompt + scope lines | no explicit untrusted-content wrapper for fetched web text |

**Bottom line:** the chat component is **not** a competing engine — it is the
SSE client of a real one. Nothing needs to be rebuilt; selection, mapping, and
diagnostics need to be completed.

---

## 3. A3 — Image Intelligence tool inventory (summary)

Full table in `IMAGE_INTELLIGENCE_TOOL_REGISTER.md`. Headline counts from a
live `unified_registry.populate()`:

```
total: 98
by source: ark_substrate 58, ark_catalogue 40
by domain: image 22, network 15, web 15, imint 12, pentest 10, osint 6,
           case 6, secops 4, recon 2, ros 2, siem 2, ot 2
```

Honesty note carried into the register: **a configured provider field is not
proof of a working provider.** Availability is gated at runtime by
`orchestrator._adapter_available` (binary present / key present / Playwright
present), so the *advertised* set to the model is a subset of the registered
set. This is the correct, honest behaviour and is preserved.

Two registry warnings surfaced during the audit — worth a follow-up (not a
blocker):

```
[Unified Registry] Ambiguous normalized alias: webfetch
[Unified Registry] Ambiguous normalized alias: siemquery
```

Ambiguous aliases mean two tools normalize to the same id
(`web.fetch` vs `webfetch`, `siem.query` vs `siem_query`); the first to claim
the id wins and the other is skipped. Union is not lost (both raw ids remain
addressable), but the collision should be made explicit.

---

## 4. A4 — Investigation state architecture

Identity objects and their carriers:

| Object | Carrier | Identity | Persistence |
|---|---|---|---|
| User / principal | `services/entitlements.Principal` | `namespace()` | config + credentials |
| Session | `SessionState` (`orchestrator.py:90`) | `session_id` | `session_store` (SQLite) |
| Case | `case_id` on session/graph | caller-supplied string | passed through, not a first-class table |
| Uploaded image | evidence node | content SHA-256 | evidence graph + recorder |
| Evidence node | `agent/evidence_graph.EvidenceNode` | `node_hash(case_id, payload)` (SHA-256) | JSON per run |
| Tool execution | `EvidenceRecorder` | `execution_id` | per-run record + index |
| Observations / hypotheses | graph nodes (tier 2) | node hash | graph |
| Findings | graph `promote_to_finding` | node hash | graph |
| Reports | report generator | case | case artefacts |
| Audit records | audit nodes (`audit_tool_call`) | node hash | graph (tamper-evident) |

**Findings:**

- There **is** a consistent investigation identity: the evidence graph is
  keyed by `case_id`, every node is hash-chained, and tool invocations emit a
  tier-0 audit node with a `derived_from` edge. This is a strong, defensible
  spine.
- **The weak link is `case_id` as a first-class object.** It is a free-form
  string threaded through sessions; there is no case table enforcing that two
  sessions claiming the same case share state, or that a case cannot be read
  across principals. Isolation today rests on the caller passing the right
  `case_id` and on session-level `principal` checks
  (`cai.py:_session_visible_to`).
- Cross-user isolation is **partial**: sessions are filtered by principal;
  the case graph path does not itself carry a principal.

---

## 5. Security & risk observations

| Risk | Severity | Where | Note |
|---|---|---|---|
| Credit condition reported as transient rate-limit | Medium | `provider_errors.py` | misleads the operator, invites fruitless retries |
| Settings says "spent", run says "rate-limited" | Medium | `key_probe` vs `provider_errors` | inconsistent truth for one key |
| No `Retry-After` / `x-ratelimit-*` handling | Low-Med | model call sites | retries (if added) would be blind |
| Case graph not principal-scoped | Medium | `evidence_graph` | isolation rests on session auth |
| Untrusted web text not explicitly fenced | Medium | OSINT/browser tools | prompt-injection surface |
| Ambiguous tool aliases | Low | `unified_registry` | silent id collision |
| `require_parameters=True` may hide a model | Low | orchestrator | surfaces as 404 `unsupported_tool_calling` |

---

## 6. Test coverage map (relevant)

- `test_cai_provider_tools.py` — error classification matrix, tool-schema
  safety, invalid-schema pre-flight. **This is where H1 is pinned today (as a
  passing *wrong* expectation).**
- `test_image_intelligence_lifecycle.py` — end-to-end image
  upload→evidence→fusion→report, honestly-by-design.
- `test_phase_c_investigate.py` — planner/executor/orchestrator/graph lifecycle.
- `test_model_authority.py`, `test_model_catalog.py`, `test_ai_gateway.py`,
  `test_huggingface_gateway.py` — model resolution, catalogs, gateway.
- `test_run_control.py` — pause/stop/steer/manual approval.
- `test_session_store.py`, `test_cai_session_authz.py` — persistence + authz.
- `test_agent_*`, `test_phase_e_adaptive.py`, `test_phase_f_cross_domain.py` —
  substrate, adaptive re-planning, cross-domain reuse.

Suite status at audit time: **807 passed, 13 pre-existing environment
failures** (ExifTool binary absent; CAI harness), 1 skipped. The 13 are
environmental, not regressions.

---

## 7. How the OpenRouter defect is proven without spending credit

A hermetic test needs no network: construct an exception carrying
`status_code=429` and a body of `"You exceeded your current quota"`, then call
`public_error`. Current behaviour → `rate_limited`. Correct behaviour →
`insufficient_credits`. The same table can add OpenRouter's real shapes:

| status | body (sanitized) | current code | correct |
|---|---|---|---|
| 429 | You exceeded your current quota | `rate_limited` | `insufficient_credits` |
| 402 | insufficient credits | `insufficient_credits` | `insufficient_credits` |
| 403 | Key limit exceeded | `insufficient_credits` | `insufficient_credits` |
| 429 | Rate limit exceeded, retry in 3s | `rate_limited` | `rate_limited` |

This is the reproducible, zero-cost proof the directive asks for. **No live
paid call is required, and none was made.** (Deferred to Phase B for
verification with your consent and a single cheap call — see the plan.)

---

## 8. Read-only audit conclusion

The platform already possesses the engine the directive describes. Phase B/C/D
should **connect, classify, and harden**, not build. The single highest-value
fix is the OpenRouter error-classification defect, which is small, testable,
and explains the reported symptom exactly. Phase A stops here for approval.
