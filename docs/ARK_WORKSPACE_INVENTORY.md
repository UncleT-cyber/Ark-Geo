# THE ARK workspace and menu inventory

Source audit of the current working tree. **Wired** means a reachable screen or control has a code path. **Mixed** means the screen combines real, local, provider-dependent, or simulated features. **Planned** means the UI is a roadmap or the capability is described in a design document. Runtime and provider availability were not tested for this inventory.

## Investigator workbench

There are four first-level workspaces in the activity rail. Telecom is a Network submenu. The Case Explorer's Telecom filter does not create a fifth workspace.

| Workspace | Status | Menus |
| --- | --- | --- |
| Image Intelligence | Wired | System Overview before upload. After analysis, Investigation, Spatial / Map, File Forensics, OCR & Vision, Source Discovery, Provenance / C2PA, Case / Report. Sidebar also has Evidence Explorer and New Investigation. |
| Network Intelligence | Mixed | Network Discovery, Traffic Analysis, HTTP / Web Analysis, Endpoint Mapping, Authorized Security Testing, Telecom & Phone. |
| Threat & SecOps | Roadmap screen | SIEM, IDS / IPS, Threat Hunting, Detection & Correlation, Incident Management, Security Operations. Cards are labelled Planned. |
| Case Workspace | Wired | Case Explorer search, saved investigations, restore, active case audit trail. Filters are All, Image, Network, SecOps, Telecom. |

Source: `ActivityBar.tsx`, `Workbench.tsx`, `NetworkWorkbench.tsx`, `SecOpsPlaceholder.tsx`, and `CaseExplorer.tsx` under `arkgeo-investigator-web/src/components/workbench/`.

### Image Intelligence

| Menu | Contents |
| --- | --- |
| System Overview | Saved investigations, 14-day activity, critical-risk count, investigation volume, risk and metadata, recent sessions. Intake is in the sidebar with a Zero-Retention toggle. |
| Investigation | Map-first case assessment, evidence summary, gaps, suspicious findings, suggested next steps. |
| Spatial / Map | Map, spatial evidence, geolocation and fusion, Street View where available. |
| File Forensics | **IMINT · 4-Pillar**, **ExifTool Tree**, **ELA**, **Consistency**, **Structure / Hex**. |
| OCR & Vision | Extracted text and visual evidence tags. |
| Source Discovery | Reverse image search, matches, and source history where available. |
| Provenance / C2PA | Manifest and signature status. |
| Case / Report | Evidence and chain of custody, analyst overrides, PDF export. |
| Evidence Explorer | Sidebar tree of file, hashes, metadata, forensics, vision, provenance, sources and case evidence. |

The command palette offers shortcuts to image upload, those investigation views, PDF export, and the protected admin entry. The older `TabBar.tsx` defines additional labels for the same image tools. The active shell uses `IMAGE_SUBVIEWS` and the sidebar. Source: `Workbench.tsx`, `CommandPalette.tsx`, `investigation/`, and `tools/`.

### Network Intelligence

| Menu | Contents and maturity |
| --- | --- |
| Network Discovery | RDAP, BGP/ASN, DNS, certificate transparency. Workspace lookups and CAI execution are separate paths today. |
| Traffic Analysis | PCAP intake, flows, endpoints and observations. |
| HTTP / Web Analysis | Single-URL HTTP security-header analysis. |
| Endpoint Mapping | Certificate transparency and discovered names. |
| Authorized Security Testing | Attestation UI, local helpers, simulation surfaces, and separate backend RE-ACT execution path. |
| Telecom & Phone | Seven-step procedure rail. Mix of local analysis, provider-backed enrichment, simulations, and gated signaling paths. |

#### Authorized Security Testing

| Submenu | Nested controls |
| --- | --- |
| Vulnerability Assessment | Nuclei, OpenVAS, Nmap NSE, OWASP Dependency-Check, Proton-Fuzz, Shadow-Route, Aegis-Patch. The matrix presents dry-run/simulation surfaces. |
| Web / API Security | DAST Config, OpenAPI Parser, Endpoint Crawler. Crawler is simulated. |
| Exposure & Secret Auditing | Entropy Scanner, Admin-Panel Detector. Admin-panel probe is simulated. |
| Compliance / Baseline | CIS Baseline Auditor, Ansible Remediation. Includes sample checks and configuration generation. |
| Social Engineering | Click-Through Board, Device Drop, Susceptibility, Pretext Builder, OSINT Recon. Simulation UI. |
| RE-ACT Chain | Plan, Scan, Exploit, Escalate, Mitigate. Target types are Network / Host, Web / API, Local Host, ROS / OT, Offline Hash. Dry run is the default. The separate backend path has live-capable adapters, so the simulation description above should not be applied to all modes. |

Source: `arkgeo-investigator-web/src/components/network/tabs/SecurityTestingTab.tsx`, `arkgeo-backend/app/api/v1/endpoints/react.py`, and `arkgeo-backend/app/agent/react_chain.py`.

#### Telecom & Phone

1. **Identify** — E.164 intake and identification.
2. **Enrich** — OSINT matrix and enrichment.
3. **Audit** — signaling gate and simulated audit paths.
4. **Geo** — map footprint and cell-tower evidence.
5. **Live Ops** — pretext and canary controls, plus gated operator features.
6. **Assess** — AI analyst, risk profile, geospatial analysis, audit next steps.
7. **No-License** — open cell database lookups and registration-region estimates.

Source: `TelecomWorkspace.tsx`, `app/api/v1/endpoints/telecom.py`, and `app/api/v1/endpoints/signaling.py`. UI controls alone do not establish live carrier integration.

## Shared and separate surfaces

- **ARK-CAI dock** — Chat, Review when an image review exists, Console. Console has Problems, Analysis Log, Plan, Agent, Evidence, Audit, Terminal. Chat shortcuts include @Agents, /help, /tools, /case, /forensics, /osint, /investigate. These are dock controls, independent of the server command catalogue.
- **Client Settings** — API Keys (BYOK), Model & Privacy, Saved Case Vault, Notifications, Support & Open Source. Investigator Profile is a separate top-bar modal.
- **Protected Admin** — Command Center, Client Directory & Telemetry, Internal Staff & RBAC, Model Gateway & API Keys, AI & OSINT Gateway, Tool Policy & Governors, Quotas & Usage Tracking, Local Tooling Binaries, Audit Logs & Chain-of-Custody, Open Source & Support.
- **Mobile companion** — HUD, Dead-Man, Offline, Settings. The desktop shell hosts the investigator workbench.

Sources: `ArkControl.tsx`, `BottomPanel.tsx`, `ClientSettingsModal.tsx`, `adminNav.ts`, `arkgeo-mobile/src/App.tsx`, and `arkgeo-desktop/main.js`.

## Roadmap and capability gaps

| Planned area | Existing foothold | Remaining scope |
| --- | --- | --- |
| Threat & SecOps | Six roadmap cards and selected backend adapters | Live SIEM ingestion/search, IDS/IPS integrations, hunting, correlation, incident management, operations dashboard. |
| OSINT / Intelligence | Source discovery, telecom enrichment, web search and reconnaissance tools | Dedicated workspace for public-source investigations, entities, relationships, timelines, and credibility. |
| Web / App Security | HTTP / Web Analysis and Authorized Security Testing submenu | Dedicated workspace for proxy/history, API and session mapping, app structure, auth-flow investigation and policy-controlled execution. |
| Unified execution and case engine | CAI streams, typed registry, Policy Guard, Evidence Graph, browser case vault | Authenticated operator ownership, shared passive discovery task, durable events/replay, backend case/task/evidence linking and cross-domain correlation. |
| Model routing and privacy | Gateway, provider settings, per-workflow retention behavior | Policy-driven routing, local-only enforcement where required, model provenance per finding. |
| Reproduction and analyst productivity | PDF reports and overrides | Reproduction bundles with plan lineage, tool/model/environment versions and rerun manifest, versioned plan templates and comparative runs. |
| Additional domain taxonomy | Selected related tools or demonstrations | Dedicated malware analysis, phishing investigations, controlled social engineering, DFIR and incident response, cloud, container/infrastructure, mobile security, wireless, compliance, and research/custom-tool workflows. Vulnerability assessment and authorized pentesting have partial surfaces today. |
| SecOps infrastructure | Architectural evaluation only | Evaluate Wazuh, Suricata, Zeek and OpenSearch connectors for read-only ingest, normalized findings and case linkage before response automation. |

The historical Phase F language covers specialist registration and execution substrate work. It does not make the SecOps roadmap cards operational or create independent OSINT or Web rail entries. The current unification plan gates the passive discovery proof on common authorization and durable task/case records. Sources: [Integrated Security Environment](ARK_INTEGRATED_SECURITY_ENVIRONMENT.md), [Project Handoff](PROJECT_HANDOFF.md), [Unified Execution Audit](ARK_UNIFIED_EXECUTION_AUDIT.md), and the architectural unification directive.
