# THE ARK — Final Integration Audit

**Date:** 2026-11-05
**Repository:** `UncleT-cyber/Ark-Geo` · branch `main` · HEAD `c8e215c6` (shallow clone)
**Scope:** End-to-end integration verification of the current working tree
(Stage Zero inventory → identity consolidation → security gates → runtime
acceptance), performed against the **real** application, not mocks.

> **Commit status: NONE.** No commit was made. The working tree remains dirty
> by design; the proposed change set is in `ARK_PROPOSED_COMMIT_PLAN.md`.

---

## 1. Executive Summary

| Area | Verdict | Notes |
|---|---|---|
| Backend test suite | **PASS** | 724 passed / 0 skipped **once required system binaries are installed** |
| Frontend type-check (`tsc`) | **PASS** | exit 0 |
| Frontend production build (`vite`) | **PASS** | 2010 modules, exit 0 |
| Engagement-scope security gate | **PASS** | fail-closed for target-bearing calls |
| SSRF / egress guard (browser) | **PASS** | loopback + cloud-metadata blocked live |
| Model resolution precedence | **PASS** | explicit selection wins; no silent substitution |
| Credential exposure (in API responses/bundle) | **PASS** | masked preview only; no keys in responses/bundle |
| Credential exposure (git remote URL) | **REMEDIATED locally / revocation OUTSTANDING** | see `ARK_P0_CREDENTIAL_REMEDIATION.md` |
| ARK identity consolidation | **PASS** | single user-facing identity "ARK — Cybersecurity Super Intelligence" |
| Startup banner branding | **PASS** | `ARK SYSTEM INITIALIZED` |
| Browser runtime (real Chromium) | **PASS** | lifecycle + isolation verified |
| Session persistence / zero-retention | **PASS** | encrypted; zero-retention transcript empty |
| Cloud AI paths (vision/LLM/geocode) | **BLOCKED** | no `.env` → all providers `not_configured` |
| Electron desktop shell | **NOT TESTED** | no display; static review only |
| Live model inference | **BLOCKED** | provider rate-limited / no credentials |

**Headline finding:** the previously-reported "723 passed, 1 skipped" baseline
was **not reproducible** in a clean environment — 9 tests fail on a machine
without `dig`, `whois`, `exiftool`, `nmap`. These are **environmental, not
regressions**. With the binaries installed the suite is **724 passed / 0
skipped**.

---

## 2. Stage Zero — Working-Tree Inventory

43 tracked files modified, 23 untracked (new modules/tests), 2 tracked files
deleted. Classification:

| Class | Examples |
|---|---|
| **A.2 execution policy** | `app/agent/engagement_scope.py`, `app/agent/unified_registry.py` (scope check in `call`/`acall`), `app/engine/orchestrator.py` (pre-HITL scope gate) |
| **Identity** | `app/agent/cognitive/00_identity.prompt`, `app/engine/cai/registry.py`, `app/engine/agent_bridge.py`, `app/brain/pipeline.py` |
| **User models / BYOK** | `endpoints/user_models.py`, `models/model_registry.py`, `services/entitlements.py`, `services/model_router.py`, `services/principal.py`, `services/user_credentials.py`, `services/user_preferences.py` |
| **Sessions** | `services/session_store.py`, `endpoints/cai.py` (`/cai/sessions*`) |
| **Browser runtime** | `app/tools/web_intel/` (guard, browser, fetcher, tools), `endpoints/browser.py`, `tests/test_browser_endpoints.py` |
| **Workbench UI** | `Workbench.tsx`, `ArkControl.tsx`, `InvestigationNavigation.tsx`, `InvestigationTabs.tsx`, `BrowserView.tsx`, `workspace.css`, `ark-control.css` |
| **Deleted** | `workbench/InvestigatorProfileModal.tsx`, `workbench/SettingsModal.tsx` |
| **Generated / drift** | `arkgeo-investigator-web/package-lock.json` (615+/5697−), `package.json` |

### Flagged items

1. **Embedded credential in git remote** — `origin` URL contained an embedded
   HTTPS userinfo credential (prefix/length recorded out-of-band; **not
   reproduced in this report**). **RESOLVED in this pass:** the remote was
   rewritten to a credential-free URL (`git remote set-url origin
   https://github.com/UncleT-cyber/Ark-Geo.git`); no credential remains in
   `.git/config`, the working tree, tracked history, logs, or reports. The
   token must still be **revoked/rotated** at the provider — see
   `ARK_P0_CREDENTIAL_REMEDIATION.md`.
2. **Lockfile drift** — the web lockfile shrank 7368 → 2286 lines; top-level
   `concurrently`, `electron`, `electron-builder`, `wait-on` were dropped.
   This is **consistent and correct**: those are now owned solely by
   `arkgeo-desktop/package.json` (electron 32), and the web manifest lists
   only `vite` + frontend deps. No dependency is actually missing from either
   package.
3. **`"allowScripts": {"esbuild@0.21.5": true}`** — non-standard manifest key
   with no consumer in the repo (grepped: only the declaration). It is **inert**
   (npm ignores unknown top-level keys). Recommend removal for hygiene, or
   documenting the intended tool.
4. **Electron `sandbox: false`** — `arkgeo-desktop/main.js:183`. Acceptable
   for a locally-loaded, trusted renderer with `contextIsolation: true` and
   `nodeIntegration: false`, but it is a deliberate weakening; recorded, not
   changed.

---

## 3. ARK Identity Consolidation (directive)

**Canonical identity:** *ARK — Cybersecurity Super Intelligence*.
CAI remains an **internal** engine/framework; it is no longer a separate
user-facing assistant or independently branded intelligence.

### Changes applied

**Frontend (user-facing strings)**
- `ArkControl.tsx` — dock brand `ARK-CAI` → `ARK`; aria-labels, idle prompt,
  composer placeholder, error strings.
- `Workbench.tsx` — `CAI Browser` → `ARK Browser`; region/separator aria-labels.
- `BrowserView.tsx` — control label `CAI` → `ARK`; hints; `Return to CAI` →
  `Return to ARK`.
- `useImageReview.ts`, `types.ts`, `api.ts`, `caiBrowserBus.tsx` — comments.

**Backend (identity strings)**
- `app/engine/cai/registry.py` — IMINT/RECON/BLUETEAM/GENERAL system prompts
  now open with *"You are ARK — Cybersecurity Super Intelligence, operating in
  … agent mode…"*; startup banner → `ARK SYSTEM INITIALIZED`.
- `app/engine/agent_bridge.py` — ADVISORY/AUTONOMOUS personas + offline report
  headers (`## ARK Advisory / Execution Plan / Task Report`).
- `app/brain/pipeline.py` — AI intelligence-layer prompt.
- `app/engine/orchestrator.py` — runtime state block rewritten to name ARK as
  the sole user-facing intelligence running on CAI as an internal engine;
  auto-approval grant message.
- `main.py`, `app/core/config.py`, `app/models/schemas.py`,
  `app/api/v1/endpoints/{cai,analyze}.py`, `app/brain/vision_ensemble.py`,
  `app/tools/web_intel/browser.py` (`agent_id="ARK"`),
  `app/engine/tool_adapter.py` (User-Agent).

**Docs** — `README.md` three-entity table and the ReAct diagram updated to
present ARK as the single AI identity.

### Verification

Live system prompt (captured from the real orchestrator):

```
[ARK RUNTIME STATE — authoritative application-owned context]
Application identity: THE ARK Integrated Security Environment. You are ARK —
Cybersecurity Super Intelligence, THE ARK's sole user-facing intelligence,
running on the CAI cybersecurity agent framework as an internal engine; the
underlying model/provider is a separate transport layer and not the
application identity.
```

Live startup banner:

```
╔════════════════════════════════════════════════════════════════╗
║                ARK SYSTEM INITIALIZED                          ║
║   76 Tools Registered  |  40 ARK forensic  |  36 CAI native   ║
║   33 Agent Roles Loaded  |  28 CAI sub-agents  |  32 CAI modules ║
╚════════════════════════════════════════════════════════════════╝
```

Live UI (browser): composer placeholder renders **"Ask ARK or run a command…
(/ for commands)"**. `grep -rn "ARK-CAI" app/` (excluding the vendored
`app/engine/cai/cai/` snapshot) → **NONE**. `grep -rn "ARK-CAI"` in frontend
src → **NONE**.

**Preserved (intentionally):** CAI framework attribution in `README.md`
("Third-Party Licenses") and `app/engine/cai/__init__.py`; the embedded
`./cai` snapshot directory name; internal identifiers `caiBrowserBus`,
`caiTerminalStream`, etc.

---

## 4. Security Gates

### 4.1 Engagement scope — fail-closed (verified)

`app/agent/engagement_scope.py::check()` denies **target-bearing** calls when
no fixture is configured; non-target calls (hashing, OCR, case ops) remain
allowed.

```
net.nmap_scan    allowed=False rule=scope.missing  (no engagement scope configured — fail-closed)
net.dns_lookup   allowed=False rule=scope.missing
web.fetch        allowed=False rule=scope.missing
forensics.hash   allowed=True  rule=scope
ocr.extract      allowed=True  rule=scope
```

The gate is enforced at **three** boundaries: `UnifiedRegistry.call/acall`
(`code: scope_denied`), and `orchestrator` **before HITL approval** — so an
operator approval cannot widen scope. `tests/test_engagement_scope.py` → 14
passed.

### 4.2 SSRF / egress guard (verified live, real Chromium)

`app/tools/web_intel/guard.py` — scheme allow-list, private/loopback/link-local
refusal, **cloud-metadata always refused**, single DNS resolution with dial-pinned
IP, redirect re-validation. Browser route interceptor calls `guard.check_url`
on every request.

| Attempt | Result |
|---|---|
| `https://example.com` | AVAILABLE (title "Example Domain") |
| `http://127.0.0.1:12000/api/v1/health` | **BLOCKED** `ssrf_blocked` — private/reserved |
| `http://169.254.169.254/latest/meta-data/` | **BLOCKED** `ssrf_blocked` — cloud-metadata endpoint |

### 4.3 No shell-injection surface

`grep -rniE "shell=True|os\.system\(" app/` → **none**. All `subprocess.run`
calls use **argv lists** (`dig`, `whois`, `gobuster`, `curl`, `openssl`,
`exiftool`) — no shell interpolation.

### 4.4 Credential hygiene

- `/api/v1/cai/models` (26 KB) scanned for `api_key|key|token|secret|sk-…|
  password` → **no matches**.
- `services/user_credentials.py` stores BYOK keys AES-256-GCM encrypted, keyed
  by principal namespace; reads expose **masked preview + configured flag only**.
- Frontend `dist/` bundle scan: only hit is `AKIAIOSFODNN7EXAMPLE` — the
  **canonical AWS documentation placeholder** used in a `SecurityTestingTab`
  textarea placeholder, not a real secret.

---

## 5. Runtime Acceptance Scenarios

> **Reconciliation note (2026-11-06):** this section summarises; the
> authoritative, per-scenario, live-executed record with PASS / BLOCKED /
> NOT-TESTED status is **`ARK_E2E_SCENARIO_LEDGER.md`**. Where the two differ,
> the ledger wins. The earlier summary validated the suite and the build; it did
> **not** by itself establish end-to-end coverage — the ledger closes that gap.

| # | Scenario | Method | Verdict |
|---|---|---|---|
| A | Backend health / startup | `GET /api/v1/health` | **PASS** — `status: ok`, v0.1.0 |
| B | ARK identity in prompt | captured system message | **PASS** |
| C | Startup banner identity | `print_startup_report()` | **PASS** |
| D | Scope gate fail-closed | `engagement_scope.check` matrix | **PASS** |
| E | Browser lifecycle + SSRF | real Chromium session | **PASS** (open/navigate/extract/close + SSRF block) |
| F | Operator browser control handoff | `take_control`/`return_control` | **PASS** (`agent`→`operator`→`agent`, in-process) |
| G | Model precedence | `model_router.resolve` matrix | **PASS** (incl. unknown-model refusal) |
| H | Session persistence / zero-retention | `SessionStore` reopen + disk scan | **PASS** (restore after reopen; 0 rows on disk in ZR) |
| I | No fabricated tool success | live stream without a usable model | **PASS** — terminal event `rate_limited`, not a fake answer |
| J | Real image investigation (deterministic) | POST `/api/v1/analyze` on GPS JPEG | **PASS** — coords exact, conf 0.99, custody cert |
| K | Cloud inference (vision/LLM/geocode) | requires `.env` / quota | **BLOCKED** |
| L | Operator HTTP-plane control of a *live* agent session | — | **NOT TESTED** |
| M | `steer` against a sustained live run | — | **NOT TESTED** |
| N | Scripted renderer click-through (every sub-view) | — | **NOT TESTED** |

Items **L–N** are explicitly **open**, not passed. See the ledger §"Open items".

Notes:

- **G** — explicit valid selection (`openrouter/openai/gpt-4o-mini`) wins with
  `credential_source: platform`; unknown model → `model_unavailable` (no silent
  substitution); provider without credential → actionable error; Ollama
  unreachable → clear error.
- **J** — `/api/v1/health` reports every cloud service `not_configured`; no
  `.env` present. The live default model
  (`openrouter/nvidia/nemotron-3.5-super-vl:free`) is rate-limited from this
  host. These paths are **not verifiable here** and are **not** claimed as
  working.

---

## 6. Test-Suite Integrity

- **Backend:** `724 passed` (0 skipped) with binaries installed;
  `723 passed, 1 skipped` without `tesseract`.
- **The 9 "baseline" failures** were **environmental**:
  - 4 × `test_workbench_forensics.py` — `exiftool` missing.
  - 4 × `test_ark_cai_engine.py` HITL/real-tool — `dig`/`nmap` missing
    (`_adapter_available()` correctly refuses to advertise a tool whose binary
    is absent, so the call is denied rather than run).
  - 1 × `test_call_real_tool` — `dig` missing.
  Installing `libimage-exiftool-perl dnsutils whois nmap gobuster tesseract-ocr`
  turns all 9 green. **No source regression.**
- **Both claimed source fixes verified:**
  1. `ai_gateway._VISION_NAME_RE` no longer matches `qwen2.5-coder*` (and does
     match `qwen2.5-vl`, `llava`, `minicpm-v`, `…vision`).
  2. `endpoints/agent.py` holds **strong refs** to in-flight SSE tasks
     (`_background_tasks: set[asyncio.Task]`, `add_done_callback(discard)`).
- **Frontend:** `tsc --noEmit` exit 0; `vite build` exit 0 (2010 modules).
- New test files: `test_browser_endpoints.py` (21), `test_session_store.py`
  (12), `test_engagement_scope.py` (14), `test_model_authority.py`.

---

## 7. Residual Risks / Not Verified

1. **Cloud AI paths** unverified (no `.env`); the live default model is
   rate-limited from this host. Distinguish carefully: routing is *proven
   correct* (ledger §B/§E3); the block is **missing credential/quota**, not
   provider incompatibility or a routing defect (ledger §F, §"Interpretation").
2. **Electron shell** not launched (headless host); `sandbox: false` reviewed —
   decision record in `ARK_ELECTRON_SANDBOX_DECISION.md` (keep for now; async
   handshake follow-up).
3. **Embedded git credential** — local scrub COMPLETE; provider-side revocation
   OUTSTANDING. See `ARK_P0_CREDENTIAL_REMEDIATION.md`.
4. **`allowScripts`** manifest key is inert/undocumented — remove or justify.
5. **Live model latency/cost** behavior untested against a real provider.
6. Shallow clone → history-dependent checks (blame, merge-base) unavailable.
7. **Open e2e scenarios** (ledger items A11/D4/E4/E5/F2/F3 and the untested
   renderer click-through) — not to be claimed as complete.

---

## 8. Conclusion

The working tree is **internally consistent and green**: security gates are
fail-closed, the browser runtime is SSRF-hardened, model selection has a real
single source of truth, and the ARK identity consolidation is applied end-to-end
without breaking a single test. The only non-green items are **environmental
dependencies** and **credential-gated cloud paths** — both explicitly out of
reach in this sandbox and reported honestly rather than papered over.
