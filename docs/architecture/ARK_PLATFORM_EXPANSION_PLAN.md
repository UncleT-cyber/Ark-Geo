# ARK Platform Expansion Plan — MCP Gateway · Notification Gateway · Mobile Companion

**Status:** Phase 0 complete — audit + architecture delivered; **awaiting Approval Gate 0**
**Governing directives:** (1) MCP Gateway, Notification Gateway & Mobile Companion;
(2) Amendment — Plugin System (MCP as mechanism, Plugins as product surface)
**Companion documents:** `ARK_MCP_GATEWAY.md`, `ARK_NOTIFICATION_GATEWAY.md`,
`ARK_MOBILE_COMPANION.md`

---

## 1. Phase 0 answers (parent §13)

### 1.1 What MCP infrastructure already exists
**None on ARK's side.** No `mcp` dependency, no client/server/adapter in `app/`.
The only MCP code is dormant upstream scaffolding inside the vendored CAI snapshot
(`app/engine/cai/cai/repl/commands/mcp.py` — a REPL `/mcp` command not wired to the
orchestrator or HTTP surface; `arkgeo-backend/cai/src` is empty so `/cai/registry`
500s). What *does* exist is a mature execution pathway MCP tools must join:
`unified_registry` (98 tools/12 domains) → `PolicyGuard` → engagement scope →
orchestrator → SSE events → evidence-graph audit nodes.

### 1.2 What notification infrastructure already exists
- In-app bell: working, **in-memory** (`src/core/notifications.ts`).
- Settings → Notifications: **client-side only** (report branding + an email-alert
  checkbox in localStorage) — no backend delivery.
- **One real channel:** Twilio SMS via SOS + Dead-Man's Switch (asyncio background
  loop from `main.py`, in-memory state).
- **Missing:** security-event contract, policy engine, dispatcher, delivery history,
  preference store, desktop OS notifications, any queue beyond the process-local
  `_QUEUE_STORE`.

### 1.3 What mobile-ready frontend infrastructure already exists
- The shared backend is fully HTTP + principal-scoped and ready to serve a client.
- The web app is **not** a PWA (no manifest/service worker/push).
- `arkgeo-mobile` exists but is the **legacy safety HUD** (separate Expo codebase) —
  not the companion, and not to be extended for it.
- Mobile-shaped frontend, end-user identity, and push are the gaps.

### 1.4 Authentication/authorization components reusable
- Admin JWT + bcrypt (`app/core/security.py`, `settings.py /login`).
- Principal model + entitlements (`principal.py`, `entitlements.py`), principal-scoped
  session visibility (`cai._session_visible_to`) and principal-keyed stores
  (`engagement_store`, `user_credentials` AES-256-GCM).
- `PolicyGuard` (capability permissions, risk→approval tiers, budgets),
  operator-declared engagement scope, audit (`admin_store.append_audit`).
- Untrusted-content fence + injection suite (`untrusted_content.py`) for all external
  payloads; spend guards (`key_probe`, entitlements, provider error taxonomy).
- **Blocking gap:** there are **no end-user accounts** — `X-ARK-Principal` is a
  declared dev stand-in, "never an auth boundary". Multi-user/multi-device (mandated
  by the parent directive) requires real identity first. Known authz debt:
  `/investigate` endpoints lack owner checks (documented in
  `CASE_GRAPH_AUTHORIZATION_BOUNDARIES.md`, **awaiting approval** — policy change).

### 1.5 How the three systems integrate with the AI orchestration engine
One engine, three attachments: **MCP Gateway** adds principal-scoped `ToolSpec`s to the
existing registry (policy-gated, audited, fenced); **Notification Gateway** subscribes
to existing findings/run events and adds an event→policy→channel pipeline beside the
orchestrator (never inside it); **Mobile Companion** is another HTTP client of the same
chat/SSE/investigation APIs with identical server-side authorization. Background
monitors (Gmail etc.) feed *events*, not model calls — deterministic filtering before
any AI escalation (parent §8).

### 1.6 Security risks & migration requirements
1. **No end-user identity** → cannot safely expose anything beyond localhost (top
   risk; prerequisite for every workstream).
2. In-memory state everywhere (deadman, queues, bell) → restart loss; new stores must
   be durable SQLite per established precedent; schema migrations need approval.
3. Case-graph authz debt (owner checks) must land before external reach.
4. Prompt-injection surface grows with MCP/email → fence is mandatory, not optional.
5. Credential handling: reuse AES-GCM principal-keyed storage; never in prompts/logs.
6. Paid API spend → per-plugin budgets + explicit enablement; no silent calls.
7. Push requires HTTPS hosting (current deployment is localhost) → deployment change
   is an approval-gated dependency of Phase 7.
8. Documented authz policy changes, DB migrations, public API exposure, continuous
   mailbox access, paid providers, production deploys — all stop for approval
   (parent §12).

### 1.7 Implementation milestones (sequence)
Parent §11 order, with the amendment folded in and one added prerequisite:

| Phase | Milestone | Notes |
|---|---|---|
| **P0** | Audit + four architecture docs | **This deliverable** |
| **P0.5** | **End-user identity foundation** (accounts, sessions, device registry) | Added prerequisite — everything multi-user depends on it |
| **P1** | Shared security event contracts | Event store + validation |
| **P2** | Notification Gateway foundation | Prefs (server-backed), Security Inbox, desktop integration |
| **P3** | Telegram integration | Linking, delivery, revocation |
| **P4** | **Plugins surface + MCP Gateway foundation** | Plugins UI in Settings rail; MCP connection manager; no separate MCP nav item |
| **P5** | Gmail security (Tier 1 read-only) | First complete demonstration |
| **P6** | Mobile Companion (PWA: chat/alerts/settings) | Consumes authorized plugin capabilities; plugin config stays Desktop |
| **P7** | Mobile push | HTTPS hosting dependency |
| **P8** | End-to-end integration & security testing | Gmail → investigation → notification → mobile |

Deviation from parent order: inserting **P0.5 identity** — justified because §C5 and
the multi-user mandate are unsatisfiable without it, and every later phase stores
principal-scoped data.

### 1.8 Estimated complexity & dependencies
- **Notification Gateway:** medium — contracts/stores/workers follow proven patterns;
  risk isolated to channel behavior.
- **MCP Gateway + Plugins:** high — protocol client, connection lifecycle, per-user
  ownership — but it plugs into a mature policy/registry/audit path; UI is additive.
- **Gmail:** high — OAuth, push sync, background worker, analysis pipeline; depends on
  P0.5 + P1 + P2.
- **Mobile PWA:** medium — auth + SW + responsive chat; push risk isolated to P7.
- **Identity (P0.5):** medium — security-critical; touches login surface (approval).
- Critical path: **P0.5 → P1 → P2 → P4 → P5 → P6 → P7 → P8** (P3 parallel to P4).

## 2. Plugins as the unified integration management surface (amendment ruling)

- **Plugins** is the product-facing name; **MCP Gateway** is infrastructure. All
  discovery, search, install/connect, account authorization, status, permissions,
  enable/disable, tool inspection, per-plugin access, disconnect/revoke, and health
  history live in **one Plugins section** — no "MCP Gateway"/"MCP Servers" nav item.
- **Phase 0 audit finding:** no Plugins section exists yet (code or docs). It will be
  **created** in the Settings rail for the P4 MVP without renaming/replacing any
  existing section; Providers & Connections keeps AI-provider scope; sidebar structure
  unchanged. Promotion to a sidebar entry is a later, explicit decision.
- Plugin states the UI must distinguish: `installed-not-connected`, `connected &
  operational`, `disabled`, `authorization expired`, `configuration required`,
  `connection error`. Installing ≠ granting account permission.
- Categories: Email & Identity · Threat Intelligence · Security Operations ·
  Development & Infrastructure · OSINT & Investigation · Communication.
- Telegram: discoverable in Plugins; **delivery preferences stay in
  Settings → Notifications**.
- Not every plugin is MCP — one validated capability manifest covers
  `mcp | native_api | oauth | local_tool | platform`.
- All execution flows through the existing authorization/orchestration stack.
- OLED-dark, no competing marketplace UI; mobile shows status only (config = Desktop).

## 3. Approval gates ahead (do not proceed without explicit approval)

1. **Approval Gate 0** — this document set (awaiting).
2. End-user identity/auth changes (P0.5) — authorization surface.
3. Case-graph owner checks — documented policy change, already awaiting approval.
4. Database migrations, public API exposure, continuous mailbox access, paid provider
   integrations, production deployment — each individually gated (parent §12).

## 4. Phase 0 compliance

Read-only audit; **no production code modified**; **no deploys**; **no paid provider
calls** (all provider behavior in these docs is architectural, not executed).
