# ArkGeo — Repository Knowledge Base

## Project Overview
ArkGeo is a modular AI geolocation and personal safety ecosystem with three applications:
- **arkgeo-backend** — FastAPI modular "Brain" AI engine (4-tier pipeline) + **ARK AI orchestration substrate** (`app/agent/`)
- **arkgeo-mobile** — React Native / Expo tactical safety HUD
- **arkgeo-investigator-web** — React / Vite forensic OSINT dashboard

## Repository
- GitHub: https://github.com/UncleT-cyber/Ark-Geo.git
- Working directly on `main` branch (no feature branches / PRs)

## Architecture: The Brain (4-Tier Pipeline)
1. **Tier 1 — EXIF Metadata**: deterministic GPS extraction (piexif + Pillow)
2. **Tier 2 — Vision Ensemble**: multi-API Vision aggregator (GeoSpy/GeoInfer)
3. **Tier 3 — Clue Extractors**: architectural, botanical, OCR, infrastructure, indoor
4. **Tier 4 — Consensus Engine**: Bayesian confidence scorer + pin aggregator

## Key Commands

### Run everything (canonical)
```bash
./launch.sh            # backend :12000 + web :12001 (+ Ollama if present)
./launch.sh status     # what is running
./launch.sh stop       # stop what launch.sh started
```
Ports are **backend 12000 / web 12001** (the vite proxy targets :12000). Do NOT
use 8000/5173 — those are stale and leave the web portal unable to reach the API.

### Backend
```bash
cd arkgeo-backend
.venv-new/bin/python -m pytest tests/ -q   # run tests (the real venv; .venv symlink is broken)
.venv-new/bin/python -m uvicorn main:app --host 0.0.0.0 --port 12000
```

### Web Portal
```bash
cd arkgeo-investigator-web
npm install
npx tsc --noEmit                        # type-check (clean)
npx vite build                          # production build
npm run dev                             # dev server (port 12001, proxies /api → :12000)
```

### Mobile
```bash
cd arkgeo-mobile
npm install
npx expo start                          # Expo dev server
```

## Tech Stack
- Backend: Python 3.13, FastAPI, Pillow, piexif, pydantic, python-jose, bcrypt, boto3, httpx
- Mobile: React Native 0.74, Expo 51, expo-camera/location/av/sqlite/secure-store, react-native-maps
- Web: React 18, Vite 5, Leaflet, axios, TypeScript 5

## Security
- AES-256-GCM encryption (app/core/security.py)
- JWT auth + bcrypt password hashing (no passlib — uses bcrypt directly)
- SHA-256 chain-of-custody hashing
- Zero-retention mode for forensic uploads
- Encrypted SQLite offline queue (mobile)

## Design Language
- OLED Dark Slate (#0B0F17), Electric Cyan (#38BDF8), Emergency Red (#EF4444)
- Tactical HUD aesthetic, mono fonts for telemetry data

## Testing
- pytest-asyncio mode=STRICT
- Run with the real venv: `.venv-new/bin/python -m pytest tests/ -q` (the `.venv` symlink is broken)
- Baseline is green: **738 passed** (725 + 13 session-authz isolation tests). When a failure only appears in the full run but passes in isolation, it is test pollution — a prior test closed the event loop, so any test using `asyncio.get_event_loop()` breaks. Convert such tests to `@pytest.mark.asyncio async def`.
- Several tests exercise **real local binaries** and fail (not skip) when they are missing: `exiftool` (deep metadata), `dig`/`whois` (DNS/WHOIS), `nmap`/`gobuster` (HITL orchestrator dispatch requires the tool to be *available*), `tesseract` (OCR; this one *skips* cleanly). On Debian: `sudo apt-get update && sudo apt-get install -y libimage-exiftool-perl dnsutils whois nmap gobuster tesseract-ocr`. With them installed the suite is fully green (738 passed / 0 skipped).
- Orchestrator/engine tests monkeypatch `litellm.acompletion` and must:
  - pass **provider-sanitized** tool names (`provider_name("net.dns_lookup") == "ark_net_dns_lookup_<hash>"`), never raw ids, since dots are invalid at the model boundary;
  - provide an **engagement-scope fixture** (`ARKGEO_ENGAGEMENT_SCOPE`) — target-bearing calls fail closed without one;
  - supply every **required** tool arg (e.g. `net.nmap_scan` requires `target` *and* `ports`) or dispatch returns "outside the permitted task schema";
  - stub `orchestrator._dispatch_tool` so no real scan/fetch runs.
- Browser-runtime tests: `tests/test_browser_endpoints.py` drives a real Chromium through the ASGI `TestClient` **portal** (`client.portal.call(...)`) so the session lives on the same event loop as the request; the lifecycle test is `skipif`-guarded on `browser.availability()`.
- Known non-blocking warning: httpx/TestClient deprecation in Starlette; pytest-asyncio `asyncio_default_fixture_loop_scope` unset.

## Gotchas
- HuggingFace model catalog is **live-first** (`https://router.huggingface.co/v1/models`) with the curated on-file whitelist as fallback — tests that assert `source == "curated"` must mock the router (respx) or they hit the network.
- Vision routing (`ai_gateway._VISION_NAME_RE`) must **not** match text-only models (`qwen2.5-coder`); a configured text-only model never receives an image.
- `asyncio.create_task` needs a strong reference (see `_spawn_background` in `app/api/v1/endpoints/agent.py`) or the stream can be GC'd mid-run.
- Egress guard (`app/tools/web_intel/guard.py`) refuses private/loopback/link-local/metadata targets and non-http(s) schemes; cloud-metadata is refused even with `ARK_WEB_ALLOW_INTERNAL=true`.
- **Managed browser sessions are per-process**: `app/tools/web_intel/browser.py` holds one in-process `browser_manager`. Sessions created by the pytest ASGI portal, or by any other process, do **not** appear in the running uvicorn — the operator plane only sees its own sessions. The operator plane is `app/api/v1/endpoints/browser.py`: `GET /api/v1/browser/status`, `GET/POST /api/v1/browser/sessions` (POST opens a session — the operator-initiated flow the workspace omnibox uses; body `{url, investigation_id, case_id}`, attribution threaded through `browser_operator_open` into `browser_manager.open`), `GET /sessions/{id}`, `/sessions/{id}/navigate`, `/sessions/{id}/history`, `/sessions/{id}/control`, `/sessions/{id}/capture`, `/sessions/{id}/frame`, `/sessions/{id}/close`. The operator plane is **not** gated by the agent-plane control suspension: navigation/history keep working while the operator holds control (control state is `agent` | `operator`).
- Backend has **no `--reload`**: adding a route requires an explicit uvicorn restart or the live process keeps serving the old app (a fresh route can 405/404 while `main.py` already defines it).

## Conventions
- No node_modules, .env, __pycache__, dist/ in version control

## Workbench Architecture (Integrated Security Environment Refactor)
The investigator UI is being transformed into the ARK ISE — an Integrated
Security Environment with workspace-based navigation.
Backend remains the source of truth for all forensic objects.

### Backend evidence model extensions (new)
- `exiftool_service.py`: deep metadata via ExifTool (`exiftool -j -G0:1 -struct`), grouped tree (EXIF/XMP/IPTC/ICC/MakerNotes)
- `consistency_engine.py`: structured metadata consistency findings (TIMELINE_ANOMALY, etc.) with status/type/severity
- `contradiction_engine.py`: cross-reference evidence layers for structured contradictions
- `c2pa_service.py`: provenance analysis (verified/unavailable/invalid/incomplete states)
- `geolocation_fusion.py`: multi-layer evidence model with explainability
- `source_discovery.py`: provider-agnostic reverse image search (pHash + extensible provider registry)
- `analyst_overrides.py`: confirm/reject/needs-review with audit logging
- `services/overview_service.py` + `api/v1/endpoints/overview.py`: **System Overview aggregate** — `GET /api/v1/overview?period=24h|7d|30d&traces=N` returns a principal-scoped snapshot (KPIs, operational-activity series, live agents, model authority, provider health, usage, security/custody, evidence/audit, recent execution traces). `build_overview(principal, *, period_hours, trace_limit)` is **async** (it probes providers via `ai_gateway.status()`). Read-only over existing stores; introduces no new telemetry. Unmeasured values are `None` (UI renders `—`), never a fabricated `0`. Read helpers: `run_control.list_controls()`, `evidence_recorder.load_run_record()/load_run_index()`.

### ARK AI orchestration substrate (`app/agent/`) — Phase A (no AI yet)
Design doc: `docs/ARK_AI_ORCHESTRATION_SPEC.md`. The three-investigator model
(Human / ARK Core / ARK AI) is **epistemic**: Core outputs are facts, AI outputs
are hypotheses. A hypothesis cannot be promoted to a finding without
corroboration from a higher epistemic tier — enforced structurally, not by
prompt.
- `agent/schemas.py`: ToolSpec, EvidenceNode/Edge/Finding/Graph, PolicyRule/Decision,
  InvestigationObjective, PlanRevision/PlanStep (the contracts Phase B+ consumes)
- `agent/tool_registry.py`: registered wrappers over the existing deterministic
  tools (custody hash, EXIF, ExifTool, reverse-geocode, telemetry, ELA, EOF,
  C2PA, consistency, OCR, geolocation fusion, source discovery, contradictions,
  vision ensemble, consensus). Each is a `ToolSpec` + thin handler; **zero behavior
  change** to `BrainPipeline`/`/analyze`. `registry.call(id, **kw)` (sync) /
  `registry.acall(id, **kw)` (async-aware).
- `agent/evidence_graph.py`: pure, audited graph ops. `build_node`/`add_node`
  (hash-validated, tamper-evident), `add_edge` (corroborate=+weight /
  contradict=-weight, sign enforced), `can_promote`/`promote_to_finding` (the
  promotion rule: tier-0/1 promotable alone; tier-2 needs tier-0/1 corroboration
  OR >=2 independent tier-2 agreements; a higher-tier contradiction blocks).
- Tests: `tests/test_agent_substrate.py` (18 tests: registry, graph, promotion rule).
- `agent/policy_guard.py` (Phase B): the authorization surface. `PolicyGuard.evaluate(tool_id)`
  returns a `PolicyDecision` (allowed/approval_tier/reason/rule_id); `authorize()` raises typed
  exceptions (`PermissionDenied` / `BudgetExceeded` / `ToolUnavailable`). Checks: capability
  permissions (parameterized `call:provider:<name>`; bare `call:provider` implies any), risk->
  approval tier (low=auto, medium/elevated=confirm_once, action/high-risk=step_confirm; explicit
  rules can only raise, never downgrade below the risk default), availability (requires_key
  resolved lazily via the existing settings store so Admin key updates take effect immediately;
  disabled always denied), and budget enforcement (steps/tokens/ms/api_calls via
  `BudgetUsage`/`record_run`). `default_rules()` ships sensible defaults. Exceptions exported.
- `evidence_graph.audit_tool_call` (Phase B): every audited tool invocation emits a tier-0
  (cryptographic) audit `EvidenceNode` with an `arguments_hash` (secrets never stored raw) plus
  a `derived_from` edge to the produced evidence node — making policy->tool->evidence lineage
  queryable on the graph. Audit nodes are hash-validated/tamper-evident like all nodes.
- Tests: `tests/test_agent_policy.py` (24 tests: allow/deny paths, permission/capability checks,
  approval tiers, availability gating, budget exhaustion across all 4 counters, typed authorize
  exceptions, custom-rule override + no-downgrade guarantee, audit emission/linking/tamper).
- Phasing: A=registry+graph, B=policy guard (done), C=smallest orchestrator
  loop (one goal), D=console tabs, E=adaptive re-planning, F=cross-domain
  reuse. Full plan incl. phases G-J and the integrated security environment:
  `docs/ARK_INTEGRATED_SECURITY_ENVIRONMENT.md`.

### ARK Super Intelligence — Phase A/B (autonomous investigation & orchestration)
Docs: `docs/architecture/` (ARK_AI_ORCHESTRATION_AUDIT.md, IMAGE_INTELLIGENCE_TOOL_REGISTER.md,
ARK_AI_IMPLEMENTATION_PLAN.md, CASE_GRAPH_AUTHORIZATION_BOUNDARIES.md). Audit conclusion: a real
orchestrator already exists (98 tools / 12 domains, ReAct loop, SSE execution events, evidence
graph, PolicyGuard) — the work is connect/classify/harden, not build.
- **Provider error classification (done)**: `app/engine/provider_errors.py` is now
  **body-decisive, status-aware**. `classify_code(status, body)` is the single taxonomy shared by
  `public_error` (CAI stream) and `ai_gateway._cloud_call` (new `GenerationResult.code`). A 429
  carrying a quota body ("You exceeded your current quota") is `insufficient_credits`, not
  `rate_limited`; a generic "limit exceeded" is credit only without throttle phrasing. Codes:
  invalid_tool_schema / insufficient_credits / authentication_failed / rate_limited /
  rate_limited_model / unsupported_tool_calling / model_unavailable / provider_rejected.
  Only status + body are read — never headers; raw body is never surfaced.
- **Bounded retry (done)**: `orchestrator._acompletion` wraps `litellm.acompletion` (used by
  `_complete` and `_stream_completion`). **OFF by default** (`ARKGEO_PROVIDER_RETRY=1` or admin
  `provider_retry_enabled`); only genuine throttles retried; max `ARKGEO_PROVIDER_RETRY_MAX` (2,
  cap 5); honours `Retry-After` (header-only) else exponential backoff capped by
  `ARKGEO_PROVIDER_RETRY_MAX_SLEEP_S`. `is_retryable()` excludes credit/auth. No paid fallback.
- **Registry collisions (done)**: `unified_registry.collisions()` exposes normalized-alias clashes
  (known: `webfetch`, `siemquery`); no capability lost.
- **Case-graph authz (documented, NOT yet changed)**: CAI sessions are principal-scoped
  (`cai._session_visible_to`) but `/investigate` endpoints and `InvestigationSession` have **no
  owner field/check** — `GET/approve/resume` act on any id. Proposed additive fix (owner field
  defaulting to ANONYMOUS, principal resolved in investigate.py, non-owner → 404, no DB migration)
  is in the boundaries doc and **awaits approval** (it changes authorization policy).
- Tests added: `test_provider_retry.py`, `test_unified_registry_collisions.py`; extended
  `test_cai_provider_tools.py` (full 400/401/402/403/404/405/422/429/500/503 matrix) and
  `test_ai_gateway.py` (gateway/stream parity). Baseline: **835 passing**, 13 pre-existing env
  failures (exiftool/nmap absent, CAI harness), 1 skipped. `tsc --noEmit` + `vite build` clean.
- Credit conservation: no live paid model call made in Phase A/B; all provider responses fabricated.
- **Identity (canonical)**: the platform has ONE user-facing intelligence —
  **ARK, Cybersecurity Super Intelligence** ("THE ARK's sole user-facing
  intelligence"). The CAI framework is an internal engine only; never brand it
  as a separate assistant (no `ARK-CAI` label, no "CAI Browser", no CAI
  banner). The canonical prompt is `app/agent/cognitive/00_identity.prompt`;
  the live orchestrator appends an `[ARK RUNTIME STATE]` block naming ARK and
  the active model. Startup banner reads `ARK SYSTEM INITIALIZED`. Internal
  identifiers (`caiBrowserBus`, `caiTerminalStream`, the `app/engine/cai/cai/`
  snapshot, README license attribution) stay as-is.
- **ARK Cognitive Architecture** (12 core units + 5 domain specialists): the
  canonical structure is `docs/ARK_INTEGRATED_SECURITY_ENVIRONMENT.md` §2.
  Contracts live in `app/agent/schemas.py` (Hypothesis, Critique,
  ContextFrame, ModelSpec, structured Finding, SpecialistSpec — units 05-10).
  `app/agent/specialists.py` registers the domain specialists (IMAGE is live
  with 16 tools; NETWORK/SECOPS/OSINT/WEB declare planned tool ids only).
  Phase C builds units 01 (orchestrator), 02 (planner), 07 (context), 09
  (model gateway), 10 (findings wiring).
- Local LLM: Ollama on-host; use cached models only (`qwen2.5-coder:3b` is the
  Phase C planner). Do NOT pull new models without explicit instruction.

### Frontend workbench shell (domain-based investigation architecture)

THE ARK is organized by INVESTIGATION DOMAINS, not individual tools. Each domain
contains every tool required to complete that investigation.
- `entities.ts`: shared entity model (DomainId, InvestigationCase, EvidenceItem, etc.)
- `useInvestigation.tsx`: InvestigationProvider context + `useInvestigation()` hook — holds domain, active case, result, history; drives domain switching across all components
- `InvestigationNavigation.tsx`: the sidebar information architecture — a scrollable body with three groups in fixed order, flowing top to bottom: **WORKSPACES** (Image Intelligence, Network Intelligence, Threat & SecOps), **INVESTIGATIONS** (Case Explorer, Use Cases — preceded by extra breathing room), **AUTOMATION** (Agents & Workflows, Planned); **SYSTEM** (Admin* role-gated, Settings; *only when authenticated) is **pinned to the sidebar footer** via `margin-top:auto`, below the scroll area. Items are 8px apart, groups 18px apart, sidebar padding 8px 14px. **No New Investigation button, no per-session recent-investigations list, no Command Palette item, and no expanded Quick-starts list** — open sessions live in the titlebar tabs; saved-case retrieval lives in Case Explorer; quick starts live in the Use Cases surface. Collapse toggle is the single button in `.investigation-nav-heading`, right-aligned (never centered).
- `ActivityBar.tsx`: superseded by `InvestigationNavigation` (the domain ActivityBar is no longer rendered; kept only for legacy reference).
- `TopBar.tsx`: the **investigation tab strip** (`tabs`/`activeTabId`/`onSelectTab`) — scrollable tab row with per-tab status dot, close, a `+` new-investigation button, and a tab-overflow menu; plus the **notification bell** (unread count, dropdown, mark-all-read) at the far right. It is the window titlebar in Electron, so it keeps the macOS `padding-left: 78px` / Windows-Linux `padding-right: 148px` safe zones and marks `.ark-tab` as `-webkit-app-region: no-drag`. NO duplicate logos, NO admin link, NO command-palette trigger or connection status (those moved to the CommandPalette hotkey and StatusBar).
- `Workbench.tsx`: wraps everything in `<InvestigationProvider>` → TopBar + InvestigationNavigation (sidebar) + MainViewport + ARK dock + StatusBar. **Full-page destinations (System Overview / Settings) and the derived-domain pitfall:** `inv.domain` is derived from the *active investigation's stored workspace* (`metaFor(activeId).workspace.domain`), not from the tab. Re-selecting an already-active tab therefore changes nothing, so the tab-activation effect never re-runs and a bare `selectTab` is a no-op once the domain has drifted. `Workbench` routes every tab selection through `activateTab(id)`, which first `patchWorkspace`es `{ domain, neutral: false }` for `system`/`settings` tabs, then `selectTab`s — this keeps the sidebar item, the tab strip and the viewport in agreement. Owns the tab registry (`useInvestigationTabs`), the notification list, and the active Settings section; handles `handleSelectSession` (reloads a dashboard session into the image workspace). Save/Export moved into the CommandPalette. When the active tab's domain is `settings`, the sidebar / main viewport / ARK dock / StatusBar are hidden and `<SettingsWorkspace>` fills the body instead.
- **Investigation tabs** (`src/core/tabs/tabRegistry.ts` + `src/core/tabs/useInvestigationTabs.ts` + `src/core/storage.ts`): a tab is `{id, sessionId, title, domain, caseId, runStatus, rev, origin, deleted?}`. `id` is the stable client tab id; `sessionId` binds to the backend durable session. Tabs persist via `core/storage.ts` (localStorage in the browser, the Electron bridge in the shell) and sync across windows with a revision-stamped BroadcastChannel merge. Selecting a tab applies its domain/case once per activation. The new-investigation `+` button creates a fresh tab; a run starting binds its `session_id` to the active tab rather than spawning a duplicate. **Close is a tombstone** — a closed tab is kept with `deleted:true` and a bumped `rev` (pruned after 24 h) so the union merge propagates the removal instead of resurrecting it; `loadTabs()` returns live tabs only.
  - **Live `session` events must use `bindSession`, never `ensureTab`.** `ensureTab` creates + activates a tab when the active tab has no session or holds a *stale* one; on the `session` SSE event that re-keys the investigation store (`activeId` changes) mid-run, so the streaming reply writes into the now-hidden slice and the UI shows nothing (the "send does nothing / reply invisible" P0). `bindSession` binds the session id to the active investigation *in place* and never switches the active tab. `ensureTab` is retained only for the notification path (`handleOpenNotification`), where opening a tab is the intended operator action.
- **Notifications** (`src/core/notifications.ts`): `pushNotification(list, n)` with a bounded cap; `notificationFromEvent(ev)` maps bus events (hitl/scope_checked/run_completed/run_failed/evidence) to notifications. The bell surfaces them and a click selects the matching tab by `sessionId`.
- **ARK dock header layout**: `.ark-dock-header` is a single non-wrapping flex row — `.ark-dock-identity` (wordmark + Advisory/Autonomous mode with a live dot) truncates with ellipsis, and `.ark-dock-actions` (the Chat/Review/Console `nav` + expand toggle) is `flex-shrink:0` and pinned right so it never wraps or orphans at narrow dock widths. Below ~1180px the view-button text labels drop to icons only to keep the row orderly.
- **Provider/model settings** (`src/components/settings/SettingsWorkspace.tsx` + `ProvidersPanel.tsx`): the **full-page Settings workspace** — a dedicated application tab (not a modal). Left rail nav (API Keys / Providers & Connections / System Health / Model & Privacy / Saved Case Vault / Notifications / Support) + right content column. Provider & connection status, ExifTool pathing and model/privacy panels live here. Opened from the sidebar **Settings** item or the CommandPalette; repeated opens reuse the one Settings tab. Styled OLED-black via `components/settings/settings-workspace.css`, which re-declares the `--cs-*` tokens so the reused panels need no markup change. Layout-only refactor — settings behaviour is unchanged. The old `ClientSettingsModal.tsx` (floating overlay), `SettingsModal.tsx` and `InvestigatorProfileModal.tsx` were removed.
- **ARK Expandable Workspace** (`Workbench.tsx` + `ArkControl.tsx` + `ark-control.css`): the dock has two display modes toggled by the `Maximize2`/`Minimize2` control in the `.ark-dock-header` (right of the Chat/Review/Console nav, `aria-label` "Expand ARK to workspace" / "Restore ARK to docked panel"). **Docked (default)** preserves the right-side panel and the operator's saved width. **Expanded** hides `.workbench-main` and grows the dock to fill the workbench body, stopping at the navigation sidebar's real boundary (layout-driven — works whether the sidebar is collapsed or not; no hardcoded offsets). `caiExpanded` state lives in `WorkbenchInner`; `dockWidthBeforeExpand` restores the exact prior width on Restore; focus returns to the toggle. Escape restores only when no overlay/menu is open (`.cmd-palette-overlay`, `.profile-modal-overlay`, `.save-prompt-overlay`, `.ark-model-popover`, `.ark-menu`); switching main workspace (domain) re-docks. It is purely a layout change — the active run/task is never cancelled or remounted.
- **Managed Browser central workspace** (`operationalTools.ts` + `BrowserWorkspace.tsx` + `browser-workspace.css`): the managed browser is a **central-workspace tool**, not a dock inspector. `operationalTools.ts` carries a `surface` field (`workspace` | `inspector`) on each `OperationalToolId` plus `isWorkspaceTool(id)`; only `browser` is a workspace tool today. `ArkControl.openInspector` dispatches workspace tools up through the `onOpenWorkspaceTool` prop, and `Workbench.tsx` holds the `workspaceTool` state that swaps the main viewport (ternary in the render: `workspaceTool === 'browser'` → `<BrowserWorkspace>`, else the normal investigation surface). The dock inspector keeps rendering the non-workspace tools (problems/log/plan/agent/evidence/audit) unchanged. A CAI `browser.*` tool event auto-opens the workspace and follows the session it drives. Leaving the workspace is implicit: `openTool`, `handleNavigateDomain`, tab activation and tab-close all clear `workspaceTool`. `BrowserWorkspace` is screenshot-first (a captured frame is the stage; `Globe` placeholder when there is no session), with a nav strip (back/forward/reload), omnibox, Capture, New session, session picker, and an evidence-artifact strip. The omnibox **starts a session when none exists** (operator-initiated flow via `POST /api/v1/browser/sessions`). The old `BrowserView.tsx` dock component was deleted.
- **Model picker effective-selection rule** (`ArkControl.tsx`): the trigger label, row highlight and `Selected` badge all use `effectiveModelId = selectedModel || adminDefaultModel`, never the server's `is_active` flag. `is_active` is computed from the load-time saved preference, so it goes stale after a switch within the session; the picker must always reflect what will actually run (explicit selection → saved preference → administrator default).
- `InvestigatorProfileModal.tsx`: removed — identity/clearance/API-key status now lives in the ARK dock / Settings; admin remains "a protected control plane — not accessible from here".
- `CaseExplorer.tsx`: CASES domain — cross-domain saved investigations + audit vault
- Sidebar is the PRIMARY navigator (no TabBar in core flow). IMAGE sidebar shows: upload (no case) OR case header + vertical sub-view nav (Investigation, Spatial/Map, File Forensics, OCR & Vision, Source Discovery, Provenance/C2PA, Case/Report) + collapsible Evidence Explorer + New Investigation.
- Sidebar collapse toggle is ON the sidebar itself (ChevronLeft = expanded→collapse, ChevronRight = collapsed→expand), not in Settings. The collapse bar sits in a dedicated header ABOVE the primary tool icons so it never displaces them by a row.
- `DashboardView.tsx`: System Overview & Analytics default view — rendered when no target loaded (IMAGE domain, no case). **No upload button in its header** (the single upload entry point is the sidebar dropzone). Recent Sessions are interactive: rows are selectable (call `onSelectSession` to reload), per-row delete (Trash2), and "Clear History" with inline confirm. Exports `loadSessions`, `recordSession`, `classifyRisk`, `deleteSession`, `clearSessions`, and the `SessionRecord` type.
- `NetworkPlaceholder.tsx`: NETWORK domain placeholder (planned capabilities, not implemented)
- `SystemOverviewWorkspace.tsx`: the standalone System Overview — a SYSTEM-level destination (domain `system`), NOT an investigation. **It is the default landing destination:** `Workbench` opens it as the active tab on first mount when no investigation is active (a `useLayoutEffect` that seeds the workspace selection to `domain: 'system'` before paint, so the first frame is already the overview and there is no Image Intelligence flash). A restored/active investigation is left untouched; the overview tab is **non-closable** per the System Overview directive §5 (it sits beside investigation tabs): `InvestigationTabs` omits the close affordance when `tab.domain === 'system'`. Rendered in the main viewport when `inv.domain === 'system'`; also opened via the sidebar **Operations** group (`InvestigationNavigation` `onSystem` → `Workbench.openSystemOverview`) as a single reuse-once tab mirroring Settings. Consumes `GET /api/v1/overview` (`api.systemOverview(period, traces)`). Sections: header + 24h/7d/30d period selector, 4 KPI cards, Operational Activity chart + Agent Activity, Inference Engine + Compute & Usage, Security & Custody + Evidence & Audit, expandable Recent Execution Traces. **Honesty contract: a measured 0 renders as `0`; an unmeasured value renders as `—` (never a fabricated 0).** Styles: `.so-*` / `.sys-overview` in `workbench.css`.
- Sidebar groups (`InvestigationNavigation.tsx`): **Operations** (top, holds *System Overview*), **Workspaces** (Image/Network/SecOps), **Investigations** (Case Explorer, Use Cases), **Automation**, and **System** (footer, pinned: Admin + Settings). The top group is labelled *Operations* deliberately — it must NOT be labelled "System", which is the reserved footer group for account/system controls.
- `SecOpsPlaceholder.tsx`: SECOPS (Threat & Security Operations) domain placeholder. Surfaces the 6 planned sub-modules: SIEM, IDS/IPS, Threat Hunting, Detection & Correlation, Incident Management, Security Operations. `SECOPS_ICONS` registry in `icons.ts` (Gauge/Siren/Crosshair/Radar/FolderSearch/Activity).
- `investigation/InvestigationOverview.tsx`: MAP-FIRST command center — map always visible at top (never disappears), Location Not Established overlay when no coords, ARK assessment tiles + WHAT WE KNOW/DON'T KNOW/SUSPICIOUS/INVESTIGATE NEXT below
- `tools/SpatialTool.tsx`: map NEVER disappears — Location Not Established overlay when no coords; fusion/spatial summary side panel
- `tools/`: SpatialTool, FileForensicsTool, DiscoveryTool, ProvenanceTool, VisionTool, CaseReportView (all operate on the same case/evidence context). CaseReportView replaces the old ReportTool as the court-ready forensic report sub-view.
- `SettingsModal.tsx`: removed — its System & API Provider Configuration now lives in the full-page `SettingsWorkspace` → Providers & Connections section. Admin remains "a protected control plane — not accessible from here."
- `CommandPalette.tsx`: Cmd/Ctrl+Shift+P and Cmd/Ctrl+K hotkeys (openTool switches to IMAGE domain + subview); also owns Save/Export now that the TopBar is tab-only.
- `BottomPanel.tsx`: domain-aware contextual console — tabs: PROBLEMS, ANALYSIS LOG, PLAN, AGENT, EVIDENCE, AUDIT (the dock is a 3×2 grid; the shared streaming feed from `inv.terminal` renders live in ANALYSIS LOG). The interactive TERMINAL tab was removed; `pushTerminal` no longer switches tabs, it just feeds ANALYSIS LOG.
- `StatusBar.tsx`: accepts `activeCaseId` prop — shows backend status, SHA-256 hash, active case, GPS
- `icons.ts`: central Lucide icon registry — DOMAIN_ICONS (image/network/cases/secops/usecases/system), SIDEBAR_ICONS, UI_ICONS (no emoji in UI)
- `DomainId` (`entities.ts`): `'system' | 'image' | 'network' | 'cases' | 'secops' | 'usecases' | 'settings'`. The tab domain union in `core/tabs/tabRegistry.ts` includes `'system'` too.
- `App.tsx`: admin reachable ONLY via stealth hotkey Cmd/Ctrl+Shift+P (fires on ALL routes) → obfuscated `/console-auth` login; admin routes never appear in workbench UI
- Session history persisted to localStorage for dashboard analytics
- VS Code Dark Slate palette (#181818 / #1E1E1E / #252526 / #007ACC)
- Existing admin routing at `/console-auth` preserved unchanged

### Frontend dev server notes
- Vite dev server runs on port 12001 (custom); `npm run dev` (HMR active)
- Backend on port 12000; vite proxy `/api` → `process.env.ARKGEO_BACKEND_URL` or :12000
- HMR pitfall: if `DashboardView.tsx` (or any file mixing component + non-component exports like `classifyRisk`) fails Fast Refresh, restart the dev server cleanly to avoid a frozen half-state where clicks stop re-rendering. `kill` the vite node PID then `npm run dev`.
- Backend tests: 879 passing (pytest), 13 pre-existing env failures
  (`test_workbench_forensics` ×4, `test_ark_cai_engine` ×5, `test_run_control`
  ×4 — exiftool/browser binaries absent in this container, not regressions).
- Frontend tests: `npm test` → `node --test "src/**/*.test.ts"` (Node 24 runs TS
  natively, zero deps). Test files are excluded from app `tsc`
  (`tsconfig.json` excludes `**/*.test.ts(x)`); import with explicit `.ts`.
- **Evidence-honesty layer (C.3/C.4/D)**: `MapWorkspace/geoEvidence.ts`
  (verified vs inferred pins), `tools/metadataAbsence.ts` (metadata state),
  `tools/reportEngine.ts` (findings composed across epistemic tiers, contested/
  unsupported never shown as conclusions).
- **Untrusted-content fence (C.5/C.6)**: `app/engine/untrusted_content.py`
  (fence + injection scan; embedded markers are defanged so the fence cannot be
  escaped) + `app/engine/injection_fixtures.py` (adversarial corpus) +
  `tests/test_prompt_injection_suite.py`.
- Env note: `Pillow==10.3.0`/`pydantic==2.7.1` pins do NOT build on Python 3.13 —
  the working venv uses upgraded Pillow+pydantic+fastapi; requirements.txt needs
  re-pinning. `exiftool` binary required (brew install exiftool).
- Backend venv in this container is `.venv-new` (`.venv/bin/*` shebangs point at
  a macOS path); run tests with `.venv-new/bin/python -m pytest tests/ -q`.
- `npx tsc --noEmit` clean; `npx vite build` clean (~2013 modules)
- Backend has no `--reload`: after adding/changing routes you MUST restart uvicorn or the running process keeps serving stale code (a route can 404 while `main.py` already defines it).
- `GET /cai/registry` returns 500 when the optional CAI runtime is absent (`arkgeo-backend/cai/src` is empty) — a dormant, optional-feature endpoint, not a Milestone B regression. `/cai/models` and `/cai/sessions` work without it.

## Model Selection Authority, Provider Access & Picker UX (Milestone B)
The model that runs is decided by one authority, not by scattered defaults.
Precedence: **explicit selection → saved user preference → administrator default**,
then availability + entitlement checks. `ARKGEO_CAI_MODEL` is folded into the
admin layer (top of admin default) so an explicit user choice still wins.

Backend modules (all new):
- `app/services/principal.py`: `principal_from_request(request)` resolves a
  sanitized `X-ARK-Principal` / `X-ARK-Organization` into a `Principal`. A
  **development stand-in for a real session** — never an auth boundary; the
  client can only address its own namespace.
- `app/services/entitlements.py`: `Principal`, `ANONYMOUS`, `evaluate(...)`,
  `resolve_entitlement(...)`, `SUBSCRIPTION_PROVIDER`. The entitlement boundary —
  decides allow_platform / allow_byok / allow_local / allowed_providers /
  subscription_models. ARK-managed (subscription) models are **declared but
  denied until granted**.
- `app/services/user_preferences.py`: per-principal saved model selection.
- `app/services/user_credentials.py`: **BYOK** store, AES-256-GCM encrypted via
  `app.core.security`, keyed by the principal namespace (cross-tenant isolation
  is the primary key). Reads expose only a masked preview + `configured`.
- `app/models/model_registry.py`: normalized `PROVIDER_MODELS`, `PROVIDER_IDENTITY`,
  `lookup`, `known_model`, `parse_model_id`, `subscription_records`. Unverified
  capabilities are reported as `"unknown"` — never invented.
- `app/services/model_router.py`: the authority. `resolve(principal, requested,
  *, has_image) -> Resolution` (ok / requested vs resolved / credential_source /
  routing_reason / error_code). `_admin_default()` (honours `ARKGEO_CAI_MODEL`
  at the top of the admin layer), `_availability(principal, provider, model)
  -> (available, reason, credential_source)`. No silent substitution unless the
  admin-configured fallback chain is explicitly enabled — and then the actual
  model is disclosed.
- `app/api/v1/endpoints/user_models.py` (`/api/v1/user/model/...`): preference
  GET/PUT/DELETE, BYOK credentials GET/POST/DELETE (SSRF guard:
  https-only, rejects loopback/private/link-local/reserved/`.internal`), and a
  read-only entitlements view. Registered in `router.py`.

Wiring: `orchestrator.py` `_resolve_model(session)` delegates to the router;
`SessionState` carries `principal` + `resolved_model`; `run()` resolves *before*
any work and fails loudly (`model_denied` event) on a denied/unavailable model.
`cai.py` passes `principal_from_request` into every stream/run endpoint and
`/cai/models` returns normalized records; `/cai/model` is principal-aware
(requested vs resolved + routing reason); `/model/switch` validates and persists
the preference.

- **Provider error classification** (`app/engine/provider_errors.py`
  `public_error`): maps a provider exception to a public `{code, message}`. A
  credit/limit body (`insufficient`, `credit`, `billing`, `limit exceeded`, …)
  on 401/402/403 is classified `insufficient_credits` **before** the credential
  branches — OpenRouter signals an exhausted key with 403 "Key limit exceeded",
  which must not surface as `authentication_failed`. 429 stays `rate_limited`
  (an exhausted quota there is transient). Raw provider detail is never echoed.
- **Key probe** (`app/services/key_probe.py` `live_probe`): the OpenRouter probe
  also reads `/auth/key`'s `limit`/`usage` — that endpoint returns 200 even for a
  spent key, so `usage >= limit` reports the key unusable rather than healthy.

Frontend picker (`ArkControl.tsx` + `ark-control.css`): `api.ts` sends a stable
per-browser `X-ARK-Principal` and the picker is authoritative — the user's saved
preference wins over the admin default, selection persists server-side, search
filters by name/id, unavailable models are disabled with a reason, capability
badges (tool/vision/free/local) are shown, and a "Use administrator default"
footer clears the preference. The image-review advisory path no longer hardcodes The advisory failure text also trusts the backend's classified error: `useImageReview` prefers the streamed `error.message` (keyed off the `code` the backend sent) and only falls back to its own status-code heuristic for HTTP-level failures — so an out-of-credit provider reads as *insufficient credits*, not a rejected credential.
a model (`ARK_CAI_MODEL = null`) so Chat and Console cannot diverge.

**Principal must ride the SSE streams too.** The three raw `fetch()` calls
(`caiStream`, `caiTerminalStream`, workspace run) bypass the axios client and
therefore its default headers; they use `principalHeaders()` (api.ts) to send
`X-ARK-Principal`. Without it the run's principal is `ANONYMOUS`, the caller's
saved model preference does not match, and the run silently falls back to the
administrator default — the defect where the composer model appeared to be
overridden by the admin dashboard. (The explicit `model` body field still wins
when present; the header matters when the selection is the saved preference.)

Tests: `tests/test_model_authority.py` (23 passing — precedence, entitlement
denial, subscription denial, credential isolation, HTTP surface, SSRF guard).
Backend suite: same 20 pre-existing/environmental failures, no new regressions.

## Operator control plane — Stop / Steer / Mode (2026-11-05)

The Stop / Steer / execution-mode controls are now **backend-owned and real**,
not frontend simulation. Design + verification: `docs/ARK_RUN_CONTROL_PLANE.md`.

- `app/engine/run_control.py` (NEW): process-local `RunControl` registry shared
  by the HTTP layer and the orchestrator. `register/unregister/get/get_for_session/
  resolve`; `request_stop()` (status becomes `stopping`, never `cancelled`);
  `submit_steer()/drain_steering()`; `MODES = {"auto","manual"}`.
- `orchestrator.py`: `SessionState.execution_mode`; `run()` creates/tears down
  the control; `_run()` checks stop at the loop top and after each tool return
  (a running tool is never interrupted mid-syscall — the stop lands when it
  returns); `_drain_steering()` injects accepted guidance and defers anything
  that would widen authority; the approval gate requires confirmation in
  `manual` mode. Neither mode bypasses engagement scope or the policy guard.
- `cai.py`: `POST /cai/stop` / `/cai/steer` / `/cai/mode`, `GET /cai/run`,
  `POST /cai/queue` + `GET /cai/queue/{sid}` are wired to the registry.
  `stop` returns `stop_requested` (never a fabricated `stopped`). `execution_mode`
  is accepted on `/stream`, `/terminal/stream`, `/workspace/{ws}/run`.
- `session_store.py`: `RUN_CANCELLED = "cancelled"`.
- Frontend (`ArkControl.tsx` + `ExecutionPanels.tsx` + `executionPresentation.ts`
  + `ark-control.css`): the permanent upper execution region is gone. The
  conversation is the primary surface; execution detail lives in one compact
  collapsible inline `ExecutionActivity` card, and a structured
  `InvestigationReport` is appended on terminal runs (both built from the run's
  own events). The header carries **no** Chat/Console switch — it is ARK
  wordmark + live status + operational tools + expand only; the conversation is
  the single surface and execution detail expands inline. While a run is active,
  Send queues (runs after the current objective) and the Send button becomes the
  single Stop control; the mode toggle persists to the backend and rolls back on
  failure. `api.ts`: `caiMode`, `caiRun`, `caiEnqueue`, `executionMode` on
  `caiTerminalStream`.
- Tests: `tests/test_run_control.py` (16 passing). Backend suite 754 passing;
  `tsc --noEmit` and `vite build` clean.
- Known limit: `RunControl` and the queue are process-local; a restart drops
  in-flight control state.

## Operator-declared engagement — execution scope (2026-11-07)

The operator defines the engagement; that declaration is the **sole source of
truth** for what ARK executes against. This replaces the old env-fixture
("fail-closed unless `ARKGEO_ENGAGEMENT_SCOPE` is set") model.

- `app/agent/engagement_store.py` (NEW): owner-isolated SQLite registry
  (`arkgeo_data/engagements.sqlite`). `create(owner_id, addresses, ports=,
  all_ports=, start=, expiry=, label=, notes=)`, `get`, `get_active`,
  `revoke`, `list_owners`, `list_active`. Targets are validated as address
  grants only (IP/IPv6/CIDR/hostname; no scheme/port/credentials/path); ports
  are 1..65535 or `all_ports`. Default window 24h. Records resolve only for the
  principal that declared them.
- `app/agent/engagement_scope.py`: `set_operator_engagement(scope)` /
  `get_operator_engagement()`. `_load()` now resolves **operator engagement
  first**, then a legacy `ARKGEO_ENGAGEMENT_SCOPE` fixture, else fail-closed
  (target-bearing calls denied; non-target calls always run). The operator
  declaration is authoritative — a fixture never overrides it. `clear_active()`
  drops the operator declaration *and* suppresses an env fixture for the life of
  the process (so a lab/CI fixture cannot silently keep governing after the
  operator stands the scope down); `effective_source()` reports `operator` /
  `fixture` / `none` and `effective_scope()` returns the scope actually enforced.
- `app/api/v1/endpoints/engagement.py` (NEW) + `router.py`: admin-JWT surface.
  `POST /api/v1/engagement` declares and **installs the active scope**;
  `GET /api/v1/engagement` returns active + history **plus `effective` /
  `effective_source`** (a fixture governing execution is disclosed, not hidden
  behind "no engagement active"); `DELETE /api/v1/engagement` stands the scope
  down (revokes the declaration and suppresses a fixture); `POST
  /api/v1/engagement/{id}/revoke` clears one declaration immediately. Every
  mutation is audited via `admin_store.append_audit`.
- `main.py`: on startup the active engagement is restored from the store, so an
  authorized scope survives a backend restart (logged `Engagement restored:`).
- `orchestrator.py`: an in-scope target-bearing call under an operator-declared
  engagement is a **standing authorization** — it runs without a further HITL
  prompt (this is the operator's directive acting as source of truth). It
  applies only to the operator-declared engagement (an env fixture does not
  grant it); manual mode and policy-mandated approvals still prompt; scope is
  still checked before dispatch, so a denial cannot be auto-approved.
- `app/engine/prompts.py`: persona realigned — concise, non-preachy, no
  fabrication; "the Operator declares an engagement … inside it ARK acts;
  outside it ARK refuses before dispatch and says so once, briefly."
- Frontend: `components/admin/EngagementPanel.tsx` (admin → **Engagement &
  Scope** nav) declares/revokes scope and shows the **effective** scope with its
  source, plus a **Stand down** button; `api.ts` `getEngagement` /
  `declareEngagement` / `revokeEngagement` / `clearEngagement`; types in
  `types.ts` (`EngagementState.effective` / `effective_source`).
- Tests: `tests/test_operator_engagement.py` (store, scope resolution, API,
  effective-source reporting, stand-down) + two orchestrator tests (operator
  engagement authorizes execution; out-of-scope target refused before dispatch).
  `tests/test_engagement_scope.py` message assertions updated to the
  operator-facing wording.
- Verified live: declare → `overview.security.scope_active: True`; restart
  restores the scope; revoke clears it; unauthenticated declare → 401; a
  `ARKGEO_ENGAGEMENT_SCOPE` fixture is reported as `effective_source: fixture`
  and `DELETE /engagement` stands it down (`effective_source: none`).

## Advisor P0 pass (2026-11-06)

- **Git credential**: `origin` had an embedded `ghu_` GitHub App user-to-server
  token. **Locally remediated** (remote rewritten to a credential-free URL; no
  token in config/history/reflog/objects/logs/reports). **Provider-side
  revocation still OUTSTANDING** (human action). No commit/push until done.
  Record: `docs/audits/ARK_P0_CREDENTIAL_REMEDIATION.md`.
- **Electron sandbox**: `sandbox:false` kept deliberately (preload uses
  synchronous IPC for the port handshake). Renderer loads **no** untrusted
  content (no iframe/webview/dangerouslySetInnerHTML); untrusted browsing is
  backend-side. Decision record: `docs/audits/ARK_ELECTRON_SANDBOX_DECISION.md`.
- **End-to-end scenarios**: live-executed ledger in
  `docs/audits/ARK_E2E_SCENARIO_LEDGER.md`. Real image investigation works
  (`/api/v1/analyze`, coords exact, custody cert); model routing proven correct;
  cloud *inference* is **BLOCKED** by provider 429/no creds (reported honestly,
  never fabricated). Open items: HTTP-plane control of a live agent session,
  `steer` on a sustained run. Renderer click-through **closed** for the
  investigation-isolation defect (section G).
- **Investigation isolation (P0, fixed)**: a tab now points to its own
  investigation; switching tabs swaps that investigation's conversation,
  execution, case context and workspace selection — no shared global state.
  Frontend store `src/core/investigation/investigationStore.ts` +
  `InvestigationStoreContext.tsx` (`activeId`, `metaFor`, `ensure`, `patchMeta`,
  `patchWorkspace`, `setRunStatus`, `drop`, `getSlice`, `setSlice`, and the
  `useInvestigationSlice` keyed-state primitive used by the workbench for
  per-investigation `thumbnailUrl`/`analyzing`/`zeroRetention`). `useInvestigation`
  multiplexes `Record<investigationId, InvestigationContext>`; `ArkControl` keys
  conversation + execution per investigation. Durable metadata
  (`ark.investigations`, localStorage) holds **no** content — transcript and
  evidence stay in the backend encrypted session store. Backend authorization
  boundary: `cai.py` `_session_visible_to(meta, principal)` scopes
  `GET/DELETE /cai/sessions/{id}` to the owning principal (cross-principal →
  `unknown session`, not an existence oracle); `list_sessions` filters by
  `principal_subject`. Tests: `tests/test_cai_session_authz.py` (13). Full suite
  **738 passed**. Design/root-cause: `docs/audits/ARK_P0_INVESTIGATION_ISOLATION.md`.
- **Servers**: backend `uvicorn --host 0.0.0.0 --port 12000`, web `vite --host
  0.0.0.0 --port 12001` (must bind 0.0.0.0 or the work-host proxy 502s).
