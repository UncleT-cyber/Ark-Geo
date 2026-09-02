# THE ARK (ArkGeo) — Project Handoff & Phase-1 Closeout

> **Status: PAUSED, NOT ABANDONED.** This document is the single source of
> truth for resuming the project. Read this first, then
> `docs/ARK_INTEGRATED_SECURITY_ENVIRONMENT.md` (architecture) and
> `docs/ARK_AI_ORCHESTRATION_SPEC.md` (AI substrate) for depth.
>
> Written at the end of Phase 1. Last verified: backend 433/433 tests passing,
> web `tsc` clean, `vite build` clean, both services running locally.

---

## 1. TL;DR

We built **the first of its kind: an integrated security environment** — an
AI-orchestrated forensic investigation platform ("THE ARK") that unifies
image forensics, geolocation, reverse visual search, network intelligence,
threat/SecOps, OSINT, certified signaling (SS7/Diameter), phone intelligence,
an Admin Console, and a terminal agent — all on one tamper-evident evidence
graph with an immutable audit trail.

The flagship **AI Investigation Mode** is real: a plan → approve → execute
loop driven by a **local** Ollama model (`qwen2.5-coder:3b`), running tools
through a policy guard and evidence graph, re-planning on contradictions,
respecting spend budgets. The terminal agent (`ark` commands in the
Workbench) is **intent-gated** — it never runs tools unless you issue a
directive naming a target.

The **big unfinished mission is telecom/phone**: capturing *as much data as
possible from a phone*. Today we have a real, multi-provider OSINT surface
(HLR / carrier / SIM-swap / CNAM / presence), a contract-complete but
**simulated** signaling engine, and a certified-personnel access boundary. The
**live** layers (osmocom lab, SDR) are gated behind hardware we do not own
yet. See §6 and §7.

---

## 2. Current State (where we left off)

### 2.1 What works, end to end (all live-verified)

| Area | State |
|---|---|
| **Direct Evidence Mode** | Upload → triple-hash custody → EXIF/ExifTool deep metadata → JPEG structure/ELA/EOF steganography → C2PA → OCR → vision ensemble → GPS/telemetry → consensus → geolocation pins. Fully working. |
| **Image Intelligence (4 feature gaps, closed in the last sessions)** | ① **Stripped-EXIF fallback**: `ImagePipeline` runs OCR→geocode when EXIF/GPS is missing; `metadata_status` STRIPPED badge in `ExifViewer`. ② **OCR→geocoding pins**: `geocodingService` turns OCR text into `geo_candidates`; amber diamonds on the map; fallback flyTo centroid. ③ **Reverse visual search**: pHash + TinEye/Serper, results + matches rendered in `ExifViewer`. ④ **Terrain IMINT**: candidate-region folders (what/where analysis) in `ExifViewer`. |
| **AI Investigation Mode (agentic)** | Phase A–F substrate complete: Tool Registry, Policy Guard (24 tests), Planner, Executor, Correlator, Critic, Hypothesis Engine, Evidence Graph, model Gateway to local Ollama. Adaptive re-planning + budgets (Phase E, 17 tests). Cross-domain NETWORK + SECOPS (Phase F, 13 tests). Identity Contract cognitive layer (13 tests). |
| **Terminal agent (ark)** | `ark inspect`, `ark metadata`, `ark ocr`, `ark jpeg`, `ark ladder`, `ark evidence`, `ark case`, `ark audit`, `ark capabilities` (new). **Intent gating** (added last session): directives with a target run tools; vague/conversational input never fires tools — the agent replies conversationally and synthesizes tool JSON results into natural-language "ARK AGENT:" answers. Capability self-knowledge: the agent enumerates its full real tool catalog from `capabilities.py`. |
| **Admin Console** | Authenticated (JWT) admin surface: clients, staff, tool policy toggles, quotas, support settings, gateway, API keys (encrypted), audit log viewer. |
| **Telecom / Phone (passive OSINT)** | `/telecom/hlr-lookup`, `cell-lookup`, `cell-local`, `presence-probe`, `/telecom/analyze`; full OSINT aggregator in `phone_osint.py` (E.164 + libphonenumber free tier, IPQS, Twilio, Infobip, OpenCNAM, Telesign/Tru.ID SIM-swap, presence footprints). **No simulation** — providers report `requires_key` when no credential exists. |
| **Certified signaling surface** | `/signaling/*` with two-layer auth: personnel JWT (`CERTIFIED_OPERATOR` / `CERTIFIED_OPERATOR_ADMIN` / `AUDITOR`) + per-operator MCC-bound tokens. Ops: SRI / ULR / ATI / PLR / IMSI / CGI / silent-SMS / IMSI-catcher / dry-run / canary. Currently on the **simulated** backend (deterministic dry-run, always flagged `live=false`). |
| **Network intelligence** | `/network/*`: RDAP, BGP, DNS, CRT, web probes, host discovery, port scan, TLS inspect — routed through the agent as tools too. |
| **Investigations & Case Vault** | Sessions, evidence graph, findings, OBS observations, chain of custody, audit trail; observations from the terminal agent fold into the active case. |

### 2.2 Repo layout
- `arkgeo-backend/` — FastAPI "Brain" + ARK AI substrate (`app/agent/`), signaling subsystem (`app/signaling/`), phone/telecom services, 433 tests.
- `arkgeo-investigator-web/` — React 18 + Vite 5 forensic Workbench (ISE). Dev server :12001, proxies `/api` → :12000.
- `arkgeo-mobile/` — Expo/React Native tactical HUD (unfinished; not part of this closeout).
- `docs/` — architecture + AI orchestration specs.

### 2.3 Test / build status (last run)
- Backend: **433 passed** (includes 8 agent-intent-gating, 13 identity-contract, 33 signaling, 28 telecom/network, 18 admin-console, 12 phone-analysis, 16 phase-C, 17 phase-E, 13 phase-F, 24 policy-guard, 14 stripped-metadata, 10 image-lifecycle tests).
- Web: `npx tsc --noEmit` clean; `npm run build` clean (only a chunk-size warning).

### 2.4 Runtime environment (as last used)
- **Ollama**: local, `qwen2.5-coder:3b` (agent planner/conversational/synthesis). Also cached: `deepseek-r1:7b`, `llama3.2`, custom `arkengineer`/`local-hacker` models.
- **Configured provider keys** (live health check): GeoSpy ✅, Gemini ✅, Google StreetView ✅. Not configured: GeoInfer, Mapbox, TinEye, Serper, Twilio, OpenCelliD, OpenAI-LLM. Storage backend: `local` (data in `arkgeo-backend/arkgeo_data/`).
- Services run on **12000 (backend)** and **12001 (web)** — note the repo's own `AGENTS.md`/.env.example still say 8000/5173; the real, working ports are 12000/12001.

### 2.5 IMPORTANT — uncommitted work
The working tree has **~109 changed/new files that are NOT committed** (last
commit is `4f7375e feat(backend): ARK Policy Guard — Phase B`). This includes
the entire agent orchestration substrate (`app/agent/cognitive/`, `domains/`,
`agent_loop.py`, `capabilities.py`, …), signaling, telecom, phone OSINT,
admin console, and all of the last sessions' image-forensics + intent-gating +
capabilities work. **Before Phase 2, commit or snapshot this tree** — it is
the entire Phase-1 result and would be lost otherwise.

---

## 3. Local Launch — Quick Start (single command)

> **Yes — you do NOT need to run backend and frontend separately.**
> `launch.sh` starts both (plus Ollama if it is off) and opens the browser.

### First-time setup (only once)
> ⚠️ **Python 3.10+ is REQUIRED.** The code uses modern typing (`str | None`,
> `list[dict]`). Do **not** create the venv with the Apple system Python 3.9
> (`/usr/bin/python3`) — it fails at import with `TypeError: You have a type
> annotation 'str | None'...`. Use 3.12+ (e.g. `/usr/local/bin/python3.12`).

```bash
cd ~/Ark-Geo                          # repo root
cd arkgeo-backend && /usr/local/bin/python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
cd ../arkgeo-investigator-web && npm install
# optional: install/start Ollama  →  brew install ollama; ollama pull qwen2.5-coder:3b
```

### Launch (daily)
```bash
./launch.sh              # everything on :12001/:12000, opens browser
./launch.sh stop         # stop what this script started
./launch.sh status       # what's up
./launch.sh backend      # backend only  (curl http://127.0.0.1:12000/api/v1/health)
./launch.sh frontend     # web only
```
Logs: `$TMPDIR/arkgeo-logs/backend.log`, `frontend.log`, `ollama.log`.
API docs: http://127.0.0.1:12000/docs.

### Manual (equivalent, if you prefer)
```bash
# Terminal 1 — backend (venv already created)
cd arkgeo-backend && .venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 12000
# Terminal 2 — web
cd arkgeo-investigator-web && npm run dev
```
The vite dev server proxies `/api/*` to the backend, so the portal needs no
API URL config.

### Tests / build (when developing)
```bash
cd arkgeo-backend && .venv/bin/python -m pytest tests/ -q      # full suite (~2.5 min)
cd arkgeo-investigator-web && npx tsc --noEmit && npm run build
```

---

## 4. Credentials (DEV SEED — change before any production use)

### Admin Console
| Role | Username | Password | How to change |
|---|---|---|---|
| Admin | `admin` | `arkgeo-admin` | Env `ARKGEO_ADMIN_USERNAME`, `ARKGEO_ADMIN_PASSWORD_HASH` (bcrypt). Login at `/#/admin` (Cmd+Shift+P also navigates). |

### Certified signaling personnel (live ops / audit)
| Role | Username | Password | Notes |
|---|---|---|---|
| Signaling Operator (live ops) | `sigops` | `sigops-cert` | `CERTIFIED_OPERATOR`, MCC scope 621. |
| Signaling Admin | `sigadmin` | `sigadmin-cert` | `CERTIFIED_OPERATOR_ADMIN` — issues operator tokens. |
| **Auditor** | `sigaudit` | `sigaudit-cert` | `AUDITOR` — reads `/signaling/audit`, cannot run ops. |

These come from `app/signaling/access.py` dev seed (bcrypt-hashed). Override
via `ARKGEO_SIGNALING_PERSONNEL_FILE`. They authenticate against
`POST /signaling/auth/token` and are used in the **Telecom Workspace →
LIVE mode credentials gate** (the UI prints these seeds itself).

### Auth model reminder
- **Admin Console** = independent JWT (`role: admin`) for `/admin/*`.
- **Signaling** = two layers: personnel JWT (role claim) **+** a short-lived
  per-operator token bound to an MCC, issued only by `sigadmin`, required for
  every live op. Every allowed **and denied** op is audit-logged.

---

## 5. Key Challenges Encountered (Phase 1)

1. **Epistemic separation (facts vs hypotheses).** The hard design problem:
   deterministic outputs (hash, EXIF, OCR) are facts; AI outputs are
   hypotheses. We made it *structural*, not prompt-based — a hypothesis cannot
   promote to a finding without higher-tier corroboration, enforced in the
   evidence graph (contradictions resolve toward the higher tier).
2. **No path to "live" without hardware.** The signaling stack is
   contract-complete and correctly gated, but real SS7/Diameter needs an
   osmo-hlr/osmo-msc lab, and real IMSI capture needs SDR + a test-band
   license. The architecture was built so that *enabling a backend is a
   config change, not a rewrite* — but the hardware is the blocker (§7).
3. **Phantom/unprompted tool execution in the terminal agent.** The agent
   would execute tools on vague input (e.g. someone typing "this is a
   conversation" triggered `inspect_local_path`). Fixed with **intent
   gating**: classification (directive/guidance/conversational) + target
   extraction + explicit INTENT RULE in the system prompt + deterministic
   fallbacks. Verified live — directives run tools, everything else does not.
4. **The agent not knowing its own capabilities.** It answered "list all your
   capabilities" with a hand-written subset ("only OSINT"). Fixed by deriving
   `capabilities.py` from the **actual tool registry** + platform features,
   injecting the inventory into every LLM prompt, classifying capability-asks
   as conversational, and adding `GET /agent/capabilities` + the
   `ark capabilities` terminal command.
5. **Stripped-EXIF images were a dead end.** When GPS/EXIF is stripped, the
   old pipeline returned nothing. Fixed with the OCR→geocode fallback
   pipeline (GeoSpy, Nominatim/Google reverse geocode) producing candidate
   pins, plus reverse-search pHash for provenance.
6. **Testing real provider lookups is flaky.** Backend tests must be
   deterministic, so provider-dependent paths are keyed and degrade to
   `requires_key`; live provider behavior was verified manually with health
   probes.
7. **Port/config drift in the repo.** Docs say 8000/5173; the real working
   config is 12000/12001 (vite proxy hard-codes 12000). This wasted time —
   hence the one-command `launch.sh`.

---

## 6. Mission, Target, Plans — especially Telecom & Phone

### 6.1 The mission (still the north star)
> **Capture as much data as possible from a phone — given an authorized
> target number or asset — and fuse it onto the same tamper-evident evidence
> graph as everything else, so the AI can investigate the person/device across
> image, network, and telecom domains in one case.**

The design is deliberately staged so data collection is **lawful and
layered**:

1. **Keyless public facts** (already real): E.164 parse, country/MCC/MNC,
   carrier, line type, timezone, geo zone, validity, formats.
2. **Licensed provider tiers** (already real, key-gated): HLR/IPQS,
   Twilio, Infobip (live/ported/roaming), OpenCNAM (caller ID), Telesign/
   Tru.ID (SIM-swap), digital-footprint availability probes.
3. **Certified signaling ops** (built, currently simulated): SRI, ULR, ATI,
   PLR, IMSI, CGI, silent-SMS, IMSI-catcher — all behind the certified-personnel
   + operator-token boundary, all audit-logged.
4. **Physical capture** (future, hardware-gated): SDR test-band BTS for
   IMSI capture; the code boundary exists (`sdr.py`) but nothing runs without
   hardware.

### 6.2 Where Phase 1 landed vs. the mission
- We **achieved** the full *OSINT-from-a-number* layer and the entire
  *authorized-signaling workflow envelope* (auth, gating, audit, dry-run).
- We **did not** achieve physical/live capture: no real SS7/Diameter traffic,
  no live IMSI capture, no silent SMS delivery, no live subscriber location.

### 6.3 Roadmap already in the docs (phases to resume)
- **Phase G** — Case engine unification (one cross-domain case: image + network + secops + telecom on one graph). *Much of this already works in practice; formalize.*
- **Phase H** — Model routing policy (local model for sensitive analysis, `zero_retention` forces local).
- **Phase I** — Court-ready reproduction bundles (case export + re-run manifest).
- **Phase J** — Analyst productivity (plan templates, comparative runs).
- **OSINT/WEB tool registration** (Phase F follow-up) — register the OSINT + WEB domains in the agent the way NETWORK + SECOPS were done.

---

## 7. Limitations — especially Telecom & Phone (the serious ones)

These are the hard constraints we hit. Phase 2 must address them head-on.

### 7.1 Live capture is not possible without hardware/licensing
- **Simulated by default.** `signaling_backend="simulated"` (config default).
  All `/signaling/*` results are deterministic dry-runs flagged
  `live=false, simulated=true`. They are *stable for a given target* but are
  **not** subscriber data.
- **osmocom backend = lab-only.** `sdr.py`/`osmocom.py` are contract-complete
  but every live op raises `BackendNotProvisioned` with the exact missing
  wiring. SRI/ULR/ATI/IMSI/CGI could run against an **osmo-hlr lab** on
  localhost (CTRL 4250, GSUP 4222, MSC 4254, SMSC, SMLC 4257) — but no lab
  process exists on this host.
- **IMSI-catcher / silent SMS = fully gated.** Need OpenBSC BTS over SDR
  (USRP/bladeRF) + test-band license; radius capped at
  `sdr_max_imsi_catcher_radius_m`. Nothing runs without the hardware.
- **Consequence:** "capture as much data as possible from a phone" today stops
  at OSINT + provider lookups. The *authorization + audit + workflow* for the
  deeper ops is done and correct; the *transport* is not provisioned.

### 7.2 Keyless data has hard ceilings (nothing fabricated)
- No live ON/OFF/roaming state without an HLR provider key — the code returns
  `requires_key` (or "unknown") rather than inventing a verdict. This is
  deliberate and correct, but it means the free tier can never tell you if a
  line is currently attached.
- No historical billing, no spam-reputation, no data-leak harvesting — those
  need licensed sources. `phone_osint.py` documents them as gaps for operator
  sign-off; they are **not** simulated.
- Social/presence layer is **link builders only** (`wa.me`, `t.me`, …); live
  profile/avatar/"last seen"/account-enumeration is not implemented (requires
  platform approval or a licensed source). `ARKGEO_SOCIAL_PROBE_ENABLED=true`
  only probes availability status codes, never scrapes account data.
- **No SIM-swap verdict without Telesign or Tru.ID keys** — again, honest
  `requires_key` rather than a guess.

### 7.3 No cross-domain case unification yet (Phase G)
The case vault is used by image and by agent observations, but there is no
single formal cross-domain case model (image + network + secops + telecom in
one findings list + one audit trail with cross-domain contradiction edges).
Phase G formalizes this. The AI substrate already routes NETWORK + SECOPS
tools through one shared graph — extend to telecom/phone.

### 7.4 Other unresolved items / known bugs
- **Uncommitted working tree (~109 files)** — must be committed/snapshotted.
- **`llm` health shows "not_configured"** while the agent runs on local
  Ollama — the health check keys off OpenAI-compatible env vars; the Ollama
  gateway path is fine but the health indicator is misleading.
- **Frontend live-signaling UI** exists in `TelecomWorkspace` (LIVE mode),
  but with the backend on `simulated` it always exercises dry-run; the LIVE
  path has not been end-to-end tested against a real lab.
- `arkgeo-mobile` (Expo tactical HUD) is an early scaffold, not functional —
  outside this closeout.
- Non-blocking warnings only: Vite chunk-size, Starlette TestClient/httpx
  deprecation.

---

## 8. Priority Action Items for Phase 2 (ordered)

1. **Commit / snapshot the working tree.** (Currently ~109 uncommitted files
   carrying the entire Phase-1 result.) Do this first.
2. **Stand up an osmo-hlr lab** (Docker or VM) and flip
   `ARKGEO_SIGNALING_BACKEND=osmocom`. Validate SRI/ULR/ATI/IMSI/CGI live
   against it with the operator-token gate. This is the single highest-value
   step for the phone mission.
3. **Complete the cross-domain case engine (Phase G)** so phone/telecom
   evidence merges with image + network on one graph with contradiction edges.
4. **Register TELECOM/PHONE tools in the agent registry** so the terminal
   agent can run `hlr-lookup`, `phone-osint`, `cell-lookup` as policy-guarded
   tools (same pattern as NETWORK + SECOPS in Phase F).
5. **Wire real provider keys** into the Admin Console (IPQS/Twilio/Infobig/
   OpenCNAM/Telesign) and verify the OSINT matrix populates live fields
   (live/roaming/SIM-swap).
6. **SDR test-band IMSI capture** — acquire hardware + license, provision
   OpenBSC BTS, exercise the `sdr` backend's radius-gated catcher. Biggest
   physical-investment item; the software boundary is ready.
7. **Health indicator fix**: report the Ollama gateway as the active LLM path.
8. **Re-verify the full suite** (433 tests), tsc, build after each change.

---

## 9. Contacts of the system (how to poke it)

| Thing | Where |
|---|---|
| Web portal | http://127.0.0.1:12001 |
| Admin login | `/#/admin` (Cmd+Shift+P) — `admin` / `arkgeo-admin` |
| API docs | http://127.0.0.1:12000/docs |
| Agent capabilities | `GET /api/v1/agent/capabilities` or terminal `ark capabilities` |
| Signaling status | `GET /api/v1/signaling/status` |
| Health | `GET /api/v1/health` |
| Telecom OPSINT | `POST /api/v1/telecom/hlr-lookup`, `/telecom/cell-lookup`, `/telecom/analyze`, `/signaling/osint` |
| Audits | `GET /api/v1/admin/audit` (admin JWT), `GET /api/v1/signaling/audit` (personnel JWT) |
| Sandbox for the terminal agent | `~/Documents/ARK_Investigations/` (e.g. `case-001` with `note.jpg` + `payload.bin`) |
