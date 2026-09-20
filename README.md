# THE ARK (ArkGeo)

An **AI-native security investigation platform** — not "an app with some AI."
The AI is the investigation conductor; the deterministic forensic core is the
trusted machinery it orchestrates.

> "The user decides what to investigate. The system guarantees what can be
> trusted and what can be executed. The AI figures out how to investigate it
> efficiently."

## The three investigators

The system is designed as three complementary roles — never competing:

| Investigator | Role | Outputs |
|---|---|---|
| **Human** | Intent, judgment, authorization, final assessment | Objectives, approvals, findings review |
| **ARK Core** | Evidence preservation, deterministic analysis, integrity, execution | Facts (cryptographic hashes, ExifTool, OCR, C2PA, consensus) |
| **ARK AI** | Planning, orchestration, correlation, hypothesis generation | Hypotheses, plans, explanations |

**Epistemic separation is structural, not by prompt.** ARK Core outputs are
facts; ARK AI outputs are hypotheses. A hypothesis **cannot be promoted to a
finding** without corroboration from a higher epistemic tier
(cryptographic → tool inference → AI hypothesis) — enforced in the evidence
graph, so a contradiction always resolves in favor of the higher tier.

## Two entry modes

### 1. Direct Evidence Mode (deterministic)
The traditional workflow stays. Upload → hash → EXIF/XMP/IPTC → JPEG/ELA →
OCR → vision → GPS → C2PA → consensus → investigation workspace.
Predictable, reproducible, court-ready. For analysts who already know what
they want to examine.

### 2. AI Investigation Mode (agentic)
Start with an *objective*, not a file:

> "Determine whether the image's claimed capture location and date are credible."

ARK proposes a plan, the analyst approves or modifies it ("skip external
source discovery", "prioritize device attribution"), then ARK executes it via
the tool registry. The plan adapts to what it learns — if EXIF GPS exists it
corroborates coordinates instead of spending budget on visual geolocation.

```
User → Objective → Plan → Approval → Tools → Evidence → Correlation → Findings → User review → Case
```

The upload workflow and the AI workflow are complementary entry points to the
same evidence graph, not competing systems.

## Architecture

```
                    HUMAN
                      │  intent / objective
                      ▼
              ARK AI ORCHESTRATOR
              (plan · route · correlate)
                      │
          ┌───────────┼───────────┐
          ▼           ▼           ▼
      ANALYSIS     EVIDENCE    PROVIDERS
      ENGINES      GRAPH       / APIS
          │           │           │
          └───────────┼───────────┘
                      ▼
              ARK CORE (deterministic)
              + ARK TOOL REGISTRY
```

- **Tool Registry** — every capability the AI can call is registered:
  tool id, name, description, domain, input/output schema, permissions,
  risk level, provider, timeout, cost, availability, audit requirement.
  The AI sees tools, not scattered functions.
- **Evidence Graph** — the spine. Tamper-evident, hash-validated nodes and
  edges (corroborate/contradict/derived-from). Plans and tool calls are
  audited onto the graph.
- **Policy Guard** — the authorization surface. Capability permissions,
  risk→approval tiers (auto / confirm_once / step_confirm), budgets, and
  availability gating sit between planner and execution.
- **Investigation Console** — the bottom panel is an execution surface for
  both analyst and agent: PLAN · AGENT · ANALYSIS · EVIDENCE · AUDIT ·
  OUTPUT · TERMINAL, under controlled permissions.

## Repository

| Directory | What |
|---|---|
| `arkgeo-backend` | FastAPI "Brain" — 4-tier deterministic pipeline + `app/agent/` orchestration substrate |
| `arkgeo-investigator-web` | React/Vite forensic OSINT workbench (THE ARK) |
| `arkgeo-mobile` | React Native/Expo companion — **de-prioritized**. Desktop/web are the primary investigation surfaces; mobile is a future optional companion |

## Implemented today

- **4-tier pipeline** — EXIF metadata → vision ensemble → clue extractors →
  Bayesian consensus (all deterministic)
- **Phase A** — tool registry + tamper-evident evidence graph (18 tests)
- **Phase B** — policy/permission guard + audit emission (24 tests)
- **THE ARK ISE** — Integrated Security Environment, workspace-based IA
  (IMAGE / NETWORK / SECOPS / CASES)
- **154 backend tests passing**, `tsc --noEmit` clean, clean production build

## Roadmap

| Phase | Scope |
|---|---|
| C | Smallest orchestrator loop: planner + executor for one goal (`verify_location_credibility`), one re-plan, `/investigate` endpoint |
| D | Investigation Console: PLAN / AGENT / EVIDENCE tabs |
| E | Adaptive re-planning, contradiction loops, cost budgets |
| F | Cross-domain reuse: register network/secops tools |
| G–J | Case engine unification, model routing, court-ready bundles, analyst productivity |

Master plan (integrated security environment, phases C–J):
[`docs/ARK_INTEGRATED_SECURITY_ENVIRONMENT.md`](docs/ARK_INTEGRATED_SECURITY_ENVIRONMENT.md).
Contracts (registry / graph / policy / objectives):
[`docs/ARK_AI_ORCHESTRATION_SPEC.md`](docs/ARK_AI_ORCHESTRATION_SPEC.md).

## Quick start

```bash
# Backend (port 8000)
cd arkgeo-backend && pip install -r requirements.txt
python -m pytest tests/ -q
python -m uvicorn main:app --reload

# Web workbench (port 12001, proxies /api → :8000)
cd arkgeo-investigator-web && npm install
npm run dev
```

## Security posture

- AES-256-GCM encryption, JWT + bcrypt auth, SHA-256 chain-of-custody
- Zero-retention mode for forensic uploads
- Every tool call audited; secrets hashed, never stored raw
- AI never runs outside the policy guard; high-risk actions require
  explicit human confirmation
