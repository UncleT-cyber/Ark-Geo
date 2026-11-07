# ARK Mobile Companion — Architecture Document

**Status:** Phase 0 audit complete — architecture proposed, awaiting Approval Gate 0
**Parent directive:** MCP Gateway, Notification Gateway & Mobile Companion (§6 Workstream C)
**Amendment:** mobile reuses authorized plugin capabilities via the shared backend;
advanced plugin configuration stays on Desktop.

---

## 1. Existing implementation evidence (what mobile-ready infrastructure exists today)

| Area | Finding | Evidence |
|---|---|---|
| `arkgeo-mobile` (Expo 51 / RN) | **Exists but is the legacy safety HUD** (camera, location, SOS, encrypted offline queue) — a separate codebase, not the companion; not to be conflated with Workstream C | `arkgeo-mobile/package.json`, `AGENTS.md` |
| Web frontend | React 18 + Vite single-page workbench — the desktop three-column layout; chat surface (`ArkControl`) is component-reuse candidate but desktop-coupled | `arkgeo-investigator-web/` |
| PWA readiness | **Not a PWA today**: no web app manifest, no service worker, no push subscription code (`public/` holds only branding/vendor assets) | `public/`, `index.html` |
| Shared backend | Complete: chat/SSE (`cai.py`), model routing (Phase H `model_registry`/`model_policy`), investigations, cases, evidence, audit — all HTTP + principal-scoped | `app/api/v1/endpoints/*` |
| Auth for mobile | **Gap:** only admin JWT exists (`settings.py /login` + bcrypt). End-user accounts do not exist; the analyst principal is a dev stand-in (`X-ARK-Principal`) | `app/core/security.py`, `app/services/principal.py` |
| Notification channels | In-app bell (in-memory) + Twilio SMS; no push (see Notification Gateway doc) | `src/core/notifications.ts`, `twilio_service.py` |
| Investigation progress data | Rich, already streamed: run lifecycle, timeline events, findings — mobile progress cards can render existing contracts | `executionPresentation.ts`, SSE events |

**Conclusion:** the shared backend is genuinely ready; the missing pieces are **real
end-user identity**, a **PWA shell** (manifest/SW/push), and a **mobile-shaped
frontend**. Native is unnecessary for the initial scope.

## 2. Proposed delivery strategy — PWA first (parent §C4)

Evaluate-and-confirm: the existing Vite app **can** support a PWA without disrupting
the desktop shell — same origin, same API, same principal model. Plan:

1. Add manifest + service worker + installability (desktop app unchanged — the SW only
   activates for mobile viewports/routes).
2. Route-level mobile experience: `/m` (or responsive breakpoints) exposing **Chat,
   Alerts, Settings** only — never the three-column workbench (parent §C3).
3. Web Push for Phase 7 (needs HTTPS hosting — see Dependencies).

## 3. Product scope (parent §C2)

- **Chat** — reuse the existing backend chat/SSE verbatim: same sessions, same model
  routing, same tool permissions, same HITL approval events (safe subset surfaced),
  same conversation history. **No second AI engine.** Investigation requests return
  progress cards; complex operations offer a desktop handoff link.
- **Alerts** — the Security Inbox from the Notification Gateway: severity, read/unread,
  acks, safe deep links into conversations/incidents (permission-checked on open).
- **Settings** — account/session management, notification preferences (read-only
  mirror of Settings → Notifications), device registration, channel status, logout +
  session revocation.
- **Plugins on mobile (amendment §6)** — mobile **consumes** authorized plugin
  capabilities through chat and displays integration status (connected/error/
  expired badges). No install/configure/revoke flows on mobile in the initial
  companion; those remain Desktop → Settings → Plugins.

## 4. Shared backend & identity (parent §C5)

One identity, one orchestration engine, one investigation store, one authorization
boundary. Tool availability on mobile = server-side `PolicyGuard` + product capability
policy — the mobile client's existence never widens permissions. **Prerequisite:**
real end-user accounts (see Platform Expansion Plan §Identity); the current
`X-ARK-Principal` stand-in is explicitly *not* an auth boundary and cannot gate a
publicly reachable mobile client.

## 5. UX requirements (parent §C3)

OLED-dark, existing branding, familiar composer, mobile navigation (bottom tabs or
equivalent), clear notification indicator, readable progress cards, loading/offline/
error states, accessible controls, approachable-not-childish. No forensic panels, no
three-column copy, no second chat input pattern.

## 6. Security considerations (parent §C7)

Secure login + persistent sessions with device revocation · server-side permission
enforcement on every call · no raw email/sensitive evidence cached on device by
default · push subscriptions bound to authenticated users + verified devices · signed
deep links · lost-device revocation via session/device store · content minimization in
push payloads.

## 7. Migration requirements

- No changes to existing investigation/case/evidence models.
- New: device + push-subscription stores (additive, principal-scoped, SQLite
  precedent). Schema migration ⇒ approval gate.
- `arkgeo-mobile` untouched (legacy safety HUD stays as-is).

## 8. Tests

Mobile login + session persistence · shared conversation history across desktop/mobile
· permission parity (a tool denied on desktop is denied on mobile) · alert delivery +
read/ack state sync · deep-link permission checks · lost-device revocation · offline
degradation · push subscription lifecycle (register/expire/revoke) · cross-account
leakage attempts.

## 9. Phased delivery

Parent §11: **Phase 6 (companion: chat/alerts/settings PWA) → Phase 7 (mobile push) →
Phase 8 (E2E)**, depending on Phase 2 (notifications) and the identity prerequisite.
Complexity: **medium** — highest risk is platform push behavior (iOS installed-PWA
requirements), isolated in Phase 7; native development explicitly deferred.
