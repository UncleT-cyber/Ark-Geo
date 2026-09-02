"""Plan Executor — runs approved plan steps through the Policy Guard.

For each step: authorize → resolve args → ``registry.acall`` → budget record →
evidence node (+ audit node + ``derived_from`` edge). Records a **tool
activity log** — this is the AGENT console view.

The executor is deterministic machinery. It never calls a model. The Policy
Guard (unit 08) decides what *may* execute; the registry (unit 03) knows what
*can* execute; the evidence graph records what *actually happened*.

Unavailable/denied steps are **skipped, not fatal**: an investigation without
vision keys still completes on the deterministic tools.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from . import evidence_graph as eg
from . import schemas as S
from .policy_guard import PolicyGuard
from .tool_registry import registry

logger = logging.getLogger(__name__)


def _args_hash(arguments: dict) -> str:
    """Canonical SHA-256 of resolved tool arguments — the memoization key
    (same encoding as the audit node's arguments_hash)."""
    import hashlib
    import json

    return hashlib.sha256(
        json.dumps(arguments, sort_keys=True, default=str).encode()
    ).hexdigest()

# Tools that consume raw image bytes directly (Phase C image domain).
_IMAGE_BYTES_TOOLS = {
    "compute_custody_hash", "validate_format", "extract_exif",
    "extract_deep_metadata", "analyze_ela", "detect_eof_anomaly",
    "run_ocr", "run_vision_ensemble", "verify_c2pa", "discover_sources",
    "run_consistency", "detect_contradictions", "aggregate_consensus",
    "fuse_geolocation",
}
_CLAIM_TYPES: dict[str, S.ClaimType] = {
    "compute_custody_hash": S.ClaimType.INTEGRITY,
    "validate_format": S.ClaimType.INTEGRITY,
    "extract_exif": S.ClaimType.METADATA,
    "extract_deep_metadata": S.ClaimType.METADATA,
    "analyze_ela": S.ClaimType.INTEGRITY,
    "detect_eof_anomaly": S.ClaimType.INTEGRITY,
    "run_consistency": S.ClaimType.TIMESTAMP,
    "run_ocr": S.ClaimType.LOCATION,
    "reverse_geocode": S.ClaimType.LOCATION,
    "resolve_telemetry": S.ClaimType.LOCATION,
    "verify_c2pa": S.ClaimType.SOURCE,
    "discover_sources": S.ClaimType.SOURCE,
    "aggregate_consensus": S.ClaimType.LOCATION,
    "fuse_geolocation": S.ClaimType.LOCATION,
    "run_vision_ensemble": S.ClaimType.LOCATION,
    # Phase F — NETWORK
    "discover_hosts": S.ClaimType.DEVICE,
    "fingerprint_service": S.ClaimType.DEVICE,
    "port_scan": S.ClaimType.OTHER,
    "tls_inspect": S.ClaimType.SOURCE,
    # Phase F — SECOPS
    "siem_query": S.ClaimType.TIMESTAMP,
    "threat_hunt": S.ClaimType.INTEGRITY,
    "detect_correlation": S.ClaimType.OTHER,
    "incident_annotate": S.ClaimType.OTHER,
    # OSINT / LOCAL-FILESYSTEM
    "inspect_local_path": S.ClaimType.METADATA,
    # Level-4 — PENTEST
    "nmap_scan": S.ClaimType.DEVICE,
    "default_cred_tester": S.ClaimType.OTHER,
    "scan_webshells": S.ClaimType.INTEGRITY,
    "crack_hash": S.ClaimType.OTHER,
    "analyze_privilege_escalation": S.ClaimType.OTHER,
    # Level-4 — ROS / OT FORENSICS
    "inspect_ros": S.ClaimType.DEVICE,
    "analyze_safety_config": S.ClaimType.INTEGRITY,
}


@dataclass
class ExecutionContext:
    """What the executor needs to resolve tool arguments (unit 07, light)."""
    case_id: str
    image_bytes: Optional[bytes] = None
    objective: Optional[S.InvestigationObjective] = None
    graph: Any = None  # EvidenceGraph — read for graph-state-driven args
    memo: dict[str, str] = field(default_factory=dict)  # (tool,args_hash)->node_id


@dataclass
class AgentLogEntry:
    """One line in the AGENT console."""
    step_id: str
    tool_id: str
    status: str            # ran | skipped | failed
    message: str
    node_id: Optional[str] = None
    elapsed_ms: int = 0

    def to_dict(self) -> dict:
        return {
            "step_id": self.step_id, "tool_id": self.tool_id,
            "status": self.status, "message": self.message,
            "node_id": self.node_id, "elapsed_ms": self.elapsed_ms,
        }


def _serializable(value: Any) -> Any:
    """Coerce pydantic/dataclass outputs into JSON-safe structures."""
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "__dataclass_fields__"):
        return _serializable(vars(value))
    if isinstance(value, dict):
        return {k: _serializable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serializable(v) for v in value]
    return value


def _coords_from_value(value: Any) -> Optional[dict[str, float]]:
    """Best-effort coordinate extraction from an evidence-node value."""
    if isinstance(value, dict):
        if "gps" in value:
            return _coords_from_value(value["gps"])
        for lat_key in ("lat", "latitude"):
            if lat_key in value and any(k in value for k in ("lon", "longitude")):
                lon_key = "lon" if "lon" in value else "longitude"
                try:
                    return {"lat": float(value[lat_key]), "lon": float(value[lon_key])}
                except (TypeError, ValueError):
                    return None
    return None


def _latest_location(graph: eg.EvidenceGraph) -> Optional[dict[str, float]]:
    """Most recent coordinate claim on the graph (graph-state-driven args).

    Scans every node's value (EXIF GPS lands on METADATA nodes) preferring
    explicitly-typed LOCATION claims when both exist.
    """
    best: Optional[S.EvidenceNode] = None
    for node in graph.nodes.values():
        if _coords_from_value(node.value) is None:
            continue
        if best is None or node.produced_at_ms > best.produced_at_ms:
            best = node
    return _coords_from_value(best.value) if best else None


def _node_value(graph: eg.EvidenceGraph, tool_id: str) -> Any:
    """Value of the most recent node produced by ``tool_id`` (or None)."""
    best: Optional[S.EvidenceNode] = None
    for node in graph.nodes.values():
        if node.tool_id != tool_id:
            continue
        if best is None or node.produced_at_ms > best.produced_at_ms:
            best = node
    return best.value if best else None


def _node_value_list(graph: eg.EvidenceGraph, tool_id: str) -> list:
    value = _node_value(graph, tool_id)
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        # Graph-state args flow across domains — a tool consumes whatever
        # list-bearing key a prior tool emitted (results / events / hosts /
        # telemetry), so NETWORK + SECOPS tools chain deterministically.
        for key in ("results", "events", "hosts", "telemetry"):
            if isinstance(value.get(key), list):
                return value[key]
    return []


def _deep_metadata(graph: eg.EvidenceGraph) -> tuple[dict, dict]:
    """(exiftool_groups, file_info) from the extract_deep_metadata node."""
    value = _node_value(graph, "extract_deep_metadata")
    if isinstance(value, dict):
        return value.get("groups") or {}, value.get("file_info") or {}
    return {}, {}


def _network_scope(ctx: ExecutionContext) -> Optional[str]:
    """Authorized network scope for NETWORK-domain tools.

    Derived from the objective's ``subject`` (a host, hostname or CIDR). No
    scope on the objective → the step is skipped with a reason, not failed.
    """
    return (ctx.objective.subject or "").strip() or None


def _resolve_args(
    tool_id: str,
    ctx: ExecutionContext,
) -> Optional[dict[str, Any]]:
    """Resolve kwargs for a registered tool from context + graph state.

    Returns ``None`` when required arguments cannot be resolved yet (the step
    is skipped with a reason, not failed).
    """
    if tool_id in _IMAGE_BYTES_TOOLS:
        if ctx.image_bytes is None:
            # No evidence to analyze — every image-domain tool is moot.
            return None
        if tool_id == "run_consistency":
            groups, file_info = _deep_metadata(ctx.graph)
            return {"exiftool_groups": groups, "file_info": file_info}
        if tool_id == "verify_c2pa" or tool_id == "discover_sources":
            groups, _ = _deep_metadata(ctx.graph)
            return {"image_bytes": ctx.image_bytes, "exiftool_groups": groups}
        if tool_id == "aggregate_consensus":
            return {
                "metadata_coords": _coords_from_value(_node_value(ctx.graph, "extract_exif")),
                "telemetry_coords": _node_value(ctx.graph, "resolve_telemetry"),
                "vision_results": _node_value_list(ctx.graph, "run_vision_ensemble"),
                "extractor_results": [],
            }
        if tool_id == "fuse_geolocation":
            return {
                "consensus": _node_value(ctx.graph, "aggregate_consensus"),
                "coordinates": _coords_from_value(_node_value(ctx.graph, "extract_exif")),
                "address": _node_value(ctx.graph, "reverse_geocode"),
                "visual_tags": _node_value_list(ctx.graph, "run_ocr"),
                "consistency_findings": _node_value_list(ctx.graph, "run_consistency"),
                "exif_raw": _node_value(ctx.graph, "extract_exif") or {},
            }
        if tool_id == "detect_contradictions":
            return {
                "consistency_findings": _node_value_list(ctx.graph, "run_consistency"),
                "geolocation_fusion": _node_value(ctx.graph, "fuse_geolocation") or {},
                "exif_raw": _node_value(ctx.graph, "extract_exif") or {},
                "gps_spoofing_detected": False,
                "anomaly_score": 0.0,
                "sanity_mismatches": [],
            }
        return {"image_bytes": ctx.image_bytes}
    if tool_id == "reverse_geocode":
        coords = _latest_location(ctx.graph)
        return {"lat": coords["lat"], "lon": coords["lon"]} if coords else None
    if tool_id == "resolve_telemetry":
        coords = _latest_location(ctx.graph)
        return {"last_known_gps": coords} if coords else {}
    # ---- Phase F — NETWORK tools resolve their scope from the objective. ----
    if tool_id in ("discover_hosts", "fingerprint_service", "port_scan",
                   "tls_inspect"):
        scope = _network_scope(ctx)
        if not scope:
            return None  # no authorized scope → skip (recorded, not fatal)
        if tool_id == "discover_hosts":
            return {"network_range": scope}
        if tool_id == "port_scan":
            ports = [
                int(p) for p in (ctx.objective.constraints.prioritize or [])
                if str(p).isdigit()
            ] or [80, 443]
            return {"host": scope, "ports": ports}
        return {"host": scope}
    # ---- Phase F — SECOPS tools consume the event timeline on the graph. ----
    if tool_id == "siem_query":
        return {
            "query": ctx.objective.natural_language or ctx.objective.goal.value,
            "events": _node_value_list(ctx.graph, "siem_query"),
        }
    if tool_id == "threat_hunt":
        return {
            "indicator": ctx.objective.natural_language or ctx.objective.subject,
            "telemetry": _node_value_list(ctx.graph, "threat_hunt"),
        }
    if tool_id == "detect_correlation":
        return {"events": _node_value_list(ctx.graph, "siem_query")}
    if tool_id == "incident_annotate":
        return None  # requires explicit analyst note — not auto-resolvable
    # ---- OSINT / LOCAL-FILESYSTEM — scope is the objective's subject. ----
    if tool_id == "inspect_local_path":
        return {"target_path": ctx.objective.subject or ""}
    return {}


def _build_evidence_node(
    tool_id: str,
    result: Any,
    ctx: ExecutionContext,
    spec: S.ToolSpec,
) -> S.EvidenceNode:
    """Turn a tool result into a tamper-evident evidence node."""
    value = _serializable(result)
    provenance = (
        S.ProvenanceType.TOOL_INFERENCE if spec.deterministic
        else S.ProvenanceType.AI_HYPOTHESIS
    )
    claim = f"{spec.name}: {'OK' if value is not None else 'empty result'}"
    return eg.build_node(
        case_id=ctx.case_id,
        tool_id=tool_id,
        provenance_type=provenance,
        claim=claim,
        claim_type=_CLAIM_TYPES.get(tool_id, S.ClaimType.OTHER),
        value=value,
        confidence=1.0 if spec.deterministic else 0.5,
        model_id=spec.provider if not spec.deterministic else None,
    )


def _decision_dict(decision: S.PolicyDecision) -> dict:
    return decision.model_dump()


class PlanExecutor:
    """Executes plan steps against the guard + registry + evidence graph."""

    async def execute(
        self,
        plan: S.PlanRevision,
        graph: eg.EvidenceGraph,
        guard: PolicyGuard,
        ctx: ExecutionContext,
    ) -> list[AgentLogEntry]:
        log: list[AgentLogEntry] = []
        for step in plan.steps:
            step.status = S.StepStatus.RUNNING
            started = time.perf_counter()

            # 1. Policy — what MAY execute (unit 08).
            decision = guard.evaluate(step.tool_id)
            if not decision.allowed:
                elapsed = int((time.perf_counter() - started) * 1000)
                step.status = S.StepStatus.SKIPPED
                log.append(AgentLogEntry(
                    step.step_id, step.tool_id, "skipped",
                    f"denied: {decision.reason}", elapsed_ms=elapsed,
                ))
                eg.audit_tool_call(
                    graph, step.tool_id,
                    {"invocation_id": step.step_id, "arguments": {},
                     "status": "skipped"},
                    policy_decision=_decision_dict(decision),
                )
                continue

            # 1b. Step confirmation — high-risk tools need a recorded approval.
            if decision.approval_tier == S.ApprovalTier.STEP_CONFIRM and \
                    not guard.is_confirmed(step.tool_id):
                elapsed = int((time.perf_counter() - started) * 1000)
                step.status = S.StepStatus.SKIPPED
                log.append(AgentLogEntry(
                    step.step_id, step.tool_id, "skipped",
                    "step confirmation required before execution",
                    elapsed_ms=elapsed,
                ))
                eg.audit_tool_call(
                    graph, step.tool_id,
                    {"invocation_id": step.step_id, "arguments": {},
                     "status": "skipped", "error": "step_confirm_unapproved"},
                    policy_decision=_decision_dict(decision),
                )
                continue

            # 2. Args from context + graph state.
            args = _resolve_args(step.tool_id, ctx)
            if args is None:
                elapsed = int((time.perf_counter() - started) * 1000)
                step.status = S.StepStatus.SKIPPED
                log.append(AgentLogEntry(
                    step.step_id, step.tool_id, "skipped",
                    "cannot resolve required arguments (e.g. GPS not yet extracted)",
                    elapsed_ms=elapsed,
                ))
                continue

            # 2b. Memoization — reuse a prior identical invocation on the graph.
            memo_key = f"{step.tool_id}:{_args_hash(args)}"
            if memo_key in ctx.memo:
                elapsed = int((time.perf_counter() - started) * 1000)
                reused_id = ctx.memo[memo_key]
                step.status = S.StepStatus.DONE
                step.result_node_id = reused_id
                log.append(AgentLogEntry(
                    step.step_id, step.tool_id, "ran",
                    f"memoized: reused evidence {reused_id}",
                    node_id=reused_id, elapsed_ms=elapsed,
                ))
                eg.audit_tool_call(
                    graph, step.tool_id,
                    {"invocation_id": step.step_id, "arguments": args,
                     "status": "memoized"},
                    policy_decision=_decision_dict(decision),
                    produced_node_id=reused_id,
                )
                continue

            # 3. Execute (unit 03) — model never involved here.
            spec = registry.get(step.tool_id).spec
            try:
                result = await registry.acall(step.tool_id, **args)
            except Exception as exc:  # noqa: BLE001 — a tool failure is not fatal
                elapsed = int((time.perf_counter() - started) * 1000)
                step.status = S.StepStatus.FAILED
                log.append(AgentLogEntry(
                    step.step_id, step.tool_id, "failed",
                    f"error: {exc}", elapsed_ms=elapsed,
                ))
                eg.audit_tool_call(
                    graph, step.tool_id,
                    {"invocation_id": step.step_id, "arguments": args,
                     "status": "failed", "error": str(exc)},
                    policy_decision=_decision_dict(decision),
                )
                continue

            elapsed = int((time.perf_counter() - started) * 1000)
            guard.record_run(
                step.tool_id,
                tokens=getattr(spec.cost_estimate, "model_tokens", 0) or 0,
                api_calls=getattr(spec.cost_estimate, "api_calls", 0) or 0,
                elapsed_ms=elapsed,
            )

            # 4. Record what happened (evidence + audit + derived_from edge).
            node = _build_evidence_node(step.tool_id, result, ctx, spec)
            eg.add_node(graph, node)
            eg.audit_tool_call(
                graph, step.tool_id,
                {"invocation_id": step.step_id, "arguments": args,
                 "status": "done"},
                policy_decision=_decision_dict(decision),
                produced_node_id=node.node_id,
            )
            ctx.memo[memo_key] = node.node_id

            step.status = S.StepStatus.DONE
            step.result_node_id = node.node_id
            log.append(AgentLogEntry(
                step.step_id, step.tool_id, "ran",
                f"{spec.name} complete", node_id=node.node_id,
                elapsed_ms=elapsed,
            ))

        plan.approved_at_ms = None  # filled by the orchestrator on approval
        return log


executor = PlanExecutor()
