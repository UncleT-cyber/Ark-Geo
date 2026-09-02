"""Network Intelligence — passive discovery endpoints.

All of these are passive: they query public registries and directories and
never probe a target with active packets.

  * ``POST /network/rdap``        — WHOIS / registration via RDAP (rdap.org)
  * ``POST /network/bgp-lookup``  — ASN / BGP route + prefix details (bgpview.io)
  * ``POST /network/dns-lookup``  — DNS over HTTPS (Cloudflare DoH)
  * ``POST /network/crt-search``  — Certificate Transparency logs (crt.sh)
  * ``POST /network/webprobe``    — single HTTP GET; security-header audit

Active scanning (port/service enumeration) and authorized security-testing
engines are NOT part of this module — they are planned behind the tool-policy
risk gate plus explicit authorization capture.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/network")

_DEFAULT_TIMEOUT = 10.0

_IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}$"
)
_URL_RE = re.compile(r"^https?://[^\s/$.?#].[^\s]*$", re.IGNORECASE)


class RdapRequest(BaseModel):
    target: str = Field(..., description="Domain or IPv4/IPv6 address")


class RdapResponse(BaseModel):
    target: str
    kind: str
    registered_org: Optional[str] = None
    handle: Optional[str] = None
    name: Optional[str] = None
    start_address: Optional[str] = None
    end_address: Optional[str] = None
    cidr: Optional[str] = None
    status: list[str] = []
    events: list[dict] = []
    detail: str = ""


@router.post("/rdap", response_model=RdapResponse)
async def rdap_lookup(body: RdapRequest):
    target = (body.target or "").strip().lower()
    if not target:
        raise HTTPException(status_code=422, detail="target is required")
    kind = "ip" if _IP_RE.match(target) else "domain"
    if kind == "domain" and not _DOMAIN_RE.match(target):
        raise HTTPException(status_code=422, detail="target must be a domain or IP address")

    try:
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, follow_redirects=True) as client:
            r = await client.get(f"https://rdap.org/{kind}/{target}")
        if r.status_code != 200:
            return RdapResponse(target=target, kind=kind,
                                detail=f"RDAP returned HTTP {r.status_code}")
        data = r.json()
    except Exception as exc:  # noqa: BLE001
        return RdapResponse(target=target, kind=kind,
                            detail=f"RDAP lookup failed: {type(exc).__name__}")

    def _vcard_org(entities: list[Any]) -> Optional[str]:
        for ent in entities or []:
            vcards = ent.get("vcardArray")
            if not isinstance(vcards, list) or len(vcards) < 2:
                continue
            props = vcards[1]
            if isinstance(props, list) and props and not isinstance(props[0], list):
                props = [props]
            for vc in props or []:
                if isinstance(vc, list) and len(vc) >= 4 and vc[0] == "fn":
                    return str(vc[3])
        return None

    resp = RdapResponse(
        target=target,
        kind=kind,
        handle=data.get("handle"),
        name=data.get("name") or data.get("ldhName"),
        registered_org=_vcard_org(data.get("entities")),
        status=[str(s) for s in (data.get("status") or [])],
        events=[{"eventAction": e.get("eventAction"), "eventDate": e.get("eventDate")}
                for e in (data.get("events") or [])],
        detail="RDAP · rdap.org",
    )
    if kind == "domain":
        resp.name = data.get("ldhName") or resp.name
    else:
        start = data.get("startAddress")
        end = data.get("endAddress")
        if start and end:
            resp.start_address = start
            resp.end_address = end
            resp.cidr = data.get("cidr0_cidrs") or data.get("cidr") or None
    return resp


class BgpLookupRequest(BaseModel):
    ip: str = Field(..., description="IPv4/IPv6 address to resolve to ASN")


class BgpLookupResponse(BaseModel):
    ip: str
    asn: Optional[int] = None
    asn_name: Optional[str] = None
    asn_description: Optional[str] = None
    country: Optional[str] = None
    ptr_record: Optional[str] = None
    prefixes: list[dict] = []
    detail: str = ""


@router.post("/bgp-lookup", response_model=BgpLookupResponse)
async def bgp_lookup(body: BgpLookupRequest):
    ip = (body.ip or "").strip()
    if not ip:
        raise HTTPException(status_code=422, detail="ip is required")
    try:
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, follow_redirects=True) as client:
            r = await client.get(f"https://api.bgpview.io/ip/{ip}")
        if r.status_code != 200:
            return BgpLookupResponse(ip=ip, detail=f"bgpview.io returned HTTP {r.status_code}")
        data = r.json().get("data") or {}
    except Exception as exc:  # noqa: BLE001
        return BgpLookupResponse(ip=ip, detail=f"BGP lookup failed: {type(exc).__name__}")

    asns = data.get("asns") or []
    asn_info = asns[0] if asns else {}
    return BgpLookupResponse(
        ip=ip,
        asn=asn_info.get("asn"),
        asn_name=asn_info.get("name"),
        asn_description=asn_info.get("description"),
        country=asn_info.get("country_code") or data.get("rir_allocation", {}).get("country_code"),
        ptr_record=data.get("ptr_record"),
        prefixes=[{"prefix": p.get("prefix"), "asn": p.get("asn"), "name": p.get("name"),
                   "description": p.get("description"), "country": p.get("country_code")}
                  for p in (data.get("prefixes") or [])][:25],
        detail=f"bgpview.io · {len(asns)} ASN(s)",
    )


class DnsLookupRequest(BaseModel):
    qname: str = Field(..., description="Name to resolve")
    type: str = Field("A", description="Record type (A, AAAA, MX, TXT, CNAME, NS)")


class DnsLookupResponse(BaseModel):
    qname: str
    type: str
    answers: list[dict] = []
    detail: str = ""


@router.post("/dns-lookup", response_model=DnsLookupResponse)
async def dns_lookup(body: DnsLookupRequest):
    qname = (body.qname or "").strip().lower()
    rtype = (body.type or "A").upper()
    if not qname or not _DOMAIN_RE.match(qname):
        raise HTTPException(status_code=422, detail="qname must be a valid domain")
    if rtype not in {"A", "AAAA", "MX", "TXT", "CNAME", "NS", "SOA"}:
        raise HTTPException(status_code=422, detail="Unsupported record type")
    try:
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, follow_redirects=True) as client:
            r = await client.get(
                "https://cloudflare-dns.com/dns-query",
                params={"name": qname, "type": rtype},
                headers={"Accept": "application/dns-json"},
            )
        if r.status_code != 200:
            return DnsLookupResponse(qname=qname, type=rtype,
                                     detail=f"DoH returned HTTP {r.status_code}")
        data = r.json()
    except Exception as exc:  # noqa: BLE001
        return DnsLookupResponse(qname=qname, type=rtype,
                                 detail=f"DNS lookup failed: {type(exc).__name__}")

    answers = [{"name": a.get("name"), "type": a.get("type"),
                "ttl": a.get("TTL"), "data": a.get("data")}
               for a in (data.get("Answer") or [])]
    return DnsLookupResponse(qname=qname, type=rtype, answers=answers,
                             detail=f"DoH Cloudflare · {len(answers)} answer(s)")


class CrtSearchRequest(BaseModel):
    domain: str = Field(..., description="Domain to search Certificate Transparency logs for")
    wildcard: bool = Field(True, description="Also match subdomains (%.")


class CrtSearchResponse(BaseModel):
    domain: str
    certificates: list[dict] = []
    detail: str = ""


@router.post("/crt-search", response_model=CrtSearchResponse)
async def crt_search(body: CrtSearchRequest):
    domain = (body.domain or "").strip().lower()
    if not domain or not _DOMAIN_RE.match(domain):
        raise HTTPException(status_code=422, detail="domain must be a valid domain")
    query = f"%25.{domain}" if body.wildcard else domain
    try:
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, follow_redirects=True) as client:
            r = await client.get("https://crt.sh/", params={"q": query, "output": "json"})
        if r.status_code != 200:
            return CrtSearchResponse(domain=domain,
                                     detail=f"crt.sh returned HTTP {r.status_code}")
        data = r.json()
    except Exception as exc:  # noqa: BLE001
        return CrtSearchResponse(domain=domain,
                                 detail=f"crt.sh lookup failed: {type(exc).__name__}")

    certs = [
        {"name_value": c.get("name_value"), "common_name": c.get("common_name"),
         "issuer_name": c.get("issuer_name"), "not_before": c.get("not_before"),
         "not_after": c.get("not_after")}
        for c in data[:100] if isinstance(c, dict)
    ]
    return CrtSearchResponse(domain=domain, certificates=certs,
                             detail=f"crt.sh · {len(certs)} certificate(s)")


class WebProbeRequest(BaseModel):
    url: str = Field(..., description="Absolute http(s) URL to inspect")


class HeaderAudit(BaseModel):
    present: bool
    ok: Optional[bool] = None
    detail: str


class WebProbeResponse(BaseModel):
    url: str
    final_url: str
    status_code: Optional[int] = None
    security_headers: dict[str, HeaderAudit] = {}
    tech_hints: dict[str, str] = {}
    grade: str = ""
    detail: str = ""


def _audit_headers(headers: httpx.Headers) -> tuple[dict[str, HeaderAudit], str]:
    audit: dict[str, HeaderAudit] = {}

    hsts = headers.get("strict-transport-security")
    audit["strict-transport-security"] = HeaderAudit(
        present=bool(hsts),
        ok=bool(hsts and "max-age=" in hsts.lower()),
        detail=hsts or "Missing — allows plaintext downgrade.",
    )
    csp = headers.get("content-security-policy")
    audit["content-security-policy"] = HeaderAudit(
        present=bool(csp), ok=None,
        detail=(csp or "")[:160] or "Missing — consider a CSP to bound XSS blast radius.",
    )
    xfo = headers.get("x-frame-options")
    audit["x-frame-options"] = HeaderAudit(
        present=bool(xfo), ok=bool(xfo and xfo.upper() in {"DENY", "SAMEORIGIN"}),
        detail=xfo or "Missing — page may be frameable (clickjacking).",
    )
    xcto = headers.get("x-content-type-options")
    audit["x-content-type-options"] = HeaderAudit(
        present=bool(xcto), ok=bool(xcto and "nosniff" in xcto.lower()),
        detail=xcto or "Missing — MIME sniffing not blocked.",
    )
    rp = headers.get("referrer-policy")
    audit["referrer-policy"] = HeaderAudit(
        present=bool(rp), ok=None,
        detail=rp or "Missing — referrer defaults to full-URL on downgrades.",
    )
    pp = headers.get("permissions-policy")
    audit["permissions-policy"] = HeaderAudit(
        present=bool(pp), ok=None, detail=(pp or "")[:120] or "Missing.",
    )
    cors = headers.get("access-control-allow-origin")
    audit["access-control-allow-origin"] = HeaderAudit(
        present=bool(cors), ok=bool(cors and cors != "*"),
        detail=cors or "No CORS header (default same-origin).",
    )

    score = sum(1 for a in audit.values() if a.ok)
    present = sum(1 for a in audit.values() if a.present)
    grade = "A" if present >= 6 else "B" if present >= 4 else "C" if present >= 2 else "D"
    return audit, grade


_TECH_HEADERS = ("server", "x-powered-by", "x-aspnet-version", "x-generator",
                 "via", "x-backend-server", "x-framework", "x-render",
                 "cf-ray", "x-served-by")


@router.post("/webprobe", response_model=WebProbeResponse)
async def webprobe(body: WebProbeRequest):
    url = (body.url or "").strip()
    if not _URL_RE.match(url):
        raise HTTPException(status_code=422, detail="url must be an absolute http(s) URL")
    try:
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, follow_redirects=True,
                                     max_redirects=4) as client:
            async with client.stream(
                "GET", url,
                headers={"User-Agent": "TheArk-WebProbe/0.1 (passive HTTP header audit)"},
            ) as r:
                status = r.status_code
                final = str(r.url)
                headers = dict(r.headers)
        tech = {h: headers.get(h, "") for h in _TECH_HEADERS if headers.get(h)}
        audit, grade = _audit_headers(httpx.Headers(headers))
        return WebProbeResponse(
            url=url, final_url=final, status_code=status,
            security_headers=audit, tech_hints=tech, grade=grade,
            detail=f"HTTP {status} · single GET, headers only",
        )
    except httpx.HTTPStatusError as exc:
        return WebProbeResponse(url=url, final_url=url, status_code=exc.response.status_code,
                                detail=f"HTTP {exc.response.status_code}")
    except Exception as exc:  # noqa: BLE001
        return WebProbeResponse(url=url, final_url=url,
                                detail=f"Probe failed: {type(exc).__name__}")
