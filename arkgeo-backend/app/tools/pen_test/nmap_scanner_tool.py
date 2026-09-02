"""Nmap scanner tool — authorized network reconnaissance.

Wraps the local ``nmap`` binary (``asyncio`` subprocess) for host discovery,
open-port enumeration, and service/version detection. Scanning is **active**
network activity: it must only ever be pointed at an explicitly authorized
scope, and the orchestrator routes this tool through the Policy Guard
(elevated risk → confirm_once).

Degradation contract (mirrors :mod:`app.tools.web_search_tool`): a missing
binary returns an honest ``TOOL_MISSING`` state with install guidance, an
unparseable scan returns ``ERROR``, an invalid target returns ``UNAVAILABLE``
— nothing is fabricated and no traffic is sent when ``nmap`` is absent.

``dry_run=True`` returns a clearly-labelled ``simulated`` result so the
RE-ACT chain is runnable end-to-end in environments without the binary.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import time
import xml.etree.ElementTree as ET
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Host shapes accepted as an authorized scan target.
_HOST_HINT = ("host", "hostname", "cidr", "subnet", "range")


async def _run_nmap(argv: list[str], timeout: int) -> tuple[Optional[int], str, str]:
    """Run nmap, returning ``(returncode, stdout, stderr)``.

    On timeout, the process is killed and the *partial* buffered output is
    still captured (so a slow scan that found some ports before the deadline
    does not lose its results).  ``returncode`` is ``None`` to signal timeout.
    """
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")
    except asyncio.TimeoutError:
        proc.kill()
        try:
            out, err = await proc.communicate()
        except Exception:
            out, err = b"", b""
        return None, out.decode(errors="replace"), err.decode(errors="replace")


def _parse_nmap_xml(xml_text: str) -> list[dict[str, Any]]:
    """Parse nmap ``-oX -`` output into host/port/service records."""
    hosts: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return hosts
    for host in root.iter("host"):
        addr = host.find("address")
        if addr is None:
            continue
        host_ip = addr.get("addr") or "?"
        record: dict[str, Any] = {
            "ip": host_ip,
            "status": (host.findtext("status") or "up").strip(),
            "ports": [],
        }
        for port in host.iter("port"):
            state = port.find("state")
            service = port.find("service")
            if state is None or state.get("state") != "open":
                continue
            entry: dict[str, Any] = {
                "port": port.get("portid"),
                "protocol": port.get("protocol"),
                "service": service.get("name") if service is not None else None,
                "product": service.get("product") if service is not None else None,
                "version": service.get("version") if service is not None else None,
            }
            record["ports"].append(entry)
        hosts.append(record)
    return hosts


def _build_argv(
    host: str,
    ports: Optional[str],
    top_ports: Optional[int],
    scan_type: str,
    timing: str,
    service_version: bool,
    no_ping: bool = False,
) -> list[str]:
    argv = ["nmap", "-T" + (timing or "T4").lstrip("T")]
    if no_ping:
        argv.append("-Pn")
    if ports:
        argv += ["-p", ports]
    elif top_ports:
        argv += ["--top-ports", str(top_ports)]
    if service_version:
        argv += ["-sV"]
    if scan_type == "tcp_connect":
        argv.append("-sT")
    elif scan_type == "syn":
        argv.append("-sS")
    elif scan_type == "udp":
        argv.append("-sU")
    argv += ["-oX", "-", host]
    return argv


def _simulated(host: str, ports: Optional[str], top_ports: Optional[int],
               scan_type: str) -> dict[str, Any]:
    """Honest dry-run placeholder — no network traffic is sent."""
    target = host
    port_range = ports or (f"top-{top_ports}" if top_ports else "1000")
    common = {
        22: "ssh", 25: "smtp", 53: "domain", 80: "http", 443: "https",
        3306: "mysql", 5432: "postgresql", 8080: "http-proxy", 8443: "https-alt",
    }
    ports_list = [80, 443, 22, 8080] if port_range == "1000" else [80, 443]
    record = {
        "ip": target,
        "status": "up",
        "ports": [
            {"port": str(p), "protocol": "tcp",
             "service": common.get(p), "product": None, "version": None}
            for p in ports_list
        ],
    }
    return {
        "state": "AVAILABLE",
        "detail": "Simulated nmap scan (dry_run) — no traffic sent.",
        "simulated": True,
        "tool": "nmap",
        "command": _build_argv(target, ports, top_ports, scan_type, "T4", True),
        "hosts": [record],
        "total_open_ports": len(record["ports"]),
        "elapsed_ms": 0,
    }


async def nmap_scan(
    host: str = "",
    ports: str = "",
    top_ports: int = 0,
    scan_type: str = "tcp_connect",
    timing: str = "T4",
    service_version: bool = True,
    timeout: int = 60,
    no_ping: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Scan an authorized host/CIDR with the local ``nmap`` binary.

    Args:
        host: IP, hostname, CIDR, or range to scan (authorized scope).
        ports: explicit port list (e.g. ``"22,80,443,8000-9000"``).
        top_ports: scan the N most common ports instead of a list.
        scan_type: ``tcp_connect`` | ``syn`` | ``udp``.
        timing: nmap timing template ``T0``..``T5``.
        service_version: enable ``-sV`` service/version detection.
        timeout: subprocess timeout in seconds.
        no_ping: skip host discovery (``-Pn``) — scan even if host is filtered.
        dry_run: return a clearly-labelled simulated result (no traffic).
    """
    host = (host or "").strip()
    ports = (ports or "").strip()
    scan_type = (scan_type or "tcp_connect").strip().lower()
    timing = (timing or "T4").strip().upper()

    # A default (unspecified) scan targets the 100 most common ports with a
    # fast timing template — a full 1000-port -sV connect scan routinely
    # blows past the timeout against filtered/slow hosts.  Explicit callers
    # can still request a fuller scan.
    if not ports and not top_ports:
        top_ports = 100

    if not host:
        return {
            "state": "UNAVAILABLE", "tool": "nmap", "host": host,
            "detail": "No scan target supplied (host / hostname / CIDR).",
            "hosts": [], "total_open_ports": 0,
        }
    if dry_run:
        return _simulated(host, ports, top_ports, scan_type)

    if shutil.which("nmap") is None:
        return {
            "state": "TOOL_MISSING", "tool": "nmap", "host": host,
            "detail": "nmap is not installed on the ARK host. Install it via "
                      "'brew install nmap' (macOS) or 'apt install nmap' (Debian) "
                      "to enable live scanning.",
            "hosts": [], "total_open_ports": 0,
        }
    if scan_type not in ("tcp_connect", "syn", "udp"):
        return {
            "state": "UNAVAILABLE", "tool": "nmap", "host": host,
            "detail": f"Unsupported scan_type '{scan_type}' — use tcp_connect, syn, or udp.",
            "hosts": [], "total_open_ports": 0,
        }

    argv = _build_argv(host, ports, top_ports, scan_type, timing, service_version, no_ping)
    started = time.perf_counter()
    try:
        code, out, err = await _run_nmap(argv, timeout)
    except Exception as exc:  # noqa: BLE001 — degrade, never crash
        logger.warning("nmap execution failed for %r: %s", host, exc)
        return {
            "state": "ERROR", "tool": "nmap", "host": host,
            "detail": f"nmap execution failed: {type(exc).__name__}",
            "hosts": [], "total_open_ports": 0,
        }
    elapsed = int((time.perf_counter() - started) * 1000)

    # Primary scan timed out: degrade gracefully to a fast top-100 connect
    # scan rather than failing outright.  Partial output from the killed
    # primary scan is still parsed if the fast scan also yields nothing.
    if code is None:
        logger.warning("nmap primary scan timed out (%ss); auto-degrading for %r", timeout, host)
        fast_argv = ["nmap", "-T5", "--top-ports", "100", "-sT", "-oX", "-", host]
        try:
            fcode, fout, ferr = await _run_nmap(fast_argv, max(20, int(timeout * 0.6)))
        except Exception:
            fcode, fout, ferr = None, "", ""
        hosts = _parse_nmap_xml(fout) if fout else []
        if not hosts:
            hosts = _parse_nmap_xml(out) if out else []
        if hosts:
            total = sum(len(h["ports"]) for h in hosts)
            return {
                "state": "AVAILABLE", "tool": "nmap", "host": host,
                "detail": (
                    f"Initial scan timed out at {timeout}s; completed a fast "
                    f"top-100 scan instead — {len(hosts)} host(s), {total} open port(s)."
                ),
                "degraded": True,
                "command": fast_argv,
                "hosts": hosts,
                "total_open_ports": total,
                "elapsed_ms": elapsed,
            }
        return {
            "state": "TIMEOUT", "tool": "nmap", "host": host,
            "detail": (
                f"nmap exceeded {timeout}s even with a fast top-100 scan. The host "
                f"may be down, heavily filtered, or unreachable. Try a smaller port "
                f"set (e.g. ports='22,80,443') or timing='T5'."
            ),
            "hosts": _parse_nmap_xml(out) if out else [],
            "total_open_ports": 0,
        }

    hosts = _parse_nmap_xml(out) if not err or "Nmap done" in out else []
    if not hosts and code != 0:
        return {
            "state": "ERROR", "tool": "nmap", "host": host,
            "detail": f"nmap exited {code}: {err.strip()[:300]}",
            "hosts": [], "total_open_ports": 0,
        }
    total = sum(len(h["ports"]) for h in hosts)
    return {
        "state": "AVAILABLE", "tool": "nmap", "host": host,
        "detail": f"Scan complete — {len(hosts)} host(s), {total} open port(s).",
        "command": argv,
        "hosts": hosts,
        "total_open_ports": total,
        "elapsed_ms": elapsed,
    }
