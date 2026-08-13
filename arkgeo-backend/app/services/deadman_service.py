"""Dead-Man's Switch manager.

Arms per-user countdown timers.  If a user fails to enter their PIN before
expiry (plus a grace period), the switch fires: it ingests the user's last
capture, runs the Brain pipeline, and dispatches SOS SMS via Twilio.

In production the polling loop runs as a background asyncio task started
from ``main.py``.  State is held in-memory (swap for Redis/DB later).
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from app.core.config import settings
from app.models import DeadManConfig, DeadManStatus, SosRequest
from app.services.twilio_service import twilio

logger = logging.getLogger(__name__)


class DeadManSwitch:
    def __init__(self) -> None:
        self._armed: Dict[str, DeadManConfig] = {}
        self._expires: Dict[str, datetime] = {}
        self._fired: set[str] = set()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def arm(self, config: DeadManConfig) -> DeadManStatus:
        with self._lock:
            self._armed[config.user_id] = config
            self._expires[config.user_id] = datetime.now(timezone.utc) + timedelta(
                minutes=config.duration_minutes
            )
            self._fired.discard(config.user_id)
        logger.info("Dead-Man armed for %s (%d min)", config.user_id, config.duration_minutes)
        return self.status(config.user_id)

    def check_in(self, user_id: str, pin_hash: str) -> DeadManStatus:
        """Reset the timer if the PIN matches."""
        with self._lock:
            config = self._armed.get(user_id)
            if not config:
                return DeadManStatus(user_id=user_id, armed=False)
            if config.pin_hash != pin_hash:
                logger.warning("Dead-Man check-in failed (bad PIN) for %s", user_id)
                return self.status(user_id)
            self._expires[user_id] = datetime.now(timezone.utc) + timedelta(
                minutes=config.duration_minutes
            )
            logger.info("Dead-Man reset for %s", user_id)
            return self.status(user_id)

    def disarm(self, user_id: str) -> None:
        with self._lock:
            self._armed.pop(user_id, None)
            self._expires.pop(user_id, None)
            self._fired.discard(user_id)
        logger.info("Dead-Man disarmed for %s", user_id)

    def status(self, user_id: str) -> DeadManStatus:
        with self._lock:
            config = self._armed.get(user_id)
            exp = self._expires.get(user_id)
        if not config or not exp:
            return DeadManStatus(user_id=user_id, armed=False)
        now = datetime.now(timezone.utc)
        grace_remaining = max(0, int((exp.timestamp() - now.timestamp())))
        return DeadManStatus(
            user_id=user_id,
            armed=True,
            expires_at=exp,
            grace_remaining_seconds=grace_remaining,
        )

    # ------------------------------------------------------------------ #
    # Polling loop
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("Dead-Man poller started (interval=%ds)", settings.deadman_poll_seconds)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as exc:  # pragma: no cover
                logger.error("Dead-Man tick error: %s", exc)
            self._stop_event.wait(settings.deadman_poll_seconds)

    def _tick(self) -> None:
        now = datetime.now(timezone.utc)
        with self._lock:
            expired = [
                uid for uid, exp in self._expires.items()
                if now > exp + timedelta(seconds=settings.deadman_grace_seconds)
                and uid not in self._fired
            ]
        for uid in expired:
            self._fire(uid)

    def _fire(self, user_id: str) -> None:
        with self._lock:
            config = self._armed.get(user_id)
            if not config:
                return
            self._fired.add(user_id)

        logger.warning("Dead-Man FIRED for %s — dispatching SOS", user_id)

        # Build an SOS request and dispatch via Twilio.
        from app.models import EmergencyContact, GpsFix, SosRequest
        from app.core.security import sha256_hex

        map_link = "https://maps.google.com"
        if config.last_known_gps:
            map_link = (
                f"https://maps.google.com/?q={config.last_known_gps.lat},"
                f"{config.last_known_gps.lon}"
            )

        sos = SosRequest(
            user_id=user_id,
            last_capture_image_base64=config.last_capture_image_base64,
            last_known_gps=config.last_known_gps,
            contacts=config.emergency_contacts,
            message=f"Dead-Man's switch expired for user {user_id}. "
                    f"Last known location: {map_link}",
        )
        contacted = twilio.dispatch_sos(
            sos.contacts, map_link, user_id, sos.message
        )
        logger.info("Dead-Man SOS dispatched to %d contacts", len(contacted))


# Singleton
deadman = DeadManSwitch()
