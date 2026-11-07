# THE ARK — CAI Agentic Browser & Web Intelligence
## Phase 0 — Capability Audit

**Date:** 2026-11-06
**Scope:** Audit existing web-research, HTTP-retrieval, browser-automation,
authorization, evidence, and operator-surface capabilities before any code is
written. Classifies every relevant capability as **implemented**, **registered**,
**bound**, **executable**, and **verified**.

---

## 1. Executive summary

THE ARK already contains a **substantial, security-conscious web-retrieval
substrate** — most of it inherited from the embedded CAI toolkit. The single
biggest finding is that **almost none of it is actually executable today**,
because the CAI-native tool tier fails to import at runtime.

| Layer | State | Notes |
|---|---|---|
| Web **search** (Tavily + keyless DuckDuckGo) | implemented, registered, bound, **executable** | `web_search` / `recon.web_search` |
| Web **fetch** (static HTTP, markdown extraction) | implemented, registered, bound, **executable** | `web_fetch` / `recon.web_fetch` — but **no SSRF guard, no redirect chain, no size/time caps** |
| Web **fetch** (hardened: SSRF + DNS-rebind + redirect re-validation + PDF) | implemented **but NOT registered / NOT executable** | CAI `fetch_url` — blocked by a package-resolution defect |
| Web **extract / links / document** | **not implemented as first-class catalogue tools** | partially inside `fetch_url`; no `web.extract`, `web.links`, `web.document` |
| **Browser automation** (Playwright/Chromium) | **not implemented** | no Playwright/Selenium/puppeteer anywhere; Chromium binary present on host |
| **Authorization boundary** | implemented, executable | `PolicyGuard` + `engagement_scope` + risk→approval tiers |
| **Evidence recording** | implemented, executable | `engine/evidence_recorder.py` (JSONL + redaction) + `evidence_graph` (hash-validated) |
| **Operator browser view** | **not implemented** | no iframe/webview/BrowserView anywhere in web or Electron |

**Root-cause defect (blocking the whole web tier):** `arkgeo-backend/cai` is a
**git submodule gitlink that was never initialised** — it exists on disk as an
**empty directory** (`git ls-tree` mode `160000`). Because `app/engine/cai/__init__.py`
inserts `<backend>/cai/src` onto `sys.path` *first*, and `<backend>/cai/src` does
not exist while `<backend>/cai` **does**, Python's namespace-package machinery
binds the top-level `cai` name to the **empty** `<backend>/cai` directory. The
embedded, complete CAI source at `app/engine/cai/cai/` is therefore shadowed and
`import cai.tools` raises `ModuleNotFoundError`. Result: the entire CAI-native
tool tier (**~0 tools**; the toolkit normally contributes ~100) silently fails to
register. `unified_registry.populate()` currently yields **83 tools**
(43 ARK substrate + 40 ARK catalogue) instead of the intended full catalogue.

---

## 2. Dependency inventory

| Dependency | Declared in `requirements.txt` | Installed in `.venv-new` (Py 3.13) | Verdict |
|---|---|---|---|
| `httpx` | yes | yes | working — static HTTP |
| `playwright` | **no** | **installed this session** | available; system Chromium 155 works headless |
| `trafilatura` | **no** | **installed this session** | readable-content extraction |
| `pypdf` | **no** | **installed this session** | PDF text extraction |
| `curl_cffi` | **no** | **installed this session** | Chrome-TLS anti-bot fallback |
| `selenium` / `pyppeteer` | no | no | not present (not needed) |
| `requests` | yes (via CAI) | yes | used by some CAI web tools |

**Host browser runtime:** `/usr/bin/chromium` — Chromium **155.0.8059.79**
(Debian 13). Verified: Playwright launches it headless with
`--no-sandbox --disable-dev-shm-usage` and renders content. Docker 29.9.2 is
present (usable for the Phase 7 fixture pages).

**Node side:** no `playwright`/`puppeteer` in `arkgeo-investigator-web/package.json`
or `arkgeo-desktop/package.json`. The Electron shell uses `BrowserWindow` only —
no `BrowserView`/`WebContentsView`, no `webview` tag, no `partition` isolation.

---

## 3. Capability matrix

Legend — **I**mplemented · **R**egistered · **B**ound (dispatch wired) ·
**E**xecutable (runs today) · **V**erified (tested live).

| Capability | ID | I | R | B | E | V | Location |
|---|---|:-:|:-:|:-:|:-:|:-:|---|
| Web search | `web_search` | ✅ | ✅ | ✅ | ✅ | ✅ | `app/tools/web_search_tool.py` |
| Web fetch (basic) | `web_fetch` | ✅ | ✅ | ✅ | ✅ | ✅ | `app/tools/web_search_tool.py` |
| Web search (catalogue) | `recon.web_search` | ✅ | ✅ | ✅ | ✅ | ⬜ | `app/engine/tool_adapter.py:479` |
| Web fetch (catalogue) | `recon.web_fetch` | ✅ | ✅ | ✅ | ✅ | ⬜ | `app/engine/tool_adapter.py:479` |
| HTTP probe | `net.curl_probe` | ✅ | ✅ | ✅ | ✅ | ⬜ | `app/engine/tool_adapter.py` |
| URL extraction (from text) | `imint.extract_urls` | ✅ | ✅ | ✅ | ✅ | ⬜ | `app/engine/tool_adapter.py` |
| **Hardened fetch (SSRF/DNS-rebind/redirect/PDF)** | `fetch_url` | ✅ | ❌ | ❌ | ❌ | ❌ | `app/engine/cai/cai/tools/web/fetch_url.py` |
| CAI `web_request_framework` | `web_request_framework` | ✅ | ❌ | ❌ | ❌ | ❌ | `app/engine/cai/cai/tools/web/headers.py` |
| CAI `google_search` / `google_dork_search` | — | ✅ | ❌ | ❌ | ❌ | ❌ | `app/engine/cai/cai/tools/web/google_search.py` |
| `web.extract` (readable content + metadata) | — | ❌ | ❌ | ❌ | ❌ | ❌ | **missing** |
| `web.links` (hyperlink enumeration) | — | ❌ | ❌ | ❌ | ❌ | ❌ | **missing** |
| `web.document` (PDF/office retrieval) | — | ⚠️ partial | ❌ | ❌ | ❌ | ❌ | inside `fetch_url._extract_pdf` only |
| `browser.*` (managed runtime) | — | ❌ | ❌ | ❌ | ❌ | ❌ | **missing** |
| Operator browser view | — | ❌ | ❌ | ❌ | ❌ | ❌ | **missing** |

**Net executable web surface today:** `web_search`, `web_fetch`, `recon.*`,
`net.curl_probe`, `imint.extract_urls` — all **unhardened static HTTP**.

---

## 4. Architecture trace

### 4.1 Tool registry (single source of truth)
`app/agent/unified_registry.py` — `unified_registry.populate()` merges **three**
sources and dedups by normalized id (first wins):

1. **ARK substrate** — `app/agent/tool_registry.py` (`registry._tools`), 43 tools.
2. **ARK catalogue** — `app/engine/tool_adapter.py` `_CATALOGUE`, 40 tools.
3. **CAI native** — `app/engine/cai/tools_importer.py` → `cai.tool_registry.TOOL_REGISTRY`, **currently 0** (import defect).

Dispatch: `unified_registry.call(id, **kw)` (sync) / `.acall(id, **kw)` (async-aware).
Schemas for the model: `.openai_tools()` / `.provider_tools(selected)`.

### 4.2 Two execution engines (both real, both dispatch through the same registry)
- **Agent orchestrator** (`app/agent/orchestrator.py`, `executor.py`) — plan-based
  investigation loop. `executor.PlanExecutor.execute` does: policy evaluate →
  step-confirm check → arg resolution → memoization → `registry.acall` →
  evidence node + `audit_tool_call`.
- **CAI engine** (`app/engine/orchestrator.py`) — the live ARK-CAI ReAct loop
  behind `POST /api/v1/cai/stream`. Per tool call it does: registry lookup →
  policy evaluate → `engagement_scope.check` → HITL approval (risk-gated) →
  `unified_registry.acall` → `EvidenceRecorder` events + Event Bus publish.

### 4.3 Authorization boundary (already strong — reuse, do not duplicate)
- `app/agent/policy_guard.py` — `PolicyGuard.evaluate(tool_id)` → `PolicyDecision`
  (allowed / approval_tier / reason / rule_id). Risk→tier: low=auto,
  medium/elevated=confirm_once, high=step_confirm. Capability permissions incl.
  parameterized `call:provider:<name>`. Budget enforcement (steps/tokens/ms/api_calls).
- `app/agent/engagement_scope.py` — **target layer**. Every target-bearing call
  (host/url/ip/domain/cidr…) must match the active engagement fixture. Fail-closed
  when a fixture is present-but-broken; no operator approval can widen scope.
- `app/agent/schemas.py` — `RiskLevel`, `ToolCategory`, `Permission`,
  `ApprovalTier`, `ToolSpec`, `Availability`, `CostEstimate`.

### 4.4 Evidence recording (already strong — reuse)
- `app/engine/evidence_recorder.py` — per-run JSONL in
  `arkgeo_data/a2_evidence/`, redaction of secrets, events:
  `tool_started/completed/failed`, `scope_checked`, `approval_required`,
  `result_verified`, `agent_selected`, `run_completed/failed`.
- `app/agent/evidence_graph.py` — hash-validated, tamper-evident evidence nodes
  + `audit_tool_call` (tier-0 cryptographic audit node with `arguments_hash`).
- `app/core/security.py` — `custody_certificate` / `custody_hash` (SHA-256).
- Zero-Retention: `session.objective.constraints.zero_retention` drops evidence
  post-use (`app/agent/orchestrator.py:257`); session store keeps metadata only.

### 4.5 Operator surface
- Web workbench: `Workbench.tsx` → TopBar + `InvestigationNavigation` (sidebar) +
  MainViewport + ARK-CAI dock + StatusBar. Sub-views are React components under
  `components/workbench/tools/`. **No** iframe/webview. Tabs via
  `core/tabs/tabRegistry.ts` + `useInvestigationTabs.ts`.
- Electron: `arkgeo-desktop/main.js` — `BrowserWindow` + `setWindowOpenHandler`
  only. No `BrowserView`/`WebContentsView`, no session `partition`.

### 4.6 CAI integration seams (for Phase 4)
`_select_provider_tools(domains, guard, prompt)` filters the registry by task
domain **and** `guard.evaluate(...).allowed` — a new tool bound to the right
domain is automatically exposed to the model and automatically gated by policy.
`_dispatch_tool` is the single execution choke point.

---

## 5. Root-cause defect — CAI package shadowing

```
app/engine/cai/__init__.py:
    _ORIGINAL_CAI_SRC = <backend>/cai/src      # does NOT exist (submodule uninitialised)
    _EMBEDDED_CAI     = <here>/cai             # COMPLETE CAI source, exists
    for _p in (_ORIGINAL_CAI_SRC, _EMBEDDED_CAI):
        if os.path.isdir(os.path.join(_p, "cai")) and _p not in sys.path:
            sys.path.insert(0, _p)             # inserts BOTH
```

`os.path.isdir(<backend>/cai/src/cai)` → **False**, so `_ORIGINAL_CAI_SRC` is
**not** inserted — good. But `<backend>/cai` (the empty submodule dir) is on
`sys.path` because the backend runs with CWD = `arkgeo-backend/` (and, in the
Electron/dev launch, the backend root is also importable). Python then treats
the **empty** `<backend>/cai` as a **namespace package**, which takes precedence
over the regular package inserted later. `cai.__path__` resolves to
`<backend>/cai` (empty) → `import cai.tools` fails.

Reproduced: `.venv-new/bin/python` with CWD `arkgeo-backend/` →
`cai.__path__ == ['<backend>/cai', '<backend>/cai']`, `import cai.tools` →
`ModuleNotFoundError`.

**Impact:** CAI-native web tools (`fetch_url`, `web_request_framework`,
`google_search`, …) plus every other CAI tool are unregistered → the model cannot
see or call them. Any browser runtime built as a CAI-native tool would inherit
this defect.

**Fix direction (Phase 2):** register the web/browser tools as **first-class ARK
substrate tools** in `app/agent/tool_registry.py` (source `ark_substrate`), which
is immune to this defect, and separately harden the CAI package-path resolution so
the CAI-native tier stops being silently dropped.

---

## 6. Security posture of the existing web tier

**Good, reusable controls:**
- CAI `fetch_url` has a genuinely strong SSRF guard: scheme allow-list; blocks
  private/loopback/link-local/multicast/reserved/unspecified; **always** blocks
  cloud-metadata hosts/IPs (AWS/GCP/Azure/Alibaba IMDS); **DNS resolved exactly
  once and the IP pinned** (DNS-rebinding mitigation); redirects followed
  **manually** with every hop re-validated; `sanitize_external_content` wraps
  remote content to defang prompt injection. ← **the model to reuse for Phase 1/3.**
- `engagement_scope` denies out-of-scope targets **before** approval/dispatch.
- Evidence redaction patterns already strip passwords/secrets.

**Gaps to close:**
- The **executable** `web_fetch`/`web_search` (`app/tools/web_search_tool.py`)
  have **no SSRF guard** — they will fetch `http://127.0.0.1`, `169.254.169.254`,
  RFC1918, etc. This is the most important security finding.
- No egress allow/deny policy, no per-tool byte/time caps on the executable path
  (only inside the unreachable `fetch_url`).
- No browser sandbox/profile isolation (nothing exists yet).
- No download isolation / file-system confinement for web content.

---

## 7. What Phase 1–7 must therefore do

1. **Repair** the CAI package-path defect so the native tier registers.
2. **Promote** the hardened fetch into first-class ARK tools and **add the
   SSRF/DNS-rebind/redirect guard to the executable path** (`web_fetch`).
3. **Add** `web.extract`, `web.links`, `web.document` as structured catalogue tools.
4. **Build** the managed Playwright/Chromium runtime (`browser.*`) as ARK
   substrate tools with session lifecycle + resource limits + isolated profiles.
5. **Wire** everything through the existing `PolicyGuard` + `engagement_scope` +
   `EvidenceRecorder` choke points (no second framework).
6. **Add** the operator browser view (screenshot-first transport, no arbitrary
   cross-origin iframe) to the existing workbench, opened on demand by CAI.
7. **Prove** it with real Chromium, screenshots, traces and evidence IDs.

**Reuse decisions:** the existing `PolicyGuard`, `engagement_scope`,
`EvidenceRecorder`, `evidence_graph`, `custody` hashing, and the CAI `fetch_url`
SSRF design are the correct primitives — the work is *binding and hardening*, not
re-architecting. No second orchestration framework will be introduced.
