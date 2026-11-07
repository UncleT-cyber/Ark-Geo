# ARK — P0 Investigation Tab Isolation & Workspace Routing

**Date:** 2026-11-05
**Priority:** P0 — functional correctness
**Component:** `arkgeo-investigator-web` (workbench) + `arkgeo-backend` (session plane)

---

## 1. Root-cause report — why tabs changed the highlight but not the context

The tab strip was *real*: `useInvestigationTabs` owns a durable, merge-safe
registry of `InvestigationTab` descriptors (`id`, `title`, `domain`, `caseId`,
`runStatus`). Clicking a tab updated `activeId` and the highlight moved.

But **every piece of investigation state that the UI renders was held in
singletons that were never keyed by the active investigation**:

| State | Owner | Keyed by tab? |
| --- | --- | --- |
| Conversation `messages` | `ArkControl.tsx` `useState` | **No** |
| Execution timeline / run id / tool | `ArkControl.tsx` `useState` | **No** |
| Backend CAI `session` handle | `ArkControl.tsx` `useRef` | **No** |
| Queue / steerings / draft | `ArkControl.tsx` `useState` | **No** |
| Inspector tool, bottom tab | `ArkControl.tsx` / `useInvestigation` | **No** |
| Case / evidence / run / findings / audit | `useInvestigation.tsx` (one context) | **No** |
| `result`, `pipeline`, `terminal`, `session` | `useInvestigation.tsx` | **No** |
| `domain`, `activeSubview`, `networkTab` | `Workbench.tsx` `useState` | **No** |
| `workspaceTool` (Browser) | `Workbench.tsx` `useState` | **No** |

`ArkControl` is mounted **once** inside `WorkbenchInner` and is never remounted
per tab, and `InvestigationProvider` wraps the whole workbench as a **single
context instance**. So switching tabs could not change any of the above: there
was only ever one conversation, one execution timeline, one case, one workspace
selection.

The tab-activation effect in `Workbench.tsx` was also **one-way and lossy**: it
copied `tab.domain` into the singleton `inv.setDomain(...)` and restored a case
snapshot, but it never captured the outgoing investigation's workspace/domain,
and it never restored the incoming investigation's sub-view. There was no
`activeInvestigationId → investigationState` edge anywhere.

Finally, `+` called `inv.clear()` on the **global** singleton, so "new
investigation" wiped the one shared context rather than opening an independent
one — the previous tab had no private copy to restore. And because a fresh tab
was created with `domain: 'image'` and IMAGE-with-no-result renders
`DashboardView`, **every** new tab landed on Image Intelligence's System
Overview, which was being used as ARK's de-facto home page.

**Conclusion:** the defects are state-ownership defects, not presentation
defects. Fixing them with active-tab CSS is impossible; the conversation, the
execution timeline, the case context and the workspace selection all had to be
re-owned under an investigation key.

---

## 2. Required model (implemented)

```
tabId            → visual tab (registry descriptor, merge-safe, durable)
investigationId  → identity of the investigation (== tab id today)
conversationId   → identity of the investigation's conversation
sessionId        → backend durable session (assigned when a run starts)
caseId           → case/evidence record, when one exists
runId            → a particular backend execution
workspaceId      → active workspace selection for that investigation
```

A tab **points to** an investigation context; the context owns its conversation,
execution history, workspace selection and case data. Two tabs never share
mutable investigation state.

### Ownership after the change

- `src/core/investigation/investigationStore.ts` — the investigation-keyed
  state model + durable metadata persistence (no conversation content, no
  evidence: those stay in the backend's encrypted session store).
- `src/core/investigation/InvestigationStoreContext.tsx` — React provider and
  `useInvestigationStore()` hook exposing
  `activeId` / `metaFor(id)` / `ensure(id)` / `patchMeta(id, …)` /
  `patchWorkspace(id, …)` / `setRunStatus(id, …)` / `drop(id)` /
  `getSlice(id, key)` / `setSlice(id, key, …)`. Also exports
  `useInvestigationSlice(key, initial)` — a `useState`-compatible primitive whose
  value is keyed by the active investigation and swaps on switch without
  unmounting the caller (used for the workbench's per-investigation evidence
  state: `thumbnailUrl`, `analyzing`, `zeroRetention`).
- `InvestigationProvider` becomes an **investigation-keyed multiplexer**: it
  holds `Record<investigationId, InvestigationContext>` and exposes the *active*
  investigation's slice through the existing `InvestigationContextValue`
  interface, so every existing consumer keeps working unchanged.
- `ArkControl` reads/writes its conversation + execution slices through the
  store keyed by `activeInvestigationId`, so switching tabs swaps the
  conversation without unmounting (backend execution is unaffected by mount
  state).

### Workspace ownership

- Each investigation stores its own workspace selection
  (`domain`, `imageSubview`, `networkTab`, `workspaceTool`).
- A **new** investigation opens a neutral investigation workspace — the ARK
  conversation plus a lightweight workspace-selection empty state — **not** the
  Image Intelligence System Overview. Selecting Image Intelligence then shows
  its own System Overview, scoped to that investigation.

### New investigation (`+`)

Creates a unique investigation identity + conversation id, a fresh workspace
selection, makes the new tab active and renders it immediately with ARK's clean
welcome state, an empty execution timeline and empty evidence/findings views. It
does **not** create a forensic case record until the operator starts an
investigation or explicitly saves one. Global preferences (model, theme,
provider config) are still inherited from their own settings scope.

### Persistence

| Layer | Durable? | Holds |
| --- | --- | --- |
| Backend `session_store` (SQLite, AES-256-GCM) | Yes | transcript, runs, evidence *references*; zero-retention stores no content |
| Tab registry (`ark.investigationTabs`, localStorage) | Yes | tab descriptors |
| Investigation metadata (`ark.investigations`, localStorage) | Yes | id/title/conversationId/sessionId/caseId/workspace selection/zeroRetention — **no** content |
| In-memory investigation store | No (session) | live conversation, execution, case context |

On reload, tabs and workspace selection restore from localStorage; for a tab
with a bound `sessionId` the transcript is rehydrated from the backend encrypted
session. A run left `running` by a dead process is reported `interrupted`, never
resumed.

### Security boundary (Scenario F)

`GET /cai/sessions/{id}` and `DELETE /cai/sessions/{id}` previously returned any
session to any caller. They now resolve the request principal and refuse a
session owned by a different principal (`404`, indistinguishable from unknown).
`GET /cai/sessions` (the list) is likewise scoped to the caller's principal, so
one operator's session *identifiers* never appear in another's list. The
anonymous principal owns exactly the rows recorded without a subject or stamped
with the literal `ANONYMOUS.subject` ("anonymous") — nothing else. Frontend
filtering is not relied on.

---

## 3. Acceptance scenarios

See `docs/audits/ARK_E2E_SCENARIO_LEDGER.md` for the executed ledger. Status
vocabulary: **PASS** / **BLOCKED** / **NOT TESTED** / **HARNESS ERR**.

<!-- RESULTS PLACEHOLDER -->
