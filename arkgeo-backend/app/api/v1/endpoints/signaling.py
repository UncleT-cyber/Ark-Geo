"""Certified live-signaling endpoints.

Every operation here sits behind the certified-personnel boundary
(:func:`require_certified`) and, for live traffic, a per-operator
authorization token (:func:`validate_operator_token`).  The active testbed
driver is selected by ``settings.signaling_backend`` — the endpoint layer
never talks to a testbed directly and every action (allowed or denied) lands
in the append-only audit trail.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.api.v1.endpoints.telecom import _derive_mcc, normalize_e164
from app.services.phone_osint import run_osint
from app.signaling.access import (
    OperatorTokenRequest,
    OperatorTokenResponse,
    PersonnelAuthRequest,
    PersonnelAuthResponse,
    PersonnelIdentity,
    issue_operator_token,
    issue_personnel_token,
    operator_token_authorizes,
    require_certified,
    require_operator_admin,
    validate_operator_token,
)
from app.signaling.audit import audit_log, new_trace_id
from app.signaling.backend import SignalingBackend, get_backend
from app.signaling.errors import SignalingError
from app.signaling.schema import (
    ImsiCatcherRequest,
    ImsiCatcherResult,
    SilentSmsRequest,
    SilentSmsResult,
    SignalingResult,
)

router = APIRouter(prefix="/signaling")
logger = logging.getLogger(__name__)


def _to_http(exc: SignalingError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail if exc.detail else exc.code)


def _mcc_of_target(target: str) -> str | None:
    """Best-effort MCC from an E.164 target (None if unknown)."""
    try:
        mcc, _ = _derive_mcc(target)
        return mcc
    except Exception:  # noqa: BLE001 - never let derivation block authz
        return None


async def _dispatch(
    identity: PersonnelIdentity,
    op: str,
    func,
    *,
    target: str,
    operator_token: Optional[str],
    mcc: Optional[str],
    trace_id: str,
    required_live_token: bool = True,
) -> SignalingResult:
    """Validate operator authorization, run the driver op, and audit."""
    target_mcc = mcc or _mcc_of_target(target)

    def deny(reason: str) -> None:
        audit_log.record(
            actor=identity.username, role=identity.role, op=op, target=target,
            operator="", mcc=target_mcc or "", trace_id=trace_id,
            outcome="denied", detail=reason,
        )

    if required_live_token:
        if not operator_token:
            deny("missing X-Operator-Authorization token")
            raise HTTPException(
                status_code=403,
                detail="X-Operator-Authorization token required for signaling operations",
            )
        try:
            auth = validate_operator_token(operator_token, required_mcc=target_mcc)
        except HTTPException as exc:
            deny(str(exc.detail))
            raise
        if not operator_token_authorizes(auth, op):
            deny(f"operator token scope '{auth.scope}' does not permit '{op}'")
            raise HTTPException(
                status_code=403,
                detail=f"Operator token scope does not permit '{op}'",
            )
    else:
        auth = None

    try:
        result: SignalingResult = await func()
    except SignalingError as exc:
        audit_log.record(
            actor=identity.username,
            role=identity.role,
            op=op,
            target=target,
            operator=(auth.operator if auth else ""),
            mcc=(auth.mcc if auth else "") or (target_mcc or ""),
            trace_id=trace_id,
            outcome="denied",
            detail=f"{exc.code}: {exc.detail if exc.detail else exc.code}",
        )
        raise _to_http(exc) from exc
    except Exception as exc:  # noqa: BLE001 - audit + re-raise as 500
        logger.exception("Signaling op '%s' failed", op)
        audit_log.record(
            actor=identity.username,
            role=identity.role,
            op=op,
            target=target,
            operator=(auth.operator if auth else ""),
            mcc=(auth.mcc if auth else "") or (target_mcc or ""),
            trace_id=trace_id,
            outcome="error",
            detail=f"unhandled: {exc.__class__.__name__}",
        )
        raise HTTPException(status_code=500, detail="Signaling operation failed") from exc

    result.trace_id = trace_id
    audit_log.record(
        actor=identity.username,
        role=identity.role,
        op=op,
        target=target,
        operator=(auth.operator if auth else ""),
        mcc=(auth.mcc if auth else "") or (target_mcc or ""),
        trace_id=trace_id,
        outcome="allowed",
        detail=f"backend={result.backend} live={result.live}",
    )
    return result


async def _active_backend() -> SignalingBackend:
    try:
        return get_backend()
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# --------------------------------------------------------------------------- #
# Status / identity / authorization
# --------------------------------------------------------------------------- #
@router.get("/status")
async def signaling_status():
    backend = await _active_backend()
    return {"backend": backend.id, "live": backend.live, "testbed": backend._testbed_label()}


@router.post("/auth/token", response_model=PersonnelAuthResponse)
async def signaling_login(request: PersonnelAuthRequest):
    resp = issue_personnel_token(request.username, request.password)
    if resp is None:
        audit_log.record(
            actor=request.username,
            role="UNVERIFIED",
            op="auth.login",
            target="",
            trace_id=new_trace_id("auth"),
            outcome="denied",
            detail="bad credentials",
        )
        raise HTTPException(status_code=401, detail="Invalid credentials")
    audit_log.record(
        actor=request.username,
        role=resp.role,
        op="auth.login",
        target="",
        trace_id=new_trace_id("auth"),
        outcome="allowed",
        detail="personnel token issued",
    )
    return resp


@router.get("/auth/me", response_model=PersonnelIdentity)
async def signaling_me(identity: PersonnelIdentity = Depends(require_certified)):
    return identity


@router.post("/auth/operator-token", response_model=OperatorTokenResponse)
async def signaling_operator_token(
    request: OperatorTokenRequest,
    admin: PersonnelIdentity = Depends(require_operator_admin),
):
    resp = issue_operator_token(request)
    audit_log.record(
        actor=admin.username,
        role=admin.role,
        op="auth.operator-token",
        target="",
        operator=request.operator,
        mcc=request.mcc,
        trace_id=resp.trace_id,
        outcome="allowed",
        detail=f"scope={request.scope} valid_hours={request.valid_hours}",
    )
    return resp


@router.get("/audit")
async def signaling_audit(
    limit: int = 100,
    identity: PersonnelIdentity = Depends(require_certified),
):
    """Audit trail. CERTIFIED_OPERATOR_ADMIN sees all entries; other
    certified roles see only their own actions."""
    entries = audit_log.recent(limit=min(limit, 500))
    if identity.role != "CERTIFIED_OPERATOR_ADMIN":
        entries = [e for e in entries if e.get("actor") == identity.username]
    return {"entries": entries}


# --------------------------------------------------------------------------- #
# SS7 / Diameter operations
# --------------------------------------------------------------------------- #
@router.post("/sri", response_model=SignalingResult)
async def signaling_sri(
    request: dict,
    identity: PersonnelIdentity = Depends(require_certified),
    operator_token: Optional[str] = Header(default=None, alias="X-Operator-Authorization"),
):
    target = normalize_e164(str(request.get("msisdn", request.get("phone", ""))))
    backend = await _active_backend()
    return await _dispatch(
        identity, "sri", lambda: backend.sri(target), target=target,
        operator_token=operator_token, mcc=_mcc_of_target(target), trace_id=new_trace_id(),
    )


@router.post("/ulr", response_model=SignalingResult)
async def signaling_ulr(
    request: dict,
    identity: PersonnelIdentity = Depends(require_certified),
    operator_token: Optional[str] = Header(default=None, alias="X-Operator-Authorization"),
):
    target = normalize_e164(str(request.get("msisdn", request.get("phone", ""))))
    backend = await _active_backend()
    return await _dispatch(
        identity, "ulr", lambda: backend.ulr(target), target=target,
        operator_token=operator_token, mcc=_mcc_of_target(target), trace_id=new_trace_id(),
    )


@router.post("/ati", response_model=SignalingResult)
async def signaling_ati(
    request: dict,
    identity: PersonnelIdentity = Depends(require_certified),
    operator_token: Optional[str] = Header(default=None, alias="X-Operator-Authorization"),
):
    target = normalize_e164(str(request.get("msisdn", request.get("phone", ""))))
    backend = await _active_backend()
    return await _dispatch(
        identity, "ati", lambda: backend.ati(target), target=target,
        operator_token=operator_token, mcc=_mcc_of_target(target), trace_id=new_trace_id(),
    )


@router.post("/plr", response_model=SignalingResult)
async def signaling_plr(
    request: dict,
    identity: PersonnelIdentity = Depends(require_certified),
    operator_token: Optional[str] = Header(default=None, alias="X-Operator-Authorization"),
):
    target = normalize_e164(str(request.get("msisdn", request.get("phone", ""))))
    backend = await _active_backend()
    return await _dispatch(
        identity, "plr", lambda: backend.plr(target), target=target,
        operator_token=operator_token, mcc=_mcc_of_target(target), trace_id=new_trace_id(),
    )


@router.post("/imsi", response_model=SignalingResult)
async def signaling_imsi(
    request: dict,
    identity: PersonnelIdentity = Depends(require_certified),
    operator_token: Optional[str] = Header(default=None, alias="X-Operator-Authorization"),
):
    target = normalize_e164(str(request.get("msisdn", request.get("phone", ""))))
    backend = await _active_backend()
    return await _dispatch(
        identity, "imsi", lambda: backend.imsi(target), target=target,
        operator_token=operator_token, mcc=_mcc_of_target(target), trace_id=new_trace_id(),
    )


@router.post("/cgi", response_model=SignalingResult)
async def signaling_cgi(
    request: dict,
    identity: PersonnelIdentity = Depends(require_certified),
    operator_token: Optional[str] = Header(default=None, alias="X-Operator-Authorization"),
):
    mcc = str(request.get("mcc", ""))
    mnc = str(request.get("mnc", ""))
    lac = request.get("lac")
    cell_id = request.get("cell_id")
    backend = await _active_backend()
    target = f"cgi:{mcc}-{mnc}"
    return await _dispatch(
        identity, "cgi", lambda: backend.cgi(mcc, mnc, lac, cell_id),
        target=target, operator_token=operator_token, mcc=mcc, trace_id=new_trace_id(),
    )


@router.post("/silent-sms", response_model=SilentSmsResult)
async def signaling_silent_sms(
    request: SilentSmsRequest,
    identity: PersonnelIdentity = Depends(require_certified),
    operator_token: Optional[str] = Header(default=None, alias="X-Operator-Authorization"),
):
    target = normalize_e164(request.target)
    backend = await _active_backend()
    trace_id = new_trace_id()
    target_mcc = _mcc_of_target(target)
    if not operator_token:
        raise HTTPException(status_code=403, detail="X-Operator-Authorization token required")
    auth = validate_operator_token(operator_token, required_mcc=target_mcc)
    if not operator_token_authorizes(auth, "silent_sms"):
        raise HTTPException(status_code=403, detail="Operator token scope does not permit 'silent_sms'")
    try:
        result = await backend.silent_sms(request)
    except SignalingError as exc:
        audit_log.record(
            actor=identity.username, role=identity.role, op="silent_sms", target=target,
            operator=auth.operator, mcc=auth.mcc or target_mcc or "", trace_id=trace_id,
            outcome="denied", detail=f"{exc.code}: {exc.detail if exc.detail else exc.code}",
        )
        raise _to_http(exc) from exc
    audit_log.record(
        actor=identity.username, role=identity.role, op="silent_sms", target=target,
        operator=auth.operator, mcc=auth.mcc or target_mcc or "", trace_id=trace_id,
        outcome="allowed", detail=f"sent={result.sent} backend={backend.id}",
    )
    return result


@router.post("/imsi-catcher", response_model=ImsiCatcherResult)
async def signaling_imsi_catcher(
    request: ImsiCatcherRequest,
    identity: PersonnelIdentity = Depends(require_certified),
    operator_token: Optional[str] = Header(default=None, alias="X-Operator-Authorization"),
):
    backend = await _active_backend()
    trace_id = new_trace_id()
    mcc = request.mcc_filter
    if not operator_token:
        raise HTTPException(status_code=403, detail="X-Operator-Authorization token required")
    auth = validate_operator_token(operator_token, required_mcc=mcc)
    if not operator_token_authorizes(auth, "imsi_catcher"):
        raise HTTPException(status_code=403, detail="Operator token scope does not permit 'imsi_catcher'")
    try:
        result = await backend.imsi_catcher(request)
    except SignalingError as exc:
        audit_log.record(
            actor=identity.username, role=identity.role, op="imsi_catcher",
            target=f"band={request.band}", operator=auth.operator,
            mcc=auth.mcc or mcc or "", trace_id=trace_id, outcome="denied",
            detail=f"{exc.code}: {exc.detail if exc.detail else exc.code}",
        )
        raise _to_http(exc) from exc
    audit_log.record(
        actor=identity.username, role=identity.role, op="imsi_catcher",
        target=f"band={request.band}", operator=auth.operator,
        mcc=auth.mcc or mcc or "", trace_id=trace_id, outcome="allowed",
        detail=f"captures={result.count} backend={backend.id}",
    )
    return result


# --------------------------------------------------------------------------- #
# Non-licensed OSINT aggregation (certified personnel; no operator token)
# --------------------------------------------------------------------------- #
class PhoneOsintRequest(BaseModel):
    phone: str = Field(..., description="International phone number (E.164)")
    keys: dict[str, str] = Field(
        default_factory=dict,
        description="Optional BYOK provider keys (ipqs / twilio_account_sid / "
                    "twilio_auth_token / infobip / opencnam_account_sid / "
                    "opencnam_auth_token). Never stored or logged.",
    )


class OsintWorkerResult(BaseModel):
    status: str = "ok"
    note: str = ""
    data: dict = Field(default_factory=dict)


class PhoneFootprint(BaseModel):
    presence: dict[str, bool] = Field(default_factory=dict)
    avatar_url: Optional[str] = None
    profile_status: Optional[str] = None
    probes: list[dict] = Field(default_factory=list)
    probed: bool = False
    simulated: bool = False
    note: str = ""


class PhoneReputation(BaseModel):
    spam_score: Optional[int] = None
    spam: Optional[bool] = None
    risky: Optional[bool] = None
    leaktory: Optional[bool] = None
    fraud_score: Optional[int] = None
    is_voip: Optional[bool] = None
    is_prepaid: Optional[bool] = None
    cnam_registered: Optional[bool] = None
    threat_intel_flags: list[str] = Field(default_factory=list)
    simulated: bool = False
    note: str = ""


class PhoneOsintResponse(BaseModel):
    ok: bool
    phone_e164: str = ""
    country_code: str = ""
    iso2: str = ""
    carrier: Optional[str] = None
    mcc: Optional[str] = None
    mnc: Optional[str] = None
    line_type: Optional[str] = None
    valid: bool = False
    possible: bool = False
    number_type: Optional[str] = None
    national_number: Optional[str] = None
    ndc: Optional[str] = None
    subscriber_number: Optional[str] = None
    national_format: str = ""
    international_format: str = ""
    geo_city: Optional[str] = None
    routing_location: Optional[str] = None
    timezone: list[str] = Field(default_factory=list)
    geo_zone: Optional[str] = None
    active: Optional[bool] = None
    ported: Optional[bool] = None
    roaming_country: Optional[str] = None
    live_state: Optional[str] = None
    line_state: Optional[str] = None
    sim_last_changed: Optional[str] = None
    sim_swap_risk: Optional[float] = None
    same_device_score: Optional[float] = None
    caller_name: Optional[str] = None
    risk: dict = Field(default_factory=dict)
    reputation: PhoneReputation = Field(default_factory=PhoneReputation)
    footprint: PhoneFootprint = Field(default_factory=PhoneFootprint)
    requires_key: list[str] = Field(default_factory=list)
    location_hint: Optional[str] = None
    provider_note: str = ""
    free_source: str = ""
    trace_id: str = ""
    workers: dict[str, OsintWorkerResult] = Field(default_factory=dict)
    detail: str = ""


@router.post("/osint", response_model=PhoneOsintResponse)
async def signaling_osint(
    request: PhoneOsintRequest,
    identity: PersonnelIdentity = Depends(require_certified),
):
    """Certified OSINT aggregation — free registry tier plus any configured
    provider tiers (HLR live state / CNAM / risk) run in parallel."""
    phone = normalize_e164(request.phone)
    trace_id = new_trace_id()
    try:
        result = await run_osint(phone, request.keys or None)
    except Exception as exc:  # noqa: BLE001
        logger.exception("OSINT aggregation failed")
        audit_log.record(
            actor=identity.username, role=identity.role, op="osint", target=phone,
            mcc=_mcc_of_target(phone) or "", trace_id=trace_id,
            outcome="error", detail=exc.__class__.__name__,
        )
        raise HTTPException(status_code=500, detail="OSINT aggregation failed") from exc

    if not result.get("ok"):
        audit_log.record(
            actor=identity.username, role=identity.role, op="osint", target=phone,
            mcc=_mcc_of_target(phone) or "", trace_id=trace_id,
            outcome="denied", detail=result.get("reason", "unparseable"),
        )
        raise HTTPException(status_code=422, detail=result.get("reason", "Unparseable number"))

    workers = {
        name: OsintWorkerResult(**w) for name, w in (result.get("workers") or {}).items()
    }
    audit_log.record(
        actor=identity.username, role=identity.role, op="osint", target=phone,
        mcc=(result.get("mcc") or "") or (_mcc_of_target(phone) or ""), trace_id=trace_id,
        outcome="allowed",
        detail=f"iso2={result.get('iso2')} carrier={result.get('carrier') or '?'} "
               f"line={result.get('line_type') or '?'} workers={len(workers)}",
    )
    return PhoneOsintResponse(trace_id=trace_id, detail=f"trace {trace_id}", **result)


# --------------------------------------------------------------------------- #
# Certified dry-run surface (no operator token required — no live traffic)
# --------------------------------------------------------------------------- #
@router.post("/dry-run", response_model=SignalingResult)
async def signaling_dry_run(
    request: dict,
    identity: PersonnelIdentity = Depends(require_certified),
):
    target = normalize_e164(str(request.get("msisdn", request.get("phone", ""))))
    backend = await _active_backend()
    return await _dispatch(
        identity, "sri", lambda: backend.sri(target), target=target, operator_token=None,
        mcc=_mcc_of_target(target), trace_id=new_trace_id(), required_live_token=False,
    )


# --------------------------------------------------------------------------- #
# Canary links — out-of-band callbacks for the LIVE OPS step.
#
# A canary link is a tracking URL: when the target device/browser opens it, the
# callback is recorded (timestamp, IP, user-agent) and surfaced in the
# workspace. Generation requires certified auth; *visiting* a link does NOT —
# that is the whole point (the target must be able to reach it without a
# session). The hit surface is intentionally minimal and benign.
# --------------------------------------------------------------------------- #
_CANARY_STORE: dict[str, dict] = {}  # token -> {phone, pretext, ts, hits: [...]}


class CanaryCreateRequest(BaseModel):
    phone: str = Field(..., min_length=5)
    pretext: str = "canary-webhook"


class CanaryCreateResponse(BaseModel):
    ok: bool = True
    token: str
    url: str
    ts: str


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return (request.client.host if request.client else "unknown")


def _record_canary_hit(token: str, request: Request) -> None:
    entry = _CANARY_STORE.get(token)
    if not entry:
        return
    entry.setdefault("hits", []).append({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "ip": _client_ip(request),
        "ua": request.headers.get("user-agent", "")[:200],
    })
    entry["last_hit_ts"] = entry["hits"][-1]["ts"]


@router.post("/canary", response_model=CanaryCreateResponse)
async def canary_create(
    body: CanaryCreateRequest,
    request: Request,
    identity: PersonnelIdentity = Depends(require_certified),
):
    token = uuid.uuid4().hex[:16]
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    url = f"{request.base_url}api/v1/signaling/canary/{token}"
    _CANARY_STORE[token] = {
        "phone": normalize_e164(body.phone),
        "pretext": body.pretext,
        "ts": ts,
        "hits": [],
    }
    audit_log.record(
        actor=identity.username, role=identity.role, op="canary_create",
        target=normalize_e164(body.phone), trace_id=new_trace_id(),
        outcome="allowed", detail=f"pretext={body.pretext}",
    )
    return CanaryCreateResponse(token=token, url=url, ts=ts)


@router.get("/canary/{token}", response_class=HTMLResponse)
async def canary_visit(token: str, request: Request):
    """Benign landing page. Visiting records the callback; no data is shown
    to the visitor (that would leak the operator's work to the target)."""
    if token not in _CANARY_STORE:
        return HTMLResponse(
            "<html><body style='font-family:monospace;background:#0b1220;color:#94a3b8;"
            "display:flex;align-items:center;justify-content:center;height:100vh'>"
            "This page is no longer active.</body></html>",
            status_code=404,
        )
    _record_canary_hit(token, request)
    return HTMLResponse(
        "<html><body style='font-family:monospace;background:#0b1220;color:#94a3b8;"
        "display:flex;align-items:center;justify-content:center;height:100vh'>"
        "Callback registered — you may close this window.</body></html>",
    )


class CanaryHitRequest(BaseModel):
    token: str = Field(..., min_length=4)


class CanaryHitResponse(BaseModel):
    ok: bool = True
    id: str
    ts: str


@router.post("/canary/hit", response_model=CanaryHitResponse)
async def canary_hit(body: CanaryHitRequest, request: Request):
    token = body.token
    if token not in _CANARY_STORE:
        raise HTTPException(404, "Unknown canary token")
    _record_canary_hit(token, request)
    return CanaryHitResponse(id=token, ts=_CANARY_STORE[token]["hits"][-1]["ts"])


class CanaryStatusResponse(BaseModel):
    ok: bool = True
    token: str
    phone: str
    pretext: str
    ts: str
    hits: list[dict]


@router.get("/canary/{token}/hits", response_model=CanaryStatusResponse)
async def canary_status(
    token: str,
    identity: PersonnelIdentity = Depends(require_certified),
):
    entry = _CANARY_STORE.get(token)
    if not entry:
        raise HTTPException(404, "Unknown canary token")
    return CanaryStatusResponse(
        token=token, phone=entry["phone"], pretext=entry["pretext"],
        ts=entry["ts"], hits=entry.get("hits", []),
    )
