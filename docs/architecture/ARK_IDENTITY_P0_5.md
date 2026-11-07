# ARK P0.5 — End-User Identity: Implementation Design

**Status:** Design for approval — no authentication/authorization behavior changed yet
**Approved:** Phase 0 review (conditions §2–§4) · **Next gate:** this document
**Constraints honored:** no second identity system · admin + local dev workflows
preserved · dev stand-in stays explicitly development-only · **no DB migration,
no provider registration, no paid calls, no deployment authorized**

---

## 1. Current-state audit (evidence)

| Surface | Today | Evidence |
|---|---|---|
| Administrator identity | **Single env-configured admin**: `admin_username` + `admin_password_hash` (env, bcrypt fallback), `POST /api/v1/auth`… `settings.py:/login` → HS256 JWT with `role: admin` (120 min), `require_admin_token` dependency | `app/core/config.py:182-191,227`, `app/api/v1/endpoints/settings.py:65-90` |
| End-user identity | **None.** Analysts are `X-ARK-Principal` header (sanitized, self-addressed only) → `Principal(subject, kind, org)`; absent header → `ANONYMOUS`. Declared "development stand-in, not an authentication boundary" | `app/services/principal.py` (module docstring), `app/services/entitlements.py:Principal` |
| Principal-aware endpoints | `cai.py`, `investigate.py`, `overview.py`, `user_models.py` resolve the principal; stores key on subject: `session_store.principal_subject`, `engagement_store` owner, `user_credentials` (AES-256-GCM namespace), `user_preferences` | grep `principal_from_request` |
| Investigation isolation | **`/investigate` gap is CLOSED** — `InvestigationSession.principal_subject`, `_owned_or_404` (non-owner → 404, not an existence oracle), `TestInvestigateAuthorization`; CAI sessions via `_session_visible_to` | `investigate.py:33-40,110-130`, `CASE_GRAPH_AUTHORIZATION_BOUNDARIES.md` (status: IMPLEMENTED) |
| Crypto available | bcrypt hash/verify, `create_access_token`/`decode_access_token` (HS256, configurable expiry), AES-256-GCM `encrypt_field`/`decrypt_field` | `app/core/security.py` |
| Admin extras | `admin_store` already models staff + RBAC (`STAFF_ROLES`, `PERMISSION_KEYS`) as JSON state (seed-flagged demo records) — not yet wired to login | `app/services/admin_store.py` |
| Rate limiting on auth | **None** (no limiter on `/login`) | grep |
| Residual risk (documented) | `case_id` is free-form; the evidence graph is keyed by `case_id` only, no owner link | `CASE_GRAPH_AUTHORIZATION_BOUNDARIES.md` §1.3–1.4 |

## 2. Design principles

1. **One identity system.** End users and administrators are rows in *one* store with
   a `role` column. The existing admin becomes the bootstrap `admin` row; the admin
   console's login request/response shapes do not change.
2. **Token-derived principals.** `principal_from_request` resolves from the bearer
   token first. The `X-ARK-Principal` header is honored **only** when
   `ARKGEO_AUTH_MODE=development` (default) — in `required` mode it is rejected
   outright. The stand-in never becomes a production boundary (condition §3).
3. **Additive only.** New SQLite store (`CREATE TABLE IF NOT EXISTS`), no alteration
   of any existing table or store ⇒ **no database migration** in the approval's sense.
4. **Short-lived access + rotating refresh with revocation.**
5. Everything existing keeps working in the default mode, byte-for-byte.

## 3. Identity store (new: `app/services/identity_store.py`)

Follows the `session_store.py` SQLite precedent (single connection per op, lock,
`local_storage_path/arkgeo_identity.db`):

```sql
users (
  id TEXT PRIMARY KEY,              -- uuid, becomes principal subject
  username TEXT UNIQUE NOT NULL,    -- case-insensitive lookup
  password_hash TEXT NOT NULL,      -- bcrypt (existing helpers)
  role TEXT NOT NULL,               -- 'admin' | 'analyst'
  status TEXT NOT NULL,             -- 'active' | 'locked'
  failed_attempts INTEGER DEFAULT 0,
  created_at TEXT, updated_at TEXT,
  must_change_password INTEGER DEFAULT 0
);
recovery_codes (
  user_id TEXT, code_hash TEXT, used INTEGER DEFAULT 0, PRIMARY KEY(user_id, code_hash)
);
refresh_sessions (
  id TEXT PRIMARY KEY,              -- family id (rotation lineage)
  user_id TEXT NOT NULL,
  device_label TEXT, device_id TEXT,
  token_hash TEXT NOT NULL,         -- SHA-256 of opaque secret (never stored raw)
  created_at TEXT, last_used_at TEXT,
  expires_at TEXT NOT NULL,
  revoked INTEGER DEFAULT 0
);
```

- **Bootstrap (idempotent, no migration):** if the store is empty and env
  `admin_username`/`admin_password_hash` are set, insert them as the `admin` row so
  today's credentials keep working. Env credentials remain a documented
  **dev/bootstrap root**: if the store is locked or empty, `/login` falls back to
  them exactly as today (production posture: store is authoritative).
- Passwords always bcrypt via existing `verify_password`/`hash_password`.

## 4. Authentication flows

### 4.1 Registration (admin-mediated first; self-registration flag later)
- `POST /api/v1/auth/register` — **admin-JWT protected** (creates analysts or admins).
  Rationale: open registration on a security product without email verification is an
  abuse vector; invites/creation by the administrator cover the multi-user need now.
- Optional `ARKGEO_SELF_REGISTER=0|1` (default **0**) for later PWA onboarding; when
  enabled, first user bootstraps as `admin`, rest are `analyst`, all `must_change_password`.
- No external provider involved ⇒ nothing to register externally (condition §4).

### 4.2 Login / tokens / refresh
- `POST /api/v1/auth/login {username,password}` →
  `{access_token (15 min, claims: sub=user_id, role, typ:"access"),
    refresh_token (opaque 32-byte secret, 30 days),
    expires_in}`. Response shape mirrors the admin login (`token_type: bearer`).
- `POST /api/v1/auth/refresh` — validates refresh (hash lookup, unexpired,
  unrevoked), **rotates**: new secret, same family id; presenting a *used* secret
  revokes the **entire family** (reuse detection) and audits `auth.refresh_reuse`.
- `POST /api/v1/auth/logout` (current family) and `/logout-all` (all families).
- Rate limiting: in-process sliding window per username+IP on login/refresh
  (5 attempts → 15-min lock via `users.status='locked'` + `failed_attempts`).
  Uniform "Invalid credentials" for unknown-user vs bad-password (no enumeration).
- `admin_login` (`settings.py`) keeps its endpoint and response, but authenticates
  against the store row first, env fallback second; still issues `role:"admin"` JWT
  ⇒ admin console, `require_admin_token`, and every admin endpoint unchanged.

### 4.3 Principal resolution (single change point)
```python
def principal_from_request(request):
    # 1. bearer token → Principal(subject=payload["sub"], kind="user")
    # 2. else, ONLY if settings.auth_mode == "development":
    #       existing X-ARK-Principal sanitization (unchanged)
    # 3. else → raise 401 on identity-required endpoints; ANONYMOUS only on
    #       explicitly public reads (health, login)
```
`ARKGEO_AUTH_MODE=development|required` (default `development` ⇒ zero behavior
change for current workflows; `required` ⇒ header stand-in rejected with 401 —
explicitly development-only, never a production boundary, per condition §3).
`principal_from_headers` (internal/tests) keeps its signature.

## 5. Coverage of the required design areas

| Area | Design |
|---|---|
| Registration & authentication | §4.1–4.2 (admin-mediated; optional flagged self-register) |
| Admin compatibility | §3 bootstrap + §4.2 dual-path login; response shapes and `role` claims unchanged; admin_store staff/RBAC untouched (convergence later, out of scope) |
| Principal-scoped authorization | §4.3 token-derived subject feeds the existing subject-keyed stores; no store re-keying needed (subject strings continue) |
| Desktop / web / mobile sessions | All clients use `Authorization: Bearer` via the same axios/fetch layer (`api.ts` gains token attach + silent refresh); desktop = same web shell; mobile PWA = same endpoints, `device_label` recorded for the device registry (P6/P7) |
| Token handling & refresh | §4.2 — 15-min access, opaque rotating refresh, family reuse detection; revocation latency ≤ access TTL (documented tradeoff; no denylist in P0.5) |
| Recovery & revocation | Recovery: **admin-mediated reset** (`POST /api/v1/auth/reset` admin-JWT → temporary password, `must_change_password=1`) + **8 one-time recovery codes** at enrollment (SHA-256 hashed, single-use). Email self-service recovery deferred (needs a mail provider — approval-gated later). Revocation: per-family and global logout, lockout, admin force-reset |
| Multi-user investigation isolation | Token subject flows into `cai`/`investigate`/`overview`/`user_models` unchanged; existing `_session_visible_to` / `_owned_or_404` now enforce against a *trusted* subject instead of a client header. Residual: `case_id` graph keying (§1 last row) — **out of P0.5 scope**, documented follow-up: bind `case_id` ownership in `storage_service` |
| MCP & OAuth credential ownership | `user_credentials` already AES-256-GCM + namespace-keyed; P4 plugins bind connections to `token sub` only — header-derived subjects are rejected in `required` mode by construction |
| `/investigate` ownership gap | Already implemented and tested (§1); P0.5 changes only where the subject *comes from* (header → token). Tests re-run as regression |
| DB migration & rollback | Additive store only — **no existing schema touched**; rollback = revert the code commit; the new `.db` file is inert; `ARKGEO_AUTH_MODE` defaults to today's behavior so rollback is also runtime-switchable |
| Automated tests | §6 matrix |

## 6. Security & regression test matrix

**New (`tests/test_identity_p0_5.py` + store unit tests):**

| # | Test | Expectation |
|---|---|---|
| 1 | Register (admin token) → login → access + refresh issued | 200; sub = user id; role claim correct |
| 2 | Register without admin token | 401 |
| 3 | Login unknown user vs wrong password | identical 401 body (no enumeration) |
| 4 | 5 failed logins → lockout; lock expires | 423/401 then recovery; `status='locked'` |
| 5 | Tampered/expired/garbage access JWT | 401 |
| 6 | Refresh rotation: old secret reuse | whole family revoked + audit event |
| 7 | Refresh after logout | 401 |
| 8 | `/logout-all` kills every device family | 401 afterwards |
| 9 | Recovery code single-use; second use fails | 401; `used=1` |
| 10 | Admin reset → temp password → `must_change_password` enforced | forced-change gate works |
| 11 | **Dev mode:** header stand-in behaves exactly as today (golden regression) | existing suite green |
| 12 | **Required mode:** `X-ARK-Principal` without bearer | 401 |
| 13 | Required mode: token A cannot read B's CAI session / investigation / engagement / credentials | 404, non-oracle shape |
| 14 | Admin login (store row and env-fallback paths) | both issue `role:admin` JWT; admin endpoints pass |
| 15 | Bootstrap idempotency: second boot does not duplicate admin | one row |
| 16 | No secrets in logs (login/refresh/audit paths) | grep-style assertion |
| 17 | Token never returned by any read endpoint; refresh secret never stored raw | store assertions |

**Regression:** full backend suite (currently 916–921 green per AGENTS), plus
`TestInvestigateAuthorization`, `test_cai_session_authz`, `test_model_authority`,
run-control and engagement tests unchanged.

## 7. Explicitly NOT in P0.5

MFA/OTP · email-based self recovery · organizations/tenancy UI · admin staff/RBAC
convergence with the new store · `case_id` owner binding (documented follow-up) ·
device registry UI (data columns land now; P6 consumes) · any change to model
routing, orchestration, or paid providers.

## 8. Implementation steps (after approval)

1. `identity_store.py` + bootstrap + unit tests.
2. `/api/v1/auth/*` endpoints (register/login/refresh/logout/reset) + rate limit.
3. `principal_from_request` mode gate (`ARKGEO_AUTH_MODE`).
4. Admin login dual-path (store first, env fallback).
5. Frontend `api.ts` bearer attach + silent refresh (admin console untouched).
6. Test matrix §6 + full suite; docs update (`AGENTS.md`, this file's status).

Estimated size: ~6 backend files + 1 frontend helper + 2 test files; no schema
changes to existing stores; default-mode behavior identical (verified by test 11).

---

**Gate:** present → approve → implement. No migration, provider registration, paid
call, or deployment occurs without separate approval.
