# ARK — End-to-End Acceptance Scenario Ledger

**Date:** 2026-11-06
**Environment:** live — backend `uvicorn` on `0.0.0.0:12000` (`.venv-new`, py3.13),
web on `0.0.0.0:12001`, Chromium present at `/usr/bin/chromium`.
**Question this answers:** *"Did the agent complete the end-to-end acceptance
scenarios, or only validate the test suite and build?"*

**Honest answer:** the earlier summary validated the suite and the build; it did
**not** establish end-to-end scenario coverage. This ledger closes that gap by
**actually executing** the scenarios below against the live stack and recording
what passed, what is blocked, and what remains untested. Status vocabulary:

- **PASS** — executed against the live stack, observed correct behaviour.
- **BLOCKED** — exercised; could not complete because a required external
  credential/plan is absent. The code path ran and failed honestly.
- **NOT TESTED** — not exercised end-to-end in this pass; remains open.
- **HARNESS ERR** — my first attempt was wrong; corrected and re-run (recorded
  for transparency, not a product defect).

---

## A. Browser / managed-runtime scenarios

Driver: the real `app.tools.web_intel` tool surface against live Chromium.

| # | Scenario | Result | Evidence |
| --- | --- | --- | --- |
| A1 | Runtime availability + engine | **PASS** | `{available:true, engine:playwright, executable:/usr/bin/chromium}` |
| A2 | Open agent-driven session | **PASS** | `ok:true`, real `bws_…` session |
| A3 | Navigate to a real site | **PASS** | url `https://example.com/`, title `Example Domain` |
| A4 | Extract page content | **PASS** | 905 chars, correct body text |
| A5 | Screenshot capture | **PASS** | `ok:true` (bytes returned by capture endpoint) |
| A6 | SSRF — loopback target | **PASS (blocked as designed)** | `state:BLOCKED, code:ssrf_blocked` |
| A7 | SSRF — cloud metadata target | **PASS (blocked as designed)** | `state:BLOCKED, code:ssrf_blocked` |
| A8 | Control hand-off agent→operator→agent | **PASS** | `take_control`→`control:operator`; `return_control`→`control:agent`; `agent_id:"ARK"` |
| A9 | Close session | **PASS** | `ok:true, closed:true` |
| A10 | Operator HTTP plane reachability | **PASS** | `/browser/status`, `/browser/sessions` 200 |
| A11 | Operator control via HTTP on an agent-owned session | **NOT TESTED** | first attempt returned 404 due to a cross-process session (HARNESS ERR); the in-process A8 proves the mechanism. HTTP-plane control of a *live* agent session needs a server-side open trigger and is left open. |

## B. Model selection / routing scenarios

Driver: `app.services.model_router.resolve` against the live settings store.

| # | Scenario | Result | Evidence |
| --- | --- | --- | --- |
| B1 | Unspecified → admin default | **PASS** | resolved `openrouter/nvidia/nemotron-3.5-super-vl:free`, `credential_source:platform` |
| B2 | Explicit valid model honoured | **PASS** | `openrouter/openai/gpt-4o-mini` → same (no substitution) |
| B3 | Explicit **unknown** model | **PASS** | `ok:false`, `resolved:None` — refused, not silently swapped |
| B4 | Local model (Ollama) | **PASS** | `ok:false`, `credential_source:local` — honest refusal (model not pulled) |
| B5 | Provider with no credential | **PASS** | `ok:false`, `credential_source:none` |
| B6 | Entitlements surface | **PASS** | `principal:anonymous, allow_platform:true, allowed_providers:["*"]` |
| B7 | Live active-model endpoint | **PASS** | `requested == resolved`, no fallback |

## C. Investigation persistence / restoration

Driver: `SessionStore` with a real SQLite file (create → reopen → read).

| # | Scenario | Result | Evidence |
| --- | --- | --- | --- |
| C1 | Persist session + transcript + run | **PASS** | meta + 2 messages + run persisted |
| C2 | **Restore after process reopen** | **PASS** | new store instance → meta, 2 messages, model intact |
| C3 | Interrupted-run honesty | **PASS** | stale `running` run reported `interrupted` |
| C4 | Zero-retention: nothing written | **PASS** | 0 rows on disk; plaintext absent from DB file bytes |
| C5 | List + delete | **PASS** | list→delete→list count decremented |

## D. Execution control

Driver: live HTTP endpoints.

| # | Scenario | Result | Evidence |
| --- | --- | --- | --- |
| D1 | `stop` | **PASS** | `{ok:true}` |
| D2 | `queue` enqueue + read | **PASS** | `queue_id` pending → `pending_count:1` |
| D3 | `classify` (deterministic) | **PASS** | `mode:autonomous, role:network_pentester, target:10.0.0.1, conf:0.8` |
| D4 | `steer` (active run) | **NOT TESTED** | needs a live run; no reachable model to sustain one (see E) |

## E. Full investigation + HITL stream (model-dependent)

| # | Scenario | Result | Evidence |
| --- | --- | --- | --- |
| E1 | **Real image investigation** (deterministic Brain) | **PASS** | POST `/api/v1/analyze` on a GPS-tagged JPEG → coords `51.5074,-0.1278` (exact), consensus conf `0.99`, country `United Kingdom`, address `Charing Cross, WC2N 5DU`, camera `ArkGeoTestCam/AK-1` |
| E2 | Chain-of-custody | **PASS** | `custody_hash`, `image_sha256`, certificate `{sha256,sha1,md5,ingested_at_ms}` |
| E3 | HITL stream — session/run/model/agent events | **PASS** | SSE: `session`, `run_created`, `model_resolved` (`fallback_used:false`), `agent_selected` (`SpecialistRole.IMINT`) |
| E4 | HITL stream — final answer | **BLOCKED** | terminal event `{"event":"error","code":"rate_limited"}` — provider 429. **No fabricated success.** |
| E5 | Tool actually executed by the model | **BLOCKED** | follows from E4 |

## F. Cloud provider execution

| # | Scenario | Result | Evidence |
| --- | --- | --- | --- |
| F1 | OpenRouter path reachable + routed | **PASS** | request reached provider; 429 returned |
| F2 | Anthropic / Gemini / LLM / TinEye / Serper / Tavily / Mapbox / Twilio / OpenCellID | **BLOCKED** | health shows `not_configured` (no `.env`) |
| F3 | Successful cloud completion | **BLOCKED** | no working credential/plan |

---

## G. Investigation isolation (P0 defect) — browser-driven UI walkthrough

Driver: the **live renderer** at `https://work-2-…/` (real Chromium, real Vite
build), plus the live HTTP plane on `:12000`. This is the click-through that
open item #4 previously listed as not performed.

| # | Scenario | Result | Evidence |
| --- | --- | --- | --- |
| G1 | New investigation starts neutral | **PASS** | `+` → clean workspace chooser; **no** System Overview, **no** evidence bleed |
| G2 | Selecting a workspace leaves neutral | **PASS** | click Image Intelligence → `workspace.neutral:false`, `domain:"image"` persisted in `ark.investigations` |
| G3 | Draft is per investigation | **PASS** | typed "isolation probe ALPHA" in tab A; new tab B composer **empty**; returning to A restored the draft |
| G4 | Workspace selection is per investigation | **PASS** | A on Image Intelligence, B still neutral — persisted independently |
| G5 | Distinct identity per investigation | **PASS** | two records, distinct `id` **and** distinct `conversationId`, in `ark.investigations` |
| G6 | Metadata carries no content | **PASS** | persisted records hold ids/workspace/status only — no transcript, no evidence |
| G7 | Session API is principal-scoped | **PASS** | anonymous reads own session `ok:true`; `X-ARK-Principal: alice` → `ok:false, unknown session` (read **and** delete) |
| G8 | Session authz regression suite | **PASS** | `tests/test_cai_session_authz.py` — 13 tests (owner read/delete, cross-principal refusal, anonymous-vs-named both directions, scoped listing, literal `anonymous` owner) |

Backend regression suite after the change: **738 passed** (725 prior + 13 in the
authz file — owner read/delete, cross-principal refusal, anonymous-vs-named, scoped listing, plus a regression for the literal
`anonymous` owner that the orchestrator records).
Frontend `tsc --noEmit` clean; `vite build` clean.

---

## Interpretation (per the advisor's request)

The advisor asked to **distinguish missing credentials from provider
incompatibility or routing defects**. The evidence separates them cleanly:

- **Routing is correct** — B1–B7 show requested→resolved provenance with no
  silent substitution, and E3 shows the run reaching a concrete provider+model.
- **The cloud failure is provider-side rate limiting, not a defect** — E4's
  terminal event is `rate_limited` (HTTP 429 class), i.e. the request was
  *accepted and routed* and the provider declined. This is **missing usable
  credential/quota**, not incompatibility.
- **Nothing was faked** — the system reports `rate_limited` rather than
  emitting a plausible-looking answer, which is the correct fail-honest
  behaviour for a forensic tool.

## Open items (must not be claimed as complete)

1. **A11** — HTTP-plane operator control of a live agent-owned session.
2. **D4** — `steer` against a sustained live run.
3. **E4/E5, F2/F3** — any scenario whose final step requires a working cloud
   credential/quota. These are **blocked**, not passed.
4. A single **browser-driven UI walkthrough** (click-through in the actual
   Electron/Vite renderer) was not performed in the earlier pass. **Closed** in
   section G, which executed the investigation-isolation click-through against
   the live renderer (neutral start, workspace selection, per-investigation
   draft and workspace, distinct identities, principal-scoped session API).
   A scripted click-through of *every* sub-view is still not exhaustive.

*This document was produced by an AI agent (OpenHands) on behalf of the ARK
maintainer.*
