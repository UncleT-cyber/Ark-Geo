"""Twilio SMS dispatch service for ArkGeo SOS alerts.

Sends emergency SMS messages with a map link to all configured emergency
contacts.  Degrades gracefully (returns ``dispatched=False``) when Twilio
credentials are not configured, logging the would-be message instead.
"""
from __future__ import annotations

import logging
from typing import List

from app.core.config import settings

logger = logging.getLogger(__name__)


class TwilioService:
    def __init__(self) -> None:
        self._client = None
        if settings.twilio_account_sid and settings.twilio_auth_token:
            try:
                from twilio.rest import Client
                self._client = Client(
                    settings.twilio_account_sid, settings.twilio_auth_token
                )
            except Exception as exc:  # pragma: no cover
                logger.warning("Twilio client init failed: %s", exc)

    @property
    def is_configured(self) -> bool:
        return self._client is not None and settings.twilio_from_number is not None

    def dispatch_sos(
        self,
        contacts: List,
        map_link: str,
        user_id: str,
        custom_message: str | None = None,
    ) -> List[str]:
        """Send an SOS SMS to each contact.  Returns list of contacted numbers."""
        contacted: List[str] = []
        body = custom_message or (
            f"⚠️ ARKGEO SOS ALERT ⚠️\n"
            f"User {user_id} triggered an emergency check-in.\n"
            f"Estimated location: {map_link}"
        )

        for contact in contacts:
            if not self.is_configured:
                logger.info(
                    "[Twilio not configured] Would send SOS to %s (%s):\n%s",
                    contact.name, contact.phone, body,
                )
                contacted.append(contact.phone)
                continue
            try:
                self._client.messages.create(  # type: ignore[union-attr]
                    to=contact.phone,
                    from_=settings.twilio_from_number,
                    body=body,
                )
                contacted.append(contact.phone)
                logger.info("SOS SMS sent to %s", contact.phone)
            except Exception as exc:
                logger.error("Failed to send SOS to %s: %s", contact.phone, exc)
        return contacted


# Singleton
twilio = TwilioService()
