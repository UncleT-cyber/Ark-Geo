THE ARK — Integrated Security Environment
<div align="center">
AI-Native Security Investigation Platform
THE ARK unifies deterministic forensic analysis, evidence management, security operations, agentic reasoning, and controlled tool execution into a single operational control plane.
</div>
> Core Principle: The human operator determines what to investigate. THE ARK determines what can be trusted, what can be safely executed, and how the investigation is recorded with cryptographic integrity.
> 
Originating as ArkGeo (an image-forensics and visual intelligence platform), THE ARK has evolved into a multi-domain security control plane while retaining its deterministic forensic foundations.
🏛️ Tripartite Investigation Model
THE ARK strictly separates responsibilities between three distinct entities to maintain epistemic rigor and operational safety:
| Entity | Role | System Outputs |
|---|---|---|
| Operator (Human) | Intent, judgment, policy authorization, final assessment | Objectives, gating approvals, case disposition |
| ARK Core | Deterministic analysis, evidence preservation, cryptographic hashing, tool runtime | Verified facts, sensor readings, raw logs, tool execution outputs |
| ARK AI / CAI Engine | Tactical planning, tool orchestration, multi-step reasoning, cross-domain correlation | Investigation plans, hypothesis generation, execution graph |
       FACTS & LOGS                  HYPOTHESES & PLANS             OBJECTIVES & GATING
┌─────────────────────────┐     ┌─────────────────────────┐     ┌─────────────────────────┐
│        ARK CORE         │     │     ARK AI / CAI        │     │     HUMAN OPERATOR      │
│  Deterministic Engine   │ ──► │   Agentic Orchestrator  │ ──► │    Final Assessment     │
└─────────────────────────┘     └─────────────────────────┘     └─────────────────────────┘

> Epistemic Constraint: An AI hypothesis is never automatically elevated to a finding. Evidence must corroborate AI-generated inferences through the Evidence Graph before case promotion.
> 
🤖 Integration of the CAI Robotics Framework
THE ARK integrates a customized fork of the CAI (Cybernetic AI / Robotics) Framework directly into its agent substrate (arkgeo-backend/app/engine/cai/).
Originally architected around autonomous agent loops, active perception, and tool execution under strict safety boundaries, the CAI framework provides THE ARK with a high-reliability ReAct (Reasoning + Acting) runtime.
Why CAI Robotics for Cybersecurity?
 * Deterministic Tool Binding: Security capabilities (nmap, extract_exif, fuse_geolocation) are exposed to agents as structured, schema-defined tools with controlled execution boundaries.
 * Closed-Loop Perception: Tool outputs feed directly back into the agent's cognitive state, enabling dynamic multi-step re-planning when new evidence is discovered.
 * Hardened Safety Boundaries: CAI agent actions pass through THE ARK's Policy Guard, ensuring tool execution remains subject to configured permissions and Human-In-The-Loop (HITL) authorization requirements.
 ┌──────────────────────────────────────────────────────────────────────────┐
 │                         THE ARK CONTROL PLANE                            │
 │                                                                          │
 │   ┌──────────────────────────────────────────────────────────────────┐   │
 │   │                    CAI ROBOTICS ENGINE (FORK)                    │   │
 │   │                                                                  │   │
 │   │   ┌───────────────┐     ┌───────────────┐     ┌───────────────┐  │   │
 │   │   │ Active        │ ──► │ Closed-Loop   │ ──► │ ReAct Tool    │  │   │
 │   │   │ Perception    │     │ Re-Planner    │     │ Dispatcher    │  │   │
 │   │   └───────────────┘     └───────────────┘     └───────┬───────┘  │   │
 │   └───────────────────────────────────────────────────────┼──────────┘   │
 └───────────────────────────────────────────────────────────┼──────────────┘
                                                             │
                                                             ▼
                                                    ┌─────────────────┐
                                                    │  POLICY GUARD   │
                                                    │  (HITL Gating)  │
                                                    └─────────────────┘

🔄 Dual Investigation Workflows
THE ARK bridges deterministic forensic workflows with dynamic agentic investigation loops.
1. Direct Evidence Workflow (Deterministic)
Designed for analysts conducting direct artifact inspections.
[Upload Artifact] ──► [SHA-256 Hash] ──► [EXIF/XMP/IPTC] ──► [ELA / Forensic Analysis]
                                                                      │
[Case File] ◄── [Evidence Graph] ◄── [Consensus Engine] ◄── [OCR / Geolocation]

2. Autonomous Agentic Workflow (Goal-Driven)
Designed for goal-driven, multi-step investigations.
[Operator Objective] ──► [CAI ReAct Planner] ──► [Policy Guard Validation]
                                                           │
[Case Disposition] ◄── [Evidence Correlation] ◄── [Tool Execution Stream]

🏗️ System Architecture
                                HUMAN OPERATOR
                                      │
                              intent / objectives
                                      │
                                      ▼
             ┌─────────────────────────────────────────────────┐
             │                ARK AI LAYER                     │
             │                                                 │
             │   CAI Robotics Runtime (ReAct Engine)           │
             │   Specialist Agents (IMINT, Net, SecOps)        │
             │   Hypothesis Generation & Correlation           │
             └────────────────────────┬────────────────────────┘
                                      │
                            policy / tool invocations
                                      │
              ┌───────────────────────┼───────────────────────┐
              ▼                       ▼                       ▼
      ┌───────────────┐       ┌───────────────┐       ┌───────────────┐
      │ TOOL REGISTRY │       │ POLICY GUARD  │       │ EVIDENCE GRAPH│
      │ (Capabilities)│       │ (HITL Gating) │       │  (Lineage)    │
      └───────┬───────┘       └───────┬───────┘       └───────┬───────┘
              │                       │                       │
              └───────────────────────┼───────────────────────┘
                                      ▼
             ┌─────────────────────────────────────────────────┐
             │                   ARK CORE                      │
             │                                                 │
             │   Deterministic Forensic Engines                │
             │   Central Config Vault & Provider Gateways      │
             │   Audit & Chain-of-Custody Emissions            │
             └─────────────────────────────────────────────────┘

🔒 Security Architecture & Guardrails
Policy Guard & HITL Gating
Every agent tool request emitted by the CAI runtime must pass through the Policy Guard before hitting the execution subsystem:
CAI Agent Proposal ──► [Policy Guard] ──► ┬──► [Auto-Approve] ──► Execute & Log
                                          ├──► [Confirm Once] ──► Operator Approval Overlay
                                          └──► [Step Confirm]  ──► HITL Interactive Prompt

Evidence Graph Lineage
Every investigative result is explicitly classified into an epistemic tier to prevent unsupported deductions from being treated as established facts:
FACT ──► OBSERVATION ──► INFERENCE ──► HYPOTHESIS ──► ASSESSMENT

 * FACT: Deterministic outputs such as cryptographic hashes, EXIF tags, tool measurements, and raw system results.
 * OBSERVATION: Extracted patterns such as OCR tokens, visual indicators, or detected artifacts.
 * INFERENCE: Corroborated deductions derived from available evidence.
 * HYPOTHESIS: AI-proposed explanations, spatial models, threat models, or investigative directions (tagged as ai_hypothesis).
 * ASSESSMENT: Final disposition reviewed and accepted by the human operator.
🌐 Security Investigation Domains
| Domain | Focus & Capabilities | Status |
|---|---|---|
| Image Intelligence (IMINT) | EXIF/XMP parsing, Error Level Analysis (ELA), OCR, visual clue extraction, geolocation fusion, C2PA provenance | ACTIVE |
| Network Security | Active/passive scanning (nmap), topology mapping, traffic inspection, PCAP analysis | ACTIVE |
| Threat & SecOps | SIEM ingestion, log correlation, IDS/IPS rule evaluation, alert triage | IN PROGRESS |
| OSINT | Open-source discovery, reverse visual search, domain and perceptual-hash matching | ACTIVE |
| Cases & Vault | Immutable evidence storage, chain-of-custody logging, formal audit bundle generation | ACTIVE |
📂 Repository Layout
.
├── arkgeo-backend/                  # FastAPI core engine & deterministic pipelines
│   ├── app/
│   │   ├── agent/                   # Specialist agent declarations & tool registries
│   │   ├── brain/                   # Deterministic forensic engines
│   │   ├── core/                    # Application configuration & security controls
│   │   └── engine/
│   │       └── cai/                 # Integrated CAI Robotics framework & ReAct runtime
│   └── tests/                       # Backend test suite
│
├── arkgeo-investigator-web/         # Unified React/Vite Investigation Workbench
│   ├── src/
│   │   ├── components/              # Workspace views
│   │   └── hooks/                   # SSE event streams & state synchronization
│
└── docs/                            # Architecture specifications & system design

⚡ Quick Start
Prerequisites
 * Python 3.11+
 * Node.js 18+
 * Local Ollama instance or supported external LLM API credentials (Gemini, OpenAI, HuggingFace)
1. Backend Engine Setup
# Navigate to backend directory
cd arkgeo-backend

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run backend unit & integration tests
python -m pytest tests/ -q

# Launch backend server (API Gateway at http://localhost:8000)
python -m uvicorn main:app --reload --port 8000

2. Web Workbench Setup
# Navigate to web application directory
cd arkgeo-investigator-web

# Install packages
npm install

# Launch Vite development server (Interface at http://localhost:5173)
npm run dev

📖 Documentation
 * Integrated Security Environment Specification
 * AI Orchestration & CAI Integration Architecture
🛡️ Design Principles
 * Evidence Before Assertion: Claims must be traceable to evidence, observations, or explicitly identified hypotheses.
 * Human Authorization: The human operator remains strictly responsible for objectives, approvals, and final assessment.
 * Controlled Execution: AI capabilities operate exclusively through registered tools and policy controls.
 * Auditability: Every investigation action leaves an immutable, inspectable audit trail.
 * Deterministic Foundations: Where deterministic tools can establish a fact, the system always prefers tool execution over LLM reasoning.
 * Least Privilege: Agents receive only the tools and permissions strictly required for the given investigation task.
<div align="center">
THE ARK — Investigate. Correlate. Preserve.
A security investigation environment where AI can reason and act without becoming the authority over the evidence.
</div>
