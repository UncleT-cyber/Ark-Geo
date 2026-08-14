# THE ARK — AI Orchestration Architecture Spec

> Status: **Design — Draft for review**
> Scope: Tool Registry, Evidence Graph, Policy/Permission Guard, Investigation
> Objective frames, Plan lineage. Defines the contracts the ARK AI orchestrator
> (Phase B+) will consume. Phase A implements the substrate with **no AI** and
> **zero behavior change** to the existing deterministic pipeline.

## 1. Design principles

1. **Three-investigator separation is epistemic.** ARK Core outputs are
   cryptographic facts / deterministic tool outputs. ARK AI outputs are
   hypotheses. A hypothesis **cannot be promoted to a finding** without a
   corroborating node of higher epistemic weight. This rule is enforced in the
   consensus engine, not by prompt etiquette.
2. **The Evidence Graph is the spine; tools are leaves.** Tools and the AI
   both read/write the graph. The AI plans against graph state, not against a
   list of untried tools. Contradictions are negative-weight edges → correlation
   is graph traversal (compute), not prompt engineering.
3. **Plan-before-execute is the transparency surface.** The plan is the
   public, auditable artifact. Chain-of-thought is never exposed — it is not
   stable evidence and changes with model versions.
4. **Plans are persisted, hash-chained, append-only.** Re-plans append
   deltas; nothing is overwritten. Plan lineage is a causal DAG of
   investigative decisions — defensible in court.
5. **Tool Registry is the universal contract.** Every capability the AI
   calls is registered with schema, risk, permissions, provider, cost. The AI
   sees a capability surface; policy sees an authorization surface.
6. **AI does not replace deterministic tools.** It decides *when results
   are sufficient and what happens next*. SHA-256 is never an LLM call.
7. **Mobile safety HUD stays deterministic.** The dead-man's switch / SOS
   path is safety-critical and never depends on an LLM being reachable. The AI
   orchestrator lives on the analyst/backend side only.

## 2. Epistemic provenance tiers

Every evidence node carries a `provenance_type`:

| Tier | Label | Examples | Admissibility |
|------|-------|----------|---------------|
| 0 | `cryptographic` | SHA-256, custody hash, file magic | Self-evident |
| 1 | `tool_inference` | ExifTool output, OCR text, ELA, C2PA verify | Reproducible |
| 2 | `ai_hypothesis` | Vision-model coordinate estimate, LLM correlation | Corroborable only |

Promotion rule (enforced structurally):
- A tier-2 node may contribute to a **finding** only if >=1 corroborating node
  (tier 0 or 1) supports the same claim, OR >=2 independent tier-2 nodes agree
  within tolerance.
- A tier-2 node may **never** override a tier-0/1 node that contradicts it.
  The contradiction is recorded as an edge; the finding reflects the higher
  tier.

This is the single most important forensic guarantee in the architecture.

## 3. Tool Registry schema

```python
class RiskLevel(str, Enum):
    LOW = "low"             # read / deterministic analysis on ingested evidence
    MEDIUM = "medium"       # action: create finding, attach evidence, update case
    ELEVATED = "elevated"   # external provider call, cost-bearing
    HIGH = "high"           # active: network scan, shell exec — per-step confirm

class ToolCategory(str, Enum):
    READ = "read"
    ANALYSIS = "analysis"
    ACTION = "action"
    HIGH_RISK = "high_risk"

class ToolSpec(BaseModel):
    tool_id: str                        # "extract_exif", stable, kebab
    name: str                           # human label
    description: str                    # surfaced to the planner LLM
    domain: DomainId                    # "image" | "network" | "secops" | "cross"
    category: ToolCategory
    risk: RiskLevel
    input_schema: dict                  # JSON Schema for arguments
    output_schema: dict                 # JSON Schema for result
    permissions: list[Permission]       # capabilities required to invoke
    provider: str                        # "exiftool" | "ark_module" | "geospy" | ...
    timeout_ms: int = 30000
    cost_estimate: CostEstimate | None = None
    availability: Availability = Availability.AVAILABLE
    audit_required: bool = True         # write an audit node on every call
    deterministic: bool = True          # False for AI/vision tools
    idempotent: bool = True             # same input -> same output
```

`CostEstimate` carries `model_tokens` / `api_calls` / `est_ms` so the planner
respects budgets. `Availability` in
`available | disabled | requires_key | requires_confirmation`.

### Capability-based permissions

Permissions are composable capabilities, not role allowlists:

```python
class Permission(str, Enum):
    READ_EVIDENCE = "read:evidence"
    CALL_PROVIDER = "call:provider"           # parameterized: call:provider:geospy
    MUTATE_CASE = "mutate:case"
    EXEC_SHELL = "exec:shell"
    QUERY_EXTERNAL = "query:external"         # reverse image search, geocoder
```

`call:provider:<name>` is parameterized so policy can allow GeoSpy but block an
unvetted provider without touching tool code.

## 4. Evidence Graph schema

```python
class EvidenceNode(BaseModel):
    node_id: str                        # "ARK-EVN-XXXXXXXX"
    case_id: str
    tool_id: str                        # producing tool (or "human")
    provenance_type: ProvenanceType     # cryptographic | tool_inference | ai_hypothesis
    claim: str                          # short natural-language claim
    claim_type: ClaimType               # location | timestamp | device | source | integrity | ...
    value: Any                          # structured payload (coords, hash, text, ...)
    confidence: float                   # 0.0-1.0 (1.0 for tier 0)
    model_id: str | None = None         # for tier-2: which model/version
    produced_at_ms: int
    hash: str                           # hash of node payload — tamper-evidence

class EvidenceEdge(BaseModel):
    edge_id: str
    src: str                            # node_id
    dst: str                            # node_id
    relation: EdgeRelation              # corroborates | contradicts | derived_from | same_asset | supersedes
    weight: float                       # +corroborate / -contradict magnitude
    created_at_ms: int
    note: str | None = None

class EvidenceGraph(BaseModel):
    case_id: str
    nodes: dict[str, EvidenceNode]
    edges: list[EvidenceEdge]
    plan_id: str | None = None          # active plan
```

### Operations (pure, audited)

- `add_node(node)` — validates hash, writes node + audit node.
- `add_edge(edge)` — records relationship. `contradicts` edges have negative
  weight; `corroborates` have positive weight.
- `promote_to_finding(node_id, claim)` — applies the promotion rule; raises
  `PromotionDenied` if a tier-2 node lacks corroboration.
- `contradictions_for(node_id)` — graph query returning contradicting edges.
- `corroboration_score(node_id)` — sum of edge weights; basis for consensus.

The existing `ConsensusEngine` and `contradiction_engine` will be refactored to
read/write this graph rather than ad-hoc lists.

## 5. Policy / Permission Guard schema

```python
class ApprovalTier(str, Enum):
    AUTO = "auto"                   # low risk, in-budget — no human gate
    CONFIRM_ONCE = "confirm_once"   # whole-plan approval (medium risk / action)
    STEP_CONFIRM = "step_confirm"   # per-step approval (high risk / active)

class PolicyRule(BaseModel):
    rule_id: str
    match: PolicyMatch              # tool_id glob, risk>=, category, domain
    approval_tier: ApprovalTier
    budget: Budget | None            # max steps / tokens / ms / cost
    require_confirmation_for: list[ToolCategory] = []
    enabled: bool = True

class PolicyDecision(BaseModel):
    allowed: bool
    approval_tier: ApprovalTier
    reason: str
    rule_id: str
```

Policy is versioned and itself audited. The guard evaluates a `PolicyDecision`
per tool call; the executor proceeds only when `allowed=True` and the required
approval (if any) has been recorded as an audit node. Budgets prevent
non-termination of adaptive re-planning.

## 6. Investigation Objective frames

Objectives are typed, not free text — for reproducibility and plan templates.

```python
class InvestigationGoal(str, Enum):
    VERIFY_LOCATION_CREDIBILITY = "verify_location_credibility"
    DEVICE_ATTRIBUTION = "device_attribution"
    TAMPER_DETECTION = "tamper_detection"
    SOURCE_DISCOVERY = "source_discovery"
    FULL_FORENSIC_PROFILE = "full_forensic_profile"

class ClaimToVerify(BaseModel):
    field: str        # "capture_location" | "capture_datetime" | "device" | ...
    value: Any

class ObjectiveConstraints(BaseModel):
    skip_external_sources: bool = False
    prioritize: list[str] = []      # tool_ids
    exclude: list[str] = []         # tool_ids
    budget: Budget | None = None
    zero_retention: bool = False

class InvestigationObjective(BaseModel):
    objective_id: str
    goal: InvestigationGoal
    subject: str                        # evidence_id or case_id
    claims_to_verify: list[ClaimToVerify] = []
    constraints: ObjectiveConstraints
    natural_language: str | None = None  # optional override
```

Each goal maps to a **plan template** (versioned). The planner selects a
template, fills it from the objective + current graph state, and adapts it.
Free-text objectives are parsed into this frame; they do not bypass it.

## 7. Plan lineage

```python
class StepStatus(str, Enum):
    PROPOSED = "proposed"; APPROVED = "approved"; RUNNING = "running"
    DONE = "done"; SKIPPED = "skipped"; FAILED = "failed"

class PlanStep(BaseModel):
    step_id: str
    tool_id: str
    arguments: dict
    rationale: str                    # why this step (graph-edge reference)
    status: StepStatus
    result_node_id: str | None = None  # evidence node produced
    started_at_ms: int | None = None
    completed_at_ms: int | None = None

class PlanRevision(BaseModel):
    revision_id: str
    parent_revision_id: str | None     # None for initial proposal
    objective_id: str
    steps: list[PlanStep]
    delta_reason: str | None = None    # why re-planned (contradiction id, etc.)
    proposed_at_ms: int
    approved_at_ms: int | None = None
    approved_by: str | None = None     # "human" | "policy:auto"
    hash: str                          # hash of revision payload — tamper-evidence
```

Plans are append-only: a re-plan creates a new `PlanRevision` whose
`parent_revision_id` points at the prior one. The revision chain is the causal
DAG of investigative decisions. Hash-chaining gives tamper-evidence consistent
with the existing custody certificate.

### Adaptive re-planning termination

Re-planning is triggered by new graph state (a contradiction edge, a missing
corroboration). It terminates when:
- the objective's claims are resolved (finding promoted or refuted), **or**
- no new corroborating/contradicting evidence after N consecutive tools, **or**
- the policy budget is exhausted -> `pause_to_ask` the analyst.

## 8. Build phasing

| Phase | Scope | AI? | Behavior change |
|-------|-------|-----|-----------------|
| **A** | Tool Registry + Evidence Graph schema + wrap existing deterministic tools | None | Zero — pure scaffolding |
| B | Policy Guard (capability checks, budgets, audit nodes) | None | Adds gates, no new outputs |
| C | Smallest orchestrator loop: planner + executor for one goal (`verify_location_credibility`), single re-plan | Yes | New `/investigate` path; `/analyze` untouched |
| D | Investigation Console: PLAN / AGENT / EVIDENCE tabs | View only | UI over existing state |
| E | Adaptive re-planning + contradiction loops + cost budgets | Yes | Dynamic behavior |
| F | Cross-domain reuse: register network/secops tools | Yes | Orchestrator is domain-agnostic |

## 9. Existing deterministic tools to register (Phase A inventory)

| tool_id | Wraps | Risk | Category | Output (node claim_type) |
|---------|-------|------|----------|--------------------------|
| `compute_custody_hash` | `security.custody_certificate` | low | read | integrity |
| `validate_format` | `security.validate_magic_bytes` | low | read | integrity |
| `extract_exif` | `MetadataExtractor.extract` | low | read | device / location / timestamp |
| `extract_deep_metadata` | `exiftool_service.extract_deep` | low | read | device / metadata |
| `reverse_geocode` | `metadata_extractor.reverse_geocode` | low | read | location |
| `resolve_telemetry` | `TelemetryService.resolve` | low | read | location |
| `analyze_ela` | `metadata_extractor.generate_ela_heatmap` | low | analysis | integrity |
| `detect_eof_anomaly` | `metadata_extractor.detect_eof_anomaly` | low | analysis | integrity |
| `verify_c2pa` | `c2pa_service.analyze` | low | analysis | source / integrity |
| `run_consistency` | `consistency_engine.analyze` | low | analysis | integrity / timestamp |
| `run_ocr` | `OcrTextExtractor.extract` | elevated | analysis | location (text) |
| `fuse_geolocation` | `geolocation_fusion.fuse` | medium | analysis | location |
| `discover_sources` | `source_discovery.analyze` | elevated | analysis | source |
| `detect_contradictions` | `contradiction_engine.detect` | low | analysis | (graph edges) |
| `run_vision_ensemble` | `VisionEnsemble.query` | elevated | analysis | location (ai_hypothesis) |
| `aggregate_consensus` | `ConsensusEngine.aggregate` | medium | analysis | location |

Tier-2 tools set `deterministic=False` and carry `model_id`.
