"""Pydantic schemas for the ARK AI orchestration substrate.

These are the *contracts* the orchestrator, policy guard, and investigation
console read and write. They are deliberately decoupled from the existing
forensic data models (``app.models``) so that the deterministic pipeline keeps
working unchanged; a Phase A tool wrapper adapts between the two.

See ``docs/ARK_AI_ORCHESTRATION_SPEC.md`` §3–7 for the design rationale.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- #
# Shared domain enum — mirrors the frontend DomainId
# --------------------------------------------------------------------------- #
DomainId = str  # "image" | "network" | "secops" | "cross"


def now_ms() -> int:
    """Current UTC time in epoch milliseconds."""
    return int(datetime.now(timezone.utc).timestamp() * 1000)


# --------------------------------------------------------------------------- #
# 3. Tool Registry
# --------------------------------------------------------------------------- #
class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    ELEVATED = "elevated"
    HIGH = "high"


class ToolCategory(str, Enum):
    READ = "read"
    ANALYSIS = "analysis"
    ACTION = "action"
    HIGH_RISK = "high_risk"


class Availability(str, Enum):
    AVAILABLE = "available"
    DISABLED = "disabled"
    REQUIRES_KEY = "requires_key"
    REQUIRES_CONFIRMATION = "requires_confirmation"


class Permission(str, Enum):
    """Composable capability permissions. ``call:provider`` is parameterized."""
    READ_EVIDENCE = "read:evidence"
    CALL_PROVIDER = "call:provider"
    MUTATE_CASE = "mutate:case"
    EXEC_SHELL = "exec:shell"
    QUERY_EXTERNAL = "query:external"


class CostEstimate(BaseModel):
    model_tokens: int = 0
    api_calls: int = 0
    est_ms: int = 0


class ToolSpec(BaseModel):
    """A registered capability the orchestrator may invoke."""
    tool_id: str
    name: str
    description: str
    domain: DomainId
    category: ToolCategory
    risk: RiskLevel
    input_schema: dict = Field(default_factory=dict)
    output_schema: dict = Field(default_factory=dict)
    permissions: list[Permission] = Field(default_factory=list)
    provider: str
    timeout_ms: int = 30000
    cost_estimate: Optional[CostEstimate] = None
    availability: Availability = Availability.AVAILABLE
    audit_required: bool = True
    deterministic: bool = True
    idempotent: bool = True


class ToolInvocation(BaseModel):
    """A concrete call to a registered tool (planned or executed)."""
    invocation_id: str
    tool_id: str
    arguments: dict = Field(default_factory=dict)
    result: Any = None
    status: str = "pending"  # pending | running | done | failed
    error: Optional[str] = None
    started_at_ms: Optional[int] = None
    completed_at_ms: Optional[int] = None


# --------------------------------------------------------------------------- #
# 4. Evidence Graph
# --------------------------------------------------------------------------- #
class ProvenanceType(str, Enum):
    """Epistemic weight of an evidence node."""
    CRYPTOGRAPHIC = "cryptographic"      # tier 0 — hash, magic bytes
    TOOL_INFERENCE = "tool_inference"   # tier 1 — ExifTool, OCR, ELA, C2PA
    AI_HYPOTHESIS = "ai_hypothesis"     # tier 2 — vision model, LLM correlation


class ClaimType(str, Enum):
    LOCATION = "location"
    TIMESTAMP = "timestamp"
    DEVICE = "device"
    SOURCE = "source"
    INTEGRITY = "integrity"
    METADATA = "metadata"
    OTHER = "other"


class EdgeRelation(str, Enum):
    CORROBORATES = "corroborates"     # positive weight
    CONTRADICTS = "contradicts"       # negative weight
    DERIVED_FROM = "derived_from"
    SAME_ASSET = "same_asset"
    SUPERSEDES = "supersedes"


class EvidenceNode(BaseModel):
    node_id: str
    case_id: str
    tool_id: str
    provenance_type: ProvenanceType
    claim: str
    claim_type: ClaimType
    value: Any
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    model_id: Optional[str] = None
    produced_at_ms: int = Field(default_factory=now_ms)
    hash: str = ""


class EvidenceEdge(BaseModel):
    edge_id: str
    case_id: str
    src: str  # node_id
    dst: str  # node_id
    relation: EdgeRelation
    weight: float = 1.0
    created_at_ms: int = Field(default_factory=now_ms)
    note: Optional[str] = None


class FindingStatus(str, Enum):
    """Workflow state of a structured finding (cognitive unit 10)."""
    DRAFT = "draft"
    NEEDS_REVIEW = "needs_review"
    VALIDATED = "validated"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class FindingSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FindingType(str, Enum):
    """Typed conclusion categories — not free-text prose."""
    TIMELINE_ANOMALY = "timeline_anomaly"
    LOCATION_CREDIBILITY = "location_credibility"
    DEVICE_ATTRIBUTION = "device_attribution"
    TAMPER_DETECTION = "tamper_detection"
    SOURCE_CONFLICT = "source_conflict"
    PROVENANCE_STATE = "provenance_state"
    CORRELATION = "correlation"
    OTHER = "other"


class Finding(BaseModel):
    """A claim promoted from evidence — court-relevant output.

    Cognitive unit 10 consumes/produces this. All fields beyond the Phase A/B
    core are optional so existing consumers (``evidence_graph`` promotion)
    keep working unchanged.
    """
    finding_id: str
    case_id: str
    claim_type: ClaimType
    claim: str
    value: Any
    confidence: float
    supporting_node_ids: list[str]
    contradicting_node_ids: list[str]
    promoted_at_ms: int = Field(default_factory=now_ms)
    finding_type: FindingType = FindingType.OTHER
    severity: FindingSeverity = FindingSeverity.MEDIUM
    status: FindingStatus = FindingStatus.NEEDS_REVIEW
    observation: Optional[str] = None
    assessment: Optional[str] = None
    domain: Optional[DomainId] = None


class EvidenceGraph(BaseModel):
    case_id: str
    nodes: dict[str, EvidenceNode] = Field(default_factory=dict)
    edges: list[EvidenceEdge] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    plan_id: Optional[str] = None


class PromotionDenied(Exception):
    """A tier-2 node cannot be promoted to a finding without corroboration."""


# --------------------------------------------------------------------------- #
# Cognitive layer contracts (ARK_INTEGRATED_SECURITY_ENVIRONMENT.md §2)
# These are the data shapes of units 05-09 — additive contracts, no behavior
# change to Phase A/B code.
# --------------------------------------------------------------------------- #
class Hypothesis(BaseModel):
    """Unit 05 — a ranked, evidence-tagged hypothesis. NEVER a fact.

    ``Hypothesis`` objects are tier-2 reasoning artifacts. They may support
    graph nodes (as ``ai_hypothesis``) but promotion to a Finding still goes
    through the evidence-graph promotion rule; the hypothesis itself is not
    promoted.
    """
    hypothesis_id: str
    case_id: str
    domain: DomainId
    claim: str                                  # "Location is likely Lagos"
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    supporting_node_ids: list[str] = Field(default_factory=list)
    contradicting_node_ids: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    model_id: Optional[str] = None              # pinned — part of provenance
    alternatives: list["HypothesisCandidate"] = Field(default_factory=list)
    created_at_ms: int = Field(default_factory=now_ms)


class HypothesisCandidate(BaseModel):
    """One ranked option inside a Hypothesis (e.g. Lagos 82% / Abuja 11%)."""
    claim: str
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    supporting_node_ids: list[str] = Field(default_factory=list)
    contradicting_node_ids: list[str] = Field(default_factory=list)


class Critique(BaseModel):
    """Unit 06 — the Critic's challenge to a conclusion. Not a verdict.

    A Critique asks what could make the target conclusion wrong; it must
    enumerate independent-evidence checks and alternative explanations. The
    orchestrator records critiques as nodes so the challenge is auditable.
    """
    critique_id: str
    case_id: str
    target_id: str                               # node_id or finding_id
    questions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    alternative_explanations: list[str] = Field(default_factory=list)
    challenges_conclusion: bool = False
    model_id: Optional[str] = None
    created_at_ms: int = Field(default_factory=now_ms)


class ContextFrame(BaseModel):
    """Unit 07 — layered investigation context for the planner/interactor.

    Levels: immediate (current step/outputs) → investigation (case + findings
    + hypotheses) → session (analyst activity) → historical (authorized prior
    cases) → organizational (tenant policy/config). The AI must know
    "we are investigating CASE-2047" without the analyst repeating it.
    """
    case_id: Optional[str] = None
    domain: Optional[DomainId] = None
    objective: Optional[InvestigationObjective] = None
    current_tool_id: Optional[str] = None
    current_step_id: Optional[str] = None
    recent_evidence_node_ids: list[str] = Field(default_factory=list)
    active_hypothesis_ids: list[str] = Field(default_factory=list)
    open_finding_ids: list[str] = Field(default_factory=list)
    session_note: Optional[str] = None
    tenant_id: Optional[str] = None
    is_zero_retention: bool = False


class GapType(str, Enum):
    """Unit 04 — kinds of gaps the correlator derives from the graph."""
    UNVERIFIED_CLAIM = "unverified_claim"
    OPEN_CONTRADICTION = "open_contradiction"
    LOW_CORROBORATION = "low_corroboration"
    MISSING_LAYER = "missing_layer"


class GraphGap(BaseModel):
    """Unit 04 — a concrete gap the orchestrator may close with a re-plan.

    ``addressable_by`` lists registered tool_ids that could close the gap;
    the model proposes an ordering among those (or termination), never a
    free-form tool pick.
    """
    gap_id: str
    gap_type: GapType
    severity: RiskLevel
    rationale: str
    addressable_by: list[str] = Field(default_factory=list)
    related_node_ids: list[str] = Field(default_factory=list)
    resolved: bool = False


# --------------------------------------------------------------------------- #
# 9. Model Gateway contracts
# --------------------------------------------------------------------------- #
class ModelCapability(str, Enum):
    PLANNING = "planning"       # objective -> plan, re-planning
    ROUTING = "routing"         # small/fast tool-selection decisions
    VISION = "vision"           # image/scene interpretation
    EMBEDDING = "embedding"     # similarity / semantic search
    OCR = "ocr"                 # text-in-image extraction
    REASONING = "reasoning"     # strong multi-step correlation
    CRITIC = "critic"           # verification / challenge


class ModelProvider(str, Enum):
    OLLAMA = "ollama"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    HUGGINGFACE = "huggingface"
    LOCAL = "local"
    OTHER = "other"


class ModelSpec(BaseModel):
    """Unit 09 — one routable model. Mirrors ToolSpec: the system (policy)
    decides which model a task may use; choice is recorded per node."""
    model_id: str
    name: str
    capabilities: list[ModelCapability]
    provider: ModelProvider
    local: bool = True
    version: str = ""                            # pinned version — provenance
    offline_ok: bool = True
    zero_retention_safe: bool = True             # may run on sensitive cases
    cost_estimate: Optional[CostEstimate] = None
    endpoint: Optional[str] = None               # e.g. Ollama model tag


# --------------------------------------------------------------------------- #
# Domain specialists — knowledge/tool-selection layers (NOT AI brains)
# --------------------------------------------------------------------------- #
class SpecialistSpec(BaseModel):
    """A domain specialist: knows its domain, routes to registered tools."""
    domain: DomainId
    name: str
    description: str
    understands: list[str] = Field(default_factory=list)
    tool_ids: list[str] = Field(default_factory=list)
    goal_mappings: dict[str, str] = Field(default_factory=dict)  # goal -> template_id


# --------------------------------------------------------------------------- #
# 5. Policy / Permission Guard
# --------------------------------------------------------------------------- #
class ApprovalTier(str, Enum):
    AUTO = "auto"
    CONFIRM_ONCE = "confirm_once"
    STEP_CONFIRM = "step_confirm"


class Budget(BaseModel):
    max_steps: int = 25
    max_tokens: int = 200_000
    max_ms: int = 600_000
    max_api_calls: int = 10


class BudgetEstimate(BaseModel):
    """Budget limits + expected burn for a plan, shown BEFORE approval.

    ``estimated_*`` sums the registered tools' cost estimates over the plan
    steps; the analyst sees whether the plan fits the objective's budget
    before anything executes.
    """
    budget: Optional[Budget] = None
    estimated_steps: int = 0
    estimated_tokens: int = 0
    estimated_ms: int = 0
    estimated_api_calls: int = 0


class PolicyMatch(BaseModel):
    tool_id_glob: Optional[str] = None
    risk_min: Optional[RiskLevel] = None
    category: Optional[ToolCategory] = None
    domain: Optional[DomainId] = None


class PolicyRule(BaseModel):
    rule_id: str
    match: PolicyMatch = Field(default_factory=PolicyMatch)
    approval_tier: ApprovalTier = ApprovalTier.AUTO
    budget: Optional[Budget] = None
    require_confirmation_for: list[ToolCategory] = Field(default_factory=list)
    enabled: bool = True


class PolicyDecision(BaseModel):
    allowed: bool
    approval_tier: ApprovalTier
    reason: str
    rule_id: str


# --------------------------------------------------------------------------- #
# 6. Investigation Objective frames
# --------------------------------------------------------------------------- #
class InvestigationGoal(str, Enum):
    VERIFY_LOCATION_CREDIBILITY = "verify_location_credibility"
    DEVICE_ATTRIBUTION = "device_attribution"
    TAMPER_DETECTION = "tamper_detection"
    SOURCE_DISCOVERY = "source_discovery"
    FULL_FORENSIC_PROFILE = "full_forensic_profile"


class ClaimToVerify(BaseModel):
    field: str
    value: Any


class ObjectiveConstraints(BaseModel):
    skip_external_sources: bool = False
    prioritize: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    budget: Optional[Budget] = None
    zero_retention: bool = False


class InvestigationObjective(BaseModel):
    objective_id: str
    goal: InvestigationGoal
    subject: str
    domain: DomainId = "image"
    claims_to_verify: list[ClaimToVerify] = Field(default_factory=list)
    constraints: ObjectiveConstraints = Field(default_factory=ObjectiveConstraints)
    natural_language: Optional[str] = None


# --------------------------------------------------------------------------- #
# 7. Plan lineage
# --------------------------------------------------------------------------- #
class StepStatus(str, Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    RUNNING = "running"
    DONE = "done"
    SKIPPED = "skipped"
    FAILED = "failed"


class PlanStep(BaseModel):
    step_id: str
    tool_id: str
    arguments: dict = Field(default_factory=dict)
    rationale: str = ""
    status: StepStatus = StepStatus.PROPOSED
    result_node_id: Optional[str] = None
    started_at_ms: Optional[int] = None
    completed_at_ms: Optional[int] = None


class PlanRevision(BaseModel):
    revision_id: str
    parent_revision_id: Optional[str]
    objective_id: str
    steps: list[PlanStep] = Field(default_factory=list)
    delta_reason: Optional[str] = None
    proposed_at_ms: int = Field(default_factory=now_ms)
    approved_at_ms: Optional[int] = None
    approved_by: Optional[str] = None
    budget_estimate: Optional["BudgetEstimate"] = None
    hash: str = ""


__all__ = [
    "DomainId",
    "now_ms",
    # Tool Registry
    "RiskLevel", "ToolCategory", "Availability", "Permission",
    "CostEstimate", "ToolSpec", "ToolInvocation",
    # Evidence Graph
    "ProvenanceType", "ClaimType", "EdgeRelation",
    "EvidenceNode", "EvidenceEdge", "Finding", "EvidenceGraph",
    "FindingStatus", "FindingSeverity", "FindingType",
    "PromotionDenied",
    # Cognitive layer contracts
    "Hypothesis", "HypothesisCandidate", "Critique", "ContextFrame",
    # Model Gateway
    "ModelCapability", "ModelProvider", "ModelSpec",
    # Domain specialists
    "SpecialistSpec",
    # Policy
    "ApprovalTier", "Budget", "PolicyMatch", "PolicyRule", "PolicyDecision",
    # Objectives
    "InvestigationGoal", "ClaimToVerify", "ObjectiveConstraints",
    "InvestigationObjective",
    # Plan lineage
    "StepStatus", "PlanStep", "PlanRevision",
]
