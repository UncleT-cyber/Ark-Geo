"""Signaling driver abstraction.

A :class:`SignalingBackend` implements the live or simulated SS7/Diameter
operations against a concrete testbed.  The active backend is selected from
``settings.signaling_backend`` (``simulated`` | ``osmocom`` | ``sdr`` |
``commercial``).  The endpoint layer never touches a testbed directly — it
talks only to this interface, which keeps the RBAC + audit boundary uniform.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from app.core.config import settings
from app.signaling.schema import (
    ImsiCatcherRequest,
    ImsiCatcherResult,
    SilentSmsRequest,
    SilentSmsResult,
    SignalingResult,
)

logger = logging.getLogger(__name__)

BACKEND_IDS = ("simulated", "osmocom", "sdr", "commercial")


class SignalingBackend(ABC):
    """Common contract every testbed driver implements.

    ``live`` distinguishes real signaling traffic from a dry-run engine.
    """

    id: str = "base"
    live: bool = False

    def describe(self) -> dict:
        return {
            "id": self.id,
            "live": self.live,
            "testbed": self._testbed_label(),
        }

    @abstractmethod
    def _testbed_label(self) -> str:
        """Human-readable testbed description for status surfaces."""

    @abstractmethod
    async def sri(self, msisdn: str) -> SignalingResult:
        """Send Routing Info — resolve roaming MSRN for an MSISDN."""

    @abstractmethod
    async def ulr(self, target: str) -> SignalingResult:
        """Update Location — register/refresh serving VLR for a subscriber."""

    @abstractmethod
    async def ati(self, msisdn: str) -> SignalingResult:
        """Any Time Interrogation — query current network state/location."""

    @abstractmethod
    async def plr(self, msisdn: str) -> SignalingResult:
        """Provide Location — request current geo-location from serving MSC."""

    @abstractmethod
    async def imsi(self, msisdn: str) -> SignalingResult:
        """IMSI resolution — map an MSISDN to its IMSI/subscriber identity."""

    @abstractmethod
    async def cgi(self, mcc: str, mnc: str, lac: int | None, cell_id: int | None) -> SignalingResult:
        """CGI/PAR — resolve a cell identifier to operator/geometry."""

    @abstractmethod
    async def silent_sms(self, request: SilentSmsRequest) -> SilentSmsResult:
        """Inject a silent (Class-0 / delivery-ack) SMS to a target."""

    @abstractmethod
    async def imsi_catcher(self, request: ImsiCatcherRequest) -> ImsiCatcherResult:
        """Run an IMSI-catcher sweep on an authorized test band."""


_REGISTRY: dict[str, type[SignalingBackend]] = {}


def register_backend(cls: type[SignalingBackend]) -> type[SignalingBackend]:
    _REGISTRY[cls.id] = cls
    return cls


def get_backend(backend_id: str | None = None) -> SignalingBackend:
    """Instantiate (singleton-per-process) the active signaling backend."""
    bid = backend_id or settings.signaling_backend
    cls = _REGISTRY.get(bid)
    if cls is None:
        raise ValueError(
            f"Unknown signaling backend '{bid}'. "
            f"Valid: {', '.join(BACKEND_IDS)}"
        )
    return cls()
