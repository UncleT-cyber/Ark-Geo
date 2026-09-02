"""Simulated signaling backend — deterministic dry-run engine.

This is the non-live engine: it re-uses the deterministic tables and helpers
from the original ``/telecom/signaling-audit`` mock so numbers stay stable for
a given target, but every result is flagged ``live=False, simulated=True`` and
the workflow steps carry explicit ``SIMULATED`` warnings.  No network traffic
is ever emitted by this backend.
"""
from __future__ import annotations

import time
from typing import Any

from app.signaling.backend import SignalingBackend, register_backend
from app.signaling.errors import TargetValidationError
from app.signaling.schema import (
    CellIdentity,
    ImsiCatcherRequest,
    ImsiCatcherResult,
    SilentSmsRequest,
    SilentSmsResult,
    SignalingResult,
    SignalingTarget,
    SubscriberRecord,
)

# Deterministic tables/helpers shared with the (superseded) telecom mock.
from app.api.v1.endpoints.telecom import (
    _CARRIER_BASELINE,
    _MCC_DEFAULT_MNC,
    _MCC_TO_ISO,
    _coverage_footprint,
    _derive_mcc,
    _pick_thread,
    _rand01,
    _rand_seed,
    _synthetic_cgimcc_mnc,
    _synthetic_imsi,
    normalize_e164,
)


def _target(msisdn: str, mcc: str | None, mnc: str | None) -> SignalingTarget:
    return SignalingTarget(msisdn=msisdn, mcc=mcc, mnc=mnc)


def _operator_name(mcc: str) -> str:
    if mcc in _MCC_DEFAULT_MNC:
        _, name = _MCC_DEFAULT_MNC[mcc]
        return name.split(" · ")[0]
    return _CARRIER_BASELINE.get("mtn", ("MTN", "NG Mobile"))[0]


@register_backend
class SimulatedBackend(SignalingBackend):
    id = "simulated"
    live = False

    def _testbed_label(self) -> str:
        return "Simulated dry-run engine — deterministic, no live SS7/Diameter traffic"

    # ------------------------------------------------------------------ #
    def _base(
        self,
        op: str,
        msisdn: str,
        steps: list[dict[str, Any]],
        raw: dict[str, Any],
    ) -> SignalingResult:
        phone = normalize_e164(msisdn)
        mcc, iso = _derive_mcc(phone)
        mnc = None
        if mcc and mcc in _MCC_DEFAULT_MNC:
            mnc, _ = _MCC_DEFAULT_MNC[mcc]
        seed = _rand_seed("sim", op, phone)
        imsi = _synthetic_imsi(mcc or "000", mnc or "00", seed) if mcc and mnc else None
        lac = int(_rand01(seed, 5) * 65535)
        ci = int(_rand01(seed, 6) * 65535)
        footprint = _coverage_footprint(iso, mcc, mnc) if iso else None
        operator = _operator_name(mcc) if mcc else None

        steps.append(
            {
                "ts": time.strftime("%H:%M:%S"),
                "kind": "sim",
                "event": f"{op}.simulated",
                "detail": "Dry-run — no live SS7/Diameter message emitted",
                "warn": "SIMULATED",
            }
        )

        return SignalingResult(
            op=op,
            backend=self.id,
            live=False,
            simulated=True,
            target=SignalingTarget(msisdn=phone, mcc=mcc, mnc=mnc, lac=lac, cell_id=ci),
            subscriber=SubscriberRecord(
                msisdn=phone,
                imsi=imsi,
                mcc=mcc,
                mnc=mnc,
                operator=operator,
                country=iso,
                vlr="VLRSIM01",
                lac=lac,
                cell_id=ci,
                roaming=False,
                alive=True,
            ),
            cell=CellIdentity(
                cgi=f"{mcc}-{mnc}-{lac:04X}-{ci:04X}" if mcc and mnc else None,
                mcc=mcc,
                mnc=mnc,
                lac=lac,
                cell_id=ci,
                operator=operator,
                country=iso,
                lat=footprint["lat"] if footprint else None,
                lon=footprint["lon"] if footprint else None,
                radius_meters=footprint["radius_meters"] if footprint else None,
            ),
            steps=steps,
            raw=raw,
            detail="Simulated dry-run result",
        )

    async def sri(self, msisdn: str) -> SignalingResult:
        steps = [
            {
                "ts": time.strftime("%H:%M:%S"),
                "kind": "sim",
                "event": "sri.dispatch",
                "detail": "Send Routing Info → simulated HLR register",
                "warn": "SIMULATED",
            },
            {
                "ts": time.strftime("%H:%M:%S"),
                "kind": "sim",
                "event": "sria.received",
                "detail": "Send Routing Info Ack — MSRN resolved",
            },
        ]
        return self._base("sri", msisdn, steps, {"thread": _pick_thread(_rand_seed("sri", msisdn))})

    async def ulr(self, target: str) -> SignalingResult:
        steps = [
            {
                "ts": time.strftime("%H:%M:%S"),
                "kind": "sim",
                "event": "ulr.request",
                "detail": "Update Location Request → simulated VLR",
                "warn": "SIMULATED",
            },
            {
                "ts": time.strftime("%H:%M:%S"),
                "kind": "sim",
                "event": "ula.received",
                "detail": "Update Location Answer — serving VLR accepted",
            },
        ]
        return self._base("ulr", target, steps, {"thread": "ULR"})

    async def ati(self, msisdn: str) -> SignalingResult:
        steps = [
            {
                "ts": time.strftime("%H:%M:%S"),
                "kind": "sim",
                "event": "ati.request",
                "detail": "Any Time Interrogation → simulated network state",
                "warn": "SIMULATED",
            }
        ]
        result = self._base("ati", msisdn, steps, {"thread": "ATI"})
        result.subscriber.lac = result.cell.lac
        result.subscriber.cell_id = result.cell.cell_id
        return result

    async def plr(self, msisdn: str) -> SignalingResult:
        steps = [
            {
                "ts": time.strftime("%H:%M:%S"),
                "kind": "sim",
                "event": "plr.request",
                "detail": "Provide Location → simulated serving MSC geo-answer",
                "warn": "SIMULATED",
            }
        ]
        result = self._base("plr", msisdn, steps, {"thread": "PLR", "source": "simulated-smlc"})
        result.raw["lat"] = result.cell.lat
        result.raw["lon"] = result.cell.lon
        return result

    async def imsi(self, msisdn: str) -> SignalingResult:
        steps = [
            {
                "ts": time.strftime("%H:%M:%S"),
                "kind": "sim",
                "event": "imsi.extract",
                "detail": "Subscriber identity resolved (deterministic dry-run)",
                "warn": "SIMULATED",
            }
        ]
        return self._base("imsi", msisdn, steps, {})

    async def cgi(self, mcc: str, mnc: str, lac: int | None, cell_id: int | None) -> SignalingResult:
        mcc = mcc or "621"
        mnc = mnc or "30"
        lac = lac if lac is not None else int(_rand01(_rand_seed(mcc, mnc), 5) * 65535)
        cell_id = cell_id if cell_id is not None else int(_rand01(_rand_seed(mcc, mnc, "ci"), 6) * 65535)
        iso = _MCC_TO_ISO.get(mcc)
        footprint = _coverage_footprint(iso, mcc, mnc) if iso else None
        return SignalingResult(
            op="cgi",
            backend=self.id,
            live=False,
            simulated=True,
            target=SignalingTarget(msisdn="", mcc=mcc, mnc=mnc, lac=lac, cell_id=cell_id),
            cell=CellIdentity(
                cgi=f"{mcc}-{mnc}-{lac:04X}-{cell_id:04X}",
                mcc=mcc,
                mnc=mnc,
                lac=lac,
                cell_id=cell_id,
                operator=_operator_name(mcc),
                country=iso,
                lat=footprint["lat"] if footprint else None,
                lon=footprint["lon"] if footprint else None,
                radius_meters=footprint["radius_meters"] if footprint else None,
            ),
            steps=[
                {
                    "ts": time.strftime("%H:%M:%S"),
                    "kind": "sim",
                    "event": "cgi.parse",
                    "detail": "CGI resolved against simulated registry",
                    "warn": "SIMULATED",
                }
            ],
            raw={},
            detail="Simulated dry-run cell identity",
        )

    async def silent_sms(self, request: SilentSmsRequest) -> SilentSmsResult:
        return SilentSmsResult(
            message_id=f"SIM-{int(time.time() * 1000)}",
            target=normalize_e164(request.target),
            sent=False,
            submitted_at_ms=int(time.time() * 1000),
            detail="Silent SMS suppressed in dry-run mode — no SM-DELIVER emitted",
        )

    async def imsi_catcher(self, request: ImsiCatcherRequest) -> ImsiCatcherResult:
        if request.band not in ("", "GSM-1800", "GSM-900"):
            raise TargetValidationError(f"Unsupported dry-run band '{request.band}'")
        now = int(time.time() * 1000)
        return ImsiCatcherResult(
            band=request.band or "GSM-1800",
            captures=[],
            count=0,
            started_ms=now,
            duration_ms=0,
        )
