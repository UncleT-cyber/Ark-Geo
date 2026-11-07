# ARK — User Settings Full-Page Refactor

**Directive:** "THE ARK — User Settings Full-Page Refactor" (P1 UI/UX). Refactor
the existing Client Settings interface — currently a floating modal, now
**deprecated** — into a dedicated **full-page Settings workspace** following THE
ARK's current OLED-black design system. **Layout/styling refactor only; do not
rewrite settings functionality.** Prefixed "before we commit:" → this gates the
pending commit.

**Status:** IMPLEMENTED — layout verified at five viewports, functional
regression suite green, frontend type-check + production build clean.

## What changed

| Area | Before | After |
| --- | --- | --- |
| Surface | Floating modal overlay (`.ark-settings-overlay` → `.ark-settings-modal`) | Full-page application tab (`.settings-workspace`) |
| Entry | ActivityBar footer gear → `setShowSettings(true)` | Sidebar **Settings** item and CommandPalette → `openSettings()` opens/reuses one `settings`-domain tab |
| Navigation | In-modal tab strip | Persistent left rail (236 px, 60 px rail < 900 px) |
| Theme | Cyan-glow modal tokens (`#090D11`) | OLED-black tokens re-declared on `.settings-workspace` (`#050505` / `#0D0D0D`), cyan used sparingly |
| Chrome | Sidebar + viewport + dock + StatusBar visible behind overlay | Investigation chrome hidden; Settings fills the body; TopBar tab strip stays |

### Files

- **New** `src/components/settings/SettingsWorkspace.tsx` — full-page shell; renders the *unchanged* panels (`ByokPanel`, `ProvidersPanel`, `SystemHealthPanel`, `ClientModelConfigPanel`, `ClientVaultManager`, `NotificationsPanel`, `SupportPanel`).
- **New** `src/components/settings/settings-workspace.css` — OLED-black tokens + two-column layout; re-declares `--cs-*` so the reused panels need no markup change.
- **Deleted** `src/components/settings/ClientSettingsModal.tsx` — the deprecated floating overlay.
- `src/components/workbench/Workbench.tsx` — replaced `showSettings` with `settingsSection`; added `openSettings()`; the `workbench-body` renders `<SettingsWorkspace>` when the active tab's domain is `settings`; tab-activation effect switches the domain; Escape handler no longer references the modal overlay.
- `src/components/workbench/entities.ts` — `DomainId` gains `'settings'`.
- `src/core/tabs/tabRegistry.ts` — `InvestigationTab.domain` gains `'settings'`; added the `deleted` tombstone flag, `loadAllTabs()`, and tombstone defaults in `makeTab`.
- `src/core/tabs/useInvestigationTabs.ts` — close is now a **tombstone** (bumped `rev`, pruned after 24 h) so the union merge propagates the removal instead of resurrecting the closed tab; UI list filters `deleted`.
- `src/client-settings.css` — removed the dead modal shell (`.ark-settings`, overlay/header/tabs/plan-badge/close); retained the reusable panel styles.
- `src/components/settings/ByokPanel.tsx` — strengthened the storage honesty note (obfuscated, not encrypted; per-device; never server-side).

## Behaviour preserved (no functional rewrite)

BYOK save/test/clear + per-provider override, provider & connection status,
ExifTool pathing, model/privacy selection, saved-case vault restore,
notifications, support links, and the admin "protected control plane" boundary
all behave exactly as before — they are the same components.

## Verification

### Layout (Chromium, computed styles)

| Viewport | bg | nav bg | nav width | modal/overlay | sidebar | dock | statusbar | overflow-x |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1440×900 | `rgb(5,5,5)` | `rgb(13,13,13)` | 236 | absent | hidden | hidden | hidden | none |
| 1280×800 | `rgb(5,5,5)` | `rgb(13,13,13)` | 236 | absent | hidden | hidden | hidden | none |
| 1024×768 | `rgb(5,5,5)` | `rgb(13,13,13)` | 236 | absent | hidden | hidden | hidden | none |
| 900×700 | `rgb(5,5,5)` | `rgb(13,13,13)` | 60 (rail) | absent | hidden | hidden | hidden | none |
| 720×600 | `rgb(5,5,5)` | `rgb(13,13,13)` | 60 (rail) | absent | hidden | hidden | hidden | none |

Screenshots: `docs/audits/screenshots/settings-before-modal.png` (before) and
`settings-after-{1440x900,1280x800,1024x768,narrow-900,narrow-720}.png` (after).

### Functional regression

| # | Scenario | Result |
| --- | --- | --- |
| R1 | Open Settings from main navigation | PASS — workspace visible, single `Settings` tab |
| R2 | Open repeatedly | PASS — exactly 1 `Settings` tab (no duplicates) |
| R3 | Switch sections | PASS — Model & Privacy / System Health / Support & Open Source headers update |
| R4 | BYOK save + test + clear | PASS — no plaintext in storage; obfuscated entry written; Test → `UNREACHABLE` (expected, no real key); clear removes it |
| R5 | Close the Settings tab | PASS — tab gone, returns to the landing dashboard |
| R6 | Refresh while Settings active | PASS — Settings tab restored |
| R7 | Switch between Settings and an investigation tab | PASS — investigation sidebar + viewport return |

### Build

- `npx tsc --noEmit` → exit 0
- `npx vite build` → built (same pre-existing >500 kB chunk advisory)

## Known residuals

- The `settings` tab title is static ("Settings"); section state is in-memory and
  resets to **API Keys** on reload. Acceptable for a layout refactor.
- BYOK storage remains obfuscation, not encryption — unchanged from before; the
  in-panel note now states this explicitly. See the outstanding provider-side
  token revocation in the release-readiness docs.
