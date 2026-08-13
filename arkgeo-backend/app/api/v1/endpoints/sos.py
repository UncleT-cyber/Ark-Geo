"""SOS endpoint – emergency trigger & dispatch."""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter

from app.core.security import sha256_hex
from app.models import SosRequest, SosResponse, ThreatAlertRequest, ThreatAlertResponse
from app.services.twilio_service import twilio

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/sos", response_model=SosResponse)
async def trigger_sos(request: SosRequest):
    sos_id = str(uuid.uuid4())

    # Build a map link from the last known GPS or consensus
    lat, lon = None, None
    if request.last_known_gps:
        lat, lon = request.last_known_gps.lat, request.last_known_gps.lon
    elif request.consensus:
        lat, lon = request.consensus.estimated_latitude, request.consensus.estimated_longitude

    if lat is not None and lon is not None and (lat != 0.0 or lon != 0.0):
        map_link = f"https://maps.google.com/?q={lat},{lon}"
    else:
        map_link = "https://maps.google.com"

    contacted = twilio.dispatch_sos(
        request.contacts, map_link, request.user_id, request.message
    )

    logger.warning("SOS %s dispatched for user %s to %d contacts",
                   sos_id, request.user_id, len(contacted))

    return SosResponse(
        sos_id=sos_id,
        dispatched=len(contacted) > 0,
        contacted=contacted,
        map_link=map_link,
    )


@router.post("/threat-alert", response_model=ThreatAlertResponse)
async def trigger_threat_alert(request: ThreatAlertRequest):
    """Threat Integration Hub — dispatch a standardized SOC alert.

    Triggered when the frontend or ingestion engine records a critical
    geofence violation or an active GPS spoofing threat.  Formats a JSON
    alert envelope and routes it via Twilio.
    """
    alert_id = str(uuid.uuid4())

    contacted = twilio.dispatch_threat_alert(
        contacts=request.contacts,
        alert_type=request.alert_type,
        description=request.description,
        coordinates=request.coordinates,
        anomaly_score=request.anomaly_score,
        user_id=request.user_id,
    )

    logger.warning(
        "Threat alert %s dispatched: type=%s score=%s to %d contacts",
        alert_id, request.alert_type, request.anomaly_score, len(contacted),
    )

    return ThreatAlertResponse(
        alert_id=alert_id,
        dispatched=len(contacted) > 0,
        contacted=contacted,
        alert_type=request.alert_type,
        message=f"Threat alert ({request.alert_type}) dispatched to {len(contacted)} contact(s)",
    )
