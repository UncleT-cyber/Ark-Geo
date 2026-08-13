"""Dead-Man's switch endpoint – arm / check-in / disarm / status."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.models import DeadManConfig, DeadManStatus
from app.services.deadman_service import deadman

router = APIRouter(prefix="/deadman")


@router.post("/arm", response_model=DeadManStatus)
async def arm(config: DeadManConfig):
    return deadman.arm(config)


@router.post("/checkin", response_model=DeadManStatus)
async def checkin(user_id: str, pin_hash: str):
    return deadman.check_in(user_id, pin_hash)


@router.post("/disarm", response_model=DeadManStatus)
async def disarm(user_id: str):
    deadman.disarm(user_id)
    return DeadManStatus(user_id=user_id, armed=False)


@router.get("/status/{user_id}", response_model=DeadManStatus)
async def status(user_id: str):
    return deadman.status(user_id)
