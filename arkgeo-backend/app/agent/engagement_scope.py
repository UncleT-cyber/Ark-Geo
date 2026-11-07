"""Engagement scope — operator-declared target authorization for execution.

The execution policy's *target* layer: every tool call that names a network
target (host / URL / IP / CIDR / domain) must fall inside the operator's
declared engagement before it may run. The operator's declaration is the
**source of truth** for what ARK executes against.

Resolution order (first match wins):

  1. An explicit ``scope`` passed by an internal caller (server-resolved,
     never client-supplied).
  2. The **operator-declared engagement** — created through the engagement
     API (:mod:`app.agent.engagement_store`) and set here as the active scope.
     Inside it ARK runs without asking; outside it, calls are denied.
  3. A legacy ``ARKGEO_ENGAGEMENT_SCOPE`` fixture file, when an operator
     points the backend at one.
  4. Fail-closed: no scope at all denies target-bearing calls.

Design rules:

  * **Fail-closed for target-bearing calls, fail-open for everything else.**
    Non-target calls (evidence hashing, OCR, case ops, diagnostics) always
    run; a target-bearing call with no active engagement is denied.
  * **No bypass**: the orchestrator consults this *before* HITL approval and
    before dispatch — an operator approval cannot widen the scope, and a
    denial cannot be auto-approved.
  * **Deterministic**, mirroring :mod:`app.agent.policy_guard`.

Legacy fixture: ``arkgeo_data/engagement_scope.json`` (relative to the
backend working directory), overridable with ``ARKGEO_ENGAGEMENT_SCOPE``.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

DEFAULT_PATH = os.path.join("arkgeo_data", "engagement_scope.json")
ENV_PATH = "ARKGEO_ENGAGEMENT_SCOPE"

# The operator-declared engagement, set by the engagement API when an operator
# authorizes targets. It is process-wide: ARK is a single-operator environment,
# and the orchestrator consults it at the execution boundary. This is the
# authoritative scope when present.
_operator_engagement: Optional[dict] = None


def set_operator_engagement(scope: Optional[dict]) -> None:
    """Install (or clear) the operator-declared engagement as the active scope."""
    global _operator_engagement
    _operator_engagement = scope if isinstance(scope, dict) else None


def get_operator_engagement() -> Optional[dict]:
    """The operator-declared engagement currently in force, if any."""
    return _operator_engagement


def _load(path: Optional[str] = None) -> tuple[str, Optional[dict]]:
    """Return ``("ok"|"missing"|"invalid", scope)``.

    The operator-declared engagement is authoritative: when one is in force it
    is the scope, full stop. Only in its absence is a legacy
    ``ARKGEO_ENGAGEMENT_SCOPE`` fixture consulted.
    """
    if _operator_engagement is not None:
        return "ok", _operator_engagement
    p = path or os.environ.get(ENV_PATH)
    if not p or not os.path.isfile(p):
        return "missing", None
    try:
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return "invalid", None
        return "ok", data
    except Exception:
        return "invalid", None


_TARGET_KEYS = (
    "host", "target", "url", "address", "ip", "domain", "hostname",
    "base_url", "endpoint", "server", "network_range", "cidr", "range",
)

# Tools that open TCP connections but whose port set cannot be derived from
# their arguments when the port argument is omitted (nmap's default top-1000,
# gobuster's default wordlist, ...). These are denied unless an explicit,
# approved port set is supplied — the scope must never be widened by a
# tool default.
_PORT_REQUIRED = {
    "net.nmap_scan", "pentest.nmap_scan", "nmap_scan", "port_scan",
    "net.dir_enum", "fingerprint_service", "tls_inspect", "net.ssl_check",
    "pentest.ssh_identity",
}
# DNS/whois-style queries resolve names; they open no TCP port and therefore
# carry no port obligation — only the address itself must be in scope.

# Scheme defaults used when a URL carries no explicit port.
_SCHEME_DEFAULT_PORTS = {"http": 80, "https": 443, "ws": 80, "wss": 443,
                         "ftp": 21}


@dataclass(frozen=True)
class ScopeDecision:
    """Outcome of a scope check for one proposed tool call."""
    allowed: bool
    reason: str
    rule_id: str = "scope"
    engagement_id: Optional[str] = None
    target: Optional[str] = None


_ALLOW = ScopeDecision(True, "no engagement scope active")


# --------------------------------------------------------------------------- #
# Time window
# --------------------------------------------------------------------------- #
def _parse_ts(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        ts = value.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _time_state(scope: dict, now: Optional[datetime] = None) -> tuple[bool, str]:
    """Check the fixture's start/expiry window. Returns (active, reason)."""
    now = now or datetime.now(timezone.utc)
    start = _parse_ts(scope.get("start"))
    expiry = _parse_ts(scope.get("expiry"))
    if start and now < start:
        return False, f"engagement scope not yet active (starts {scope.get('start')})"
    if expiry and now > expiry:
        return False, f"engagement scope expired at {scope.get('expiry')}"
    if not start and not expiry:
        return False, "engagement scope has no start/expiry window — refusing target access"
    return True, ""


# --------------------------------------------------------------------------- #
# Target / port extraction
# --------------------------------------------------------------------------- #
def _iter_targets(args: dict) -> list[str]:
    out: list[str] = []
    for key in _TARGET_KEYS:
        val = args.get(key)
        if isinstance(val, str) and val.strip():
            out.append(val.strip())
        elif isinstance(val, (list, tuple)):
            out.extend(str(v).strip() for v in val if str(v).strip())
    return out


def _split_url(value: str) -> tuple[Optional[str], Optional[int]]:
    """Return ``(explicit_port_or_None, scheme_default_or_None)`` for a URL."""
    m = re.match(r"^(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*)://(?P<rest>.+)$", value)
    if not m:
        return None, None
    rest = m.group("rest").split("/", 1)[0].split("?", 1)[0]
    if rest.startswith("["):  # ipv6 literal
        hostpart, _, portpart = rest[1:].partition("]")
        portpart = portpart.lstrip(":")
    else:
        hostpart, _, portpart = rest.partition(":")
    if portpart.isdigit():
        return int(portpart), None
    default = _SCHEME_DEFAULT_PORTS.get(m.group("scheme").lower())
    return None, default


def _host_of(value: str) -> str:
    """Reduce a target string to a bare host / CIDR / domain."""
    v = value.strip()
    if "://" in v:
        # URL: keep the authority only (drop scheme, path, query).
        v = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", v)
        v = v.split("/", 1)[0].split("?", 1)[0]
    if v.startswith("["):  # [ipv6]:port
        v = v[1:].partition("]")[0]
    elif "/" in v:
        pass  # CIDR — keep as written
    elif v.count(":") == 1 and v.rsplit(":", 1)[1].isdigit():
        v = v.rsplit(":", 1)[0]  # host:port
    return v.strip().rstrip(".").lower()


def _extract_ports(args: dict) -> tuple[Optional[list[int]], Optional[int]]:
    """Return ``(explicit_ports, url_default_port)`` for a call."""
    ports: list[int] = []
    saw_explicit = False
    for key in ("port", "ports", "port_list"):
        val = args.get(key)
        if val is None or val == "" or val == 0:
            continue
        if isinstance(val, (list, tuple)):
            for p in val:
                try:
                    ports.append(int(p))
                    saw_explicit = True
                except (TypeError, ValueError):
                    pass
        else:
            for p in re.findall(r"\d+", str(val)):
                ports.append(int(p))
                saw_explicit = True
    # URL-derived port
    url_default = None
    for key in ("url", "target", "endpoint", "base_url"):
        val = args.get(key)
        if isinstance(val, str) and "://" in val:
            explicit, default = _split_url(val)
            if explicit is not None:
                ports.append(explicit)
                saw_explicit = True
            elif default is not None and url_default is None:
                url_default = default
    return (sorted(set(ports)) if saw_explicit else None), url_default


def _address_approved(host: str, scope: dict) -> bool:
    approved = scope.get("approved_addresses") or []
    host_l = host.lower()
    # Exact string match (hostname or literal IP).
    if any(host_l == str(a).lower() for a in approved):
        return True
    # CIDR containment for IP literals.
    try:
        ip = ipaddress.ip_address(host_l)
    except ValueError:
        return False
    for a in approved:
        try:
            net = ipaddress.ip_network(str(a), strict=False)
        except ValueError:
            continue
        if ip in net:
            return True
    return False


def _ports_approved(ports: list[int], scope: dict) -> tuple[bool, str]:
    if scope.get("all_ports"):
        return True, ""
    approved = {int(p) for p in (scope.get("approved_ports") or [])}
    bad = [p for p in ports if p not in approved]
    if bad:
        return False, (f"port(s) {bad} not in approved ports {sorted(approved)}")
    return True, ""


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def check(tool_id: str, args: Optional[dict] = None,
          path: Optional[str] = None, *,
          scope: Optional[dict] = None,
          require_scope: bool = False) -> ScopeDecision:
    """Decide whether ``tool_id`` may run with ``args`` under the active scope.

    ``allowed=True`` when the call names no target (evidence hashing, OCR,
    case ops, diagnostics) or when the named target falls inside the active
    engagement. ``allowed=False`` when a target-bearing call has no active
    engagement, when the engagement is broken/expired, or when the target or
    port falls outside it.

    ``scope`` lets an internal caller pass a server-resolved engagement;
    ``require_scope`` forbids the process-global fallback (multi-user callers
    must supply their own resolved engagement).
    """
    if require_scope:
        state = "ok" if isinstance(scope, dict) else "missing"
    elif scope is not None:
        state = "ok" if isinstance(scope, dict) else "invalid"
    else:
        state, scope = _load(path)
    if state == "missing":
        # Fail-closed: no engagement in force — deny target-bearing calls.
        # Non-target calls (evidence hashing, diagnostics, case ops) still run.
        targets = _iter_targets(args or {})
        if targets:
            return ScopeDecision(
                False,
                "no engagement is active — declare one to authorize targets",
                rule_id="scope.missing",
            )
        return _ALLOW
    if state == "invalid":
        return ScopeDecision(
            False,
            "the active engagement is unreadable — target access denied "
            "(fail-closed)",
            rule_id="scope.invalid",
        )
    assert scope is not None
    eng_id = scope.get("engagement_id")

    if require_scope and (not eng_id
                          or not isinstance(scope.get("approved_addresses"), list)
                          or not (isinstance(scope.get("approved_ports"), list)
                                  or scope.get("all_ports"))):
        return ScopeDecision(False, "engagement is missing required authorization fields",
                             rule_id="scope.invalid")

    targets = _iter_targets(args or {})
    if not targets:
        # Not a target-bearing call (evidence hashing, OCR, case ops, ...).
        return ScopeDecision(True, "no target named", engagement_id=eng_id)

    active, why = _time_state(scope)
    if not active:
        return ScopeDecision(False, why, rule_id="scope.window", engagement_id=eng_id)

    explicit_ports, url_default = _extract_ports(args or {})
    all_ports = bool(scope.get("all_ports"))

    for raw in targets:
        host = _host_of(raw)
        if not _address_approved(host, scope):
            return ScopeDecision(
                False,
                f"target '{raw}' is outside the declared engagement "
                f"(engagement {eng_id}; declared: "
                f"{', '.join(str(a) for a in scope.get('approved_addresses', []))})",
                rule_id="scope.address", engagement_id=eng_id, target=raw,
            )
        if all_ports:
            continue
        if explicit_ports:
            ok, why = _ports_approved(explicit_ports, scope)
            if not ok:
                return ScopeDecision(
                    False, f"target '{raw}': {why}",
                    rule_id="scope.port", engagement_id=eng_id, target=raw,
                )
        elif url_default is not None:
            ok, why = _ports_approved([url_default], scope)
            if not ok:
                return ScopeDecision(
                    False, f"target '{raw}': implicit port {url_default} not "
                           f"declared — pass an explicit declared port",
                    rule_id="scope.port", engagement_id=eng_id, target=raw,
                )
        elif tool_id in _PORT_REQUIRED:
            approved = sorted(int(p) for p in (scope.get("approved_ports") or []))
            return ScopeDecision(
                False,
                f"tool '{tool_id}' requires an explicit port; declared ports "
                f"are {approved} (no default/blanket port scan is permitted)",
                rule_id="scope.port_required", engagement_id=eng_id, target=raw,
            )

    return ScopeDecision(
        True, f"target(s) within engagement {eng_id}",
        engagement_id=eng_id, target=targets[0],
    )


def summary_lines(path: Optional[str] = None) -> list[str]:
    """Human-readable scope block for the runtime capability context.

    Returns ``[]`` when no engagement is in force (nothing to disclose).
    """
    state, scope = _load(path)
    if state != "ok" or not scope:
        return []
    active, why = _time_state(scope)
    status = "ACTIVE" if active else f"INACTIVE ({why})"
    addresses = ", ".join(str(a) for a in scope.get("approved_addresses", []))
    if scope.get("all_ports"):
        ports = "all ports"
    else:
        ports = ", ".join(str(p) for p in scope.get("approved_ports", [])) or "none"
    label = scope.get("label") or scope.get("engagement_id")
    lines = [
        f"Engagement {label}: {status}",
        f"Declared targets: {addresses or 'none'} (ports: {ports})",
        "These targets are authorized by the operator — execute against them "
        "directly, without asking. Any other target is outside the engagement "
        "and is refused before dispatch.",
    ]
    if scope.get("expiry"):
        lines.append(f"Engagement expires: {scope.get('expiry')}")
    return lines


def credentials(path: Optional[str] = None) -> dict:
    """The engagement's credential map (server-side secrets — never log)."""
    state, scope = _load(path)
    if state != "ok" or not scope:
        return {}
    creds = scope.get("credentials")
    return creds if isinstance(creds, dict) else {}


__all__ = ["ScopeDecision", "check", "summary_lines", "credentials",
           "set_operator_engagement", "get_operator_engagement",
           "DEFAULT_PATH", "ENV_PATH"]
