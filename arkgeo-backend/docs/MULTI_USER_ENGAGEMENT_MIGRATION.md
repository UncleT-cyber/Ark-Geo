# ARK multi-user engagement foundation — staged backend change

## Current status
This branch introduces an explicit per-request `scope=` / `require_scope=True` interface to the existing scope guard, with regression tests. It **does not** make the public deployment multi-tenant ready. The existing fixture-based callers continue to use their legacy path until the authenticated execution pipeline is migrated.

## Verified code concerns
- `app/agent/engagement_scope.py` reads a process-global JSON fixture from `ARKGEO_ENGAGEMENT_SCOPE`.
- `check()` denies target-bearing calls with missing scope, but non-target calls remain usable.
- `app/agent/policy_guard.py` separately governs permissions, approvals, budgets, and availability.
- A global fixture must not be used as the source of authority for a public multi-user execution request.

## Remaining implementation gates (do not deploy execution to untrusted users before these pass)
1. Identify the authenticated principal for **every** entrypoint (HTTP, websocket/stream, jobs, agent loop, orchestrator, legacy tool adapters). Reject missing identities for target execution.
2. Implement persistent, owner-scoped engagement records, membership, start/expiry, target and port grants, audit events, and server-side credential references. Never trust a scope dictionary submitted by a browser.
3. Resolve an engagement from the authenticated principal and selected engagement ID; pass the server-resolved dictionary to `check(..., scope=..., require_scope=True)` at **every** network execution boundary, including retries and asynchronous jobs.
4. Re-check engagement authorization and target/port restrictions immediately before dispatch; handle DNS resolution, redirects, IPv6, CIDR, and indirect tool arguments to prevent bypass.
5. Bind execution approval to the user, engagement, exact arguments and tool; prevent cross-user approvals.
6. Keep advisory conversation independent of engagement. Prompt context must use the authenticated user's own active engagement or a neutral message, not a global lab fixture.
7. Add end-to-end multi-user tests (Alice/Bob, missing/expired/revoked engagement, concurrency, host/port, redirects, agent connectivity), then stage rollout behind a disabled-by-default feature flag.

## Security note
The explicit `scope` argument is an **internal server-side API**, not an authorization token. Caller identity and ownership checks are prerequisites before any user-controlled scope may be passed. Existing production execution must not be considered secured by this foundation alone.
