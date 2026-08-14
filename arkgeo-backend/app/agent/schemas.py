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


class Finding(BaseModel):
    """A claim promoted from evidence — court-relevant output."""
    finding_id: str
    case_id: str
    claim_type: ClaimType
    claim: str
    value: Any
    confidence: float
    supporting_node_ids: list[str]
    contradicting_node_ids: list[str]
    promoted_at_ms: int = Field(default_factory=now_ms)


class EvidenceGraph(BaseModel):
    case_id: str
    nodes: dict[str, EvidenceNode] = Field(default_factory=dict)
    edges: list[EvidenceEdge] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    plan_id: Optional[str] = None


class PromotionDenied(Exception):
    """A tier-2 node cannot be promoted to a finding without corroboration."""


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
    "PromotionDenied",
    # Policy
    "ApprovalTier", "Budget", "PolicyMatch", "PolicyRule", "PolicyDecision",
    # Objectives
    "InvestigationGoal", "ClaimToVerify", "ObjectiveConstraints",
    "InvestigationObjective",
    # Plan lineage
    "StepStatus", "PlanStep", "PlanRevision",
]
