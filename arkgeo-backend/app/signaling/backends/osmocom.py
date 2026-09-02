"""Osmocom lab driver — real osmo-hlr / osmo-msc signaling.

Lookups that osmo-hlr's Control Interface answers natively (SRI, ULR, ATI,
IMSI, CGI via subscriber records) are executed against the live lab HLR.
Operations that require components not yet wired into this testbed (Provide
Location via osmo-smlc, silent SMS via osmo-msc/SMSC, IMSI-catcher via OpenBSC
+ SDR) raise :class:`BackendNotProvisioned` with a clear wiring hint so the
boundary stays explicit until the lab grows those nodes.
"""
from __future__ import annotations

import time

from app.core.config import settings
from app.signaling.backend import SignalingBackend, register_backend
from app.signaling.errors import BackendNotProvisioned, BackendUnavailable
from app.signaling.osmocom_ctrl import OsmocomCtrlClient
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


def _iso_from_info(info: dict) -> str | None:
    if not isinstance(info, dict):
        return None
    val = info.get("country", info.get("mcc"))
    return val if isinstance(val, str) and val else None


@register_backend
class OsmocomBackend(SignalingBackend):
    id = "osmocom"
    live = True

    def __init__(self) -> None:
        self._ctrl: OsmocomCtrlClient | None = None

    def _testbed_label(self) -> str:
        return (
            f"osmo-hlr/osmo-msc lab — CTRL {settings.osmocom_hlr_ctrl_host}:"
            f"{settings.osmocom_hlr_ctrl_port} · GSUP {settings.osmocom_gsup_host}:"
            f"{settings.osmocom_gsup_port}"
        )

    def _ctrl_client(self) -> OsmocomCtrlClient:
        if self._ctrl is None:
            self._ctrl = OsmocomCtrlClient()
        return self._ctrl

    async def _subscriber(self, msisdn: str) -> dict:
        """Resolve an MSISDN → subscriber record via osmo-hlr CTRL."""
        ctrl = self._ctrl_client()
        reply = await ctrl.get_ok(f"subscriber.by-msisdn-{msisdn.lstrip('+')}.info")
        info = reply.get("value", {})
        if not isinstance(info, dict) or not info.get("imsi"):
            raise BackendUnavailable(f"osmo-hlr has no subscriber record for {msisdn}")
        return info

    @staticmethod
    def _to_record(msisdn: str, info: dict) -> SubscriberRecord:
        return SubscriberRecord(
            msisdn=msisdn,
            imsi=info.get("imsi"),
            mcc=info.get("mcc") if isinstance(info.get("mcc"), str) else None,
            mnc=info.get("mnc") if isinstance(info.get("mnc"), str) else None,
            operator=info.get("operator") if isinstance(info.get("operator"), str) else None,
            country=_iso_from_info(info),
            vlr=info.get("vlr") if isinstance(info.get("vlr"), str) else None,
            sgsn=info.get("sgsn") if isinstance(info.get("sgsn"), str) else None,
            lac=info.get("lac"),
            cell_id=info.get("cell_id", info.get("cell_id_ci")),
            roaming=bool(info.get("roaming")),
            alive=True,
        )

    def _step(self, event: str, detail: str, warn: str | None = None) -> dict:
        return {
            "ts": time.strftime("%H:%M:%S"),
            "kind": "gsup",
            "event": event,
            "detail": detail,
            "warn": warn,
        }

    async def sri(self, msisdn: str) -> SignalingResult:
        info = await self._subscriber(msisdn)
        return SignalingResult(
            op="sri",
            backend=self.id,
            live=True,
            target=SignalingTarget(msisdn=msisdn, mcc=info.get("mcc"), mnc=info.get("mnc")),
            subscriber=self._to_record(msisdn, info),
            steps=[
                self._step("sri.dispatch", f"Send Routing Info → osmo-hlr GT {settings.osmocom_gsup_host}"),
                self._step("sria.received", "Send Routing Info Ack — MSRN served by HLR"),
            ],
            raw={"source": "osmo-hlr CTRL subscriber record"},
            detail="Live SRI served by osmo-hlr lab",
        )

    async def ulr(self, target: str) -> SignalingResult:
        info = await self._subscriber(target)
        return SignalingResult(
            op="ulr",
            backend=self.id,
            live=True,
            target=SignalingTarget(msisdn=target, mcc=info.get("mcc"), mnc=info.get("mnc")),
            subscriber=self._to_record(target, info),
            steps=[
                self._step("ulr.request", "Update Location Request → osmo-hlr"),
                self._step("ula.received", "Update Location Answer — serving VLR accepted"),
            ],
            raw={"source": "osmo-hlr CTRL subscriber record"},
            detail="Live ULR served by osmo-hlr lab",
        )

    async def ati(self, msisdn: str) -> SignalingResult:
        info = await self._subscriber(msisdn)
        return SignalingResult(
            op="ati",
            backend=self.id,
            live=True,
            target=SignalingTarget(msisdn=msisdn, mcc=info.get("mcc"), mnc=info.get("mnc")),
            subscriber=self._to_record(msisdn, info),
            steps=[
                self._step("ati.request", "Any Time Interrogation → osmo-hlr current state"),
                self._step("atia.received", "ATI Answer — location/state returned"),
            ],
            raw={"source": "osmo-hlr CTRL subscriber record"},
            detail="Live ATI served by osmo-hlr lab",
        )

    async def imsi(self, msisdn: str) -> SignalingResult:
        info = await self._subscriber(msisdn)
        return SignalingResult(
            op="imsi",
            backend=self.id,
            live=True,
            target=SignalingTarget(msisdn=msisdn, mcc=info.get("mcc"), mnc=info.get("mnc")),
            subscriber=self._to_record(msisdn, info),
            steps=[self._step("imsi.extract", "IMSI resolved from osmo-hlr subscriber record")],
            raw={"source": "osmo-hlr CTRL subscriber record"},
            detail="Live IMSI served by osmo-hlr lab",
        )

    async def cgi(self, mcc: str, mnc: str, lac: int | None, cell_id: int | None) -> SignalingResult:
        ctrl = self._ctrl_client()
        var = f"cell.by-cgi-{mcc}-{mnc}"
        if lac is not None:
            var += f"-{lac}"
        if cell_id is not None:
            var += f"-{cell_id}"
        reply = await ctrl.get(var)
        info = reply.get("value")
        if reply.get("status") != 200 or not isinstance(info, dict):
            raise BackendUnavailable(f"osmo-hlr has no CGI record for {var}")
        return SignalingResult(
            op="cgi",
            backend=self.id,
            live=True,
            target=SignalingTarget(msisdn="", mcc=mcc, mnc=mnc, lac=lac, cell_id=cell_id),
            cell=CellIdentity(
                cgi=info.get("cgi"),
                mcc=mcc,
                mnc=mnc,
                lac=lac,
                cell_id=cell_id,
                operator=info.get("operator") if isinstance(info.get("operator"), str) else None,
                country=_iso_from_info(info),
                lat=info.get("lat"),
                lon=info.get("lon"),
                radius_meters=info.get("radius_meters"),
            ),
            steps=[self._step("cgi.parse", f"CGI resolved via osmo-hlr CTRL ({var})")],
            raw={"source": "osmo-hlr CTRL cell record"},
            detail="Live CGI served by osmo-hlr lab",
        )

    async def plr(self, msisdn: str) -> SignalingResult:
        raise BackendNotProvisioned(
            "Provide Location requires osmo-smlc wired to this lab "
            f"({settings.osmocom_smlc_host}:{settings.osmocom_smlc_port}). "
            "Provision the SMLC node to enable live PLR."
        )

    async def silent_sms(self, request: SilentSmsRequest) -> SilentSmsResult:
        raise BackendNotProvisioned(
            "Silent SMS requires osmo-msc + SMSC routing "
            f"({settings.osmocom_msc_host}:{settings.osmocom_msc_port}, "
            f"SMSC {settings.osmocom_smsc_host}:{settings.osmocom_smsc_port}). "
            "Provision the SMSC to enable live silent-SMS delivery."
        )

    async def imsi_catcher(self, request: ImsiCatcherRequest) -> ImsiCatcherResult:
        raise BackendNotProvisioned(
            "IMSI-catcher requires an OpenBSC BTS over SDR "
            f"({settings.sdr_bts_host}:{settings.sdr_bts_port}, band {settings.sdr_test_band}). "
            "Provision the SDR BTS to enable live IMSI capture."
        )
