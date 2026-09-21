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

### Backend
```bash
cd arkgeo-backend
python -m pytest tests/ -q              # run tests (196 passing)
python -m uvicorn main:app --reload     # start dev server (port 8000)
```

### Web Portal
```bash
cd arkgeo-investigator-web
npm install
npx tsc --noEmit                        # type-check (clean)
npx vite build                          # production build
npm run dev                             # dev server (port 5173, proxies /api → :8000)
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
- 19 tests across metadata extraction, consensus engine, and pipeline integration
- Known non-blocking warning: httpx/TestClient deprecation in Starlette

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
- `ActivityBar.tsx`: far-left DOMAIN nav — IMAGE (primary), NETWORK (placeholder), **SECOPS** (Threat & Security Operations placeholder), CASES (cross-domain case layer) + **settings gear** (footer, opens SettingsModal) + ARK wordmark. Profile is opened from TopBar avatar, NOT the ActivityBar footer.
- `TopBar.tsx`: single ARK identity (one wordmark/logo), command palette trigger, connection/API status — NO duplicate logos, NO admin link. Has a **macOS safe-zone** `padding-left: 68px` so content clears native traffic-light window controls in desktop/Electron mode.
- `Workbench.tsx`: wraps everything in `<InvestigationProvider>` → TopBar + ActivityBar + Sidebar + MainViewport + BottomPanel + StatusBar. Owns `showSettings` state; renders `<SettingsModal>` and handles `handleSelectSession` (reloads a dashboard session into the image workspace).
- `InvestigatorProfileModal.tsx`: identity/clearance/API-key status; states "Admin is a protected control plane — not accessible from here"
- `CaseExplorer.tsx`: CASES domain — cross-domain saved investigations + audit vault
- Sidebar is the PRIMARY navigator (no TabBar in core flow). IMAGE sidebar shows: upload (no case) OR case header + vertical sub-view nav (Investigation, Spatial/Map, File Forensics, OCR & Vision, Source Discovery, Provenance/C2PA, Case/Report) + collapsible Evidence Explorer + New Investigation.
- Sidebar collapse toggle is ON the sidebar itself (ChevronLeft = expanded→collapse, ChevronRight = collapsed→expand), not in Settings. The collapse bar sits in a dedicated header ABOVE the primary tool icons so it never displaces them by a row.
- `DashboardView.tsx`: System Overview & Analytics default view — rendered when no target loaded (IMAGE domain, no case). **No upload button in its header** (the single upload entry point is the sidebar dropzone). Recent Sessions are interactive: rows are selectable (call `onSelectSession` to reload), per-row delete (Trash2), and "Clear History" with inline confirm. Exports `loadSessions`, `recordSession`, `classifyRisk`, `deleteSession`, `clearSessions`, and the `SessionRecord` type.
- `NetworkPlaceholder.tsx`: NETWORK domain placeholder (planned capabilities, not implemented)
- `SecOpsPlaceholder.tsx`: SECOPS (Threat & Security Operations) domain placeholder. Surfaces the 6 planned sub-modules: SIEM, IDS/IPS, Threat Hunting, Detection & Correlation, Incident Management, Security Operations. `SECOPS_ICONS` registry in `icons.ts` (Gauge/Siren/Crosshair/Radar/FolderSearch/Activity).
- `investigation/InvestigationOverview.tsx`: MAP-FIRST command center — map always visible at top (never disappears), Location Not Established overlay when no coords, ARK assessment tiles + WHAT WE KNOW/DON'T KNOW/SUSPICIOUS/INVESTIGATE NEXT below
- `tools/SpatialTool.tsx`: map NEVER disappears — Location Not Established overlay when no coords; fusion/spatial summary side panel
- `tools/`: SpatialTool, FileForensicsTool, DiscoveryTool, ProvenanceTool, VisionTool, CaseReportView (all operate on the same case/evidence context). CaseReportView replaces the old ReportTool as the court-ready forensic report sub-view.
- `SettingsModal.tsx`: System & API Provider Configuration — surfaces GeoSpy/OpenAI Vision/LLLM keys (status only, keys are server-side), Mapbox token (client env), ExifTool binary pathing, and backend connection state. Reached ONLY via the ActivityBar footer gear icon — NEVER from admin. Footer note: "Admin is a protected control plane — not accessible from here."
- `CommandPalette.tsx`: Cmd/Ctrl+Shift+P and Cmd/Ctrl+K hotkeys (openTool switches to IMAGE domain + subview)
- `BottomPanel.tsx`: domain-aware contextual console — tabs: PROBLEMS, ANALYSIS LOG, EVIDENCE, AUDIT, TERMINAL (terminal has command parser: help/status/clear/scan/connect)
- `StatusBar.tsx`: accepts `activeCaseId` prop — shows backend status, SHA-256 hash, active case, GPS
- `icons.ts`: central Lucide icon registry — DOMAIN_ICONS (image/network/cases), SIDEBAR_ICONS, UI_ICONS (no emoji in UI)
- `App.tsx`: admin reachable ONLY via stealth hotkey Cmd/Ctrl+Shift+P (fires on ALL routes) → obfuscated `/console-auth` login; admin routes never appear in workbench UI
- Session history persisted to localStorage for dashboard analytics
- VS Code Dark Slate palette (#181818 / #1E1E1E / #252526 / #007ACC)
- Existing admin routing at `/console-auth` preserved unchanged

### Frontend dev server notes
- Vite dev server runs on port 12001 (custom); `npm run dev` (HMR active)
- Backend on port 8000; vite proxy `/api` → :8000
- HMR pitfall: if `DashboardView.tsx` (or any file mixing component + non-component exports like `classifyRisk`) fails Fast Refresh, restart the dev server cleanly to avoid a frozen half-state where clicks stop re-rendering. `kill` the vite node PID then `npm run dev`.
- Backend tests: 226 passing (pytest), 11 warnings (HMAC key length non-blocking)
- Env note: `Pillow==10.3.0`/`pydantic==2.7.1` pins do NOT build on Python 3.13 —
  the working venv uses upgraded Pillow+pydantic+fastapi; requirements.txt needs
  re-pinning. `exiftool` binary required (brew install exiftool).
- `npx tsc --noEmit` clean; `npx vite build` clean (~1902 modules)
