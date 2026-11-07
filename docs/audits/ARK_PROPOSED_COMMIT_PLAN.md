# THE ARK — Proposed Commit Plan

**Status: NOT EXECUTED.** No commit was made. This is a reviewable proposal for
how to split the current dirty working tree into reviewable commits on `main`.

Working tree at time of writing: **43 modified, 23 untracked, 2 deleted**;
branch `main`, HEAD `c8e215c6`, shallow clone.

---

## Principles

1. One logical change per commit; every commit **builds and tests green**.
2. Security-relevant changes (scope gate, egress guard) are isolated so they
   can be reviewed and reverted independently.
3. Generated/incidental churn (lockfile) is separated from source.
4. The credential in `origin` is **not** touched by any commit; it is fixed
   operationally (see below).

---

## Pre-commit (operational, not a git commit)

```bash
# 1. Scrub the embedded credential from the remote (rotate the token first).
git remote set-url origin https://github.com/UncleT-cyber/Ark-Geo.git
```

---

## Proposed commits (in order)

### 1. `security(scope): fail-closed engagement-scope enforcement for target-bearing tools`
- `arkgeo-backend/app/agent/engagement_scope.py` (new)
- `arkgeo-backend/app/agent/unified_registry.py` (scope check in `call`/`acall`)
- `arkgeo-backend/app/engine/orchestrator.py` (pre-HITL scope gate — *scope
  hunk only*)
- `arkgeo-backend/tests/test_engagement_scope.py`
- *Why first:* the highest-risk change; the orchestrator scope hunk is small
  and reviewable on its own.

### 2. `security(browser): SSRF-hardened managed browser runtime + operator transport`
- `arkgeo-backend/app/tools/web_intel/` (new: `guard.py`, `browser.py`,
  `fetcher.py`, `tools.py`, `__init__.py`)
- `arkgeo-backend/app/api/v1/endpoints/browser.py` (new)
- `arkgeo-backend/app/api/v1/router.py` (browser router registration hunk)
- `arkgeo-backend/tests/test_browser_endpoints.py`
- `arkgeo-investigator-web/src/components/workbench/BrowserView.tsx` (new)
- `arkgeo-investigator-web/src/components/workbench/caiBrowserBus.tsx` (new)

### 3. `feat(models): per-principal model selection, BYOK, entitlements`
- `app/models/model_registry.py`, `app/services/entitlements.py`,
  `app/services/model_router.py`, `app/services/principal.py`,
  `app/services/user_credentials.py`, `app/services/user_preferences.py` (new)
- `app/api/v1/endpoints/user_models.py` (new)
- `app/api/v1/endpoints/cai.py` (model endpoints hunk)
- `tests/test_model_authority.py`
- `arkgeo-investigator-web/src/components/settings/ProvidersPanel.tsx` (new)

### 4. `feat(sessions): durable encrypted investigation-session store`
- `app/services/session_store.py` (new)
- `app/api/v1/endpoints/cai.py` (`/cai/sessions*` hunk)
- `tests/test_session_store.py`
- `arkgeo-investigator-web/src/core/notifications.ts`,
  `src/core/desktop.ts` (new), `src/components/workbench/InvestigationTabs.tsx`
  (new), `UseCasesView.tsx` (new)

### 5. `refactor(identity): single user-facing identity — ARK, Cybersecurity Super Intelligence`
- **Backend:** `app/engine/cai/registry.py`, `app/engine/agent_bridge.py`,
  `app/brain/pipeline.py`, `app/brain/vision_ensemble.py`,
  `app/engine/orchestrator.py` (runtime-state hunk), `app/core/config.py`,
  `app/models/schemas.py`, `app/api/v1/endpoints/{cai,analyze}.py`,
  `app/engine/tool_adapter.py`, `main.py`
- **Frontend:** `ArkControl.tsx`, `Workbench.tsx`, `BrowserView.tsx`,
  `useImageReview.ts`, `types.ts`, `api.ts`, `caiBrowserBus.tsx`,
  `ark-control.css`
- `README.md`, `AGENTS.md` (identity + testing notes)
- *Note:* split the `orchestrator.py` scope hunk (commit 1) from the
  identity hunk (this commit) with `git add -p`.

### 6. `feat(workbench): investigation tabs, sidebar hierarchy, dock header layout, browser dock`
- `Workbench.tsx`, `ArkControl.tsx`, `InvestigationNavigation.tsx`,
  `TopBar.tsx`, `CommandPalette.tsx`, `BottomPanel.tsx`,
  `useInvestigation.tsx`, `entities.ts`, `icons.ts`, `workspace.css`,
  `ark-control.css`, `workbench.css`, `main.tsx`, `vite.config.ts`
- Deleted: `workbench/InvestigatorProfileModal.tsx`,
  `workbench/SettingsModal.tsx`
- `components/settings/ClientSettingsModal.tsx`
- *Note:* this is the largest UI commit; if desired, split into
  "navigation/tabs" and "dock layout" commits.

### 7. `chore(deps): realign web lockfile; desktop owns electron toolchain`
- `arkgeo-investigator-web/package-lock.json`, `package.json`
- `arkgeo-desktop/{main.js,preload.js,package.json,package-lock.json}`
- `launch.sh`
- *Why separate:* pure dependency/packaging churn; must not hide source diffs.

### 8. `test(agent): engine streaming/dispatch regression coverage`
- `tests/test_agent_streaming.py`, `tests/test_cai_dispatch_sot.py`,
  `tests/test_cognitive_contracts.py`, `tests/test_identity_contract.py`,
  `tests/test_model_catalog.py`, `tests/test_osint_tools.py`,
  `tests/test_ark_cai_engine.py`, `tests/test_ai_gateway.py`,
  `app/api/v1/endpoints/agent.py` (strong-ref fix),
  `app/services/ai_gateway.py` (vision-regex fix)

### 9. `docs(audit): integration audit, readiness matrix, commit plan`
- `docs/audits/ARK_FINAL_INTEGRATION_AUDIT.md`
- `docs/audits/ARK_RELEASE_READINESS_MATRIX.md`
- `docs/audits/ARK_PROPOSED_COMMIT_PLAN.md`
- `docs/audits/ARK_E2E_SCENARIO_LEDGER.md` (live-executed scenario status)
- `docs/audits/ARK_P0_CREDENTIAL_REMEDIATION.md` (credential: no token material)
- `docs/audits/ARK_ELECTRON_SANDBOX_DECISION.md` (sandbox decision record)

### Gate (advisor directive)
No commit/push until (a) the credential is **revoked at the provider**, and
(b) the advisor grants commit authorization. Commits 1–9 above remain a
*proposal*; the working tree is intentionally left dirty.

---

## Files that need `git add -p` (mixed hunks)

| File | Hunks |
|---|---|
| `app/engine/orchestrator.py` | scope gate (commit 1) vs identity (commit 5) |
| `app/api/v1/endpoints/cai.py` | models (commit 3) vs sessions (commit 4) vs identity (commit 5) |
| `app/api/v1/router.py` | browser router (commit 2) vs others |

---

## Verification gate before each push

```bash
cd arkgeo-backend && OPENAI_API_KEY=x CAI_LICENSE_OFF=true .venv-new/bin/python -m pytest tests/ -q
cd ../arkgeo-investigator-web && npx tsc --noEmit && npx vite build
```

Expected: `724 passed`, tsc exit 0, build exit 0.

---

## Explicitly NOT in this plan

- Rotating the exposed git credential — **operational**, do it manually.
- Committing `arkgeo_data/` or `.env` — gitignored runtime evidence.
- Any change to the vendored `app/engine/cai/cai/` snapshot.
