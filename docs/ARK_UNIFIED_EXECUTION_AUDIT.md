# THE ARK unified execution audit

## Baseline and decision

Audited the working tree on `main` at `74ffca7f` (`fix: clarify CAI dual licensing per Alias Robotics request`). The working tree already contained CAI, tool-adapter, tests, settings and workbench changes, an edited CAI submodule lockfile, and untracked virtual-environment files. Findings refer to the audited working tree unless explicitly marked as design. Existing changes were preserved.

**Phase 1 is gated.** The existing DNS and certificate transparency clients are suitable to reuse. The current dispatch and case boundaries cannot meet the acceptance scenario without establishing an operator identity and ownership boundary, closing equivalent CAI routes around that boundary, and adding durable task and case links. The audit therefore delivers the implementation design and verification gates. A new production route, a second registry, and an in-memory approximation of durable task history would each leave the acceptance scenario incomplete.

## Current architecture

| Layer | Inspected code | Verified behavior |
| --- | --- | --- |
| Application entry | `arkgeo-investigator-web/src/components/workbench/Workbench.tsx`, `useInvestigation.tsx`, `ArkControl.tsx`, `BottomPanel.tsx`, `src/api.ts` | React workbench with domain navigation, a shared client investigation context, separate right-dock views, and several API clients. Dock and workspace share selected case context. They do not read a shared backend task record. |
| API composition | `arkgeo-backend/main.py:create_app`, `app/api/v1/router.py` | FastAPI mounts independent route groups. CORS is applied globally. The router has no shared operations principal dependency. Administrative routes apply their own token dependency. Signaling has a separate purpose-specific operator token. |
| CAI integration | `app/engine/cai/cai/`, `app/engine/cai/registry.py`, `app/engine/cai/tools_importer.py`, `app/engine/agent_bridge.py` | The vendored framework provides agent and native tool infrastructure. The ARK registry exposes workspace role metadata and builds a combined catalogue. The workspace CAI HTTP route invokes ARK's orchestrator with a workspace. A role in a catalogue or session is insufficient evidence that the matching native factory was invoked. |
| Intent and commands | `app/engine/router.py`, `local_command_router.py`, `slash.py`, `app/api/v1/endpoints/cai.py`, `ArkControl.tsx`, `BottomPanel.tsx` | Chat has local shortcuts and sends other input to the CAI terminal stream. Console has another command parser and uses server slash completion. Backend dispatch handles some commands locally, then routes other text to advisory or autonomous CAI paths. Server slash registrations contain no passive-discovery workflow. |
| Registry | `app/agent/tool_registry.py:ToolRegistry`, `unified_registry.py:UnifiedToolRegistry.populate`, `app/engine/tool_adapter.py`, `app/engine/cai/cai/tool_registry.py` | The unified registry aggregates substrate, ARK adapter catalogue, and native CAI entries. The substrate has richer permission and availability specs. The aggregation does not establish one enforceable set of output schemas, cancellation semantics, deadlines, and availability states for all entries. The CAI tools endpoint still reads the adapter catalogue. |
| Execution and models | `app/engine/orchestrator.py:run`, `app/agent/orchestrator.py`, `executor.py`, `agent_loop.py`, `react_chain.py`, `model_gateway.py`, `app/services/ai_gateway.py` | CAI owns conversational advisory and ReAct execution, using LiteLLM and central provider settings. The investigation engine has a separate plan, execute and evidence loop. The agent task endpoint and ReAct chain supply further execution paths. The investigation planner has its own model-gateway abstraction. |
| Policy | `app/agent/policy_guard.py:PolicyGuard`, `executor.py:PlanExecutor`, `app/engine/orchestrator.py:approve,run` | The substrate checks permission, availability, budget and approval tier. The CAI loop separately checks risk and supports session-wide auto-approval. The CAI loop does not invoke the substrate guard at the dispatch point. Direct network lookups also do not invoke it. |
| Evidence and storage | `app/agent/schemas.py`, `evidence_graph.py`, `app/models/schemas.py`, `app/services/storage_service.py`, `analyst_overrides.py`, `settings_store.py`, `useInvestigation.tsx` | Typed request and response schemas are distinct from persistence. Evidence Graph has hashed nodes, signed corroboration and contradiction weights, and promotion rules. Existing SQLite tables cover settings and overrides. Image bytes have their own storage service. Case Explorer primarily reads browser history and snapshots. No shared case, task and event database schema was found on the discovery path. |
| Observability | `app/services/bus.py:EventBus`, `app/api/v1/endpoints/cai.py:events`, `app/api/v1/endpoints/agent.py`, `ArkBusContext.tsx` | CAI SSE emits session, tool, approval and completion events. The bus also broadcasts arguments and results to a process-wide topic and workspace topics. Queues are process-local and have no replay. Agent-task events have a separate endpoint. The browser bus retains at most 200 events in memory. |

The existing design documents describe the intended epistemic separation and guard. Treat their phase labels as design history. The active endpoints and dispatch code determine which guarantees hold. See [ARK AI orchestration specification](ARK_AI_ORCHESTRATION_SPEC.md) and [Integrated Security Environment](ARK_INTEGRATED_SECURITY_ENVIRONMENT.md).

## Fragmentation map

| Origin | Actual path | State and observable result | Consequence |
| --- | --- | --- | --- |
| Network Discovery Enumerate | `NetworkWorkbench.tsx:DiscoveryTab` → sequential `api.rdap`, `api.bgpLookup` for IPv4-looking input, `api.dnsLookup`, `api.crtSearch` for domains → `endpoints/network.py` | Results are component state. A separate Fold action adds selected observations to the client case. The normal action has no server-side task ID, progress events, or cancellation. | Navigating away loses the mounted results. The browser can save folded observations, but that is a different action from persisting a task. The code also attempts an A lookup with the IPv4-shaped input, despite the DNS handler's domain validator. |
| CAI operational prompt | Chat → `/cai/terminal/stream` → `engine/orchestrator.py:run` → unified registry dispatch | `SessionState` and approvals live in process memory. Workspace and case IDs can be caller supplied. DNS and WHOIS adapters use `dig` and `whois`; CT uses a separate `urllib` implementation with a different output schema. | A similar prompt can perform different work from Enumerate. Session or case labels do not persist a case relationship. |
| Slash or workspace command | Dock-local shortcut or Console parser → `/cai/command` or `/cai/workspace/{workspace}/run` | Some slash commands mutate conversational state. The workspace route sets a CAI workspace. No registered deterministic passive workflow spans either path. | Autocomplete and capability visibility differ across the dock. Listing a tool does not prove availability, policy eligibility, or dispatch compatibility. |
| Endpoint Mapping | `NetworkWorkbench.tsx:EndpointsTab` → CT endpoint → local state → optional fold | Reuses the CT HTTP handler but has its own execution and fold state. | A future task-backed CT step can serve both views while preserving their presentations. |
| IMINT | Workbench upload → `/analyze` → Brain cascade → client `runImagePipeline` → separate advisory review | Image results and selected audit data persist in browser snapshots. The explicit `/investigate` plan/approve/resume flow has a separate process-local investigation session and Evidence Graph. Advisory review is a separate stream. | Existing deterministic image analysis remains the evidence producer. Advisory text and the two execution mechanisms have different identity, retention and lifecycle rules. |
| Case Explorer | `CaseExplorer.tsx` → `useInvestigation.tsx` → browser history and snapshots | Browser storage keys `ark.caseHistory` and `ark.caseSnapshots`; capped history and snapshot retention. CAI case adapters also address a filesystem vault independently. | A case ID supplied to CAI does not prove that the browser case or any backend case exists, or that the caller owns it. |
| Network traffic, web, telecom, security testing | Specialized components → dedicated network/ingest, webprobe, telecom and security/agent endpoints | Tool-specific state, output types and approval paths. The security attestation endpoint records a self-asserted declaration and is not an authenticated execution grant. | Preserve these entry points during the proof. Later migrate their execution behind the common policy and event contract. |
| Threat & SecOps | `SecOpsPlaceholder.tsx` plus substrate and CAI adapter inventory | Workspace lists planned modules. Selected adapters accept telemetry or external configuration. | Tool presence does not establish an integrated SIEM, IDS, or incident workflow. |

### Security blockers and required closure

1. **Identity and ownership.** The inspected CAI stream, approval, event and passive lookup routes lack a common authenticated workbench principal. Reusing an admin bearer token would couple the operator surface to the protected control plane. Establish a distinct operator principal, derive role and capability server-side, and enforce owner/case access on create, confirm, cancel, read and event replay. A local lab binding can be a deployment control, but it does not establish per-case ownership.
2. **Equivalent execution paths.** Registering a passive workflow while leaving equivalent tool execution reachable through legacy CAI, direct APIs, and agent dispatch would leave the mandated policy bypass test unsatisfied. Put the participating handlers behind the same guard. The first slice needs a fixed capability allowlist and a deterministic passive provider set. Reject raw shell, port scans, direct target HTTP and tool substitutions. Inventory equivalent native aliases and either migrate or fence them before exposing the workflow.
3. **Approval and scope.** A prompt, client case ID, or attestation is not authority. Approvals must bind an authenticated principal to the canonical target, plan revision, allowed step IDs and expiry. Inspect `engine/orchestrator.py:approve` before reusing it. It accepts a session and optionally an execution ID, with a session-wide auto-approval mode. Phase 1 should use plan-specific approval and no blanket grant.
4. **Durability and confidentiality.** Existing task/session maps and the global event bus cannot establish durable ownership or replay. Persist owner-bound task transitions, case associations and sanitized event records before publication. Avoid broadcasting target data or provider payloads on `ark`. Keep raw evidence and credentials outside event envelopes and model instructions.
5. **Provider result semantics.** DNS and CT handlers can return HTTP 200 with failure text and empty lists. Do not treat that response as a successful lookup with no records. Preserve distinctions among verified empty, provider failure, invalid output, timeout and cancellation. Normalize/bound provider data and treat DNS TXT, CT names, and other external strings as evidence data rather than model instructions.

## Target architecture

```text
Network form ─┐
Slash parser ─┼─> ARK operation admission ─> validated plan ─> operator approval
CAI intent  ──┘                 │                                    │
                                │                                    v
                                │                  Policy Guard + registered handlers
                                │                                    │
                                └──────────────> task/case/evidence + event journal
                                                                     │
                                         Chat / Plan / Activity / Console / Network / Cases
```

- **CAI boundary.** CAI produces a typed operation candidate and later summarizes verified evidence. Use the existing intent/router and slash catalogue as adapters. For the proof, only the selected operation and its strict target schema can be proposed. Ambiguity leads to a clarification or unsupported response. A model proposal is never executed directly. No changes to the vendored CAI code are required by this design.
- **Capability boundary.** Register the shared DNS and CT clients through the existing typed substrate and expose them through the existing unified registry. Extract provider clients from route handlers and keep compatibility wrappers where required. Separate stable canonical IDs from provider-safe function aliases, detect collisions, and enforce availability, input/output schema, permissions, risk, timeout, cancellation and workspace metadata at the adapter. Expose configured, disabled, experimental, installed and planned states separately from execution eligibility.
- **Task boundary.** Extend the existing guarded execution substrate with a durable task adapter. Do not clone the ReAct loop. Use an opaque task ID, operation ID, case ID, owner, canonical scope, plan digest, authorization decision, idempotency key, lifecycle, timestamps and an event cursor. Store task and case associations transactionally. Store provider artifacts once and link them to Evidence Graph nodes and findings. Keep operator-visible observations distinct from AI interpretation and preserve existing promotion rules.
- **Event boundary.** Use authenticated per-task SSE with durable ordered event IDs and replay from a cursor. Persist first, then publish a wakeup. On reconnect, replay persisted events and deduplicate by ID. Keep bounded queues, heartbeats and scoped reads. A refresh should resolve a case's task IDs and reload the same results without reissuing provider requests.
- **UI boundary.** Keep Chat for intake, Plan for scope and approval, Activity for status and verified tool events, and Console for diagnostics. Network Discovery and Cases fetch the same task and evidence projection. Selecting an item may navigate and restore view state without launching another execution.

### Lifecycle and failure handling

Use `CREATED → PLANNING → AWAITING_APPROVAL → QUEUED → RUNNING → COMPLETED | FAILED | CANCELLED`. Support denial and expiry before dispatch, with a terminal reason and no tool work. A completed task may carry explicit per-step errors and partial evidence. An all-failed task is failed. Use conditional updates to prevent double approval, claim or terminal writes. Scope the idempotency key to the principal and request digest. Repeating the key with different input is a conflict. A safe retry creates a linked attempt, preserves completed evidence, and requires fresh approval when scope changes.

Use deadlines for each provider and for the overall task. Cancel queued work transactionally. A running task may enter cancellation only if the worker can propagate a cancellation token into the HTTP request, stop scheduling steps and record a terminal acknowledgement. Provider work already accepted may still finish remotely. A worker crash records interruption after its lease expires. Preserve partial results and avoid automatic re-execution unless the step's retry contract makes that safe. The first slice does not advertise pause or resume.

## Phase 1 implementation sequence and acceptance gates

1. **Operator and policy foundation.** Establish an authenticated operator dependency and bounded passive capability. Bind the plan and approval to exactly one validated public hostname. Reject URLs, IP literals, CIDRs, options, wildcards, internal names, multiple targets, and out-of-scope operations in this slice. Define explicit query types and CT subdomain scope. Verify equivalent CAI/legacy paths fail closed when authorization is missing.
2. **Shared provider clients.** Reuse the DoH and CT implementations after extracting transport, validating results and mapping provider failures. Use fixed HTTPS provider destinations, bounded responses and explicit redirect policy. Preserve existing RDAP and BGP behaviors as separately identified operations during migration. They are outside the requested DNS/CT proof. A capability flag should accurately indicate that distinction.
3. **Authoritative record.** Add the smallest transactional backend store for cases, tasks, and ordered events, with owner-based reads, approval compare-and-set, and artifact references. SQLite is a candidate for the single-user lab. Use the existing Evidence Graph for the case's provenance model, and document how browser-only cases coexist or migrate. Do not silently duplicate a backend case into browser evidence storage.
4. **Converge the three entry points.** Wire Enumerate for valid domain targets, a registered structured command, and the CAI typed intent to the same admission and executor. The example request should create a case and a plan, ask for passive scope confirmation, run the two registered capabilities once, then populate both the dock and the Network view. Case Explorer should query the backend case projection and reopen the same task and evidence.
5. **Release gate.** Verify with mocked providers and synthetic evidence. Cover parser parity, registry lookup, strict input, auth and ownership, plan revision and expiry, idempotency under concurrent requests, no provider requests before approval, sanitized ordered event replay, refresh and navigation, partial failure, all-failed runs, cancellation and legacy bypass attempts. Use a browser against fixtures to verify plan confirmation and task reuse from both Chat and Enumerate. Gate the feature until these checks pass.

## Domain maturity and expansion roadmap

| Domain | Audited maturity |
| --- | --- |
| Network, web, digital forensics | Network DNS/CT/RDAP/BGP, PCAP, web header analysis and IMINT pipelines have wired entry points. Web/API security beyond existing probes remains partial. |
| Vulnerability assessment and authorized penetration testing | UI, attestations, registered tools, and agent routes exist. Shared policy and durable task ownership are incomplete. Treat these paths as lab capabilities. |
| Threat intelligence, DFIR, incident response, and security research | Case evidence, selected enrichment and forensic tools, and local/custom tool infrastructure exist. End-to-end DFIR and incident workflows remain partial or planned. |
| Malware analysis, phishing, controlled social engineering, cloud, containers, wireless, compliance | Catalogue entries or related lab utilities may exist. No end-to-end workspace execution was verified for these domains. |
| Mobile security | The mobile safety app and telecom tools are present. A dedicated mobile-security assessment workflow was not verified. |
| SIEM, IDS/IPS, monitoring, hunting, detection engineering | Planned SecOps modules and selected tool adapters exist. Continuous ingestion, correlation, operator response and operational lifecycle were not verified. |

After the proof, migrate passive RDAP/BGP and Endpoint Mapping first. Then adapt IMINT upload and the existing Brain/cascade as evidence producers with preservation of zero-retention semantics. Next migrate web and API analysis, followed by evidence intake, DFIR and case-backed reporting. Add sensitive actions only after target scope and isolation are proven. Treat custom research tools as registry extensions with explicit schemas, policy, timeouts and isolated execution.

### SecOps integration-first options

- **Wazuh** for endpoint telemetry and alerts. Start with a read-only connector scoped to selected alert indices. Preserve source alert IDs and original event times. [Wazuh architecture](https://documentation.wazuh.com/current/getting-started/architecture.html)
- **Suricata** for network alerts and protocol telemetry. Consume EVE JSON first. Treat changes to inline enforcement as a separate approved response action. [Suricata EVE JSON](https://docs.suricata.io/en/latest/output/eve/eve-json-output.html)
- **Zeek** for connection, DNS, HTTP and TLS investigation context. Normalize a small set of logs and correlate on timestamp and flow identity where available. [Zeek common logs](https://docs.zeek.org/en/current/reference/logs/index.html)
- **OpenSearch Security Analytics** for indexed hunting, detector findings and correlation. Reuse it where already deployed. Keep the task/case journal separate from the telemetry index lifecycle. [OpenSearch Security Analytics](https://docs.opensearch.org/latest/security-analytics/)

ARK should own connector credentials, schema normalization, provenance links, deduplication, case correlation, hunting workflow, rule-change review, incident history and approval of response actions. Begin with read-only ingest and normalized evidence. Add rule-management and response dispatch after identity, policy, audit and rollback behavior have been verified.

## Verification and change boundary

Ran from `arkgeo-backend`:

```sh
.venv/bin/python -m pytest -q tests/test_agent_policy.py tests/test_agent_substrate.py tests/test_cai_dispatch_sot.py tests/test_ark_cai_engine.py tests/test_telecom_network.py
```

**81 passed, 9 failed.** Failures include stale references to `_run_cai_tool` and `orch.tools`, a legacy provider function-name assertion, a local real-tool output assertion, and event-loop setup failures. The CAI dependency also reported that the sandbox prevented writing its usage file. These are findings on the audited dirty baseline. A clean-commit comparison was not performed, so this audit does not attribute them to a specific earlier change.

Frontend checks from `arkgeo-investigator-web` passed with `./node_modules/.bin/tsc --noEmit` and `./node_modules/.bin/vite build`. Vite reported an unresolved build-time `./vendor/leaflet.css` reference and an oversized chunk warning. Browser behavior was not verified.

Security checks were static tracing of auth dependencies, approval and dispatch, scope validators, storage and bus payloads. No intrusive external testing or deployment was performed. No browser acceptance run was performed because the unified Phase 1 workflow is gated. Existing tests demonstrate component coverage and expose baseline drift. They do not establish Phase 1 acceptance.

**Exact audit change** is this Markdown file. Recommended next commit boundary is the audit alone, followed by an independently reviewable Phase 1 foundation commit covering the operator principal, passive policy adapters, and baseline dispatch-test reconciliation. Keep the existing unrelated work and CAI submodule edits out of both boundaries.
