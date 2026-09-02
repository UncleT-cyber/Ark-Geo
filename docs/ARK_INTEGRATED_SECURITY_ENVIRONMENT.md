# THE ARK — Integrated Security Environment (Master Plan)

> **Goal: ONE integrated security environment.**
> One case engine. One evidence graph. One AI orchestrator. One console.
> Many investigation domains — IMAGE, NETWORK, SECOPS, OSINT, and everything
> after — all speaking the same language: `case · evidence · asset · event ·
> finding · source · relationship · confidence · analyst decision`.
>
> This document builds on `ARK_AI_ORCHESTRATION_SPEC.md` (the contracts:
> tool registry, evidence graph, policy guard, objectives, plan lineage). The
> spec defines *what things are*; this document defines *the order we build
> them and the shape of the finished system*.

---

## 1. The unification thesis

Everything in THE ARK is one substrate with many domains — never siloed
brains. Five isolated "AI for X" systems would each relearn the same three
investigator model, the same evidence rules, the same policy surface, and
the same graph. We build the substrate once and let domains contribute
**tools**, not architectures.

```
                    HUMAN (intent · judgment · authorization)
                                │  objective
                                ▼
                        ARK AI ORCHESTRATOR
                   (plan · route · correlate · hypothesis)
                                │
              ┌─────────────────┼─────────────────┐
              ▼                 ▼                 ▼
          IMAGE tools        NETWORK tools      SECOPS tools
          (hash/exif/ela/    (discovery/        (siem/ids/
           ocr/c2pa/geo)      fingerprint/)      hunt/correlation)
              │                 │                 │
              └─────────────────┼─────────────────┘
                                ▼
                    UNIFIED EVIDENCE GRAPH
                      + ARK CORE (deterministic)
                      + TOOL REGISTRY (contract)
                                │
                                ▼
                        FINDINGS → CASE ENGINE
                                │
                                ▼
                     HUMAN VALIDATION → CASE
```

**Non-negotiable invariants** (structural, never prompt-enforced):

1. **Epistemic separation.** Crypto facts (tier 0) → tool inference (tier 1)
   → AI hypothesis (tier 2). A hypothesis is **structurally refused** promotion
   to a finding without a corroborating higher-tier node. A contradiction
   always resolves in favor of the higher tier. (Implemented: `evidence_graph`
   promotion rule, 18 substrate tests.)
2. **Every tool call passes the Policy Guard.** Capability permission → risk
   → approval tier → budget → availability. All decisions audited as
   hash-validated graph nodes. (Implemented: `policy_guard`, 24 policy tests.)
3. **Evidence content is untrusted input.** OCR text, EXIF strings, captured
   pages, SIEM event payloads can all carry instructions. They live in the
   **data channel only** — never the control channel. An image cannot edit the
   objective, the plan, or the model's instructions.
4. **AI never gates safety paths.** The mobile SOS / dead-man's switch is
   deterministic and LLM-independent, forever.
5. **Everything the AI does is reproducible.** Tool versions, model versions,
   objective, plan, and graph state are pinned and shippable as a reproduction
   bundle with the case.

---

## 2. ARK Cognitive Architecture — 12 core units

THE ARK's AI is **not "one LLM"**. It is a cognitive layer that sits above
and across every security domain. The LLM is a *component inside* this layer,
behind the Model Gateway — never the architecture itself.

```
                         THE ARK
                            │
                  ┌─────────┴─────────┐
                  │   ARK COGNITIVE   │
                  │       LAYER       │
                  └─────────┬─────────┘
                            │
        ┌───────────────────┼────────────────────┐
        │                   │                    │
   CORE COGNITION      DOMAIN SPECIALISTS    TOOL LAYER
        │                   │                    │
        │             ┌─────┼─────┐              │
        │             │     │     │              │
        │           IMAGE NETWORK SECOPS      ExifTool
        │           OSINT WEB                 Suricata / OCR / GIS / APIs
        │
        └────────────── CASE / EVIDENCE ──────────────┘
```

**The separation rule** (what keeps this from becoming "a giant prompt with
200 functions attached"):

| Concern | Owner |
|---|---|
| Understands the domain | **Specialist** (knowledge + tool-selection layer) |
| Knows what can execute | **Tool Registry** |
| Decides what *may* execute | **Policy Governor** |
| Decides what to do next | **Orchestrator** |
| Records what actually happened | **Evidence layer** |
| Challenges conclusions | **Critic** |
| Formalizes conclusions | **Findings Engine** |
| Preserves the investigation | **Case system** |

### The 12 core units → module map

| # | Unit | Responsibility | Module | Status |
|---|---|---|---|---|
| 01 | **Orchestrator** | Conducts: domain → specialist → tools → sequence → sufficiency | `agent/orchestrator.py` | Phase C |
| 02 | **Investigation Planner** | Objective → structured plan; revises on new evidence | `agent/planner.py` | Phase C |
| 03 | **Tool Router** | AI intent → registered tool (ExifTool / C2PA / OCR / SIEM…) | `agent/tool_registry.py` | ✅ Phase A |
| 04 | **Evidence Correlator** | Links results across tools; support/contradiction | `agent/correlator.py` (+ `evidence_graph`) | Phase E |
| 05 | **Hypothesis Engine** | Ranked, evidence-tagged hypotheses, never facts | `agent/hypothesis.py` (contract: `Hypothesis`) | Phase E |
| 06 | **Verification / Critic Engine** | Challenges conclusions; independent-evidence checks | `agent/critic.py` (contract: `Critique`) | Phase E |
| 07 | **Context & Memory Engine** | Immediate / investigation / session / case / org context | `agent/context_memory.py` (contract: `ContextFrame`) | Phase C (light) |
| 08 | **Policy / Permission Governor** | Tool/target/tenant authorization, risk→approval, budgets | `agent/policy_guard.py` | ✅ Phase B |
| 09 | **Model Gateway** | Model abstraction: local/cloud/vision/embedding/OCR; provider-agnostic | `agent/model_gateway.py` (contract: `ModelSpec`) | Phase C |
| 10 | **Findings Engine** | Conclusions → structured `Finding` (type/severity/status/evidence) | `agent/findings.py` (+ `evidence_graph`) | Phase C (wiring) |
| 11 | **Analyst Interaction Engine** | Natural-language steering → controlled ARK actions | `agent/interaction.py` + frontend | Phase D |
| 12 | **Report / Communication Engine** | Writes from case state only; never invents | `agent/report_engine.py` | Phase I |

Units 03 and 08 **exist and are verified** (Phase A/B). Units
01, 02, 07, 09, 10 are Phase C's build surface — **done** (see §3). Units
04, 05, 06 are Phase E.
Unit 11 is Phase D, unit 12 is Phase I.

### Domain specialists — not separate AI brains

Specialists are *knowledge + tool-selection layers* on top of the same
cognitive core. Same orchestrator, same graph, same governor — only the
specialist and its tool set change.

| Specialist | Understands | Tool set (first wave) | Status |
|---|---|---|---|
| 🖼 **IMAGE Intelligence** | EXIF/XMP/IPTC/MakerNotes, JPEG, provenance, geolocation, OCR, visual clues, source history | hash, ExifTool, JPEG/ELA, OCR, vision, C2PA, reverse search, geocoding, GIS, weather, solar, similarity | ✅ 16 registered tools |
| 🌐 **NETWORK Intelligence** | hosts, services, protocols, traffic, topology, certificates | discovery, service inventory, traffic, topology, DNS-as-evidence | Phase F |
| 🛡️ **THREAT & SECOPS** | SIEM, IDS/IPS, events, correlations, incidents, hunting, telemetry | SIEM query, threat hunt, correlation, incident annotate | Phase F |
| 🌍 **OSINT / Intelligence** | public sources, entities, relationships, timelines, credibility | source search, entity extraction, relationship build, timeline | Phase F |
| 🌐 **WEB / App Security** | HTTP, APIs, sessions, apps, endpoints, auth flows | proxy, HTTP history, endpoint map, app structure | Phase F |

### Cases are the shared memory, not a brain

A case collects **IMAGE + NETWORK + SECOPS + OSINT + WEB** evidence. The AI
correlates *across* them — the image's IP, the network's suspicious host, the
OSINT source, and the SECOPS alert become nodes on one graph, and the
correlator can surface "these artifacts are potentially related." That is the
integrated security environment: **one cognitive core, many specialists, one
case/evidence fabric.**

---

## 3. Verified baseline (today)

| Component | Status | Evidence |
|---|---|---|
| 4-tier deterministic pipeline | ✅ working | 4 test files, integration tests |
| Phase A — Tool Registry + Evidence Graph | ✅ done | `tests/test_agent_substrate.py` — 18 passing |
| Phase B — Policy Guard + audit emission | ✅ done | `tests/test_agent_policy.py` — 24 passing |
| Full backend suite | ✅ green | **269 passed** on Python 3.13 |
| Phase C — planner → guard → executor → graph | ✅ done | `tests/test_phase_c_investigate.py` — 16 passing; live run vs `qwen2.5-coder:3b` (model-proposed plan executed, findings promoted) |
| Phase D — Investigation Console (PLAN / AGENT / EVIDENCE) | ✅ done | `BottomPanel.tsx` PLAN (objective + merged revision chain + approve/resume + gaps), AGENT (tool activity + budget burn), EVIDENCE (findings / corroboration + contradiction edges / nodes / hypotheses / critiques); `api.ts` create/approve/get/resume; `tsc --noEmit` clean |
| Phase E — Adaptive re-planning + budgets | ✅ done | `tests/test_phase_e_adaptive.py` — 17 passing (contradiction → hash-chained delta → in-budget exit, budget pause → resume, memoization, gap semantics); live run: model closed `GAP-D35B9B2C` open-contradiction, 4 iterations, done at 7/25 steps |
| Phase F — Cross-domain NETWORK + SECOPS | ✅ done | `tests/test_phase_f_cross_domain.py` — 13 passing; NETWORK + SECOPS specialists route registered tools through the unchanged loop, evidence on the shared case graph; `port_scan`/`incident_annotate` gated by step-confirm; merged plan lineage on the console |
| ARK Identity Contract (cognitive layer §6) | ✅ done | `app/agent/cognitive/` 00-05 core + `app/agent/domains/` identity/reasoning/tools for image/network/secops/osint/web/cases; `context_builder.py` composes core → domain → tools; gateway routes through it; `tests/test_identity_contract.py` — 13 passing; live qwen runs produce valid registered-only plans |
| Frontend workbench | ✅ builds | `tsc --noEmit` clean, vite build clean |
| Local LLM runtime | ✅ ready | Ollama 0.32.9 on-host, **qwen2.5-coder:3b cached** (1.9 GB), responds to API |

### Environment fixes applied during verification
- `Pillow==10.3.0` / `pydantic==2.7.1` pins do not build on Python 3.13 →
  upgraded to compatible versions. **Action:** pin the working set in
  `requirements.txt` (do not ship floats).
- `exiftool` binary missing on this host → installed via Homebrew. Add a
  preflight check to backend startup.

---

## 4. Model strategy — start small, on-host, domain-agnostic

Phase C runs on **qwen2.5-coder:3b via Ollama** (already on this Mac, no
download). Coder-tuned models are imperfect planners; that is *fine* — Phase C
proves the loop and the failure modes with a cheap local model, and the
orchestrator is written model-agnostic so we swap in a stronger/larger model
without touching the loop.

| Role | Phase | Model |
|---|---|---|
| Planning / routing (first cut) | C–D | qwen2.5-coder:3b (local, cached) |
| Planning / routing (later) | E+ | stronger local or remote reasoning model, chosen by policy |
| Scene / vision reasoning | E+ | vision-capable model (local or provider) |
| Embeddings / similarity | F+ | local embedding model |
| Sensitive / offline analysis | any | force local model via policy (`zero_retention`), never external |

**Rule:** the system decides which model runs, via the same registry/policy
machinery as tools. Model choice is recorded on every node (`model_id` +
version) — part of provenance, not an implementation detail.

---

## 5. The phased build

Each phase has an exit gate (tests / demo) and **keeps the deterministic
pipeline untouched**. `DomainId` in the schema is already
`image | network | secops | cross`; the code path is domain-neutral from
Phase C onward.

### Phase C — Smallest orchestrator loop  ← NEXT
*Builds cognitive units 01, 02, 07, 09, 10. One objective, one goal, one
closed loop. Image is the first domain because its pipeline is mature, but
the loop itself is domain-agnostic.*

- **New endpoint** `POST /api/v1/investigate` — takes a typed objective.
- **Planner** — maps goal → plan template → concrete `PlanStep`s. First goal:
  `verify_location_credibility`. LLM proposes ordering + reasoning;
  deterministic template is the fallback if the model is unreachable
  (model must never be a hard dependency).
- **Executor** — for each step: `PolicyGuard.authorize(tool_id)` →
  `registry.acall(id, **args)` → write evidence node (+ audit node +
  `derived_from` edge). Skips/pauses on `PermissionDenied` /
  `BudgetExceeded` / `ToolUnavailable`.
- **Approval model** — plan returned to caller with `status=proposed`;
  approval: `approve` | `amend` (analyst edits steps/args) | `reject`.
  Amendment is itself an audited human decision node.
- **Convergence** — stop when claims resolved, or after N steps with no new
  corroborating/contradicting evidence, or budget exhausted → `pause_to_ask`.
- **New adapter** `app/agent/llm/ollama.py` — thin Ollama client
  (`qwen2.5-coder:3b`), JSON-schema-constrained output, timeout, non-streaming.
  Model calls are **not** tools; they feed the planner only.
- **Tests** — planner (template selection, fallback), executor (authorize/
  skip/audit), endpoint integration with a stub LLM. **Exit gate:**
  end-to-end `objective → plan → execute → evidence → assessment` on a
  fixture image with the real local model.

### Phase D — Investigation Console (PLAN / AGENT / EVIDENCE)
*Builds cognitive unit 11 (analyst interaction surface).*
- Bottom panel gains the three substrate tabs first: PLAN (objective + steps +
  approve/amend), AGENT (tool activity log), EVIDENCE (graph viewer).
- These make the loop visible and steerable. ANALYSIS/AUDIT/OUTPUT/TERMINAL
  attach as the substrate supports them; TERMINAL stays capability-gated —
  command execution is a registered `exec:*` tool behind policy, never a raw
  shell the agent drives.
- Exit gate: analyst can start an AI investigation from the IMAGE workspace,
  see the plan, approve/amend, watch execution, and inspect graph evidence.

### Phase E — Adaptive re-planning + budgets
*Builds cognitive units 04 (correlator), 05 (hypothesis engine), 06 (critic).*
- Graph-state-aware next-action selection: the orchestrator derives **gaps**
  from the graph (missing corroboration, open contradictions, unverified
  claims) and the model proposes among those + termination — not free-form
  tool picking.
- Hard budgets (steps / tokens / ms / API calls) with `pause_to_ask` on
  exhaustion; budget estimate rendered on the plan **before** approval.
- **Tool-call memoization**: `(tool_id, args_hash)` result reuse on the graph —
  re-plans become cheap and consistent.
- Exit gate: a contradiction detected mid-run triggers a re-plan delta
  (append-only, hash-chained) that terminates within budget.

### Phase F — Cross-domain: NETWORK + SECOPS specialists register
The payoff of the registry-first decision. Register the NETWORK and SECOPS
specialists (unit 03 routers for their domains); the orchestrator, graph,
console, and guard are unchanged.
- **NETWORK** (first wave): `discover_hosts` (low), `fingerprint_service`
  (elevated), `port_scan` (high, step-confirm), `tls_inspect` (elevated).
- **SECOPS** (first wave): `siem_query` (low), `threat_hunt` (elevated),
  `detect_correlation` (medium), `incident_annotate` (medium/action).
- Exit gate: a NETWORK objective and a SECOPS objective run end-to-end through
  the same loop, producing evidence on the same case graph.

### Phase G — Case engine unification
- Cases become cross-domain: one case collects image + network + secops
  evidence, findings span domains, contradiction edges cross domain
  boundaries ("SIEM shows logon at 09:00 UTC but EXIF says capture at 09:00
  UTC from a different device").
- The existing frontend CASES domain (CaseExplorer) reads from this engine.
- Exit gate: one case with evidence from ≥2 domains, one findings list, one
  audit trail.

### Phase H — Model routing (policy-decided)
- Model registry mirrors the tool registry: `ModelSpec` (id, capability,
  local/remote, cost, offline-ok, pinned version). Policy decides which model
  a planner or vision call may use; `zero_retention` forces local.
- Exit gate: a policy rule routes sensitive analysis to the local model and
  the finding records it.

### Phase I — Court-ready reproduction bundles
- Every case can export: objective frame, plan lineage (hash-chained),
  full evidence graph, tool + model + env versions, and a re-run manifest.
- Exit gate: export a case and re-derive a finding from the manifest alone.

### Phase J — Analyst productivity
- Reusable plan templates library (goal → template, versioned).
- Comparative runs (two objectives over one case; diff of evidence sets).
- Analyst decisions recorded as nodes (`confirm`/`reject`/`needs_review`)
  feeding the template library (what plans actually resolve cases).

---

## 6. The ARK Identity Contract — one brain, many domain identities

The cognitive layer is a **composed prompt architecture**, not one monolithic
system prompt. Identity ≠ domain prompt ≠ tool instructions. The runtime
composes, per investigation:

```
ARK CORE IDENTITY      ← 00_identity.prompt      (who ARK is, how it behaves)
+ ARK GOVERNANCE       ← 01_governance.prompt    (what ARK is allowed to do)
+ ARK TOOL CONTRACT    ← 02_tool_contract.prompt  (tool-first, registered-only)
+ ARK EVIDENCE CONTRACT← 03_evidence_contract.prompt (FACT/OBSERVATION/INFERENCE/ASSESSMENT)
+ ARK REASONING POLICY ← 04_reasoning_policy.prompt  (verifiable work, not plausible prose)
+ ARK REPORTING CONTRACT ← 05_reporting_contract.prompt (one output shape for all domains)
+ <DOMAIN> SPECIALIST  ← domains/<domain>/{identity,reasoning,tools}.prompt
+ AVAILABLE TOOLS      ← dynamic, from the Tool Registry
```
The user message carries case context: objective goal, subject/scope,
natural language, claims to verify (and gap + budget state for adaptive
steps). The core is immutable; only the domain block and tool surface swap.

### Files (prompt files are data, not code)
- `app/agent/cognitive/00_identity.prompt` … `05_reporting_contract.prompt`
  — the stable ARK core (identity, governance, tool contract, evidence
  contract, reasoning policy, reporting contract).
- `app/agent/domains/{image,network,secops,osint,web,cases}/`
  `{identity,reasoning,tools}.prompt` — per-domain specialist identity.
  Domain keys match `SpecialistSpec.domain`. OSINT/WEB/CASES exist as
  identity contracts now; their engines register later (architectural
  placeholders, same as NETWORK/SECOPS were pre-Phase F).
- `app/agent/context_builder.py` — runtime composer. Missing files degrade
  gracefully (skip section); the model gateway is never a hard dependency.
- `app/agent/model_gateway.py` — planner + adaptive calls route through the
  composed contract.

### Identity establishes
ARK investigates, it doesn't guess — if a tool can verify something, call
it and state exactly what was found. ARK distinguishes evidence from
inference (FACT / OBSERVATION / INFERENCE / ANALYST ASSESSMENT). ARK is
domain-agnostic and tool-first. ARK is human-controlled (the analyst
remains final decision-maker). ARK is security-conscious (tenant isolation,
permissions, tool risk, authorization, evidence integrity, audit). Persistent
internal principle: **never optimize for sounding intelligent — optimize for
producing verifiable investigative work.**

### Cases are not a specialist brain
`domains/cases/` is the shared intelligence + evidence-management layer. It
preserves, organizes, reconciles, and reports; it never invents conclusions.

### Verification
`tests/test_identity_contract.py` — 13 passing: prompt-file inventory for all
declared domains, section ordering, domain-block swap with stable core,
dynamic tool injection (no cross-domain leakage), graceful degradation,
case-context user prompt, gateway routing through the composed contract, and
call-site compatibility. Live vs `qwen2.5-coder:3b`: the model produced
valid registered-only plans under the composed identity for NETWORK, SECOPS,
and IMAGE, and a full NETWORK objective ran end-to-end (discover_hosts →
fingerprint_service → adaptive tls_inspect).

---

## 6b. "And more" — the longer arc

- **Prompt-injection evaluation suite** — a regression fixture set: images,
  OCR text, and captured pages crafted to steer the agent; every Phase C+
  release must not be steerable off its objective.
- **Observability** — every agent run emits telemetry (step timing, budget
  burn, graph deltas) so investigation *costs* are visible per case.
- **Domain-agnostic sharing** — OSINT, cyber threat intel, and identity
  domains register tools under the same `DomainId`; nothing new in the core.
- **Deterministic-first principle in perpetuity** — if a step can be answered
  by a registered deterministic tool, the planner must prefer it; the LLM
  decides sufficiency, not whether SHA-256 or ExifTool should run.

---

## 7. Immediate next actions

1. Commit the env fixes: pin the working `requirements.txt` set (Pillow,
   pydantic, fastapi resolved on Python 3.13) and add an `exiftool` preflight
   check. *(Small, safe, unblocks CI/onboarding.)*
2. Phase F follow-up — register OSINT + WEB domains the same way NETWORK +
   SECOPS landed (`tool_registry.py` handlers, `_CLAIM_TYPES`/`_MISSING_LAYERS`
   rows, planner templates, `goal_mappings`, executor arg branches, per-domain
   tests). The loop is already domain-agnostic, so this is additive-only.
3. Wire real handler bodies behind the deterministic offline adapters
   (`discover_hosts` → subnet sweep, `siem_query` → SIEM API, etc.) with the
   network/admin approval carve-outs already reserved in `PolicyGuard`.
4. Write the first prompt-injection fixtures (the doc mandates these land
   before the agent touches external content — OSINT/WEB tools are the first
   that ingest external input).
