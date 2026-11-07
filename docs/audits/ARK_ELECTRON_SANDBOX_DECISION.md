# ARK — Electron Renderer Sandbox Decision Record

**Status:** REVIEWED — no code change made (deliberate; see §5)
**Date:** 2026-11-06
**Component:** `arkgeo-desktop` (Electron 32 shell)

## 1. Current configuration

`main.js` creates the window with:

```js
webPreferences: {
  preload: path.join(__dirname, 'preload.js'),
  nodeIntegration: false,     // renderer has no Node
  contextIsolation: true,     // preload/renderer worlds are separated
  sandbox: false,             // renderer is NOT OS-sandboxed
}
```

## 2. What `sandbox: false` actually changes

`sandbox: true` runs the renderer in a Chromium OS-level sandbox (seccomp/AppArmor
on Linux, Seatbelt on macOS, AppContainer on Windows) and restricts the
**preload** script to a small polyfilled subset of Node.

`sandbox: false` removes that OS-level confinement. It does **not** by itself
grant Node to the renderer — `nodeIntegration: false` and
`contextIsolation: true` already keep the renderer in a browser-only world with
a narrow `contextBridge` surface.

## 3. Why it is currently `false`

`preload.js` uses `ipcRenderer.sendSync('ark:get-backend-port-sync')` to resolve
the backend port **synchronously before renderer JS runs**. Under
`sandbox: true`, synchronous IPC via the preload's own `require('electron')`
path is not available in the sandboxed-preload subset, so the port would not be
resolved in time and the first backend call from the renderer would race the
shell. The flag is therefore **functional**, not accidental.

## 4. Exposure analysis (what is actually at risk)

| Question | Finding |
| --- | --- |
| Does the renderer load untrusted web content? | **No.** No `<iframe>`, `<webview>`, `srcDoc`, or `dangerouslySetInnerHTML` anywhere in `src/`. |
| Where does untrusted browsing happen? | In the **backend** Playwright Chromium (`app/tools/web_intel/`), a separate process with its own SSRF guard — never inside the Electron renderer. |
| Renderer Node access? | None (`nodeIntegration:false`). |
| Preload surface? | Four members: `getStatus`, `getBackendPort`, `isElectron`, `platform`, `backendPort`. Read-only, no arbitrary IPC passthrough. |
| Remote-content images? | Evidence previews are backend-proxied (`attachment.url`), not arbitrary remote origins. |

Net: the renderer executes only first-party application code. The classic
`sandbox:false` exploit chain (untrusted page → renderer RCE → OS) has **no
untrusted-page link** in the current architecture.

## 5. Decision

**Keep `sandbox: false` for this release; do not change it in the P0 pass.**

Rationale: flipping it without testing breaks the synchronous port handshake
(§3) and could leave the desktop app unable to reach the backend. The advisor's
guidance — "changing it without testing preload and IPC compatibility could
break the desktop application, so it should be handled deliberately" — is
adopted verbatim.

### Recommended follow-up (tracked, not P0)

1. Move port resolution to an **async** handshake (`invoke`/`handle`) so the
   preload no longer needs synchronous IPC.
2. Then set `sandbox: true` and re-test: preload load, `window.ark.*` surface,
   backend reachability, titlebar/overlay behaviour on macOS + Windows.
3. Add a packaging-time assertion that `sandbox` is `true` in production builds.
4. Consider `app.enableSandbox()` as a belt-and-braces default.

## 6. Residual risk

Low, **conditional on** the renderer never gaining the ability to load remote
or attacker-influenced HTML. If a future feature embeds a remote page in the
renderer (e.g. an in-app OSINT browser view rather than the backend one), this
decision must be re-opened *before* that feature ships.

*This document was produced by an AI agent (OpenHands) on behalf of the ARK
maintainer.*
