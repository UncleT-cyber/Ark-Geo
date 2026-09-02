"""Shared data model for the live-signaling driver layer.

These models are backend-agnostic: the simulated (dry-run) engine, the
osmo-hlr/osmo-msc lab driver and the (future) licensed operator gateway all
produce and consume the same shapes so the certified access boundary and the
audit trail stay uniform.
"""
from __future__ import annotations

import enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Certifications / identity
# --------------------------------------------------------------------------- #
class CertifiedRole(str, enum.Enum):
    CERTIFIED_OPERATOR = "CERTIFIED_OPERATOR"
    CERTIFIED_OPERATOR_ADMIN = "CERTIFIED_OPERATOR_ADMIN"
    AUDITOR = "AUDITOR"


CERTIFIED_ROLES = tuple(role.value for role in CertifiedRole)

SIGNALING_OPS = (
    "sri",
    "ulr",
    "ati",
    "plr",
    "imsi",
    "cgi",
    "silent_sms",
    "imsi_catcher",
)


class PersonnelRecord(BaseModel):
    username: str
    full_name: str
    role: str
    password_hash: str = ""
    active: bool = True
    operator_scopes: list[str] = Field(default_factory=list)


class OperatorAuthorization(BaseModel):
    operator: str
    mcc: str
    scope: str = "sri,ulr,ati,plr,imsi,cgi,silent_sms,imsi_catcher"
    valid_until: int
    trace_id: str = ""


# --------------------------------------------------------------------------- #
# Signaling operations
# --------------------------------------------------------------------------- #
class SignalingTarget(BaseModel):
    """A validated E.164 phone number plus optional cell context."""

    msisdn: str
    mcc: Optional[str] = None
    mnc: Optional[str] = None
    lac: Optional[int] = None
    cell_id: Optional[int] = None


class SubscriberRecord(BaseModel):
    """Normalised subscriber detail returned by SRI/ULR/ATI/IMSI."""

    msisdn: str
    imsi: Optional[str] = None
    mcc: Optional[str] = None
    mnc: Optional[str] = None
    operator: Optional[str] = None
    country: Optional[str] = None
    vlr: Optional[str] = None
    sgsn: Optional[str] = None
    lac: Optional[int] = None
    cell_id: Optional[int] = None
    roaming: Optional[bool] = None
    alive: Optional[bool] = None


class CellIdentity(BaseModel):
    cgi: Optional[str] = None
    mcc: Optional[str] = None
    mnc: Optional[str] = None
    lac: Optional[int] = None
    cell_id: Optional[int] = None
    operator: Optional[str] = None
    country: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    radius_meters: Optional[float] = None


class SilentSmsRequest(BaseModel):
    target: str
    text: str = Field(default="", max_length=140)
    delivery_report: bool = False


class SilentSmsResult(BaseModel):
    message_id: str
    target: str
    sent: bool
    submitted_at_ms: int
    detail: str


class ImsiCatcherRequest(BaseModel):
    band: str = ""
    radius_m: int = 0
    capture_seconds: int = 15
    mcc_filter: Optional[str] = None


class ImsiCatcherResult(BaseModel):
    band: str
    captures: list[dict[str, Any]] = Field(default_factory=list)
    count: int = 0
    started_ms: int = 0
    duration_ms: int = 0


class SignalingResult(BaseModel):
    op: str
    backend: str
    live: bool
    simulated: bool = False
    target: SignalingTarget
    subscriber: Optional[SubscriberRecord] = None
    cell: Optional[CellIdentity] = None
    steps: list[dict[str, Any]] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)
    trace_id: str = ""
    detail: str = ""
