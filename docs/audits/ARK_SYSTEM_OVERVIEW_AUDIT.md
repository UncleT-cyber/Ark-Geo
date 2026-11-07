# THE ARK — System Overview: Phase 0 Audit & Data-Source Mapping

Scope: build a standalone, production-quality System Overview dashboard for THE
ARK, separated from Image Intelligence, backed only by real runtime data.

This document is the Phase 0 deliverable required by the directive (§6, §11).
It records the actual files/architecture found and classifies every proposed
metric as **AVAILABLE / DERIVABLE / MISSING / UNSUPPORTED** *before* any UI was
written.

---

## 1. Frontend architecture (arkgeo-investigator-web)

| Concern | File | Notes |
|---|---|---|
| App routing | `src/App.tsx` | `HashRouter`; only `/` (Workbench), admin login, admin console, 404. No per-workspace routes — workspaces are internal state, not routes. |
| Root shell | `src/components/workbench/Workbench.tsx` | Owns domain state via the investigation store, renders TopBar + sidebar + main viewport + ARK dock + StatusBar. Settings is a full-page takeover (`workbench-body-settings`). |
| Sidebar IA | `src/components/workbench/InvestigationNavigation.tsx` | Groups: WORKSPACES (image/network/secops), INVESTIGATIONS (Case Explorer, Use Cases), AUTOMATION (Agents & Workflows — planned), SYSTEM (Admin, Settings). |
| Domain model | `src/components/workbench/entities.ts` | `DomainId = 'image' \| 'network' \| 'cases' \| 'secops' \| 'usecases' \| 'settings'`. |
| Icons | `src/components/workbench/icons.ts` | Central Lucide registry. `DOMAIN_ICONS`, `SUBVIEW_ICONS`, `SECOPS_ICONS`. |
| Tab registry | `src/core/tabs/tabRegistry.ts` | ONE store for investigation tabs. `InvestigationTab` holds navigation metadata only (id, sessionId, title, domain, caseId, runStatus). No forensic content. |
| Tab hook | `src/core/tabs/useInvestigationTabs.ts` | `createTab` / `bindSession` / `ensureTab` / close. `bindSession` binds a backend session to the *active* tab (P0 fix — `ensureTab` used to spawn duplicates). |
| Investigation store | `src/core/investigation/investigationStore.ts` | Per-investigation durable metadata (`InvestigationMeta`), incl. `workspace` selection (domain, subview, networkTab, workspaceTool, neutral). |
| Per-investigation state | `src/components/workbench/useInvestigation.tsx` | One `InvestigationContext` **per investigation**, plus per-investigation result/pipeline/terminal/bottom-tab. |
| ARK dock | `src/components/workbench/ArkControl.tsx` | Conversation + composer + model selector + execution mode + inline execution card. Dock width `--ark-dock-width`, expand/restore. |
| Execution card | `src/components/workbench/ExecutionPanels.tsx` + `executionPresentation.ts` | Derives labels/summaries from backend events only. |
| Existing IMAGE overview | `src/components/workbench/DashboardView.tsx` | **This is the mispositioned "System overview"**: Image-Intelligence-scoped (investigation volume, risk & metadata, recent target sessions). Belongs to IMAGE, not system. |
| Theme tokens | `src/styles.css` (`:root`) | `--bg-darkest #0B0C10`, `--bg-dark #12141A`, `--bg-card #181B22`, `--bg-elevated #252A36`, `--cyan #007ACC`, `--cyan-bright #38BDF8`, `--success #10B981`, `--warning #F59E0B`, `--emergency #EF4444`, text/border tokens. |

**Decision:** System Overview is a new **workspace identity** inside the existing
Workbench shell (a `DomainId`, like `settings`/`usecases`), reached from the
sidebar. It is **not** a new router. Image Intelligence keeps `DashboardView`
as its own metrics canvas.

## 2. Backend architecture (arkgeo-backend)

| Concern | File | Notes |
|---|---|---|
| Router | `app/api/v1/router.py` | Aggregates endpoints under `/api/v1`. |
| Health | `app/api/v1/endpoints/health.py` | `GET /health` — status, version, per-provider `configured/not_configured`, uptime. |
| Durable sessions | `app/services/session_store.py` | SQLite (`arkgeo_sessions.db`), encrypted. Tables: `sessions`, `messages`, `runs` (status/model/started/ended/error/evidence_refs). `list_sessions` is principal-scoped. |
| Sessions API | `app/api/v1/endpoints/cai.py` | `GET /cai/sessions`, `GET /cai/sessions/{id}`, `DELETE /cai/sessions/{id}` — principal-scoped (owner check). |
| Run control | `app/engine/run_control.py` | In-process `RunControl` (running/stopping/cancelled/completed/failed) + steering. `GET /cai/run?session_id=`. |
| Orchestrator | `app/engine/orchestrator.py` | Emits typed events: `run_created`, `model_resolved`, `agent_selected`, `scope_checked`, `hitl`, `tool_call`, `tool_started`, `result_verified`, `evidence_recorded`, `tool`, `run_completed`, `run_cancelled`, `error`. Persists session/run. |
| Evidence recorder | `app/engine/evidence_recorder.py` | Per-run typed event log + `runs_index.json` under `arkgeo_data/a2_evidence/` (458 runs on disk). Redacts secrets. |
| Model authority | `app/services/model_router.py` (`resolve`), `app/api/v1/endpoints/cai.py` (`GET /cai/model`, `GET /cai/models`) | Resolves requested→resolved model per principal (user selection > admin default > entitlement). Discloses provider, credential source, routing reason. |
| AI gateway | `app/api/v1/endpoints/ai.py` (`GET /ai/status`), `app/services/ai_gateway.py` | Route status (cloud/local_ollama/unconfigured), per-provider configured/probed/latency. |
| Engagement scope | `app/agent/engagement_scope.py` | `check()`, `summary_lines()`. Fixture `arkgeo_data/engagement_scope.json`. |
| Tool catalogue | `app/api/v1/endpoints/cai.py` (`GET /cai/tools`) | 40 real tools with domain + risk. |
| Admin store | `app/services/admin_store.py` | Tool policy (enabled/risk), quotas, audit log, per-client usage counters. Admin-token gated. |
| Principal | `app/services/principal.py` | `X-ARK-Principal` header → namespaced principal (dev stand-in). |

## 3. Data-source mapping (per proposed metric)

| # | Metric | Class | Source |
|---|---|---|---|
| 1 | Total saved investigations | **AVAILABLE** | `GET /cai/sessions` (count, principal-scoped) |
| 2 | Active investigations (running runs) | **DERIVABLE** | `/cai/sessions` rows with `last_run_status == 'running'`; live runs cross-checked with `GET /cai/run` |
| 3 | Active agents | **DERIVABLE** | `run_control` live runs (status running/stopping). Names from `agent_selected` events. |
| 4 | Tool executions (total / ok / failed) | **DERIVABLE** | `runs` rows + `evidence_recorder` `runs_index.json` (per-run `event_count`, `last_event`). |
| 5 | Pending approvals | **DERIVABLE** | `hitl` events without a following `approval_*`; live via session `pending_tool` |
| 6 | Operational activity events (period) | **DERIVABLE** | Run/event timestamps from `runs_index.json` / session store; period filter 24h/7d/30d |
| 7 | Agent activity (specialist, task, state, elapsed) | **DERIVABLE** | Live `run_control` + `agent_selected` + `tool_started` timestamps |
| 8 | Model & provider health | **AVAILABLE** | `GET /cai/model`, `GET /cai/models`, `GET /ai/status`, `GET /health` |
| 9 | Provider latency / last success | **DERIVABLE** | `ai_gateway.status()` per-provider `latency_ms` + `probed` |
| 10 | Requests / tokens / cost | **MISSING** | No per-request token or cost accounting is captured in the CAI path. `admin_store` client `usage` counters exist but are admin-scoped and not per-principal-run. |
| 11 | Local vs cloud inference usage | **DERIVABLE** | Provider classification (`local` flag on model records / `ollama`) over run history |
| 12 | Security controls (scope, approvals, isolation) | **DERIVABLE** | `engagement_scope.check/summary_lines`, `hitl` events, `run_control` mode |
| 13 | Evidence & audit records | **AVAILABLE** | `evidence_recorded` events; `GET /cai/sessions/{id}` `evidence_refs` |
| 14 | Recent execution traces | **DERIVABLE** | `runs_index.json` (run_id, last_event, timestamp, event_count) + `GET /cai/sessions/{id}` runs |
| 15 | Cost savings vs competing clouds | **UNSUPPORTED** | No reliable pricing data captured; will not be invented (§4.D, §12). |

**Verdict:** the dashboard can be built almost entirely from **AVAILABLE +
DERIVABLE** data. The only genuinely **MISSING** area is token/cost accounting,
and the only **UNSUPPORTED** claim is "cost savings" — both will be surfaced
honestly as *unavailable* (`—`), never fabricated.

## 4. Smallest backend addition

One principal-scoped aggregate endpoint, `GET /api/v1/overview`, that reads the
existing session store + run-control + evidence index + model router + health
and returns the KPI/activity/trace payload the dashboard renders. It adds **no
new telemetry subsystem** — it aggregates what already exists, filtered to the
caller's principal.

## 5. Isolation contract (must not regress — §9)

* One `InvestigationContext` per investigation (already true).
* System Overview is a system-level destination: opening it must not create a
  case, must not fabricate a case id, and must not overwrite the active
  investigation. Switching back restores the investigation's own workspace and
  conversation.
* The Overview tab is non-closable and sits beside investigation tabs.
