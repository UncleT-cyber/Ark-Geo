"""AI gateway status endpoint — the runtime route every AI consumer is on.

Reports the unified provider cascade state (``cloud`` / ``local_ollama`` /
``offline``) that powers the GS / GI / LLM badges in the web header and the
Admin Console model-gateway panel.  Reads are cheap (server-side cache) and
never expose key material — only configured flags and route state.
"""
from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, File, HTTPException, UploadFile

from app.services.ai_gateway import ai_gateway

router = APIRouter()


@router.get("/ai/status")
async def ai_status() -> dict[str, Any]:
    return await ai_gateway.status()

_AUDIO_TYPES = {"audio/webm": "webm", "audio/mp4": "mp4", "audio/ogg": "ogg"}
_MAX_AUDIO_BYTES = 5 * 1024 * 1024


@router.get("/ai/transcription")
async def transcription_status() -> dict[str, bool]:
    return {"available": bool(ai_gateway._cloud_key("openai"))}


@router.post("/ai/transcription")
async def transcribe(file: UploadFile = File(...)) -> dict[str, str]:
    key = ai_gateway._cloud_key("openai")
    if not key:
        raise HTTPException(503, "OpenAI transcription is unavailable.")
    mime = (file.content_type or "").split(";", 1)[0]
    extension = _AUDIO_TYPES.get(mime)
    if not extension:
        raise HTTPException(415, "Unsupported recording format.")
    audio = await file.read(_MAX_AUDIO_BYTES + 1)
    if not audio:
        raise HTTPException(400, "The recording was empty.")
    if len(audio) > _MAX_AUDIO_BYTES:
        raise HTTPException(413, "The recording is too large.")
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                f"{ai_gateway._cloud_base('openai')}/audio/transcriptions",
                headers={"Authorization": f"Bearer {key}"},
                data={"model": "gpt-transcribe"},
                files={"file": (f"recording.{extension}", audio, mime)},
            )
            response.raise_for_status()
            text = response.json()["text"]
            if not isinstance(text, str):
                raise ValueError("Invalid transcription")
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
        raise HTTPException(502, "The transcription provider could not process the recording.") from exc
    return {"text": text.strip()}
