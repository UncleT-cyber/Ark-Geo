"""ARK Admin control-plane endpoints — Command Center, Client Telemetry,
Staff RBAC, Model Gateway, Tool Policy, Quotas, Tooling, Audit Logs and
Open-Source support settings.

All endpoints under /admin/* require the admin JWT (reuses the dependency
from the existing settings router).  Every mutating action writes an
append-only audit entry with actor, action, target, IP and timestamp.
API key *values* are never read or returned here — the gateway section
surfaces only ``configured`` flags and masked previews from the encrypted
SettingsStore.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, List, Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.api.v1.endpoints.settings import require_admin_token
from app.core.config import settings as bootstrap_settings
from app.services.admin_store import (
    PERMISSION_KEYS,
    STAFF_ROLES,
    admin_store,
)
from app.services.key_probe import live_probe
from app.services.model_catalog import (
    MODEL_PROVIDERS,
    PROVIDER_MODEL_KEY,
    fetch_models,
)
from app.services.settings_store import settings_store
from app.services.ai_gateway import get_active_litellm_model
from app.services.bus import bus

router = APIRouter(prefix="/admin")
logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Request / response models
# --------------------------------------------------------------------------- #
class TelemetryModel(BaseModel):
    last_login_ip: str = ""
    country: str = ""
    city: str = ""
    asn: str = ""
    proxy: bool = False
    vpn: bool = False
    tor_exit: bool = False
    user_agent: str = ""
    os: str = ""
    browser: str = ""
    tls_fingerprint: str = ""


class UsageModel(BaseModel):
    active_cases: int = 0
    storage_bytes: int = 0
    api_spend_usd: float = 0.0
    tokens_consumed: int = 0


class ClientCreate(BaseModel):
    full_name: str
    email: str
    plan: str = "free"
    status: str = "active"
    telemetry: Optional[TelemetryModel] = None
    usage: Optional[UsageModel] = None


class ClientPatch(BaseModel):
    plan: Optional[str] = None
    telemetry: Optional[TelemetryModel] = None
    usage: Optional[UsageModel] = None


class StaffCreate(BaseModel):
    username: str
    full_name: str
    role: str = "SECURITY_OPERATOR"
    permissions: dict[str, bool] = Field(default_factory=dict)


class StaffPatch(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = None
    permissions: Optional[dict[str, bool]] = None
    active: Optional[bool] = None


class QuotaPatch(BaseModel):
    storage_bytes: Optional[int] = None
    max_active_cases: Optional[int] = None
    monthly_token_budget: Optional[int] = None
    rate_limit_rpm: Optional[int] = None
    api_spend_cap_usd: Optional[float] = None


class SupportPatch(BaseModel):
    show_banner: Optional[bool] = None
    bmc_url: Optional[str] = None
    github_url: Optional[str] = None
    discord_url: Optional[str] = None


class GatewayPatch(BaseModel):
    active_llm_provider: Optional[str] = None
    ollama_url: Optional[str] = None
    ollama_model: Optional[str] = None
    huggingface_url: Optional[str] = None
    huggingface_model: Optional[str] = None
    openai_model: Optional[str] = None
    gemini_model: Optional[str] = None
    anthropic_model: Optional[str] = None
    openrouter_model: Optional[str] = None
    vision_enabled: Optional[bool] = None
    task_models: Optional[dict[str, str]] = None


class ToolingPatch(BaseModel):
    exiftool: Optional[dict[str, Any]] = None
    tesseract: Optional[dict[str, Any]] = None
    ollama: Optional[dict[str, Any]] = None
    local_nodes: Optional[List[dict[str, Any]]] = None


# --------------------------------------------------------------------------- #
# Command Center overview
# --------------------------------------------------------------------------- #
@router.get("/overview")
async def admin_overview(admin: str = Depends(require_admin_token)):
    clients = admin_store.list_clients()
    staff = admin_store.list_staff()
    tool_policy = admin_store.get_tool_policy()
    quotas = admin_store.get_quotas()
    support = admin_store.get_support()

    by_status = {"active": 0, "suspended": 0, "banned": 0}
    for c in clients:
        by_status[c.get("status", "active")] = by_status.get(c.get("status", "active"), 0) + 1

    total_storage = sum(c.get("usage", {}).get("storage_bytes", 0) for c in clients)
    total_spend = sum(c.get("usage", {}).get("api_spend_usd", 0.0) for c in clients)
    total_tokens = sum(c.get("usage", {}).get("tokens_consumed", 0) for c in clients)
    total_cases = sum(c.get("usage", {}).get("active_cases", 0) for c in clients)

    enabled_high_risk = [
        name for name, p in tool_policy.items()
        if p.get("enabled") and p.get("risk_level") == "HIGH"
    ]

    return {
        "clients": {
            "total": len(clients),
            "active": by_status.get("active", 0),
            "suspended": by_status.get("suspended", 0),
            "banned": by_status.get("banned", 0),
        },
        "staff": {"total": len(staff), "active": sum(1 for s in staff if s.get("active"))},
        "cases": {"total": total_cases},
        "usage": {
            "storage_bytes": total_storage,
            "api_spend_usd": round(total_spend, 2),
            "tokens_consumed": total_tokens,
        },
        "tools": {
            "enabled": sum(1 for p in tool_policy.values() if p.get("enabled")),
            "total": len(tool_policy),
            "enabled_high_risk": enabled_high_risk,
        },
        "audit_count": len(admin_store.list_audit()),
        "support": {"show_banner": support.get("show_banner", True)},
        "quotas": quotas,
        "generated_at_ms": int(time.time() * 1000),
    }


# --------------------------------------------------------------------------- #
# Client Directory & Telemetry
# --------------------------------------------------------------------------- #
@router.get("/clients")
async def list_clients(admin: str = Depends(require_admin_token)):
    return {"clients": admin_store.list_clients()}


@router.post("/clients", status_code=201)
async def create_client(body: ClientCreate, admin: str = Depends(require_admin_token)):
    if body.plan not in ("free", "pro", "enterprise"):
        raise HTTPException(status_code=422, detail="plan must be free|pro|enterprise")
    if body.status not in ("active", "suspended", "banned"):
        raise HTTPException(status_code=422, detail="status must be active|suspended|banned")
    record = {
        "client_id": f"CLT-{uuid.uuid4().hex[:8].upper()}",
        "full_name": body.full_name,
        "email": body.email,
        "plan": body.plan,
        "status": body.status,
        "created_at": f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
        "seed": False,
        "telemetry": body.telemetry.model_dump() if body.telemetry else {},
        "usage": body.usage.model_dump() if body.usage else {},
    }
    admin_store.upsert_client(record)
    admin_store.append_audit(admin, "client.create", record["client_id"],
                             detail=f"Created client {record['full_name']} ({record['plan']})")
    return record


@router.get("/clients/{client_id}")
async def get_client(client_id: str, admin: str = Depends(require_admin_token)):
    rec = admin_store.get_client(client_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Client not found")
    return rec


@router.patch("/clients/{client_id}")
async def patch_client(client_id: str, body: ClientPatch, admin: str = Depends(require_admin_token)):
    rec = admin_store.get_client(client_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Client not found")
    if body.plan is not None:
        if body.plan not in ("free", "pro", "enterprise"):
            raise HTTPException(status_code=422, detail="plan must be free|pro|enterprise")
        rec["plan"] = body.plan
    if body.telemetry is not None:
        rec["telemetry"] = body.telemetry.model_dump()
    if body.usage is not None:
        rec["usage"] = body.usage.model_dump()
    admin_store.upsert_client(rec)
    admin_store.append_audit(admin, "client.update", rec["client_id"], detail="Updated client record")
    return rec


@router.post("/clients/{client_id}/status")
async def client_status(client_id: str, body: dict[str, str],
                        admin: str = Depends(require_admin_token)):
    status = (body or {}).get("status")
    if status not in ("active", "suspended", "banned"):
        raise HTTPException(status_code=422, detail="status must be active|suspended|banned")
    rec = admin_store.set_client_status(client_id, status)
    if not rec:
        raise HTTPException(status_code=404, detail="Client not found")
    admin_store.append_audit(
        admin, f"client.{status}", client_id,
        detail=f"Sessions invalidated: {rec.get('sessions_invalidated', 0)}",
    )
    return rec


@router.post("/clients/{client_id}/terminate-sessions")
async def terminate_sessions(client_id: str, admin: str = Depends(require_admin_token)):
    rec = admin_store.get_client(client_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Client not found")
    n = int(rec.get("usage", {}).get("active_cases", 0)) or 1
    admin_store.append_audit(admin, "client.terminate_sessions", client_id,
                             detail=f"Force-terminated {n} active session(s)")
    return {"client_id": client_id, "sessions_terminated": n}


@router.delete("/clients/{client_id}")
async def delete_client(client_id: str, admin: str = Depends(require_admin_token)):
    if not admin_store.delete_client(client_id):
        raise HTTPException(status_code=404, detail="Client not found")
    admin_store.append_audit(admin, "client.delete", client_id, detail="Purged client state")
    return {"deleted": True, "client_id": client_id}


# --------------------------------------------------------------------------- #
# Staff & RBAC
# --------------------------------------------------------------------------- #
@router.get("/staff")
async def list_staff(admin: str = Depends(require_admin_token)):
    return {"staff": admin_store.list_staff(), "roles": list(STAFF_ROLES),
            "permission_keys": list(PERMISSION_KEYS)}


@router.post("/staff", status_code=201)
async def create_staff(body: StaffCreate, admin: str = Depends(require_admin_token)):
    if body.role not in STAFF_ROLES:
        raise HTTPException(status_code=422, detail=f"role must be one of {STAFF_ROLES}")
    record = {
        "staff_id": f"STF-{uuid.uuid4().hex[:6].upper()}",
        "username": body.username,
        "full_name": body.full_name,
        "role": body.role,
        "active": True,
        "seed": False,
        "permissions": {k: bool(body.permissions.get(k, False)) for k in PERMISSION_KEYS},
        "created_at": f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
    }
    admin_store.upsert_staff(record)
    admin_store.append_audit(admin, "staff.create", record["staff_id"],
                             detail=f"Created staff {body.username} ({body.role})")
    return record


@router.patch("/staff/{staff_id}")
async def patch_staff(staff_id: str, body: StaffPatch, admin: str = Depends(require_admin_token)):
    rec = admin_store.get_staff(staff_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Staff member not found")
    if body.full_name is not None:
        rec["full_name"] = body.full_name
    if body.role is not None:
        if body.role not in STAFF_ROLES:
            raise HTTPException(status_code=422, detail=f"role must be one of {STAFF_ROLES}")
        rec["role"] = body.role
    if body.permissions is not None:
        rec["permissions"] = {k: bool(body.permissions.get(k, rec["permissions"].get(k, False)))
                              for k in PERMISSION_KEYS}
    if body.active is not None:
        rec["active"] = body.active
    admin_store.upsert_staff(rec)
    admin_store.append_audit(admin, "staff.update", staff_id,
                             detail=f"Updated {rec['username']} role/permissions")
    return rec


@router.post("/staff/{staff_id}/deactivate")
async def deactivate_staff(staff_id: str, admin: str = Depends(require_admin_token)):
    if staff_id == "STF-0001":
        raise HTTPException(status_code=403, detail="Cannot deactivate the root platform account")
    rec = admin_store.deactivate_staff(staff_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Staff member not found")
    admin_store.append_audit(admin, "staff.deactivate", staff_id,
                             detail=f"Deactivated {rec['username']}")
    return rec


# --------------------------------------------------------------------------- #
# Audit Logs & Chain-of-Custody
# --------------------------------------------------------------------------- #
@router.get("/audit-logs")
async def audit_logs(actor: Optional[str] = None, action: Optional[str] = None,
                     target: Optional[str] = None, query: str = "",
                     admin: str = Depends(require_admin_token)):
    return {"logs": admin_store.list_audit(actor=actor, action=action, target=target, query=query)}


# --------------------------------------------------------------------------- #
# Tool Policy & Governors
# --------------------------------------------------------------------------- #
@router.get("/tool-policy")
async def tool_policy(admin: str = Depends(require_admin_token)):
    return {"policy": admin_store.get_tool_policy()}


@router.post("/tool-policy/{tool}/toggle")
async def toggle_tool(tool: str, body: dict[str, bool],
                      admin: str = Depends(require_admin_token)):
    if not admin_store.set_tool_state(tool, bool((body or {}).get("enabled", False))):
        raise HTTPException(status_code=404, detail="Unknown tool")
    admin_store.append_audit(admin, "tool_policy.toggle", tool,
                             detail=f"Enabled={bool((body or {}).get('enabled', False))}")
    return {"policy": admin_store.get_tool_policy()}


# --------------------------------------------------------------------------- #
# Quotas & Usage Tracking
# --------------------------------------------------------------------------- #
@router.get("/quotas")
async def quotas(admin: str = Depends(require_admin_token)):
    return {"quotas": admin_store.get_quotas()}


@router.patch("/quotas/{tier}")
async def patch_quota(tier: str, body: QuotaPatch, admin: str = Depends(require_admin_token)):
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    updated = admin_store.set_quota_plan(tier, patch)
    if not updated:
        raise HTTPException(status_code=404, detail="Unknown quota tier")
    admin_store.append_audit(admin, "quota.update", tier, detail="Updated quota plan")
    return {"quotas": admin_store.get_quotas()}


# --------------------------------------------------------------------------- #
# Local Tooling Binaries
# --------------------------------------------------------------------------- #
@router.get("/tooling")
async def tooling(admin: str = Depends(require_admin_token)):
    return {"tooling": admin_store.get_tooling()}


@router.post("/tooling/test")
async def test_tooling(admin: str = Depends(require_admin_token)):
    tooling = admin_store.get_tooling()
    # ExifTool / Tesseract — check binary availability on PATH.
    for tool, ver_flag in (("exiftool", "-ver"), ("tesseract", "--version")):
        rec = tooling.get(tool, {})
        import shutil
        rec["available"] = bool(shutil.which(rec.get("path", tool)))
        rec["detail"] = "Detected on PATH" if rec["available"] else "Binary not found on PATH"
    # Ollama node — probe the configured base URL.
    ollama = tooling.get("ollama", {})
    url = (ollama.get("url") or "http://localhost:11434").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            r = await client.get(f"{url}/api/tags")
        ollama["available"] = r.status_code == 200
        ollama["detail"] = f"HTTP {r.status_code} from {url}" if ollama["available"] else f"HTTP {r.status_code}"
    except Exception as exc:  # noqa: BLE001
        ollama["available"] = False
        ollama["detail"] = f"Unreachable: {exc}"
    admin_store.set_tooling(tooling)
    admin_store.append_audit(admin, "tooling.test", "", detail="Re-probed local tooling health")
    return {"tooling": admin_store.get_tooling()}


@router.put("/tooling")
async def update_tooling(body: ToolingPatch, admin: str = Depends(require_admin_token)):
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    admin_store.set_tooling(patch)
    admin_store.append_audit(admin, "tooling.update", "", detail="Updated local tooling config")
    return {"tooling": admin_store.get_tooling()}


# --------------------------------------------------------------------------- #
# Open Source & Support settings
# --------------------------------------------------------------------------- #
@router.get("/support")
async def support(admin: str = Depends(require_admin_token)):
    return {"support": admin_store.get_support()}


@router.patch("/support")
async def patch_support(body: SupportPatch, admin: str = Depends(require_admin_token)):
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    admin_store.set_support(patch)
    admin_store.append_audit(admin, "support.update", "", detail="Updated support/banner settings")
    return {"support": admin_store.get_support()}


# --------------------------------------------------------------------------- #
# Model Gateway & API Keys
# --------------------------------------------------------------------------- #
from app.services.key_probe import PROVIDER_KEY_MAP as _PROVIDER_KEY_MAP
from app.services.key_probe import live_probe, PROVIDER_KEY_FIELDS


@router.get("/gateway")
async def gateway(admin: str = Depends(require_admin_token)):
    gw = admin_store.get_gateway()
    masked = settings_store.get_keys_masked()
    providers: dict[str, dict[str, Any]] = {}
    for pid, key_name in _PROVIDER_KEY_MAP.items():
        st = masked.get(key_name, {"configured": False, "key_preview": None})
        providers[pid] = {
            "configured": st.get("configured", False),
            "preview": st.get("key_preview"),
        }
    gw["providers"] = providers
    return {"gateway": gw}


@router.put("/gateway")
async def update_gateway(body: GatewayPatch, admin: str = Depends(require_admin_token)):
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    admin_store.set_gateway(patch)
    admin_store.append_audit(admin, "gateway.update", "", detail="Updated model gateway settings")
    # Broadcast a global MODEL_CHANGED event so live surfaces (terminal banner,
    # workspace headers) rebind to the new active model without a page refresh.
    try:
        info = get_active_litellm_model()
        model_string = info.get("model", "unknown")
        provider = model_string.split("/", 1)[0] if "/" in model_string else model_string
        bus.publish("model.changed", {"provider": provider, "model": model_string})
    except Exception:  # noqa: BLE001 — broadcast must never break the save
        pass
    return await gateway(admin)


@router.get("/gateway/models")
async def gateway_models(provider: str = "", admin: str = Depends(require_admin_token)):
    """Live (or curated) model catalog for one provider — feeds the unified
    Active Provider & Model selector in the Admin Console."""
    provider = (provider or "").lower().strip()
    if provider not in MODEL_PROVIDERS:
        raise HTTPException(status_code=422, detail=f"provider must be one of {MODEL_PROVIDERS}")
    key_field = PROVIDER_MODEL_KEY.get(provider)
    api_key = settings_store.get_key(key_field) if key_field else ""
    gw = admin_store.get_gateway()
    base_url = gw.get("ollama_url", "") if provider == "ollama" else gw.get("huggingface_url", "")
    result = await fetch_models(provider, api_key=api_key, base_url=base_url)
    return {"provider": provider, **result}


@router.post("/gateway/test")
async def test_gateway_provider(body: dict[str, str], admin: str = Depends(require_admin_token)):
    provider = (body or {}).get("provider", "")
    if provider not in _PROVIDER_KEY_MAP:
        raise HTTPException(status_code=422, detail="Unknown provider")
    fields = PROVIDER_KEY_FIELDS.get(provider, (_PROVIDER_KEY_MAP[provider],))
    stored = {name: settings_store.get_key(name) for name in fields}
    primary = stored.get(fields[0])
    if not primary:
        return {"provider": provider, "configured": False, "detail": "No admin key configured"}
    extra = {name: value for name, value in stored.items() if name != fields[0] and value}
    result = await live_probe(provider, primary, extra)
    return {"provider": provider, "configured": True, **result}


# --------------------------------------------------------------------------- #
# Admin "test-key" alias for the gateway screen
# --------------------------------------------------------------------------- #
@router.post("/test-key")
async def admin_test_key(body: dict[str, str], admin: str = Depends(require_admin_token)):
    provider = (body or {}).get("provider", "")
    return await test_gateway_provider({"provider": provider}, admin=admin)
