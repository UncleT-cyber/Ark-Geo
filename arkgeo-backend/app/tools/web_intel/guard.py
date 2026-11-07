"""Web-intelligence security boundary — the untrusted-content egress guard.

One place where every outbound web request (static fetch *and* managed-browser
navigation) is validated before it leaves the process. This is the ARK-side
equivalent of CAI's ``fetch_url`` SSRF guard, promoted to a first-class,
reusable module so the browser runtime cannot bypass it.

Controls:

* **Scheme allow-list** — only ``http``/``https``.
* **Address policy** — private, loopback, link-local, multicast, reserved and
  unspecified addresses are refused. Cloud-metadata endpoints (AWS/GCP/Azure/
  Alibaba IMDS) are refused **always**, even when internal access is authorised.
* **DNS-rebinding resistance** — hostnames are resolved exactly once and the
  resulting IP is returned so the caller dials the *pinned* address rather than
  re-resolving the FQDN.
* **Redirect re-validation** — callers re-run :func:`check_url` on every hop.
* **Explicit internal override** — internal targets are only reachable when the
  operator sets ``ARK_WEB_ALLOW_INTERNAL=true`` *and* the engagement scope
  authorises the target (enforced downstream by ``engagement_scope``).

This module performs no I/O beyond DNS resolution and reads no files.
"""
from __future__ import annotations

import ipaddress
import os
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

# Cloud-metadata hostnames that must never be reachable, regardless of policy.
_METADATA_HOSTS: frozenset[str] = frozenset({
    "metadata.google.internal",
    "metadata",
    "metadata.azure.com",
    "instance-data",
})

# Numeric metadata endpoints (IMDS).
_METADATA_IPS: frozenset[str] = frozenset({
    "169.254.169.254",   # AWS / GCP / Azure / DigitalOcean / Alibaba
    "100.100.100.200",   # Alibaba Cloud secondary
    "fd00:ec2::254",     # AWS IPv6 IMDS
})

_ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https"})

_ALLOW_INTERNAL_ENV = "ARK_WEB_ALLOW_INTERNAL"


class SSRFBlocked(Exception):
    """Raised when an outbound request is refused by the egress guard."""


def allow_internal() -> bool:
    """Whether the operator has authorised internal targets for this process."""
    raw = os.getenv(_ALLOW_INTERNAL_ENV)
    return bool(raw) and raw.strip().lower() in {"1", "true", "yes", "on"}


def is_unsafe_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True when *ip* is not a globally routable public address."""
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _resolve(host: str) -> list[str]:
    """Resolve *host* to its A/AAAA records (single resolution point)."""
    infos = socket.getaddrinfo(host, None)
    addrs: list[str] = []
    for info in infos:
        addr = str(info[4][0])
        if addr not in addrs:
            addrs.append(addr)
    return addrs


@dataclass(frozen=True)
class EgressDecision:
    """Outcome of an egress check: the IP to dial plus the original host."""
    url: str
    resolved_ip: str
    host_header: str
    host: str


def check_url(url: str, *, allow_internal_targets: bool | None = None) -> EgressDecision:
    """Validate *url* and return the pinned dial target.

    Args:
        url: absolute http(s) URL.
        allow_internal_targets: overrides :func:`allow_internal` when supplied.

    Returns:
        An :class:`EgressDecision` whose ``resolved_ip`` the caller must dial
        (do not re-resolve the FQDN — that is the rebinding defence).

    Raises:
        SSRFBlocked: on scheme, host, or address policy violation.
    """
    if allow_internal_targets is None:
        allow_internal_targets = allow_internal()

    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise SSRFBlocked(f"scheme '{scheme}' is not allowed (only http/https)")

    host = (parts.hostname or "").lower()
    if not host:
        raise SSRFBlocked("URL has no host component")

    # Cloud metadata is ALWAYS refused.
    if host in _METADATA_HOSTS or host in _METADATA_IPS:
        raise SSRFBlocked(f"host '{host}' is a cloud-metadata endpoint")

    # Literal IP.
    try:
        ip_obj = ipaddress.ip_address(host)
    except ValueError:
        ip_obj = None
    if ip_obj is not None:
        if not allow_internal_targets and is_unsafe_ip(ip_obj):
            raise SSRFBlocked(f"host '{host}' is a private/reserved address")
        return EgressDecision(url=url, resolved_ip=host,
                              host_header=parts.netloc, host=host)

    # FQDN → resolve once, validate every record.
    try:
        addrs = _resolve(host)
    except socket.gaierror as exc:
        raise SSRFBlocked(f"cannot resolve host '{host}': {exc}") from exc

    safe: list[str] = []
    for addr in addrs:
        if addr in _METADATA_IPS:
            raise SSRFBlocked(f"host '{host}' resolves to cloud-metadata '{addr}'")
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if not allow_internal_targets and is_unsafe_ip(ip):
            raise SSRFBlocked(
                f"host '{host}' resolves to private/loopback/link-local '{addr}'"
            )
        safe.append(addr)

    if not safe:
        raise SSRFBlocked(f"no usable addresses for host '{host}'")
    return EgressDecision(url=url, resolved_ip=safe[0],
                          host_header=parts.netloc, host=host)


def pinned_url(decision: EgressDecision) -> str:
    """Return the URL with its FQDN replaced by the validated IP literal.

    The original FQDN is carried in the ``Host`` header by the caller so virtual
    hosting and TLS SNI still work.
    """
    parts = urlsplit(decision.url)
    if (parts.hostname or "").lower() == decision.resolved_ip.lower():
        return decision.url
    ip_netloc = f"[{decision.resolved_ip}]" if ":" in decision.resolved_ip else decision.resolved_ip
    netloc = f"{ip_netloc}:{parts.port}" if parts.port else ip_netloc
    return urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, parts.fragment))


def is_public_url(url: str) -> bool:
    """Convenience predicate: True when *url* passes the guard with no override."""
    try:
        check_url(url, allow_internal_targets=False)
        return True
    except SSRFBlocked:
        return False
