"""Live signaling subsystem — SS7/Diameter drivers + certified access.

Submodules:
    backend       — SignalingBackend ABC + registry/factory
    backends/     — simulated (dry-run), osmocom (osmo-hlr lab), sdr, commercial
    access        — certified-personnel RBAC + per-operator authorization
    audit         — append-only signaling audit trail
    osmocom_ctrl  — osmo-hlr Control Interface client
"""
from __future__ import annotations

# Importing the backend modules registers their classes with the driver registry.
from app.signaling import backends  # noqa: F401
