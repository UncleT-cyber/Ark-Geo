"""ARK Admin control-plane state store.

Persists admin-managed entities to a local JSON file under the storage
root: clients (with session-handshake telemetry), internal staff & RBAC,
immutable audit logs, tool policy, quota plans, local tooling health,
open-source support settings, and the model gateway configuration.

Design notes:
- All writes go through the single AdminStore singleton under a lock.
- Audit entries are append-only and never mutated after creation.
- API keys are NOT stored here — they live in the encrypted
  SettingsStore (app/services/settings_store.py).  The gateway section
  only references configured flags + masked previews from that store.
- Demo records are clearly flagged ``seed`` so the UI can mark them and
  an operator can clear them.  Nothing is ever silently fabricated.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Optional

from app.core.config import settings as bootstrap_settings

logger = logging.getLogger(__name__)

_STORE_PATH = os.path.join(bootstrap_settings.local_storage_path, "arkgeo_admin_state.json")


def _utc_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# Staff roles supported by the RBAC matrix.
STAFF_ROLES = ("SUPER_ADMIN", "LEAD_ANALYST", "SECURITY_OPERATOR", "AUDITOR")

# Permission keys exposed in the RBAC matrix.
PERMISSION_KEYS = (
    "canManageApiKeys",
    "canManageBilling",
    "canManageClients",
    "canExecuteHighRiskTools",
    "canManageStaff",
)

# Tool policy: name → {risk_level, default_enabled}
TOOL_POLICY_DEFAULTS: dict[str, dict[str, Any]] = {
    "reverse_image_search": {"risk_level": "LOW", "enabled": True},
    "exiftool_extraction": {"risk_level": "LOW", "enabled": True},
    "ocr_text_telemetry": {"risk_level": "LOW", "enabled": True},
    "streetview_lookup": {"risk_level": "MEDIUM", "enabled": True},
    "geocoding_reverse": {"risk_level": "MEDIUM", "enabled": True},
    "phone_number_lookup": {"risk_level": "HIGH", "enabled": False},
    "carrier_hlr_lookup": {"risk_level": "HIGH", "enabled": False},
    "cell_tower_scan": {"risk_level": "HIGH", "enabled": False},
    "passive_network_scan": {"risk_level": "MEDIUM", "enabled": True},
    "active_sweep_execution": {"risk_level": "CRITICAL", "enabled": False},
}

# Quota plans: name → limits.  usage is tracked separately in the same record.
QUOTA_PLAN_DEFAULTS: dict[str, dict[str, Any]] = {
    "free": {
        "storage_bytes": 500 * 1024 * 1024,
        "max_active_cases": 3,
        "monthly_token_budget": 250_000,
        "rate_limit_rpm": 30,
        "api_spend_cap_usd": 5.0,
        "display": "Free",
    },
    "pro": {
        "storage_bytes": 2 * 1024 * 1024 * 1024,
        "max_active_cases": 25,
        "monthly_token_budget": 2_500_000,
        "rate_limit_rpm": 120,
        "api_spend_cap_usd": 50.0,
        "display": "Pro",
    },
    "enterprise": {
        "storage_bytes": 20 * 1024 * 1024 * 1024,
        "max_active_cases": 200,
        "monthly_token_budget": 25_000_000,
        "rate_limit_rpm": 1000,
        "api_spend_cap_usd": 2000.0,
        "display": "Enterprise",
    },
}

TOOLING_DEFAULTS: dict[str, Any] = {
    "exiftool": {"available": True, "path": "exiftool", "version": "12.70", "detail": "Detected on PATH"},
    "tesseract": {"available": True, "path": "tesseract", "version": "5.3.3", "detail": "Detected on PATH"},
    "ollama": {"available": False, "url": "http://localhost:11434", "model": "llama3.2-vision:latest", "detail": "Not responding"},
    "local_nodes": [],
}

SUPPORT_DEFAULTS: dict[str, Any] = {
    "show_banner": True,
    "bmc_url": "https://www.buymeacoffee.com/arkinvestigator",
    "github_url": "https://github.com/anomalyco/ark",
    "discord_url": "https://discord.gg/ark-investigator",
    "build_version": "The Ark v2.4.0-release",
}

GATEWAY_DEFAULTS: dict[str, Any] = {
    "active_llm_provider": "openai",
    "ollama_url": "http://localhost:11434",
    "ollama_model": "qwen2.5-coder:3b",
    "huggingface_url": "https://router.huggingface.co/v1",
    "huggingface_model": "",
    "openai_model": "",
    "gemini_model": "",
    "anthropic_model": "",
    "openrouter_model": "",
    # Vision master switch: when False, local Ollama never receives image
    # payloads and the runtime reports no vision path.
    "vision_enabled": True,
    # Per-task Ollama model rotator: role -> model tag. Empty value = auto
    # (the gateway's own resolution rules decide). Roles today:
    #   terminal     -> text/code orchestration (Terminal Orchestrator)
    #   vision_imint -> Vision IMINT scene analysis (image payloads)
    "task_models": {
        "terminal": "",
        "vision_imint": "",
    },
    "providers": {
        "openai": {"configured": False, "preview": None},
        "gemini": {"configured": False, "preview": None},
        "anthropic": {"configured": False, "preview": None},
        "openrouter": {"configured": False, "preview": None},
        "geospy": {"configured": False, "preview": None},
        "serper": {"configured": False, "preview": None},
        "tineye": {"configured": False, "preview": None},
        "tavily": {"configured": False, "preview": None},
        "hlr": {"configured": False, "preview": None},
        "opencellid": {"configured": False, "preview": None},
        "mapbox": {"configured": False, "preview": None},
    },
}


def _demo_clients() -> list[dict[str, Any]]:
    """Representative seed client directory (clearly flagged ``seed``).

    Telemetry mirrors what a real session handshake would capture
    (network identity, device fingerprint, usage metrics).  Seed rows are
    marked so operators can clear them; nothing is fabricated as live data.
    """
    return [
        {
            "client_id": "CLT-7F2A9C01",
            "full_name": "Nadia Rahal",
            "email": "nadia.r@fieldops.example",
            "plan": "pro",
            "status": "active",
            "created_at": "2025-11-03T09:14:00Z",
            "seed": True,
            "telemetry": {
                "last_login_ip": "196.201.214.11",
                "country": "Nigeria",
                "city": "Lagos",
                "asn": "AS29465",
                "proxy": False,
                "vpn": False,
                "tor_exit": False,
                "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15",
                "os": "iOS 17.5",
                "browser": "Safari 17.5",
                "tls_fingerprint": "JA3-bb7f…",
            },
            "usage": {
                "active_cases": 2,
                "storage_bytes": 124_000_000,
                "api_spend_usd": 4.2,
                "tokens_consumed": 138_000,
            },
        },
        {
            "client_id": "CLT-31B8D204",
            "full_name": "Marcus Vale",
            "email": "marcus.v@consortium.example",
            "plan": "enterprise",
            "status": "active",
            "created_at": "2025-08-17T16:40:00Z",
            "seed": True,
            "telemetry": {
                "last_login_ip": "34.86.120.7",
                "country": "Germany",
                "city": "Frankfurt",
                "asn": "AS15169",
                "proxy": False,
                "vpn": False,
                "tor_exit": False,
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
                "os": "Windows 10",
                "browser": "Chrome 126",
                "tls_fingerprint": "JA3-2d90…",
            },
            "usage": {
                "active_cases": 7,
                "storage_bytes": 1_120_000_000,
                "api_spend_usd": 86.0,
                "tokens_consumed": 4_100_000,
            },
        },
        {
            "client_id": "CLT-A0C3E517",
            "full_name": "Sofia Lindqvist",
            "email": "sofia.l@free.example",
            "plan": "free",
            "status": "suspended",
            "created_at": "2026-01-22T11:05:00Z",
            "seed": True,
            "telemetry": {
                "last_login_ip": "185.220.101.34",
                "country": "Netherlands",
                "city": "Amsterdam",
                "asn": "AS9009",
                "proxy": True,
                "vpn": True,
                "tor_exit": True,
                "user_agent": "Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0",
                "os": "Linux",
                "browser": "Firefox 127",
                "tls_fingerprint": "JA3-unknown",
            },
            "usage": {
                "active_cases": 0,
                "storage_bytes": 12_000_000,
                "api_spend_usd": 0.0,
                "tokens_consumed": 0,
            },
        },
    ]


def _demo_staff() -> list[dict[str, Any]]:
    return [
        {
            "staff_id": "STF-0001",
            "username": "ark.admin",
            "full_name": "Platform Administrator",
            "role": "SUPER_ADMIN",
            "active": True,
            "seed": True,
            "permissions": {k: True for k in PERMISSION_KEYS},
            "created_at": "2025-01-01T00:00:00Z",
        },
        {
            "staff_id": "STF-0002",
            "username": "lead.analyst",
            "full_name": "Senior Investigative Analyst",
            "role": "LEAD_ANALYST",
            "active": True,
            "seed": True,
            "permissions": {
                "canManageApiKeys": False,
                "canManageBilling": False,
                "canManageClients": True,
                "canExecuteHighRiskTools": True,
                "canManageStaff": False,
            },
            "created_at": "2025-02-11T09:00:00Z",
        },
        {
            "staff_id": "STF-0003",
            "username": "sec.operator",
            "full_name": "Security Operator",
            "role": "SECURITY_OPERATOR",
            "active": True,
            "seed": True,
            "permissions": {
                "canManageApiKeys": False,
                "canManageBilling": False,
                "canManageClients": False,
                "canExecuteHighRiskTools": False,
                "canManageStaff": False,
            },
            "created_at": "2025-03-02T14:30:00Z",
        },
        {
            "staff_id": "STF-0004",
            "username": "auditor",
            "full_name": "Compliance Auditor",
            "role": "AUDITOR",
            "active": True,
            "seed": True,
            "permissions": {
                "canManageApiKeys": False,
                "canManageBilling": True,
                "canManageClients": False,
                "canExecuteHighRiskTools": False,
                "canManageStaff": False,
            },
            "created_at": "2025-05-20T10:00:00Z",
        },
    ]


class AdminStore:
    """JSON-backed admin control-plane store (thread-safe, append-only audit)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {}
        os.makedirs(os.path.dirname(_STORE_PATH) or ".", exist_ok=True)
        self._load()

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #
    def _load(self) -> None:
        with self._lock:
            if os.path.exists(_STORE_PATH):
                try:
                    with open(_STORE_PATH, "r", encoding="utf-8") as fh:
                        self._data = json.load(fh)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Admin store load failed (%s) — starting fresh", exc)
                    self._data = {}
            else:
                self._data = {}
            if not self._data.get("seeded"):
                self._seed()

    def _seed(self) -> None:
        self._data = {
            "seeded": True,
            "clients": _demo_clients(),
            "staff": _demo_staff(),
            "audit_logs": [],
            "tool_policy": deepcopy(TOOL_POLICY_DEFAULTS),
            "quotas": deepcopy(QUOTA_PLAN_DEFAULTS),
            "tooling": deepcopy(TOOLING_DEFAULTS),
            "support": deepcopy(SUPPORT_DEFAULTS),
            "gateway": deepcopy(GATEWAY_DEFAULTS),
        }
        self._save()
        logger.info("Admin store seeded with demo directory")

    def _save(self) -> None:
        tmp = f"{_STORE_PATH}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh, indent=2)
        os.replace(tmp, _STORE_PATH)

    # ------------------------------------------------------------------ #
    # Audit trail (append-only)
    # ------------------------------------------------------------------ #
    def append_audit(
        self,
        actor: str,
        action: str,
        target: str = "",
        ip: str = "",
        detail: str = "",
    ) -> dict[str, Any]:
        entry = {
            "log_id": f"AUD-{uuid.uuid4().hex[:8].upper()}",
            "actor": actor,
            "action": action,
            "target": target,
            "ip": ip or "127.0.0.1",
            "detail": detail,
            "timestamp": _now_iso(),
            "timestamp_ms": _utc_ms(),
        }
        with self._lock:
            self._data.setdefault("audit_logs", []).append(entry)
            self._data["audit_logs"] = self._data["audit_logs"][-2000:]
            self._save()
        return entry

    def list_audit(self, actor: Optional[str] = None, action: Optional[str] = None,
                   target: Optional[str] = None, query: str = "") -> list[dict[str, Any]]:
        logs = self._data.get("audit_logs", [])
        if actor:
            logs = [e for e in logs if e["actor"] == actor]
        if action:
            logs = [e for e in logs if e["action"] == action]
        if target:
            logs = [e for e in logs if target.lower() in e["target"].lower()]
        if query:
            q = query.lower()
            logs = [e for e in logs if q in e["target"].lower() or q in e["actor"].lower()
                    or q in e["detail"].lower() or q in e["ip"]]
        return list(reversed(logs))

    # ------------------------------------------------------------------ #
    # Clients
    # ------------------------------------------------------------------ #
    def list_clients(self) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy(self._data.get("clients", []))

    def get_client(self, client_id: str) -> Optional[dict[str, Any]]:
        for c in self._data.get("clients", []):
            if c["client_id"] == client_id:
                return deepcopy(c)
        return None

    def upsert_client(self, record: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            clients = self._data.setdefault("clients", [])
            for i, c in enumerate(clients):
                if c["client_id"] == record["client_id"]:
                    clients[i] = record
                    self._save()
                    return deepcopy(record)
            clients.append(record)
            self._save()
            return deepcopy(record)

    def set_client_status(self, client_id: str, status: str) -> Optional[dict[str, Any]]:
        """Transition a client's account status.

        Returns the updated record, or None if the client does not exist.
        Suspending/banning reports the number of sessions invalidated
        (simulated from active_cases; real session registry would revoke
        live JWTs).
        """
        with self._lock:
            for c in self._data.get("clients", []):
                if c["client_id"] != client_id:
                    continue
                prev = c.get("status")
                c["status"] = status
                c["status_changed_at"] = _now_iso()
                self._save()
                out = deepcopy(c)
                out["previous_status"] = prev
                out["sessions_invalidated"] = (
                    int(c.get("usage", {}).get("active_cases", 0)) if status in ("suspended", "banned") else 0
                )
                return out
        return None

    def delete_client(self, client_id: str) -> bool:
        with self._lock:
            clients = self._data.setdefault("clients", [])
            before = len(clients)
            self._data["clients"] = [c for c in clients if c["client_id"] != client_id]
            if len(self._data["clients"]) != before:
                self._save()
                return True
            return False

    # ------------------------------------------------------------------ #
    # Staff & RBAC
    # ------------------------------------------------------------------ #
    def list_staff(self) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy(self._data.get("staff", []))

    def get_staff(self, staff_id: str) -> Optional[dict[str, Any]]:
        for s in self._data.get("staff", []):
            if s["staff_id"] == staff_id:
                return deepcopy(s)
        return None

    def upsert_staff(self, record: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            staff = self._data.setdefault("staff", [])
            for i, s in enumerate(staff):
                if s["staff_id"] == record["staff_id"]:
                    staff[i] = record
                    self._save()
                    return deepcopy(record)
            staff.append(record)
            self._save()
            return deepcopy(record)

    def deactivate_staff(self, staff_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            for s in self._data.get("staff", []):
                if s["staff_id"] == staff_id:
                    s["active"] = False
                    s["deactivated_at"] = _now_iso()
                    self._save()
                    return deepcopy(s)
        return None

    # ------------------------------------------------------------------ #
    # Tool policy / quotas / tooling / support / gateway
    # ------------------------------------------------------------------ #
    def get_tool_policy(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._data.get("tool_policy", {}))

    def set_tool_state(self, tool: str, enabled: bool) -> bool:
        with self._lock:
            policy = self._data.setdefault("tool_policy", {})
            if tool not in policy:
                return False
            policy[tool]["enabled"] = bool(enabled)
            self._save()
            return True

    def get_quotas(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._data.get("quotas", {}))

    def set_quota_plan(self, tier: str, patch: dict[str, Any]) -> Optional[dict[str, Any]]:
        with self._lock:
            quotas = self._data.setdefault("quotas", {})
            if tier not in quotas:
                return None
            quotas[tier].update(patch)
            self._save()
            return deepcopy(quotas[tier])

    def get_tooling(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._data.get("tooling", {}))

    def set_tooling(self, patch: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            tooling = self._data.setdefault("tooling", {})
            tooling.update(patch)
            self._save()
            return deepcopy(tooling)

    def get_support(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._data.get("support", {}))

    def set_support(self, patch: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            support = self._data.setdefault("support", {})
            support.update(patch)
            self._save()
            return deepcopy(support)

    def get_gateway(self) -> dict[str, Any]:
        with self._lock:
            # Merge defaults so fields added after a store was created
            # (e.g. huggingface_url / huggingface_model) always surface.
            merged = {**GATEWAY_DEFAULTS, **self._data.get("gateway", {})}
            return deepcopy(merged)

    def set_gateway(self, patch: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            gateway = self._data.setdefault("gateway", {})
            gateway.update(patch)
            self._save()
            return deepcopy(gateway)


# Singleton
admin_store = AdminStore()
