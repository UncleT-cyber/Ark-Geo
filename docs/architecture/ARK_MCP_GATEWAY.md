# ARK MCP Gateway — Architecture Document

**Status:** Phase 0 audit complete — architecture proposed, awaiting Approval Gate 0
**Parent directive:** MCP Gateway, Notification Gateway & Mobile Companion (§4 Workstream A)
**Amendment:** Plugin System — MCP Integration and Navigation Requirements
**Scope of this document:** MCP as the integration *mechanism*; **Plugins as the product surface**

---

## 1. Ruling — Plugins is the unified integration surface

Per the amendment:

- All user-facing MCP/integration discovery, configuration, and management is accessed
  through **Plugins**. There is **no** separate "MCP Gateway" or "MCP Servers" item in
  main navigation — ever. MCP is an implementation detail shown inside plugin details
  (integration type: `mcp`), not a destination.
- **Phase 0 audit finding:** the referenced "existing Plugins section" **does not exist
  today** — no `Plugins` component, nav entry, route, or doc reference exists in
  `arkgeo-investigator-web/src`, `arkgeo-mobile`, or `docs/`. The nearest surfaces are
  Settings → **Providers & Connections** (`SettingsWorkspace.tsx` rail, `Plug` icon) and
  the admin plane (`components/admin/*`).
- Therefore "preserve the existing Plugins section" resolves to: **create Plugins once,
  correctly**, without renaming/replacing any existing section, without touching the
  sidebar's group structure, and without disturbing Providers & Connections (which keeps
  its job: AI provider/model/keys).
- **Recommended placement (decision for approval):** a **Plugins** section in the
  Settings rail (alongside Providers & Connections) for the Phase 4 MVP, promoted to a
  sidebar entry only if the management experience outgrows Settings. This introduces no
  new main-navigation item for MCP and changes no existing navigation.

## 2. Existing implementation evidence (what MCP infrastructure exists today)

| Area | Finding | Evidence |
|---|---|---|
| ARK MCP client/server | **None.** No `mcp` dependency, no client/server/adapter in `app/` | `arkgeo-backend/requirements.txt` (no `mcp`), repo-wide grep |
| Dormant upstream scaffolding | Vendored CAI snapshot ships an upstream REPL `/mcp` command (load/list/add/remove servers, attach tools to agents). **Not wired** to ARK's orchestrator or HTTP surface | `app/engine/cai/cai/repl/commands/mcp.py` |
| CAI runtime submodule | `arkgeo-backend/cai/src` empty → `/cai/registry` 500s (dormant optional feature) | `AGENTS.md` gotchas |
| Tool execution contract MCP tools must plug into | Mature: `ToolSpec` registry (98 tools / 12 domains), adapter, policy guard, engagement scope, audit nodes, SSE execution events | `app/agent/unified_registry.py`, `tool_registry.py`, `tool_adapter.py`, `policy_guard.py`, `engagement_scope.py`, `evidence_graph.audit_tool_call` |
| Authorization | `PolicyGuard` (capability permissions, risk→approval tiers, budgets), operator-declared engagement scope, principal-scoped sessions | `app/agent/policy_guard.py`, `app/agent/engagement_store.py`, `app/api/v1/endpoints/cai.py:_session_visible_to` |
| Credential storage pattern | AES-256-GCM, principal-namespace keyed (BYOK) — the pattern external OAuth grants should reuse | `app/services/user_credentials.py`, `app/core/security.py` |
| Untrusted-content handling | Fence + injection scan for external content reaching the model — **must** wrap MCP/email tool outputs | `app/engine/untrusted_content.py`, `tests/test_prompt_injection_suite.py` |
| Spend guards | Entitlements, key probe, provider error classification — "never silently spend" already enforced for model calls; needs an analogue for paid plugin APIs | `app/services/entitlements.py`, `key_probe.py`, `app/engine/provider_errors.py` |

**Conclusion:** ARK has zero MCP infrastructure but a complete, battle-tested *execution*
pathway. MCP integration is a **connector problem**, not an engine problem.

## 3. Proposed architecture

```
Plugins UI (Settings → Plugins)                 ← product experience, one surface
        │  (manifest read / config / enable / revoke)
        ▼
Plugin Manager (backend service)
  ├─ plugin_registry      — validated capability manifests (§4)
  ├─ connection_manager   — per-principal ownership, health, enable/disable, revoke
  ├─ mcp_client           — transport to MCP servers, tool discovery, schema validation
  ├─ native adapters      — non-MCP integrations behind the same manifest interface
  └─ plugin_audit         — principal-scoped audit records (admin_store.append_audit pattern)
        │
        ▼
Existing execution path (UNCHANGED)
  unified_registry → PolicyGuard → engagement scope → orchestrator dispatch
        → SSE execution events → evidence graph audit node
```

- The MCP connection manager is a **backend service**, mirroring the connection-manager
  requirements (discovery, metadata, health, schema validation, ownership, credential
  lifecycle, enable/disable, revocation, timeouts, limits, audit).
- Tools surfaced from a plugin are registered as ordinary `ToolSpec`s **scoped to the
  owning principal** — the model never sees credentials; the adapter resolves them at
  execution time from `user_credentials`-style encrypted storage.
- Transports: start with **Streamable HTTP / SSE** transports for remote servers;
  `stdio` local-command transports are excluded from Phase 4 (they are arbitrary code
  execution and require an explicit later decision).
- Every MCP tool call is an ordinary audited tool call: same policy tiers, same budgets,
  same engagement rules, same untrusted-content fence on returned payloads.

## 4. Plugin capability manifest (validated, one shape for all integration types)

```jsonc
{
  "id": "gmail",                     // stable slug
  "name": "Gmail Security",
  "category": "email_identity",      // amendment §3 taxonomy
  "integration_type": "mcp | native_api | oauth | local_tool | platform",
  "description": "...",
  "tools": [ { "id": "...", "name": "...", "input_schema": {...}, "risk": "low|medium|action|high-risk" } ],
  "permissions": [ "mail.readonly" ],          // least-privilege scope list
  "config_requirements": ["oauth"],            // what the user must provide
  "authorization_scope": "account | tenant | none",
  "availability": "available | requires_config | disabled_by_policy",
  "states": ["installed", "connected", "disabled", "auth_expired", "config_required", "connection_error"],
  "health": { "status": "...", "checked_at": "..." }
}
```

Manifests are **server-validated** (schema-checked on registration); the UI renders only
what the manifest declares. Installing ≠ authorizing: `installed` and `connected` are
distinct states (amendment §2/§5).

## 5. Categories (amendment §3)

`email_identity` (Gmail, Outlook, M365) · `threat_intel` (VirusTotal, AbuseIPDB,
urlscan.io, MISP) · `security_operations` (SIEM, EDR, Wazuh, cloud security) ·
`development_infra` (GitHub, Vercel, Supabase, Cloudflare) · `osint_investigation`
(browser research, image intelligence, geospatial providers) · `communication`
(Telegram, other messaging). Telegram is **discoverable in Plugins**; its notification
**delivery preferences stay in Settings → Notifications**.

## 6. Security considerations

- External MCP responses and plugin payloads are **untrusted data** — always passed
  through `untrusted_content` fence + injection scan before reaching the model.
- The AI **cannot grant itself permissions**: manifest changes and OAuth grants require
  operator action through the Plugins UI; `PolicyGuard` remains the sole execution gate.
- Principal isolation: connections, tools, and audit records are keyed by principal;
  cross-user access returns not-found (pattern: `_session_visible_to`).
- Credentials never appear in prompts, responses, SSE events, or logs (redaction
  pattern: `provider_errors`, `evidence_recorder.redact`).
- Paid plugin APIs: per-plugin spend budget + explicit enable, analogue of
  `key_probe`/entitlements — no silent paid calls.
- Malicious servers: timeouts, output size bounds, tool-count limits, schema
  validation, connection allow-listing by the operator.

## 7. Migration requirements

- **No database migration in Phase 4 MVP** — new SQLite store following
  `engagement_store.py`/`admin_store.py` precedent (owner-scoped, additive).
  Anything requiring schema migration triggers the parent directive's approval gate.
- Existing identity limitation (below) must be solved first — see
  `ARK_PLATFORM_EXPANSION_PLAN.md` §Identity.

## 8. Tests (mocked providers; real integrations separately authorized)

Connection/revocation lifecycle · unauthorized tool invocation denied by PolicyGuard ·
cross-user isolation (foreign principal → not-found) · manifest schema validation ·
malformed/hostile MCP payloads fenced · spend budget enforcement ·
enable/disable/auth-expired state transitions · audit record emitted per execution.

## 9. Phased delivery

Fits parent §11 **Phase 4 (MCP Gateway foundation)**, preceded by Phase 1 (event
contracts) and Phase 2 (notifications), followed by Phase 5 (Gmail as first complete
demonstration, Tier 1 read-only). Plugins UI (MVP in Settings rail) lands **with**
Phase 4 — never a separate MCP navigation item.
