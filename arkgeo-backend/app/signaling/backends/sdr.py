"""OpenBSC + USRP/GSU SDR backend — test-band BTS / IMSI-catcher.

Contract-complete: the operation signatures match the live driver contract,
but nothing runs until the SDR hardware (USRP/bladeRF), the test band license
and an OpenBSC network are provisioned.  Every call raises
:class:`BackendNotProvisioned` with the exact wiring that is missing.
"""
from __future__ import annotations

from typing import NoReturn

from app.core.config import settings
from app.signaling.backend import SignalingBackend, register_backend
from app.signaling.errors import BackendNotProvisioned
from app.signaling.schema import ImsiCatcherRequest, ImsiCatcherResult, SilentSmsRequest, SilentSmsResult


@register_backend
class SdrBackend(SignalingBackend):
    id = "sdr"
    live = True

    def _testbed_label(self) -> str:
        return (
            f"OpenBSC + SDR test band — BTS {settings.sdr_bts_host}:{settings.sdr_bts_port} · "
            f"band {settings.sdr_test_band} · catcher radius ≤ {settings.sdr_max_imsi_catcher_radius_m}m"
        )

    def _gate(self, capability: str) -> NoReturn:
        raise BackendNotProvisioned(
            f"{capability} requires an OpenBSC BTS on SDR hardware "
            f"({settings.sdr_bts_host}:{settings.sdr_bts_port}, band {settings.sdr_test_band}). "
            "Provision the SDR + test-band license to enable this live operation."
        )

    async def sri(self, msisdn: str):
        self._gate("SRI")

    async def ulr(self, target: str):
        self._gate("ULR")

    async def ati(self, msisdn: str):
        self._gate("ATI")

    async def plr(self, msisdn: str):
        self._gate("PLR")

    async def imsi(self, msisdn: str):
        self._gate("IMSI")

    async def cgi(self, mcc: str, mnc: str, lac: int | None, cell_id: int | None):
        self._gate("CGI/PAR")

    async def silent_sms(self, request: SilentSmsRequest) -> SilentSmsResult:
        self._gate("Silent SMS")

    async def imsi_catcher(self, request: ImsiCatcherRequest) -> ImsiCatcherResult:
        if request.radius_m and request.radius_m > settings.sdr_max_imsi_catcher_radius_m:
            self._gate(
                f"IMSI-catcher radius {request.radius_m}m exceeds test-band ceiling "
                f"({settings.sdr_max_imsi_catcher_radius_m}m)"
            )
        self._gate("IMSI-catcher sweep")
