# THE ARK — Release Readiness Matrix

**Date:** 2026-11-05 · HEAD `c8e215c6` (shallow) · no commit made
Legend: ✅ ready · ⚠️ ready with caveat · ❌ not ready · ⬜ not verifiable here

---

## A. Build & Test

| Item | Status | Evidence |
|---|---|---|
| Backend suite (with system binaries) | ✅ | `724 passed` |
| Backend suite (bare environment) | ⚠️ | 9 env-dependent failures (exiftool/dig/nmap) |
| Frontend type-check | ✅ | `npx tsc --noEmit` exit 0 |
| Frontend production build | ✅ | `npx vite build` exit 0, 2010 modules |
| Dependency install (web) | ✅ | lockfile v3 consistent with manifest |
| Dependency install (desktop) | ✅ | separate lock, electron 32 |
| `allowScripts` manifest key | ⚠️ | inert/undocumented — remove or justify |

## B. Security

| Item | Status | Evidence |
|---|---|---|
| Engagement scope fail-closed | ✅ | `check()` matrix; 14 tests |
| Scope gate before HITL (no widening) | ✅ | `orchestrator` pre-approval check |
| SSRF egress guard | ✅ | live loopback + metadata blocked |
| Cloud-metadata hard-deny | ✅ | `169.254.169.254` blocked |
| No shell interpolation | ✅ | grep: no `shell=True`/`os.system` |
| Credential masking (BYOK) | ✅ | masked preview only |
| No secrets in API responses | ✅ | `/cai/models` scan clean |
| No secrets in frontend bundle | ✅ | only AWS doc placeholder |
| Embedded git remote credential | ⚠️ | locally scrubbed; provider-side revocation OUTSTANDING (`ARK_P0_CREDENTIAL_REMEDIATION.md`) |
| Electron `sandbox: false` | ⚠️ | reviewed — decision record `ARK_ELECTRON_SANDBOX_DECISION.md` (keep for now) |

## C. Identity

| Item | Status | Evidence |
|---|---|---|
| Single user-facing identity | ✅ | "ARK — Cybersecurity Super Intelligence" |
| No `ARK-CAI` in app/ (excl vendored) | ✅ | grep NONE |
| No `ARK-CAI` in frontend src | ✅ | grep NONE |
| Canonical prompt `00_identity.prompt` | ✅ | "You are ARK, the cognitive… layer" |
| Runtime identity block | ✅ | captured from live orchestrator |
| Startup banner | ✅ | `ARK SYSTEM INITIALIZED` |
| CAI attribution preserved | ✅ | README licenses + `cai/__init__` |

## D. Model Management

| Item | Status | Evidence |
|---|---|---|
| Single source of truth (`model_router.resolve`) | ✅ | called from cai/user_models/orchestrator |
| Explicit selection precedence | ✅ | explicit valid wins |
| No silent substitution | ✅ | unknown → `model_unavailable` |
| Provider-without-credential error | ✅ | actionable message |
| Local runtime unavailable error | ✅ | Ollama clear error |
| Live inference | ⬜ | rate-limited / no creds |

## E. Browser Runtime

| Item | Status | Evidence |
|---|---|---|
| Runtime availability detection | ✅ | `available:true`, chromium, playwright |
| Open / navigate / extract / close | ✅ | real Chromium e2e |
| SSRF on navigation | ✅ | `ssrf_blocked` |
| Operator control handoff | ✅ | `agent`→`operator` |
| Screenshot-first transport (no cross-origin DOM proxy) | ✅ | PNG bytes endpoints |
| 21 browser endpoint tests | ✅ | incl. real-Chromium lifecycle |

## F. Persistence

| Item | Status | Evidence |
|---|---|---|
| Encrypted session store | ✅ | AES-256-GCM fields |
| Zero-retention transcript empty | ✅ | `/cai/sessions/{id}` |
| Restart honesty (`interrupted`) | ✅ | `mark_interrupted_runs` |
| Evidence = references only | ✅ | hashes/exec ids |
| 12 session-store tests | ✅ | pass |

## G. Operations / Platform

| Item | Status | Evidence |
|---|---|---|
| Backend starts on :12000 | ✅ | `/health` ok |
| Cloud services configured | ❌ | all `not_configured` (no `.env`) |
| Docker | ⬜ | unavailable in sandbox |
| Electron desktop shell | ⬜ | headless host |
| Shallow clone limits | ⚠️ | no blame/merge-base |

---

## Blocking-Release Checklist

**Must fix before release**
1. ⚠️ **Rotate the embedded credential at the provider** (local scrub done; the
   token must still be revoked/rotated — see `ARK_P0_CREDENTIAL_REMEDIATION.md`).
2. ❌ Provide a real `.env` and re-run the cloud-gated scenarios on a
   credentialed host (ledger §E4/E5, §F2/F3).

**Should fix before release**
3. ⚠️ Remove or document `package.json#allowScripts`.
4. ⚠️ Convert the Electron port handshake to async, then enable `sandbox: true`
   and re-test (`ARK_ELECTRON_SANDBOX_DECISION.md` §5).
5. ⚠️ Declare the system-binary prerequisites (`exiftool`, `dig`, `whois`,
   `nmap`, `gobuster`, `tesseract`) in the deployment/CI setup.

**Explicitly OPEN (do not claim complete)**
- Operator HTTP-plane control of a live agent session (ledger A11).
- `steer` against a sustained live run (ledger D4).
- Scripted renderer click-through of every sub-view (ledger §Open items).

**No action**
- Lockfile shrink (correct — desktop deps moved to their own package).
- Deleted `InvestigatorProfileModal.tsx` / `SettingsModal.tsx` (replaced by
  `ClientSettingsModal.tsx` + `InvestigationNavigation` settings entry).
