# ARK Notification Gateway — Architecture Document

**Status:** Phase 0 audit complete — architecture proposed, awaiting Approval Gate 0
**Parent directive:** MCP Gateway, Notification Gateway & Mobile Companion (§5 Workstream B)

---

## 1. Existing implementation evidence (what notification infrastructure exists today)

| Component | State | Evidence |
|---|---|---|
| In-app notification bell | **Working, in-memory only** — bounded list built from bus events (hitl/scope/run/evidence), unread count, mark-all-read; lost on reload | `src/core/notifications.ts`, `NotificationBell` in `InvestigationTabs.tsx`, `Workbench.tsx` |
| Settings → Notifications panel | **Client-side only** — report branding (logo/watermark) + an "email alerts" checkbox persisted in `ByokContext`/localStorage. **No backend, no delivery** | `src/components/settings/NotificationsPanel.tsx` |
| Outbound SMS (real delivery) | **Working** — Twilio dispatch with graceful degradation (logs when unconfigured); used by SOS + Dead-Man's Switch | `app/services/twilio_service.py`, `app/api/v1/endpoints/sos.py` |
| Background worker precedent | **Working** — Dead-Man's Switch asyncio polling loop started from `main.py`; state in-memory (docstring itself says "swap for Redis/DB later") | `app/services/deadman_service.py` |
| Security-event model | **Does not exist** — findings live in evidence graph / run records / admin audit, none of which is a notification-eligible event with severity + delivery state | `app/engine/evidence_recorder.py`, `app/agent/evidence_graph.py`, `app/services/admin_store.py` |
| Delivery queue | **Does not exist** — the only queue is the in-process, process-local `_QUEUE_STORE` for chat objectives (lost on restart) | `app/api/v1/endpoints/cai.py:302` |
| Desktop OS notifications | **Do not exist** — no `Notification` API usage, no service worker, no permission request anywhere in the web app | repo-wide grep |
| Persistence stores available | SQLite-store precedent is mature and reusable | `session_store.py`, `engagement_store.py`, `settings_store.py`, `admin_store.py` |

**Conclusion:** ARK has *one real delivery channel* (Twilio SMS, emergency-scoped), an
in-memory in-app bell, and strong persistence precedents — but **no event contract, no
policy engine, no dispatcher, no history, and no real preference store**. Workstream B
is greenfield on a solid foundation.

## 2. Proposed architecture

```
Producers (existing)                      Notification Gateway (new, backend)
  evidence_graph findings ──┐
  run failures / HITL ──────┼─► Security Event Ingestion ─► event store (SQLite, principal-scoped)
  monitors (Workstream A) ──┘            │
                                         ▼
                            Notification Policy Engine
                            (severity ≥ HIGH default, per-user prefs,
                             ownership, suppression/dedup, quiet hours)
                                         │
                                         ▼
                            Dispatcher ─► Delivery Workers (asyncio, bounded retries)
                                          ├─ Desktop (Web Push / OS notification when PWA)
                                          ├─ Telegram (Phase 3)
                                          └─ SMS (existing Twilio — kept for SOS/deadman)
                                         │
                                         ▼
                            Notification History (status, acks, errors)
```

- Reuses: asyncio background-task pattern (`deadman_service`/`_spawn_background`),
  SQLite store pattern, `bus.py` for fan-out, Twilio for early SMS validation,
  `redact()` for content minimization.
- New: event store + policy engine + dispatcher + real preference store (replacing the
  localStorage-only NotificationsPanel backend gap; the panel gains a server-backed
  section while keeping report branding).

## 3. Event contract (server-validated — parent §B4)

`event_id, event_type, severity (HIGH|CRITICAL initially), principal_id,
source_integration, case_id?, evidence_ref?, title_safe, summary_safe, created_at,
dedup_key, status, authorization_context` — validated server-side; AI-generated content
may fill *title/summary only*, never ownership/recipient fields.

## 4. Product defaults (parent §B2)

Desktop: enabled · Telegram: enabled · Mobile push: enabled · WhatsApp: disabled ·
Minimum outbound severity: **HIGH**. Lower severities stay in the ARK Security Inbox.
Enabled ≠ connected — the UI must distinguish preference from endpoint verification.

## 5. Telegram (Phase 3)

ARK-owned bot · single-use short-lived linking tokens · verified chat ownership ·
safe templates (no raw email/evidence/tokens) · delivery acks + failure logs ·
revocation. **Discoverable in Plugins; delivery preferences remain in
Settings → Notifications** (amendment §3). Interactive incident actions are out of
scope until explicitly authorized.

## 6. Reliability & security

Durable event persistence · idempotent scheduling · dedup keys (no repeat alerts for an
unchanged incident) · per-channel delivery records · bounded retries with backoff ·
rate limiting · quiet hours · escalation for CRITICAL · delivery-health monitoring ·
user-triggered test notifications. Security: principal-scoped delivery, verified
endpoints, strict recipient ownership, content minimization, signed incident deep
links, permission checks on open, audit records, abuse prevention — the gateway is
**never** a generic messaging service.

## 7. Migration requirements

- **Phase 2 MVP: no schema migration** — new additive SQLite stores (event,
  preference, delivery) per the established store precedent. A unified relational
  schema (if ever wanted) requires the parent directive's migration approval.
- Existing localStorage notification prefs migrate into the server-backed store
  (read-once import) without breaking the bell.

## 8. Tests

Severity filtering (HIGH passes, below stays inbox) · recipient isolation (principal A's
events never reach B) · dedup/idempotency · retry-then-failure recorded honestly ·
quiet hours · Telegram link token single-use + revocation · preference vs endpoint
state distinction · offline desktop → persisted for later sync · rate limits.

## 9. Phased delivery

Parent §11: **Phase 1 (event contracts) → Phase 2 (foundation: prefs, Security Inbox,
desktop integration) → Phase 3 (Telegram) → Phase 7 (mobile push)**, feeding Phase 8
end-to-end. Complexity: **medium** — the risky unknowns (channel auth, push platform
behavior) are isolated in Phases 3/7.
