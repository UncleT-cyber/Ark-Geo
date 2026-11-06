# THE ARK — P0 Tool-Binding Regression: Investigation & Repair Report

**To:** Operator / Principal Coding Agent
**Priority:** Critical (P0)
**Milestone:** A.1 — CAI Execution Integration
**Status:** Complete — restricted diagnostic tool bound to the model and proven via live chat
**Date:** Fri Nov 06 2026
**Branch:** `main` (working tree; nothing pushed or committed)

---

## 1. Executive summary

The operator observed that an active ARK CAI session reported only ~19 bound tools and **no execution tool** (no shell, filesystem, Python, PTY, or Docker), returning `NO EXECUTION TOOL BOUND` and declining a Docker diagnostic.

Investigation found this is **intended architecture, not a bug**: CAI-native tools (which include `generic_linux_command`, `execute_code`, `run_command`, `ShellSession`, PTY, and Docker exec) are **deliberately excluded** from model binding by `tool.source != "cai_native"` in `app/engine/orchestrator.py` — a safety control preventing unrestricted shell execution. The ARK catalogue (41 forensic/security tools) is bound instead, but it contained **no local-environment diagnostic tool**, so the model had no way to answer "is Docker available?".

**Repair:** Added a new restricted, read-only diagnostic tool `system.diagnostics` to the ARK catalogue (source `ark_catalogue`, so it binds to the model) plus domain routing so Docker/system prompts select it. Verified end-to-end through the live ARK chat: the model received the schema, generated a valid tool call, ARK authorized it, the backend executed real Docker/OS/runtime diagnostics, returned real output, and the model reported it accurately. All 7 operator verification steps passed.

**No unrestricted execution was enabled** — `generic_linux_command`, `execute_code`, `run_command`, PTY, and Docker-exec remain unbound.

---

## 2. Exact source of the tool binding (the "19 tools")

Tool binding happens in `app/engine/orchestrator.py::_select_provider_tools()` which filters `unified_registry.list()` through these rules, in order:

| Filter | Line | Effect |
|---|---|---|
| `tool.domain in domains` | 189 | Domain-scoping — only tools whose domain matches the detected task domains |
| `tool.source != "cai_native"` | 190 | **All CAI-native tools excluded** (shell, execute_code, run_command, PTY, Docker exec) |
| `tool.tool_id not in {case.attach, evidence.analyst_override}` | 191 | Two case tools excluded |
| `tool.tool_id not in _SIMULATED_ADAPTERS` | 199 | Phase-F offline adapters excluded (`discover_hosts`, `fingerprint_service`, `port_scan`, `tls_inspect`, `siem_query`, `threat_hunt`, `detect_correlation`, `incident_annotate`) — they return canned data, not real observations |
| telecom gating | 200 | `telecom.*` tools only for phone tasks |
| `_adapter_available(tool.tool_id)` | 201 | Binary/config availability (dig, whois, nmap, gobuster, openssl, exiftool, SIEM URL, provider API keys) |
| `tool.source != "ark_substrate" or guard.evaluate(tool.tool_id).allowed` | 202 | Policy Guard allows/denies substrate tools |

Then `unified_registry.provider_tools(selected)` builds the request-local wire catalogue. `ProviderTools.provider_name()` (app/agent/provider_tools.py:21) **aliases dotted tool IDs** to hashed names because `_VALID_NAME = [A-Za-z0-9_-]{1,64}` rejects dots. Example: `net.dns_lookup` → `ark_net_dnslookup_<16-hex>`, `system.diagnostics` → `ark_system_diagnostics_5b0e9112a7c3ef78`. The model must emit the **alias**, not the real ID.

Domain selection (`_task_domains`, orchestrator.py:128) maps prompts/roles to domain sets. E.g. the Docker prompt was classified `role=network_pentester` → domains `{network, pentest, recon}` — **`system` was not included**, so a `system`-domain tool would not bind. (Fixed — see §5.)

Result for a general docker prompt: **17 tools bound** (the operator's "~19" is a domain-scoped variant). None are shell/execution tools.

---

## 3. Registered vs. bound tool comparison

### Registry — all 85 registered tools (`unified_registry.populate()`)

| Source | Count | Notes |
|---|---|---|
| ark_substrate | 43 | Specialist substrate tools (image, network, secops, pentest, osint, imint, case, siem, ot, ros) |
| ark_catalogue | 42 | Real forensic tools in `app/engine/tool_adapter.py` (now incl. `system.diagnostics`) |
| cai_native | 0* | CAI cybersecurity toolkit — registered at backend startup (36 modules seen in server logs) but **never bound** due to the `source != "cai_native"` filter |

*\*cai_native registration showed 0 in a standalone import (path-related) but 36 at backend startup; either way it is excluded from binding by the source filter.*

### Bound to the model (docker prompt, `role=network_pentester`, domains `{network,pentest,recon,system}`)

**17 tools bound**, including the new `system.diagnostics`. Full bound set:

```
ark_system_diagnostics_5b0e9112a7c3ef78  ->  system.diagnostics   (NEW)
ark_net_dnslookup_...                    ->  net.dns_lookup
ark_net_whois_...                        ->  net.whois
ark_net_nmap_scan_...                    ->  net.nmap_scan
ark_net_dir_enum_...                     ->  net.dir_enum
ark_net_subdomain_enum_...               ->  net.subdomain_enum
ark_net_curl_probe_...                   ->  net.curl_probe
ark_net_ssl_check_...                    ->  net.ssl_check
ark_recon_web_search_...                 ->  recon.web_search
ark_recon_web_fetch_...                  ->  recon.web_fetch
ark_pentest_nmap_scan_...                ->  pentest.nmap_scan
ark_pentest_priv_esc_...                 ->  pentest.priv_esc
ark_pentest_webshell_scan_...            ->  pentest.webshell_scan
ark_pentest_hash_crack_...               ->  pentest.hash_crack
ark_pentest_default_creds_...            ->  pentest.default_creds
ark_pentest_ssh_identity_...             ->  pentest.ssh_identity
```

### Tools explicitly NOT bound (security control exercised)

| Tool | Source | Why not bound |
|---|---|---|
| `generic_linux_command` | cai_native | `source != "cai_native"` |
| `execute_code` | cai_native | `source != "cai_native"` |
| `run_command` / `run_command_async` | cai_native | `source != "cai_native"` |
| `ShellSession` / PTY | cai_native | `source != "cai_native"` |
| Docker exec (container.py) | cai_native | `source != "cai_native"` |
| `discover_hosts`, `port_scan`, `tls_inspect`, `fingerprint_service` | ark_substrate | `_SIMULATED_ADAPTERS` (canned data) |

---

## 4. CAI-native shell implementation — verified present, deliberately unbound

The following CAI-native implementations **exist** in `app/engine/cai/cai/tools/` but are `source="cai_native"` and therefore excluded from model binding:

| Implementation | File | Capability |
|---|---|---|
| `ShellSession` (PTY) | `executor.py:70` | Interactive PTY sessions, `docker exec -i -t`, `subprocess.Popen` |
| `run_command` / `run_command_async` | `executor.py` | Shell command execution |
| `execute_code` | `reconnaissance/exec_code.py` | Arbitrary Python/code execution |
| `scripting_tool` | `others/scripting.py` | Module-based scripting (os/sys/subprocess/shutil blocked) |
| `_run_docker_async` | `container.py:97` | Docker container exec |
| `run_ssh_command_with_credentials` | `command_and_control/sshpass.py` | SSH via sshpass |

**Verdict:** The omission of shell execution is **intentional** — a safety control. These are not "broken"; they are correctly excluded from the model's tool surface to prevent unrestricted shell execution (per Milestone C planning: unified execution gateway, target authorization, sandboxing, credential isolation, audit).

---

## 5. Backend runtime identity

Direct execution of `system.diagnostics` (operation `all`) returned:

| Field | Value |
|---|---|
| OS | macOS Darwin 25.6.0 (Darwin Kernel Version 25.6.0, x86_64) |
| Processor | x86_64 / i386 |
| Python | 3.12.13 (Clang 21.0.0) |
| Executable | `/Users/admin/Ark-Geo/arkgeo-backend/.venv/bin/python` |
| PID / CWD | observed per-run, `/Users/admin/Ark-Geo/arkgeo-backend` |

---

## 6. Docker availability — three-way distinction

| Question | Answer | Evidence |
|---|---|---|
| Docker installed on the Mac? | **Yes** | `docker` CLI at `/usr/local/bin/docker`, v29.4.0 |
| Docker available in backend runtime? | **Yes** | `shutil.which("docker")` → `/usr/local/bin/docker`; `docker version` → client 29.4.0 |
| Docker daemon reachable? | **Yes** | `docker info --format '{{.ServerVersion}}'` → `29.4.0`; `docker ps` lists `ark-lab-ssh`, `ark-lab-http` (running 3+ hours) |
| Docker unreachable due to container/remote isolation? | **No** | Backend runs on the Mac host with OrbStack socket `/var/run/docker.sock → /Users/admin/.orbstack/run/docker.sock`; no container/remote isolation blocks it |

**Docker is fully available in the backend runtime.** (Do **not** confuse "no Docker *execution tool* bound to the model" with "Docker absent" — the CLI and daemon are present; only a model-invocable diagnostic was missing.)

---

## 7. Restricted diagnostic capability implemented

Added to `app/engine/tool_adapter.py`:

**`system.diagnostics`** (domain `system`, risk `low` — no HITL required)

- **Input:** `operation` ∈ {`os_info`, `docker_check`, `runtime_info`, `all`} (default `all`), structured string enum
- **Output:** JSON with `operation`, `status`, and `os` / `docker` / `runtime` objects
- **Constraints:**
  - No `command`, `cmd`, `shell`, or arbitrary-execution parameter
  - Never returns filesystem contents, environment variables/secrets, or raw command output
  - Docker check limited to CLI path/version + daemon server version (no container/image inspection)
  - `system.diagnostics` re-checks the engagement scope internally (defense in depth)

Also added domain routing in `app/engine/orchestrator.py::_task_domains()`:

```python
if re.search(r"\b(?:docker|system diagnostic|environment diagnostic)\b", prompt, re.I):
    domains.add("system")
```

This ensures Docker/system prompts select the `system` domain so `system.diagnostics` binds (previously domains were `{network,pentest,recon}` for a Docker prompt, excluding `system`).

---

## 8. Decisive chat test — all 7 operator verification steps PASSED

Prompt: *"Run system.diagnostics with operation 'all' and report the backend operating system, Docker CLI/daemon status, and Python runtime version."*

| # | Requirement | Result | Evidence |
|---|---|---|---|
| 1 | Model receives diagnostic tool schema | PASS | `system.diagnostics` in bound schemas (alias `ark_system_diagnostics_5b0e9112a7c3ef78`), `/cai/tools` reports 42 tools |
| 2 | Model generates valid tool call | PASS | `TOOL_CALL system.diagnostics args={"operation": "all"}` |
| 3 | ARK authorizes the request | PASS | risk=low → no HITL; scope allows `system` domain; no denial |
| 4 | Backend executes the diagnostic | PASS | Real `platform`/`sys`/`subprocess(docker info)` calls, 2590 ms |
| 5 | Tool returns real output | PASS | `status=ok`, real Docker v29.4.0 + Darwin 25.6.0 + Python 3.12.13 |
| 6 | Model reports result accurately | PASS | Final answer: "Docker CLI installed (v 29.4.0) and daemon reachable... macOS Darwin 25.6.0 (x86_64)... Python 3.12.13" |
| 7 | Execution event auditable | PASS | Full SSE trace saved to `arkgeo_data/a2_evidence/p0_docker_diagnostic_chat_proof.json` |

**Model final answer (verbatim excerpt):**

> **System Diagnostics Summary**
> - **Backend Operating System:** macOS Darwin — Darwin Kernel Version 25.6.0, x86_64/i386
> - **Docker:** CLI installed (v 29.4.0 at /usr/local/bin/docker) and daemon reachable (server also v 29.4.0)
> - **Python Runtime:** 3.12.13 ..., executable at /Users/admin/Ark-Geo/arkgeo-backend/.venv/bin/python

**Also verified — earlier aliasing failure mode:** When the model was asked the operator's exact phrasing ("Check whether Docker is available..."), it initially emitted tool names matching **no schema alias** (7× `tool=None` denials: "outside the permitted task schema") because it tried real dotted names (`system.diagnostics`) instead of the hashed alias. This confirms ProviderTools aliasing is real and model-discovery of aliased names is fragile. The direct `system.diagnostics` prompt above proves the pathway works when the model selects the tool.

---

## 9. Security controls exercised

| Control | How applied |
|---|---|
| No unrestricted shell | `generic_linux_command`, `execute_code`, `run_command`, PTY, Docker exec remain `cai_native` → unbound |
| No arbitrary command | `system.diagnostics` accepts only `operation` enum; no command parameter |
| No filesystem/secrets leakage | Output limited to `os`/`docker`/`runtime` structured fields; no file contents or env vars |
| HITL gate intact | `system.diagnostics` is `risk=low` → auto; risky tools (nmap, ssh_identity) still require HITL |
| Engagement scope | `system.diagnostics` re-checks scope internally; scope enforcement remains fail-closed (opt-in via `ARKGEO_ENGAGEMENT_SCOPE`) |
| CAI-native exclusion preserved | `tool.source != "cai_native"` unchanged — no shell-execution pathway added |

---

## 10. Exact files modified (this session)

| File | Change |
|---|---|
| `arkgeo-backend/app/engine/tool_adapter.py` | Added `_docker_diagnostics()`, `_system_diagnostics()`; registered `ArkTool("system.diagnostics", ..., "system", ..., RISK_LOW)`; imported `shutil` locally in `_docker_diagnostics` |
| `arkgeo-backend/app/engine/orchestrator.py` | Added `docker|system diagnostic|environment diagnostic` → `domains.add("system")` in `_task_domains()` |

**Evidence records:** `arkgeo-backend/arkgeo_data/a2_evidence/p0_docker_diagnostic_chat_proof.json` (full SSE trace + final answer).

---

## 11. Remaining blockers

1. **CAI-native shell execution remains unbound by design.** This is correct for now, but means the model cannot run arbitrary shell/Python/Docker-exec through chat. Full shell execution requires the Milestone C unified execution gateway + target authorization + sandboxing — **do not enable without operator review.**
2. **Provider-tools aliasing fragility:** dotted tool IDs are hashed to aliases (`ark_system_diagnostics_<hash>`). Models sometimes emit real dotted names, causing `tool=None` denials. This affects all dotted-ID tools (net.*, pentest.*, imint.*, etc.), not just `system.diagnostics`. Consider allowing dots in provider names or mapping real names as fallback aliases.
3. **cai_native registry registration** showed 0 tools in a standalone import (path-related); at backend startup it registers 36. Worth confirming the tools_importer path is stable.

---

## Sign-off

The P0 objective is met: **THE ARK can invoke the restricted local diagnostic tool through its chat interface and report its real result.** Docker is available in the backend runtime (CLI v29.4.0, daemon reachable via OrbStack); the previous "NO EXECUTION TOOL BOUND" was the intended CAI-native exclusion plus the absence of a local diagnostic tool — now resolved with `system.diagnostics`.

No unrestricted execution enabled. No Milestone B work begun. Awaiting operator review before any further tool activation.
