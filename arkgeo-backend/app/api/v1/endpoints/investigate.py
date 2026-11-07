"""AI Investigation endpoints — Phase C.

Entry point for AI Investigation Mode:

* ``POST /investigate`` — supply evidence (multipart file) + a typed objective
  (JSON form field). Returns a **proposed** investigation: objective, plan
  steps, planner source, empty graph. Nothing has executed yet.
* ``POST /investigate/{id}/approve`` — approve (or amend) the plan, then run
  it through the Policy Guard. Returns the completed session: plan statuses,
  AGENT activity log, evidence graph, and structured findings.
* ``GET /investigate/{id}`` — current session state (poll from the console).

The deterministic ``/analyze`` pipeline is untouched. This is the second
entry mode, not a replacement for the first.
"""
from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from app.agent import schemas as S
from app.agent.orchestrator import orchestrator
from app.services.principal import principal_from_request

router = APIRouter()
logger = logging.getLogger(__name__)


def _owned_or_404(investigation_id: str, principal):
    """Return the session only if it belongs to ``principal``, else raise 404.

    A cross-owner request is reported exactly like an unknown id, so the
    endpoint is not an existence oracle (mirrors ``cai._session_visible_to``).
    """
    session = orchestrator.get(investigation_id)
    if session is None or getattr(session, "principal_subject", None) != principal.subject:
        raise HTTPException(status_code=404,
                            detail=f"Unknown investigation {investigation_id}")
    return session


class ApproveRequest(BaseModel):
    approved_by: str = "analyst"
    amend_steps: list[dict[str, str]] = Field(default_factory=list)


class ResumeRequest(BaseModel):
    approved_by: str = "analyst"
    budget: dict = Field(default_factory=dict)  # optional Budget override


class AmendRequest(BaseModel):
    steps: list[dict[str, str]] = Field(default_factory=list)


def _parse_objective(raw: str) -> S.InvestigationObjective:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid objective JSON: {exc}")

    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Objective must be a JSON object")

    goal_name = data.get("goal", "verify_location_credibility")
    try:
        goal = S.InvestigationGoal(goal_name)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown goal '{goal_name}' — "
                   f"expected one of {[g.value for g in S.InvestigationGoal]}",
        )

    claims = [
        S.ClaimToVerify(field=c["field"], value=c.get("value"))
        for c in (data.get("claims_to_verify") or [])
        if isinstance(c, dict) and c.get("field")
    ]
    constraints_raw = data.get("constraints") or {}
    constraints = S.ObjectiveConstraints(**constraints_raw) \
        if isinstance(constraints_raw, dict) else S.ObjectiveConstraints()

    return S.InvestigationObjective(
        objective_id=f"OBJ-{uuid.uuid4().hex[:8].upper()}",
        goal=goal,
        subject=data.get("subject", "uploaded-evidence"),
        domain=data.get("domain", "image"),
        claims_to_verify=claims,
        constraints=constraints,
        natural_language=data.get("natural_language"),
    )


@router.post("/investigate")
async def create_investigation(
    request: Request,
    file: UploadFile = File(...),
    objective: str = Form(...),
):
    """Start an AI investigation: evidence + objective → proposed plan."""
    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Empty image upload")

    principal = principal_from_request(request)
    obj = _parse_objective(objective)
    session = await orchestrator.start(
        obj, image_bytes=image_bytes, principal_subject=principal.subject,
    )
    logger.info(
        "Investigation %s started (goal=%s, domain=%s, planner=%s)",
        session.investigation_id, obj.goal.value, obj.domain,
        session.planner_source,
    )
    return session.to_dict()


@router.post("/investigate/{investigation_id}/approve")
async def approve_investigation(
    investigation_id: str,
    body: ApproveRequest,
    request: Request,
):
    """Approve (optionally amend) the plan and execute it."""
    _owned_or_404(investigation_id, principal_from_request(request))
    try:
        session = await orchestrator.approve(
            investigation_id,
            approved_by=body.approved_by,
            amend_steps=body.amend_steps or None,
        )
    except KeyError:
        raise HTTPException(status_code=404,
                            detail=f"Unknown investigation {investigation_id}")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return session.to_dict()


@router.post("/investigate/{investigation_id}/resume")
async def resume_investigation(
    investigation_id: str,
    body: ResumeRequest,
    request: Request,
):
    """Resume a paused (pause_to_ask) investigation, optionally with a new
    budget. Continues the adaptive loop from the current graph state."""
    _owned_or_404(investigation_id, principal_from_request(request))
    budget = S.Budget(**body.budget) if body.budget else None
    try:
        session = await orchestrator.resume(
            investigation_id,
            budget=budget,
            approved_by=body.approved_by,
        )
    except KeyError:
        raise HTTPException(status_code=404,
                            detail=f"Unknown investigation {investigation_id}")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return session.to_dict()


@router.get("/investigate/{investigation_id}")
async def get_investigation(investigation_id: str, request: Request):
    session = _owned_or_404(investigation_id, principal_from_request(request))
    return session.to_dict()


# --------------------------------------------------------------------------- #
# Cross-domain CASES layer (Phase G) — one case, many domains.
# --------------------------------------------------------------------------- #
def _owned_sessions(principal) -> list:
    """Every investigation owned by ``principal`` (case unification input)."""
    return [
        s for s in orchestrator.store.list()
        if getattr(s, "principal_subject", None) == principal.subject
    ]


@router.get("/cases")
async def list_cases(request: Request):
    """Case summaries across every domain, newest first."""
    from app.agent.case_engine import list_cases as _list_cases

    return {"cases": _list_cases(_owned_sessions(principal_from_request(request)))}


@router.get("/cases/{case_id}")
async def get_case(case_id: str, request: Request):
    """Unified case view: union evidence, findings, cross-domain
    contradictions, and one audit trail across every investigation on the
    case. Reported as 404 when the case has no investigation for this caller
    (no existence oracle)."""
    from app.agent.case_engine import case_view

    sessions = [
        s for s in _owned_sessions(principal_from_request(request))
        if s.case_id == case_id
    ]
    if not sessions:
        raise HTTPException(status_code=404, detail=f"Unknown case {case_id}")
    return case_view(case_id, sessions)
