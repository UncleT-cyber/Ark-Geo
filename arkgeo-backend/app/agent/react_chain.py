"""Level-4 RE-ACT chain — Plan → Scan → Exploit → Escalate → Mitigate.

The autonomous authorized-engagement security chain. Given an **explicitly
authorized** scope it walks five phases, recording every step on an evidence
graph with the same discipline as the investigation orchestrator (unit 03 /
unit 08 / graph + audit nodes):

    PLAN       builds a structured engagement plan from the target scope.
    SCAN       enumerates the scope: ``nmap_scan`` (hosts/services),
               ``scan_webshells`` (owned web root), ``inspect_ros`` (OT).
    EXPLOIT    verifies exposure: ``default_cred_tester`` (authorized=True).
    ESCALATE   post-exploitation recon: ``analyze_privilege_escalation``
               (local host) and offline ``crack_hash`` recovery.
    MITIGATE   deterministic remediation posture derived from the evidence.

Authorization model
-------------------
* The chain owns a dedicated :class:`PolicyGuard` grant that **includes
  ``exec:shell``** — active / subprocess capabilities are intentionally NOT on
  the standard investigator grant, so the ordinary orchestrator loop keeps them
  denied (skipped honestly). The RE-ACT chain is the explicit, dedicated
  surface that may run them.
* Every request must carry ``authorized=True`` plus an operator identity and a
  resolvable scope; otherwise the chain refuses to start and records a refusal
  node on the case graph. No tool is ever invoked without both.
* High-risk (step_confirm) tools are pre-confirmed **once per chain run** as the
  recorded operator approval — the entire engagement is the approved scope.

``mode="dry_run"`` is honoured for every tool that supports it (simulation with
no network traffic / no subprocess execution); read-only DFIR tools
(webshell scan, safety audit) are always passive.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from . import evidence_graph as eg
from . import schemas as S
from .policy_guard import PolicyGuard
from .tool_registry import registry

logger = logging.getLogger(__name__)

# The chain's dedicated grant — active capabilities live here and only here.
_CHAIN_PERMISSIONS = [
    S.Permission.READ_EVIDENCE,
    S.Permission.QUERY_EXTERNAL,
    S.Permission.CALL_PROVIDER,
    S.Permission.EXEC_SHELL,
    S.Permission.MUTATE_CASE,
]

# Default budget sized for a full five-phase engagement (callers may override).
_DEFAULT_CHAIN_BUDGET = S.Budget(
    max_steps=40,
    max_tokens=200_000,
    max_ms=900_000,
    max_api_calls=60,
)

# Claim-type mapping for chain tools (mirrors executor._CLAIM_TYPES).
_CHAIN_CLAIM_TYPES: dict[str, S.ClaimType] = {
    "nmap_scan": S.ClaimType.DEVICE,
    "scan_webshells": S.ClaimType.INTEGRITY,
    "inspect_ros": S.ClaimType.DEVICE,
    "analyze_safety_config": S.ClaimType.INTEGRITY,
    "default_cred_tester": S.ClaimType.OTHER,
    "crack_hash": S.ClaimType.OTHER,
    "analyze_privilege_escalation": S.ClaimType.OTHER,
}

# Tools the operator permanently approved ("always") for terminal-driven
# engagements — the permission prompt is skipped for these on future requests.
# In-memory per-process; a restart resets the remembered approvals.
_ALWAYS_APPROVED: set[str] = set()


class ChainPhase(str, Enum):
    PLAN = "plan"
    SCAN = "scan"
    EXPLOIT = "exploit"
    ESCALATE = "escalate"
    MITIGATE = "mitigate"


class EngagementKind(str, Enum):
    NETWORK = "network"   # host / CIDR + optional port list
    WEB = "web"           # target_url (+ web_root for webshell surface)
    HOST = "host"         # local authorized box — priv-esc enumeration
    OT = "ot"             # ROS / safety config forensics
    OFFLINE = "offline"   # offline hash recovery (no target contact)


class ReactTarget(BaseModel):
    """The authorized scope of an engagement. Never empty by contract."""
    kind: EngagementKind
    host: Optional[str] = None
    ports: str = ""
    target_url: Optional[str] = None
    web_root: Optional[str] = None
    ros2: bool = False
    safety_config_path: Optional[str] = None
    reference_config_path: Optional[str] = None
    hash_value: Optional[str] = None
    hash_type: str = "auto"
    wordlist: Optional[str] = None

    def summary(self) -> str:
        if self.kind == EngagementKind.NETWORK:
            return f"network {self.host} ({self.ports or 'default ports'})"
        if self.kind == EngagementKind.WEB:
            bits = [self.target_url]
            if self.web_root:
                bits.append(f"web-root {self.web_root}")
            return " / ".join(b for b in bits if b)
        if self.kind == EngagementKind.HOST:
            return f"host {self.host or 'local'}"
        if self.kind == EngagementKind.OT:
            bits = ["ROS 2" if self.ros2 else "ROS 1"]
            if self.safety_config_path:
                bits.append(self.safety_config_path)
            return " / ".join(bits)
        return f"offline hash ({self.hash_type})"


class ReactRequest(BaseModel):
    """One authorized engagement request.

    ``mode="pending"`` plans the engagement and stores a ``pending_approval``
    session WITHOUT executing anything — the terminal permission flow uses this
    so the operator is asked before any active tool runs. ``approve()`` then
    executes the plan with ``mode="active"`` / ``mode="dry_run"``.
    """
    operator: str = Field(..., min_length=1)
    authorized: bool = False
    target: ReactTarget
    mode: str = "active"           # active | dry_run | pending
    notes: str = ""
    budget: dict = Field(default_factory=dict)  # optional Budget override


@dataclass
class ReactSession:
    """One chain run: request, evidence graph, phase results, findings."""
    session_id: str
    case_id: str
    request: ReactRequest
    graph: eg.EvidenceGraph
    guard_usage: dict = field(default_factory=dict)
    status: str = "proposed"       # proposed | running | done | rejected | paused | failed
    rejection_reason: Optional[str] = None
    phases: list[dict] = field(default_factory=list)
    activity: list[dict] = field(default_factory=list)
    findings: list[dict] = field(default_factory=list)
    mitigation: list[dict] = field(default_factory=list)
    created_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    updated_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "case_id": self.case_id,
            "request": self.request.model_dump(),
            "status": self.status,
            "rejection_reason": self.rejection_reason,
            "phases": self.phases,
            "activity": self.activity,
            "findings": self.findings,
            "mitigation": self.mitigation,
            "budget_usage": self.guard_usage,
            "graph": eg.to_dict(self.graph),
            "created_at_ms": self.created_at_ms,
            "updated_at_ms": self.updated_at_ms,
        }


def _gen_session_id() -> str:
    return f"ARK-REACT-{uuid.uuid4().hex[:8].upper()}"


def _gen_case_id() -> str:
    return f"ARK-CASE-{uuid.uuid4().hex[:8].upper()}"


class _ReactStore:
    """Thread-safe in-memory store of chain sessions (mirrors orchestrator)."""

    def __init__(self) -> None:
        import threading
        self._sessions: dict[str, ReactSession] = {}
        self._lock = threading.Lock()

    def put(self, session: ReactSession) -> None:
        with self._lock:
            self._sessions[session.session_id] = session

    def get(self, session_id: str) -> Optional[ReactSession]:
        with self._lock:
            return self._sessions.get(session_id)

    def list(self) -> list[ReactSession]:
        with self._lock:
            return list(self._sessions.values())


class ReactChain:
    """Unit 01 (dedicated) — the five-phase authorized engagement conductor."""

    def __init__(self) -> None:
        self.store = _ReactStore()

    # ------------------------------------------------------------------ #
    # Public entry points
    # ------------------------------------------------------------------ #
    async def run(self, request: ReactRequest) -> ReactSession:
        """Execute the whole chain against an authorized scope."""
        session = ReactSession(
            session_id=_gen_session_id(),
            case_id=_gen_case_id(),
            request=request,
            graph=eg.EvidenceGraph(case_id=_gen_case_id()),
            status="running",
        )

        if not request.authorized:
            session.status = "rejected"
            session.rejection_reason = (
                "authorization not declared — the RE-ACT chain only runs on "
                "explicitly authorized scope (request.authorized must be true)"
            )
            eg.add_node(
                session.graph,
                eg.build_node(
                    session.case_id, "react_chain",
                    S.ProvenanceType.CRYPTOGRAPHIC,
                    f"RE-ACT refused by {request.operator}: no authorization",
                    S.ClaimType.OTHER,
                    {"operator": request.operator, "reason": session.rejection_reason},
                ),
            )
            self.store.put(session)
            return session

        if not self._scope_resolvable(request.target):
            session.status = "rejected"
            session.rejection_reason = (
                f"scope not resolvable for engagement kind "
                f"'{request.target.kind.value}' — no target to act on"
            )
            self.store.put(session)
            return session

        guard = self._build_guard(request)

        # The operator's authorization is the recorded approval for the whole
        # engagement — high-risk (step_confirm) tools are pre-confirmed once.
        for tool in self._planned_tools(request.target):
            guard.record_confirmation(tool)

        eg.add_node(
            session.graph,
            eg.build_node(
                session.case_id, "react_chain",
                S.ProvenanceType.CRYPTOGRAPHIC,
                f"Engagement authorized by {request.operator} "
                f"(mode={request.mode}) on {request.target.summary()}",
                S.ClaimType.OTHER,
                {"operator": request.operator, "mode": request.mode,
                 "target": request.target.model_dump()},
            ),
        )

        try:
            await self._execute(session, guard)
        except Exception as exc:  # noqa: BLE001 — chain failure is not fatal
            logger.exception("RE-ACT %s failed", session.session_id)
            session.status = "failed"
            session.activity.append({
                "phase": "chain", "status": "failed", "message": str(exc),
            })

        session.guard_usage = guard.usage.to_dict()
        session.updated_at_ms = int(time.time() * 1000)
        self.store.put(session)
        return session

    async def plan(self, request: ReactRequest) -> ReactSession:
        """Plan an engagement WITHOUT executing tools; await operator approval.

        This is the terminal permission gate: the chain builds the engagement
        plan and stores a ``pending_approval`` session. No tool is invoked and
        no authorization node is recorded until :meth:`approve` — so an unprobed
        ``nmap`` is never the result of planning alone.
        """
        session = ReactSession(
            session_id=_gen_session_id(),
            case_id=_gen_case_id(),
            request=request,
            graph=eg.EvidenceGraph(case_id=_gen_case_id()),
            status="pending_approval",
        )
        if not self._scope_resolvable(request.target):
            session.status = "rejected"
            session.rejection_reason = (
                f"scope not resolvable for engagement kind "
                f"'{request.target.kind.value}' — no target to act on"
            )
            self.store.put(session)
            return session

        guard = self._build_guard(request)
        session.phases = await self._plan(session, guard)
        session.guard_usage = guard.usage.to_dict()
        session.activity.append({
            "phase": ChainPhase.PLAN.value, "status": "done",
            "message": "awaiting operator approval before any tool executes",
        })
        session.updated_at_ms = int(time.time() * 1000)
        self.store.put(session)
        return session

    async def approve(
        self,
        session_id: str,
        operator: str = "terminal",
        mode: str = "active",
        always: bool = False,
    ) -> ReactSession:
        """Authorize and execute a pending engagement plan.

        ``mode``    — ``active`` or ``dry_run`` (simulated tools, no traffic).
        ``always``  — remember the planned tools so the terminal permission
                      prompt is skipped on future requests.
        """
        session = self.store.get(session_id)
        if not session:
            raise KeyError(session_id)
        if session.status != "pending_approval":
            raise ValueError(
                f"session {session_id} is '{session.status}', not awaiting "
                "approval — only pending plans can be approved")

        session.request.operator = operator
        session.request.mode = mode
        guard = self._build_guard(session.request)
        planned = self._planned_tools(session.request.target)
        for tool in planned:
            guard.record_confirmation(tool)
        if always:
            _ALWAYS_APPROVED.update(planned)

        eg.add_node(
            session.graph,
            eg.build_node(
                session.case_id, "react_chain",
                S.ProvenanceType.CRYPTOGRAPHIC,
                f"Engagement approved by {operator} (mode={mode}, "
                f"always={always}) on {session.request.target.summary()}",
                S.ClaimType.OTHER,
                {"operator": operator, "mode": mode, "always": always,
                 "target": session.request.target.model_dump()},
            ),
        )

        session.status = "running"
        try:
            await self._execute(session, guard)
        except Exception as exc:  # noqa: BLE001 — chain failure is not fatal
            logger.exception("RE-ACT %s failed", session.session_id)
            session.status = "failed"
            session.activity.append({
                "phase": "chain", "status": "failed", "message": str(exc),
            })
        session.guard_usage = guard.usage.to_dict()
        session.updated_at_ms = int(time.time() * 1000)
        self.store.put(session)
        return session

    def planned_tools_for(self, target: ReactTarget) -> list[str]:
        """The ordered tool set an engagement on ``target`` would run."""
        return self._planned_tools(target)

    def always_approved_tools(self) -> list[str]:
        """Tools the operator permanently approved via the permission prompt."""
        return sorted(_ALWAYS_APPROVED)

    @staticmethod
    def _build_guard(request: ReactRequest) -> PolicyGuard:
        guard = PolicyGuard(granted_permissions=_CHAIN_PERMISSIONS)
        if request.budget:
            try:
                guard.set_budget(S.Budget(**request.budget))
            except Exception:  # noqa: BLE001 — malformed budget, fall back
                logger.warning("RE-ACT budget ignored (malformed): %s",
                               request.budget)
        else:
            guard.set_budget(_DEFAULT_CHAIN_BUDGET)
        return guard

    async def _execute(self, session: ReactSession,
                       guard: PolicyGuard) -> None:
        """Run the full Plan → Scan → Exploit → Escalate → Mitigate walk."""
        session.phases = await self._plan(session, guard)
        await self._scan(session, guard)
        await self._exploit(session, guard)
        await self._escalate(session, guard)
        session.findings, session.mitigation = await self._mitigate(session, guard)
        session.status = "paused" if guard.usage.exhausted() else "done"

    # ------------------------------------------------------------------ #
    # Phase 1 — PLAN
    # ------------------------------------------------------------------ #
    async def _plan(self, session: ReactSession,
                    guard: PolicyGuard) -> list[dict]:
        """Deterministic engagement plan: phase → tools → cost/risk summary."""
        phases: list[dict] = []
        plan_rows = {
            ChainPhase.SCAN: (self._scan_tools(session.request.target), "enumerate"),
            ChainPhase.EXPLOIT: (self._exploit_tools(session.request.target), "verify exposure"),
            ChainPhase.ESCALATE: (self._escalate_tools(session.request.target), "local post-exploitation recon"),
            ChainPhase.MITIGATE: ([], "defensive remediation posture"),
        }
        for phase, (tools, rationale) in plan_rows.items():
            phases.append({
                "phase": phase.value,
                "tool_ids": tools,
                "rationale": rationale,
                "skippable": True,
            })
        session.phases = phases
        session.activity.append({
            "phase": ChainPhase.PLAN.value, "status": "done",
            "message": f"engagement plan built for {session.request.target.summary()}",
            "tool_ids": [t for p in phases for t in p["tool_ids"]],
        })
        return phases

    # ------------------------------------------------------------------ #
    # Phase 2 — SCAN
    # ------------------------------------------------------------------ #
    async def _scan(self, session: ReactSession, guard: PolicyGuard) -> None:
        target = session.request.target
        if target.kind == EngagementKind.OT:
            await self._invoke(session, guard, "inspect_ros",
                               ros2=target.ros2,
                               safety_config_path=target.safety_config_path or "",
                               dry_run=session.request.mode == "dry_run")
            if target.safety_config_path:
                await self._invoke(session, guard, "analyze_safety_config",
                                   config_path=target.safety_config_path,
                                   reference_path=target.reference_config_path or "")
            return
        if target.kind == EngagementKind.OFFLINE:
            return  # no live surface to scan
        if target.host:
            await self._invoke(session, guard, "nmap_scan",
                               host=target.host,
                               ports=target.ports,
                               dry_run=session.request.mode == "dry_run")
        if target.kind == EngagementKind.WEB and target.web_root:
            await self._invoke(session, guard, "scan_webshells",
                               target_path=target.web_root)

    # ------------------------------------------------------------------ #
    # Phase 3 — EXPLOIT
    # ------------------------------------------------------------------ #
    async def _exploit(self, session: ReactSession, guard: PolicyGuard) -> None:
        target = session.request.target
        if target.kind == EngagementKind.OFFLINE:
            return  # hash recovery is escalate, not a live exploit
        if target.kind == EngagementKind.WEB and target.target_url:
            await self._invoke(
                session, guard, "default_cred_tester",
                target_url=target.target_url,
                authorized=session.request.authorized,
                dry_run=session.request.mode == "dry_run",
            )
        # NETWORK / HOST kinds have no exploit primitive in the Level-4 kit —
        # exposure verification is scan-driven; escalate covers the local box.

    # ------------------------------------------------------------------ #
    # Phase 4 — ESCALATE
    # ------------------------------------------------------------------ #
    async def _escalate(self, session: ReactSession, guard: PolicyGuard) -> None:
        target = session.request.target
        if target.kind == EngagementKind.OFFLINE:
            if target.hash_value and target.wordlist:
                await self._invoke(
                    session, guard, "crack_hash",
                    hash_value=target.hash_value,
                    hash_type=target.hash_type or "auto",
                    wordlist=target.wordlist,
                    dry_run=session.request.mode == "dry_run",
                )
            return
        if target.kind in (EngagementKind.HOST, EngagementKind.WEB):
            # WEB escalate runs on the owned web-root copy when provided;
            # a HOST engagement enumerates the box itself.
            root = "/"
            if target.kind == EngagementKind.WEB:
                if not target.web_root:
                    return
                root = target.web_root
            await self._invoke(
                session, guard, "analyze_privilege_escalation",
                target_root=root,
                dry_run=session.request.mode == "dry_run",
            )

    # ------------------------------------------------------------------ #
    # Phase 5 — MITIGATE
    # ------------------------------------------------------------------ #
    async def _mitigate(self, session: ReactSession,
                        guard: PolicyGuard) -> tuple[list[dict], list[dict]]:
        """Deterministic remediation posture derived from the evidence.

        Findings promote from graph nodes whose tool output indicates an
        issue; mitigation rows map each finding to concrete remediations.
        """
        findings: list[dict] = []
        mitigation: list[dict] = []
        for node in session.graph.nodes.values():
            if node.tool_id == "react_chain":
                continue
            value = node.value
            if not isinstance(value, dict):
                continue
            finding = self._finding_from_node(node, value)
            if not finding:
                continue
            findings.append(finding)
            mitigation.append(self._mitigation_for(node.tool_id, finding["severity"]))

        session.activity.append({
            "phase": ChainPhase.MITIGATE.value, "status": "done",
            "message": f"mitigation posture built: {len(findings)} finding(s), "
                       f"{len(mitigation)} remediation item(s)",
        })
        return findings, mitigation

    # ------------------------------------------------------------------ #
    # Helpers — planning, scope checks, invocation, evidence.
    # ------------------------------------------------------------------ #
    def _scan_tools(self, target: ReactTarget) -> list[str]:
        if target.kind == EngagementKind.OT:
            tools = ["inspect_ros"]
            if target.safety_config_path:
                tools.append("analyze_safety_config")
            return tools
        tools = []
        if target.host:
            tools.append("nmap_scan")
        if target.kind == EngagementKind.WEB and target.web_root:
            tools.append("scan_webshells")
        return tools

    def _exploit_tools(self, target: ReactTarget) -> list[str]:
        if target.kind == EngagementKind.WEB and target.target_url:
            return ["default_cred_tester"]
        return []

    def _escalate_tools(self, target: ReactTarget) -> list[str]:
        if target.kind == EngagementKind.OFFLINE:
            return ["crack_hash"] if target.hash_value and target.wordlist else []
        if target.kind == EngagementKind.HOST:
            return ["analyze_privilege_escalation"]
        if target.kind == EngagementKind.WEB and target.web_root:
            return ["analyze_privilege_escalation"]
        return []

    def _planned_tools(self, target: ReactTarget) -> list[str]:
        seen: list[str] = []
        for tools in (self._scan_tools(target), self._exploit_tools(target),
                      self._escalate_tools(target)):
            for t in tools:
                if t not in seen:
                    seen.append(t)
        return seen

    def _scope_resolvable(self, target: ReactTarget) -> bool:
        if target.kind == EngagementKind.NETWORK:
            return bool(target.host)
        if target.kind == EngagementKind.WEB:
            return bool(target.target_url or target.web_root or target.host)
        if target.kind == EngagementKind.HOST:
            return True
        if target.kind == EngagementKind.OT:
            return bool(target.ros2 or target.safety_config_path)
        return bool(target.hash_value)

    # ------------------------------------------------------------------ #
    async def _invoke(
        self,
        session: ReactSession,
        guard: PolicyGuard,
        tool_id: str,
        **kwargs: Any,
    ) -> Optional[dict]:
        """Policy-guarded tool call with audit + evidence-node recording."""
        decision = guard.evaluate(tool_id)
        if not decision.allowed:
            session.activity.append({
                "phase": _phase_of(tool_id), "tool_id": tool_id,
                "status": "skipped", "message": f"denied: {decision.reason}",
            })
            eg.audit_tool_call(
                session.graph, tool_id,
                {"invocation_id": _gen_session_id(), "arguments": kwargs,
                 "status": "skipped"},
                policy_decision=decision.model_dump(),
            )
            return None
        if decision.approval_tier == S.ApprovalTier.STEP_CONFIRM and \
                not guard.is_confirmed(tool_id):
            session.activity.append({
                "phase": _phase_of(tool_id), "tool_id": tool_id,
                "status": "skipped",
                "message": "step confirmation not recorded",
            })
            return None

        started = time.perf_counter()
        try:
            result = await registry.acall(tool_id, **kwargs)
        except Exception as exc:  # noqa: BLE001 — tool failure is not fatal
            elapsed = int((time.perf_counter() - started) * 1000)
            session.activity.append({
                "phase": _phase_of(tool_id), "tool_id": tool_id,
                "status": "failed", "message": f"error: {exc}",
                "elapsed_ms": elapsed,
            })
            eg.audit_tool_call(
                session.graph, tool_id,
                {"invocation_id": _gen_session_id(), "arguments": kwargs,
                 "status": "failed", "error": str(exc)},
                policy_decision=decision.model_dump(),
            )
            return None

        elapsed = int((time.perf_counter() - started) * 1000)
        spec = registry.get(tool_id).spec
        guard.record_run(
            tool_id,
            tokens=getattr(spec.cost_estimate, "model_tokens", 0) or 0,
            api_calls=getattr(spec.cost_estimate, "api_calls", 0) or 0,
            elapsed_ms=elapsed,
        )

        value = _serializable(result)
        node = eg.build_node(
            case_id=session.case_id,
            tool_id=tool_id,
            provenance_type=S.ProvenanceType.TOOL_INFERENCE,
            claim=f"{spec.name}: complete",
            claim_type=_CHAIN_CLAIM_TYPES.get(tool_id, S.ClaimType.OTHER),
            value=value,
            confidence=1.0,
        )
        eg.add_node(session.graph, node)
        eg.audit_tool_call(
            session.graph, tool_id,
            {"invocation_id": _gen_session_id(), "arguments": kwargs,
             "status": "done"},
            policy_decision=decision.model_dump(),
            produced_node_id=node.node_id,
        )
        session.activity.append({
            "phase": _phase_of(tool_id), "tool_id": tool_id,
            "status": "ran", "message": f"{spec.name} complete",
            "node_id": node.node_id, "elapsed_ms": elapsed,
        })
        return value

    # ------------------------------------------------------------------ #
    def _finding_from_node(self, node: S.EvidenceNode,
                           value: dict) -> Optional[dict]:
        """Turn a completed tool node into a structured finding when warranted."""
        state = value.get("state")
        if state in ("UNAVAILABLE", "ERROR", "TOOL_MISSING"):
            return None  # nothing bad found — the tool itself was absent

        if node.tool_id == "scan_webshells":
            detections = value.get("detections") or []
            if not detections:
                return None
            return {
                "finding_id": _gen_session_id(),
                "tool_id": node.tool_id,
                "severity": "high",
                "title": "webshell indicators detected",
                "detail": f"{len(detections)} file(s) with webshell signatures",
                "node_id": node.node_id,
                "value": detections,
            }
        if node.tool_id == "default_cred_tester":
            hits = value.get("hits") or []
            if not hits:
                return None
            return {
                "finding_id": _gen_session_id(),
                "tool_id": node.tool_id,
                "severity": "critical",
                "title": "default credentials valid",
                "detail": f"{len(hits)} valid default-credential login(s)",
                "node_id": node.node_id,
                "value": hits,
            }
        if node.tool_id == "analyze_privilege_escalation":
            issues = value.get("issues") or []
            if not issues:
                return None
            return {
                "finding_id": _gen_session_id(),
                "tool_id": node.tool_id,
                "severity": value.get("severity") or "high",
                "title": "privilege-escalation surface exposed",
                "detail": f"{len(issues)} escalation primitive(s) enumerated",
                "node_id": node.node_id,
                "value": issues,
            }
        if node.tool_id == "crack_hash":
            plaintext = value.get("plaintext")
            if not plaintext:
                return None
            return {
                "finding_id": _gen_session_id(),
                "tool_id": node.tool_id,
                "severity": "critical",
                "title": "hash recovered",
                "detail": f"offline hash recovered as '{plaintext}'",
                "node_id": node.node_id,
                "value": value,
            }
        if node.tool_id == "analyze_safety_config":
            findings = value.get("findings") or []
            severity = value.get("overall_severity") or "PASS"
            if severity == "PASS":
                return None
            return {
                "finding_id": _gen_session_id(),
                "tool_id": node.tool_id,
                "severity": severity.lower(),
                "title": "safety-config drift / tamper",
                "detail": f"{len(findings)} deviation(s) from baseline",
                "node_id": node.node_id,
                "value": findings,
            }
        return None

    def _mitigation_for(self, tool_id: str, severity: str) -> dict:
        table = {
            "nmap_scan": (
                "Close or firewall all exposed ports; apply host-based "
                "segmentation and re-verify with a post-change scan."),
            "scan_webshells": (
                "Quarantine flagged files, rotate the web-root credentials, "
                "and add an egress WAF/IPS rule; scan the full tree after "
                "cleanup."),
            "default_cred_tester": (
                "Force credential rotation for all default accounts, enforce "
                "unique per-device credentials, and re-test."),
            "crack_hash": (
                "Upgrade to a strong password hash with per-account salt "
                "(bcrypt/argon2) and force reset on affected accounts."),
            "analyze_privilege_escalation": (
                "Remove SUID/world-writable primitives, restrict sudo "
                "entries, and patch the identified escalation paths."),
            "inspect_ros": (
                "Restrict ROS master/topic access to the authenticated "
                "subnet; enable ACLs on topic/parameter surfaces."),
            "analyze_safety_config": (
                "Restore the safety baseline from the authoritative copy, "
                "revalidate E-stop / protective-stop paths, and re-sign the "
                "config."),
        }
        return {
            "tool_id": tool_id,
            "severity": severity,
            "remediation": table.get(
                tool_id, "Verify the finding and apply vendor remediation."),
        }


def _phase_of(tool_id: str) -> str:
    if tool_id in ("nmap_scan", "scan_webshells", "inspect_ros",
                   "analyze_safety_config"):
        return ChainPhase.SCAN.value
    if tool_id == "default_cred_tester":
        return ChainPhase.EXPLOIT.value
    if tool_id in ("crack_hash", "analyze_privilege_escalation"):
        return ChainPhase.ESCALATE.value
    return ChainPhase.SCAN.value


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


def _compose_chain_answer(session: ReactSession) -> str:
    """Deterministic natural-language summary of a finished engagement."""
    if session.status == "rejected":
        return f"Engagement refused: {session.rejection_reason or 'no authorization'}"
    if session.status == "pending_approval":
        return (
            "Engagement planned for "
            f"{session.request.target.summary()} — awaiting operator approval."
        )
    target = session.request.target.summary()
    mode = session.request.mode
    lines = [
        f"RE-ACT engagement on {target} completed ({session.status}, mode={mode})."
    ]
    if session.findings:
        lines.append(f"Findings: {len(session.findings)} exposure(s) confirmed.")
        for finding in session.findings:
            lines.append(
                f"- [{finding.get('severity', 'medium').upper()}] "
                f"{finding.get('title')}: {finding.get('detail')}"
            )
    else:
        lines.append("No exploitable exposure confirmed in the authorized scope.")
    if session.mitigation:
        lines.append(f"Remediation ({len(session.mitigation)}):")
        for item in session.mitigation:
            lines.append(f"- {item.get('remediation')}")
    return "\n".join(lines)


def chain_task_result(session: ReactSession) -> dict:
    """Coerce a chain session into the agent-task result shape.

    Lets the terminal render a RE-ACT engagement through the same renderer as a
    normal agent task: tool activity lines, an ``ARK AGENT:`` answer, findings,
    and the mitigation posture.
    """
    tool_calls = [
        {
            "step_id": f"STEP-{n:02d}",
            "tool_id": activity.get("tool_id"),
            "arguments": {},
            "status": activity.get("status", "ran"),
            "message": activity.get("message", ""),
            "node_id": activity.get("node_id"),
            "elapsed_ms": activity.get("elapsed_ms", 0),
        }
        for n, activity in enumerate(
            (a for a in session.activity if a.get("tool_id")), start=1)
    ]
    return {
        "task_id": session.session_id,
        "case_id": session.case_id,
        "status": session.status,
        "kind": "pentest",
        "session_id": session.session_id,
        "session": session.to_dict(),
        "target": session.request.target.summary(),
        "answer": _compose_chain_answer(session),
        "model_id": None,
        "model_calls": 0,
        "target_path": None,
        "sandbox_root": None,
        "tool_calls": tool_calls,
        "observations": [],
        # RE-ACT findings are chain-shaped ({title, detail, severity}); they are
        # returned separately from the investigation-shaped ``findings`` array.
        "findings": [],
        "pentest_findings": session.findings,
        "mitigation": session.mitigation,
        "budget_usage": session.guard_usage,
        "iterations": len(tool_calls),
    }


react_chain = ReactChain()
