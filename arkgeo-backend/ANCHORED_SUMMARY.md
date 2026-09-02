## Objective
- Unify THE ARK's embedded CAI engine into ONE ARK-CAI engine (single tool surface, dispatcher, model source) and route every workspace through it; make all provided tools reliably usable; build out the Telecom/Phone intelligence workstream as a legitimate, authorized digital-forensics capability.

## Important Details
- Unified engine merges THREE tool universes (agent/tool_registry + ARK `tool_adapter` + CAI `cai.tool_registry`) via one schema builder + `_dispatch_tool`, deduped by name. CAI dispatch now uses the populated `cai.tool_registry.TOOL_REGISTRY` (fixed; was empty).
- **Telecom/Phone security boundary (held this session):** The user, as a personal digital-forensics professional, asked to explore "backdoor"/license-bypass means for tower/location data. Decision: build the **authorized** path only. Live signaling intelligence goes through the `app/signaling` subsystem, which already enforces certified-operator JWT → per-operator MCC-bound token → scope → **audit trail**. The `commercial` backend is a config-driven REST adapter to a *licensed* gateway and is inert (raises `BackendNotProvisioned`) until the user provisions credentials. I did NOT implement any license/authorization bypass, covert IMSI-catcher against non-consenting devices, or unauthorized on/off tracking. The legitimate route (licensed gateway + certified operator + audit) achieves the investigative goal lawfully.
- Workspace model: IMAGE / NETWORK / SECOPS / CASES. There is **no** "telecom" workspace; telecom/phone tools must be tagged domain `"network"` to surface there (a tagging bug was fixed — they were previously filtered out entirely).

## Work State
### Completed
- **Unified engine**: CAI dispatch registry fix (single source of truth), nmap hardening (fast top-100 + auto-degrade + loop-safe `_run`), full tool-surface resolution verified (109 distinct / 287 instances, 0 unresolved). Tests: `test_cai_dispatch_sot.py`, `test_nmap_robust.py`.
- **IMEI intelligence (NEW)**: `app/services/imei_analysis.py` — IMEI/IMEI-SV validation (3GPP Luhn check digit), structure (TAC/SNR/CD/RBI), RBI→manufacturer, pluggable TAC DB (seed + `settings.imei_tac_db_path`), MEID, serial fallback, honest `confidence`. Tool `telecom.imei_decode` added + surfaced in NETWORK workspace. Tests: `tests/test_imei.py` (6 pass).
- **Telecom tools surfaced**: retagged `telecom.fact_sheet|analyze|telemetry|imei_decode` from domain `"telecom"` → `"network"` so they actually appear in the Network Intelligence workspace (previously filtered out → "not functioning"). Verified all four resolve and `imei_decode` returns structured output.
- **Signaling backends**:
  - `simulated` — deterministic dry-run, clearly flagged `live=False, simulated=True`; verified returns IMSI/CGI/lat-lon from deterministic tables (lab/dev safe).
  - `commercial` — rewritten from a pure stub into a real, config-driven REST adapter (`signaling_commercial_base_url` + `signaling_commercial_api_key` in `app/core/config.py`). Calls the licensed provider's `{base}/{op}` with Bearer key, maps response → `SignalingResult`. Inert + `BackendNotProvisioned` until provisioned; only reachable behind the certified-operator/audit gate. No bypass.
  - `osmocom` / `sdr` — RF-lab backends for controlled hardware (authorized research path).
- Reference + OSINT layer (`phone_registry`, `phone_osint`, `phone_analysis`) already real: libphonenumber (carrier/country/MCC-MNC/line-type/timezone/region) + licensed HLR providers (Twilio/Infobip/IPQS → active/ported/roaming/fraud) gated by BYOK/Admin key. Explicitly no fabrication/enumeration.

### Active / Next
- To get **live** location/state today the user can: (a) set a Twilio/Infobip/IPQS key for HLR OSINT (carrier/country/region/active/ported/roaming), or (b) provision a licensed SS7/Diameter gateway (the `commercial` adapter then activates), or (c) use `osmocom`/`sdr` in a controlled RF lab.
- Optional: populate `settings.imei_tac_db_path` with an authoritative TAC dump for exact model resolution (seed only gives RBI-level + a few examples).
- Optional: wire `telecom.*` + `telecom.imei_decode` into the agent/tool_registry substrate (currently ARK-catalogue only) and add a frontend panel in the NETWORK workspace for phone/IMEI intake + results.
- Earlier cross-cutting TODOs (non-blocking): a few CAI network handlers (`shodan.py`, `fetch_url.py`) lack explicit timeouts; full backend suite has 1 env-fail (`test_call_real_tool`, macOS `dig localhost`→::1).

### Blocked
- (none)

## Next Move
1. User to provision either an HLR API key (OSINT live state) or a licensed signaling gateway (set the two `signaling_commercial_*` settings) to exercise live paths; everything else is functional now.
2. If desired, add a NETWORK-workspace frontend panel for phone/IMEI intake + a populated TAC database.

## Relevant Files
- `app/services/imei_analysis.py` (NEW), `tests/test_imei.py` (NEW).
- `app/engine/tool_adapter.py` — `_telecom_imei` + `telecom.imei_decode` (domain `network`); `_net_nmap_scan`/`_pentest_nmap_scan`; `_run` loop-safe.
- `app/signaling/backends/commercial.py` (rewritten to real adapter), `app/signaling/backends/simulated.py`, `app/signaling/access.py`, `app/signaling/backend.py`.
- `app/core/config.py` — `signaling_commercial_base_url` / `signaling_commercial_api_key`.
- `app/services/phone_registry.py`, `app/services/phone_osint.py`, `app/services/phone_analysis.py` (existing, real).
- `app/engine/orchestrator.py` — `_dispatch_tool` / `_run_cai_tool` (CAI SOT fix).
- `tests/test_cai_dispatch_sot.py`, `tests/test_nmap_robust.py`.
