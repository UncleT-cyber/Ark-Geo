"""Commercial operator gateway backend — licensed SCCP/DIAMETER path.

This is the *authorized* route to live signaling intelligence (ATI/CGI/IMSI/
SRI/PLR). It is NOT a bypass: it calls a licensed operator or number-
intelligence provider's REST API using credentials YOU provision in
``settings.signaling_commercial_base_url`` / ``signaling_commercial_api_key``.
Until both are set the backend raises :class:`BackendNotProvisioned`, and the
endpoint layer still enforces the certified-operator JWT + per-operator MCC
token + audit trail before any driver method runs.

The adapter is provider-shape tolerant: it POSTs the operation + parameters to
``{base_url}/{op}`` with ``Authorization: Bearer <key>`` and maps whatever the
provider returns into the unified :class:`SignalingResult` schema, copying the
fields it recognizes (``subscriber.*``, ``cell.*``, ``steps``, ``raw``) and
leaving anything unrecognized in ``raw`` for the analyst.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.core.config import settings
from app.signaling.backend import SignalingBackend, register_backend
from app.signaling.errors import BackendNotProvisioned
from app.signaling.schema import (
    ImsiCatcherRequest,
    ImsiCatcherResult,
    SilentSmsRequest,
    SilentSmsResult,
    SignalingResult,
    SignalingTarget,
    SubscriberRecord,
    CellIdentity,
)

logger = logging.getLogger(__name__)


def _creds() -> tuple[str, str]:
    base = (settings.signaling_commercial_base_url or "").rstrip("/")
    key = settings.signaling_commercial_api_key or ""
    if not base or not key:
        raise BackendNotProvisioned(
            "Commercial gateway is not provisioned. Set "
            "signaling_commercial_base_url and signaling_commercial_api_key "
            "(licensed operator / number-intelligence provider)."
        )
    return base, key


async def _call(op: str, payload: dict[str, Any], timeout: float = 30.0) -> dict[str, Any]:
    base, key = _creds()
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        r = await client.post(
            f"{base}/{op}",
            json=payload,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
    if r.status_code != 200:
        raise BackendNotProvisioned(f"Commercial gateway returned HTTP {r.status_code} for {op}")
    try:
        return r.json()
    except Exception:  # noqa: BLE001
        raise BackendNotProvisioned(f"Commercial gateway returned non-JSON for {op}")


def _subscriber_from(raw: dict[str, Any], msisdn: str) -> SubscriberRecord:
    s = raw.get("subscriber", {}) or {}
    return SubscriberRecord(
        msisdn=msisdn,
        imsi=s.get("imsi"),
        mcc=s.get("mcc"),
        mnc=s.get("mnc"),
        operator=s.get("operator"),
        country=s.get("country"),
        vlr=s.get("vlr"),
        lac=s.get("lac"),
        cell_id=s.get("cell_id"),
        roaming=bool(s.get("roaming", False)),
        alive=bool(s.get("alive", s.get("active", False))),
    )


def _cell_from(raw: dict[str, Any]) -> CellIdentity:
    c = raw.get("cell", {}) or {}
    return CellIdentity(
        cgi=c.get("cgi"),
        mcc=c.get("mcc"),
        mnc=c.get("mnc"),
        lac=c.get("lac"),
        cell_id=c.get("cell_id"),
        operator=c.get("operator"),
        country=c.get("country"),
        lat=c.get("lat"),
        lon=c.get("lon"),
        radius_meters=c.get("radius_meters"),
    )


@register_backend
class CommercialGatewayBackend(SignalingBackend):
    id = "commercial"
    live = True

    def _testbed_label(self) -> str:
        return "Licensed operator SCCP/DIAMETER gateway (provisioned REST adapter)"

    async def sri(self, msisdn: str) -> SignalingResult:
        raw = await _call("sri", {"msisdn": msisdn})
        return SignalingResult(
            op="sri", backend=self.id, live=True, simulated=False,
            target=SignalingTarget(msisdn=msisdn),
            subscriber=_subscriber_from(raw, msisdn),
            cell=_cell_from(raw),
            steps=[{"ts": time.strftime("%H:%M:%S"), "kind": "live",
                    "event": "sri.ack", "detail": "MSRN resolved via licensed gateway",
                    "warn": None}],
            raw=raw, detail="Live SRI via licensed commercial gateway",
        )

    async def ulr(self, target: str) -> SignalingResult:
        raw = await _call("ulr", {"target": target})
        return SignalingResult(
            op="ulr", backend=self.id, live=True, simulated=False,
            target=SignalingTarget(msisdn=target),
            subscriber=_subscriber_from(raw, target),
            cell=_cell_from(raw),
            steps=[{"ts": time.strftime("%H:%M:%S"), "kind": "live",
                    "event": "ula.received", "detail": "Serving VLR accepted (licensed)"}],
            raw=raw, detail="Live ULR via licensed commercial gateway",
        )

    async def ati(self, msisdn: str) -> SignalingResult:
        raw = await _call("ati", {"msisdn": msisdn})
        return SignalingResult(
            op="ati", backend=self.id, live=True, simulated=False,
            target=SignalingTarget(msisdn=msisdn),
            subscriber=_subscriber_from(raw, msisdn),
            cell=_cell_from(raw),
            steps=[{"ts": time.strftime("%H:%M:%S"), "kind": "live",
                    "event": "ati.answer", "detail": "Subscriber state + location via ATI (licensed)"}],
            raw=raw, detail="Live ATI via licensed commercial gateway",
        )

    async def plr(self, msisdn: str) -> SignalingResult:
        raw = await _call("plr", {"msisdn": msisdn})
        res = SignalingResult(
            op="plr", backend=self.id, live=True, simulated=False,
            target=SignalingTarget(msisdn=msisdn),
            subscriber=_subscriber_from(raw, msisdn),
            cell=_cell_from(raw),
            steps=[{"ts": time.strftime("%H:%M:%S"), "kind": "live",
                    "event": "plr.answer", "detail": "Provide-Location geo-answer (licensed)"}],
            raw=raw, detail="Live PLR via licensed commercial gateway",
        )
        res.raw["lat"] = (res.cell.lat if res.cell else None)
        res.raw["lon"] = (res.cell.lon if res.cell else None)
        return res

    async def imsi(self, msisdn: str) -> SignalingResult:
        raw = await _call("imsi", {"msisdn": msisdn})
        return SignalingResult(
            op="imsi", backend=self.id, live=True, simulated=False,
            target=SignalingTarget(msisdn=msisdn),
            subscriber=_subscriber_from(raw, msisdn),
            cell=_cell_from(raw),
            steps=[{"ts": time.strftime("%H:%M:%S"), "kind": "live",
                    "event": "imsi.resolved", "detail": "IMSI resolved (licensed)"}],
            raw=raw, detail="Live IMSI resolution via licensed commercial gateway",
        )

    async def cgi(self, mcc: str, mnc: str, lac: int | None, cell_id: int | None) -> SignalingResult:
        raw = await _call("cgi", {"mcc": mcc, "mnc": mnc, "lac": lac, "cell_id": cell_id})
        return SignalingResult(
            op="cgi", backend=self.id, live=True, simulated=False,
            target=SignalingTarget(msisdn="", mcc=mcc, mnc=mnc, lac=lac, cell_id=cell_id),
            cell=_cell_from(raw),
            steps=[{"ts": time.strftime("%H:%M:%S"), "kind": "live",
                    "event": "cgi.resolved", "detail": "Cell identity resolved (licensed)"}],
            raw=raw, detail="Live CGI/PAR via licensed commercial gateway",
        )

    async def silent_sms(self, request: SilentSmsRequest) -> SilentSmsResult:
        raw = await _call("silent-sms", request.model_dump())
        return SilentSmsResult(
            message_id=raw.get("message_id"),
            target=request.target,
            sent=bool(raw.get("sent", False)),
            submitted_at_ms=int(time.time() * 1000),
            detail=raw.get("detail", "Silent SMS dispatched via licensed gateway"),
        )

    async def imsi_catcher(self, request: ImsiCatcherRequest) -> ImsiCatcherResult:
        raw = await _call("imsi-catcher", request.model_dump())
        caps = raw.get("captures") or []
        return ImsiCatcherResult(
            band=request.band or "GSM-1800",
            captures=caps,
            count=int(raw.get("count", len(caps))),
            started_ms=int(time.time() * 1000),
            duration_ms=int(raw.get("duration_ms", 0)),
            detail=raw.get("detail", "IMSI-catcher sweep via licensed gateway"),
        )
