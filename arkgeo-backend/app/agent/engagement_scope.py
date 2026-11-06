"""Engagement scope — target authorization for tool execution (Milestone A.2).

The execution policy's *target* layer: every tool call that names a network
target (host / URL / IP / CIDR / domain) must match the active engagement
fixture before it may run. This is the mechanism that makes an out-of-scope
request **denied by ARK's execution policy** rather than merely discouraged.

Design rules:

  * **Fail-closed for target-bearing calls, fail-open for everything else.**
    With no fixture file present the module allows everything (normal
    application use is unrestricted). If a fixture *is* present but broken or
    expired, target-bearing calls are denied.
  * **No bypass**: the orchestrator consults this *before* HITL approval and
    before dispatch — an operator approval cannot widen the scope, and a
    denial cannot be auto-approved.
  * **Deterministic, no I/O beyond reading one small JSON file**, mirroring
    :mod:`app.agent.policy_guard`.

Fixture location: ``arkgeo_data/engagement_scope.json`` (relative to the
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

# Scope enforcement is opt-in: the fixture is only authoritative when the
# operator points the backend at it (ARKGEO_ENGAGEMENT_SCOPE, set for lab
# engagements). Without it, every target-bearing call is allowed — existing
# application behaviour and the wider test suite are unaffected.
def _load(path: Optional[str] = None) -> tuple[str, Optional[dict]]:
    """Return ``("ok"|\"missing\"|\"invalid\", scope)``.

    ``path`` or ``ARKGEO_ENGAGEMENT_SCOPE`` must be set explicitly; there is
    no silent fallback to a default fixture file.
    """
    p = path or os.environ.get(ENV_PATH)
    if not p or not os.path.isfile(p):
        return "missing", None
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
# Fixture loading
# --------------------------------------------------------------------------- #
def _load(path: Optional[str] = None) -> tuple[str, Optional[dict]]:
    """Return ``("ok"|"missing"|"invalid", scope)``."""
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
    approved = {int(p) for p in (scope.get("approved_ports") or [])}
    bad = [p for p in ports if p not in approved]
    if bad:
        return False, (f"port(s) {bad} not in approved ports {sorted(approved)}")
    return True, ""


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def check(tool_id: str, args: Optional[dict] = None,
          path: Optional[str] = None) -> ScopeDecision:
    """Decide whether ``tool_id`` may run with ``args`` under the active scope.

    Returns :class:`ScopeDecision`. ``allowed=True`` when no fixture exists
    but the call names no target (non-target calls such as evidence hashing,
    system diagnostics remain allowed). ``allowed=False`` when a fixture
    exists but is broken/expired, or when no fixture exists and the call
    names a network target (fail-closed).
    """
    state, scope = _load(path)
    if state == "missing":
        # Fail-closed: no scope fixture configured — deny target-bearing
        # calls. Non-target calls (evidence hashing, system diagnostics,
        # case ops) remain allowed so normal application operation is not
        # broken.
        targets = _iter_targets(args or {})
        if targets:
            return ScopeDecision(
                False,
                "no engagement scope configured — target access denied "
                "(fail-closed)",
                rule_id="scope.missing",
            )
        return _ALLOW
    if state == "invalid":
        return ScopeDecision(
            False,
            "engagement scope fixture is present but unreadable — target "
            "access denied (fail-closed)",
            rule_id="scope.invalid",
        )
    assert scope is not None
    eng_id = scope.get("engagement_id")

    targets = _iter_targets(args or {})
    if not targets:
        # Not a target-bearing call (evidence hashing, OCR, case ops, ...).
        return ScopeDecision(True, "no target named", engagement_id=eng_id)

    active, why = _time_state(scope)
    if not active:
        return ScopeDecision(False, why, rule_id="scope.window", engagement_id=eng_id)

    explicit_ports, url_default = _extract_ports(args or {})

    for raw in targets:
        host = _host_of(raw)
        if not _address_approved(host, scope):
            return ScopeDecision(
                False,
                f"target '{raw}' is outside the authorized engagement scope "
                f"(engagement {eng_id}; approved: "
                f"{', '.join(str(a) for a in scope.get('approved_addresses', []))})",
                rule_id="scope.address", engagement_id=eng_id, target=raw,
            )
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
                           f"approved — pass an explicit approved port",
                    rule_id="scope.port", engagement_id=eng_id, target=raw,
                )
        elif tool_id in _PORT_REQUIRED:
            approved = sorted(int(p) for p in (scope.get("approved_ports") or []))
            return ScopeDecision(
                False,
                f"tool '{tool_id}' requires an explicit port; approved ports "
                f"are {approved} (no default/blanket port scan is permitted)",
                rule_id="scope.port_required", engagement_id=eng_id, target=raw,
            )

    return ScopeDecision(
        True, f"target(s) within engagement {eng_id} scope",
        engagement_id=eng_id, target=targets[0],
    )


def summary_lines(path: Optional[str] = None) -> list[str]:
    """Human-readable scope block for the runtime capability context.

    Returns ``[]`` when no fixture is present (nothing to disclose).
    """
    state, scope = _load(path)
    if state != "ok" or not scope:
        return []
    active, why = _time_state(scope)
    status = "ACTIVE" if active else f"INACTIVE ({why})"
    lines = [
        f"Engagement scope: {scope.get('engagement_id')} — {status}",
        "Authorized targets: "
        + "; ".join(
            f"{t.get('id')} [{', '.join(map(str, t.get('addresses', [])))} "
            f"port(s) {', '.join(map(str, t.get('ports', [])))}]"
            for t in scope.get("targets", [])
        ),
        "Approved ports (any target): "
        + ", ".join(str(p) for p in scope.get("approved_ports", [])),
        "All other targets and ports are DENIED by ARK execution policy. "
        "For scan tools pass explicit approved ports — blanket/default port "
        "ranges are refused.",
    ]
    return lines


def credentials(path: Optional[str] = None) -> dict:
    """The fixture's credential map (server-side secrets — never log)."""
    state, scope = _load(path)
    if state != "ok" or not scope:
        return {}
    creds = scope.get("credentials")
    return creds if isinstance(creds, dict) else {}


__all__ = ["ScopeDecision", "check", "summary_lines", "credentials",
           "DEFAULT_PATH", "ENV_PATH"]
