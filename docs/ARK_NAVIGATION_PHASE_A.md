# Investigation-first navigation checkpoint

Phase A on `main`. The working tree already contains frontend, CAI, and backend changes. This phase changes the investigator shell and its navigation only.

## Current to target mapping

| Existing destination | Phase A destination |
| --- | --- |
| Activity rail · Image Intelligence | Workspaces → Image Intelligence. The System Overview, image intake and Zero-Retention toggle remain in the Image workspace. |
| Image sidebar · Investigation, Spatial / Map, File Forensics, OCR & Vision, Source Discovery, Provenance / C2PA, Case / Report | Contextual Workspace Controls inside the main workspace. Existing image result requirement applies. |
| File Forensics · IMINT · 4-Pillar, ExifTool Tree, ELA, Consistency, Structure / Hex | Same nested tabs inside File Forensics. |
| Image sidebar · Evidence Explorer | Workspace Controls → Evidence Explorer. |
| Image sidebar · New Investigation | Global New Investigation → existing image intake reset, with inline confirmation when a case is active. Conversational session creation belongs to Phase B. |
| Activity rail · Network Intelligence | Workspaces → Network Intelligence. |
| Network sidebar · Network Discovery, Traffic Analysis, HTTP / Web Analysis, Endpoint Mapping, Authorized Security Testing, Telecom & Phone | Contextual Workspace Controls. The same view components receive the same tab IDs. |
| Authorized Security Testing · Vulnerability Assessment, Web / API Security, Exposure & Secret Auditing, Compliance / Baseline, Social Engineering, RE-ACT Chain | Same nested menus and controls inside Authorized Security Testing, including the original vulnerability matrix, simulation labels, and attestation flow. |
| Telecom & Phone · Identify, Enrich, Audit, Geo, Live Ops, Assess, No-License | Same procedure rail inside Telecom & Phone. |
| Activity rail · Threat & SecOps | Workspaces → Threat & SecOps. SIEM, IDS / IPS, Threat Hunting, Detection & Correlation, Incident Management and Security Operations remain on the planned roadmap. |
| Activity rail · Case Workspace | Workspaces → Case Workspace or Library & Operations → Case Explorer. Both open the same component. Search, domain filters, saved-case restore and audit stay there. |
| Dashboard recent analysis and saved investigations | Dashboard retains its existing controls. Recent Sessions adds a searchable shortcut to the existing case records and restore handler. View All opens Case Explorer. |
| Command palette · image upload and views, PDF export, protected admin entry | Existing keyboard shortcut and TopBar trigger. Library & Operations → Tools & Integrations opens the same palette. |
| Right dock · Chat, contextual Review and Console | Same mounted right dock. Problems, Analysis Log, Plan, Agent, Evidence, Audit and Terminal stay in Console. |
| Profile avatar | TopBar and System → Investigator Profile open the same modal. |
| Settings gear | System → Settings. API Keys, Model & Privacy, Saved Case Vault, Notifications, Support & Open Source remain in the modal. |
| Protected admin route and control-plane sections | Existing route, shortcut, guard and sections. System shows an Admin shortcut only when the existing admin session is authenticated. |
| Mobile HUD, Dead-Man, Offline and Settings | Existing companion navigation. |

Use Cases is a searchable destination catalog in Phase A. Security Assessment and Network Discovery both open the passive discovery workspace. Image Forensics opens the existing forensics view when evidence exists and image intake otherwise. Web & API Security opens HTTP / Web Analysis. Phishing Investigation, Threat Hunting and Custom Workflow are labelled Planned. Threat Hunting links to the SecOps roadmap. Agents and Saved Workflows are shown as planned directory/library entries. Existing Console Agent activity remains accessible.

## Source findings and later phase boundaries

- `App.tsx` mounts the workbench at the root hash route and guards the separate admin console via `adminAuth`. The admin slug is configured by `VITE_ADMIN_ROUTE_SLUG`. No common authenticated operator session boundary was found for CAI conversation ownership.
- `Workbench.tsx` and `useInvestigation.tsx` own selected domain, tab, case and result state. Workspace buttons call existing API wrappers and domain-specific endpoints. The navigation change uses those same callbacks and does not submit any execution request.
- `ArkControl.tsx` owns its in-memory transcript. `app/engine/orchestrator.py` uses a process-local session dictionary. The existing case vault stores saved case records and snapshots separately. Phase A reads that vault and does not introduce another store or pretend case records are persistent chat transcripts.
- A durable **case** groups evidence and findings. A **session** is a conversational resource which may link to a case. A **task** is an execution record and a **use case** is a reusable template or navigation starting point. Phase B depends on a durable, ownership-scoped session contract. The unified execution audit describes the task and authorization dependencies.
- Phase A changes neither presentation modes nor the central composer. Session rename, archive and tabs, adaptive panel roles, guided execution forms and live task integration belong to subsequent checkpoints.

## AI-first capability requirement

Evaluate every new cybersecurity capability for CAI integration. Where appropriate, expose a discoverable, typed operation that CAI can plan, invoke, monitor, and report on. Manual controls and CAI must share the same execution backend and pass the same scope, policy, approval, audit, and evidence checks. Deterministic handlers remain authoritative for execution and results. CAI selects and sequences them, coordinates work, and interprets their outputs. Document any integration blocker or reason for keeping a capability manual in its review.

Phase A adds navigation to existing capabilities and introduces no execution handlers.
