# ArkGeo — Repository Knowledge Base

## Project Overview
ArkGeo is a modular AI geolocation and personal safety ecosystem with three applications:
- **arkgeo-backend** — FastAPI modular "Brain" AI engine (4-tier pipeline)
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
python -m pytest tests/ -q              # run tests (19 passing)
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
- Git: user.name=openhands, user.email=openhands@all-hands.dev
- Commits include `Co-authored-by: openhands <openhands@all-hands.dev>`
- No node_modules, .env, __pycache__, dist/ in version control

## Workbench Architecture (Forensic IDE Refactor)
The investigator UI is being transformed into a VS Code-style workbench.
Backend remains the source of truth for all forensic objects.

### Backend evidence model extensions (new)
- `exiftool_service.py`: deep metadata via ExifTool (`exiftool -j -G0:1 -struct`), grouped tree (EXIF/XMP/IPTC/ICC/MakerNotes)
- `consistency_engine.py`: structured metadata consistency findings (TIMELINE_ANOMALY, etc.) with status/type/severity
- `contradiction_engine.py`: cross-reference evidence layers for structured contradictions
- `c2pa_service.py`: provenance analysis (verified/unavailable/invalid/incomplete states)
- `geolocation_fusion.py`: multi-layer evidence model with explainability
- `source_discovery.py`: provider-agnostic reverse image search (pHash + extensible provider registry)
- `analyst_overrides.py`: confirm/reject/needs-review with audit logging

### Frontend workbench shell (domain-based investigation architecture)
THE ARK is organized by INVESTIGATION DOMAINS, not individual tools. Each domain
contains every tool required to complete that investigation.
- `entities.ts`: shared entity model (DomainId, InvestigationCase, EvidenceItem, etc.)
- `useInvestigation.tsx`: InvestigationProvider context + `useInvestigation()` hook — holds domain, active case, result, history; drives domain switching across all components
- `ActivityBar.tsx`: far-left DOMAIN nav — IMAGE (primary), NETWORK (placeholder), CASES (cross-domain case layer) + profile button (footer) + ARK wordmark
- `TopBar.tsx`: single ARK identity (one wordmark/logo), command palette trigger, connection/API status — NO duplicate logos, NO admin link
- `Workbench.tsx`: wraps everything in `<InvestigationProvider>` → TopBar + ActivityBar + Sidebar + MainViewport + BottomPanel + StatusBar
- `InvestigatorProfileModal.tsx`: identity/clearance/API-key status; states "Admin is a protected control plane — not accessible from here"
- `CaseExplorer.tsx`: CASES domain — cross-domain saved investigations + audit vault
- Sidebar is the PRIMARY navigator (no TabBar in core flow). IMAGE sidebar shows: upload (no case) OR case header + vertical sub-view nav (Investigation, Spatial/Map, File Forensics, OCR & Vision, Source Discovery, Provenance/C2PA, Case/Report) + collapsible Evidence Explorer + New Investigation.
- Sidebar collapse toggle is ON the sidebar itself (PanelLeftClose/Open), not in Settings.
- `DashboardView.tsx`: System Overview & Analytics default view — rendered when no target loaded (IMAGE domain, no case)
- `NetworkPlaceholder.tsx`: NETWORK domain placeholder (planned capabilities, not implemented)
- `investigation/InvestigationOverview.tsx`: MAP-FIRST command center — map always visible at top (never disappears), Location Not Established overlay when no coords, ARK assessment tiles + WHAT WE KNOW/DON'T KNOW/SUSPICIOUS/INVESTIGATE NEXT below
- `tools/SpatialTool.tsx`: map NEVER disappears — Location Not Established overlay when no coords; fusion/spatial summary side panel
- `tools/`: SpatialTool, FileForensicsTool, DiscoveryTool, ProvenanceTool, VisionTool, ReportTool (all operate on the same case/evidence context)
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
- Backend tests: 154 passing (pytest), 11 warnings (HMAC key length non-blocking)
- `npx tsc --noEmit` clean; `npx vite build` clean (~1901 modules)
