"""Telecom intelligence analysis — AI-assisted assessment of phone facts.

The analyst consumes the real fact sheet (keyless reference facts from
libphonenumber metadata + public numbering plans, merged with any provider-tier
results the client already collected) and produces a structured assessment.

Model path is *best-effort* and ordered:

  1. OpenAI-compatible ``LLMClient.chat_json`` (sync; wrapped in
     ``asyncio.to_thread``).
  2. local ``ModelGateway`` (Ollama) via the agent unit.
  3. deterministic heuristic built entirely from the real fact sheet.

Every path returns the same schema. Model output is *input*, never authority:
the normalizer coerces any shape into the schema and fills gaps with the
heuristic — mirroring the structural invariant that the AI orchestrates the
deterministic pipeline, never a hard dependency of it.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.agent.model_gateway import gateway
from app.brain.clue_extractors.base import llm_client
from app.services.phone_registry import derive_free_e164, derive_phonenumbers_intel

logger = logging.getLogger(__name__)

ANALYST_SYSTEM_PROMPT = """You are the ARK Tactical Intelligence Orchestrator.

The operator already sees the raw telecom payload on screen — carrier, MCC/MNC,
formats, country, timezone, and any live state are visible. Do NOT repeat raw
data points back at them, and do NOT dump the JSON dictionary as bullet points.
Act as an expert forensics analyst and add analyst value on top of that data.

Read the supplied telecom fact sheet and produce THREE concise intelligence
sections:

1. RISK PROFILE — Analyze carrier fraud vectors, billing-country anomalies and
   SIM-swap risk. Call out anything inconsistent (ported numbers, prepaid/VoIP
   flags, missing live state, fraud/risk scores) and grade the threat honestly.

2. GEOSPATIAL ANALYSIS — Explain what the target timezone and country prefix
   mean for real-time tracking accuracy limits. State the spatial precision you
   can actually trust (country-level vs NDC/routing-gateway vs cell-sector) and
   what degrades or improves it.

3. AUDIT NEXT-STEPS — Give the single next EXACT tactical tool recommendation to
   execute next, e.g. 'Target identified on mobile roaming carrier network;
   deploy Method 3 Canary Webhook to isolate local gateway routing IP.' Reference
   the real available surface (HLR key, certified tier-2 airlock, OpenCelliD cell
   lookup, canary link generator, case fold) and pick ONE decisive next move.

Respond with valid JSON ONLY, exactly these keys:
- title: short case-line title (string)
- risk_profile: the RISK PROFILE section, 2-4 sentences (string)
- geospatial_analysis: the GEOSPATIAL ANALYSIS section, 2-4 sentences (string)
- audit_next_steps: the AUDIT NEXT-STEPS section, 1-3 imperative sentences (string)
- confidence: one of "high" | "medium" | "low"
- caveats: array of strings (data provenance, precision, missing tiers)

Hard rules:
- NEVER fabricate facts, PII, identifiers, coordinates or live state not present in the fact sheet.
- A number is not a person. Do not speculate about the subscriber's identity.
- Flag honestly when provider tiers are missing ("requires key") and downgrade confidence accordingly.
- No markdown fences, no commentary — valid JSON only."""


def build_fact_sheet(phone: str, context: dict[str, Any]) -> dict[str, Any]:
    """Merge keyless reference intel with any client-supplied context.

    The client sends the merged facts it already collected (reference +
    OSINT + audit); the free reference intel is re-derived server-side so the
    endpoint is self-sufficient even with an empty context.
    """
    free = derive_free_e164(phone)
    intel = derive_phonenumbers_intel(phone) if free.get("ok") else {}
    base: dict[str, Any] = {
        "phone_e164": intel.get("e164") or phone,
        "parse_ok": bool(free.get("ok")),
        "valid": bool(intel.get("valid")),
        "possible": bool(intel.get("possible")),
        "iso2": intel.get("iso2") or free.get("iso2"),
        "country_code": free.get("country_code"),
        "line_type": intel.get("number_type") or free.get("line_type"),
        "number_type": intel.get("number_type"),
        "carrier": intel.get("carrier") or free.get("carrier"),
        "mcc": free.get("mcc"),
        "mnc": free.get("mnc"),
        "national_format": intel.get("national_format"),
        "international_format": intel.get("international_format"),
        "ndc": intel.get("ndc"),
        "subscriber_number": intel.get("subscriber_number"),
        "geo_city": intel.get("geo_city"),
        "timezone": intel.get("timezone") or [],
    }
    for key in ("iso2", "carrier", "mcc", "mnc", "line_type", "number_type", "geo_city"):
        if context.get(key) and context[key] != base.get(key):
            base[key] = context[key]
    for key in (
        "active", "ported", "roaming_country", "live_state", "line_state",
        "caller_name", "sim_swap_risk", "fraud_score", "requires_key",
        "tier", "thread", "imsi_revealed", "cgi_revealed",
    ):
        if key in context and context[key] is not None:
            base[key] = context[key]
    if isinstance(context.get("timezone"), list) and context["timezone"]:
        base["timezone"] = context["timezone"]
    presence = context.get("presence")
    if isinstance(presence, dict) and presence:
        base["presence"] = {str(k): bool(v) for k, v in presence.items()}
    base["footprint_probed"] = bool(context.get("footprint_probed"))
    return base


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, str):
        return [x.strip() for x in value.splitlines() if x.strip()]
    return []


def heuristic_assessment(facts: dict[str, Any]) -> dict[str, Any]:
    """Deterministic assessment built entirely from the real fact sheet."""
    phone = facts.get("phone_e164") or ""
    iso = facts.get("iso2") or "??"
    carrier = facts.get("carrier")
    valid = bool(facts.get("valid"))
    number_type = facts.get("number_type")
    line_type = facts.get("line_type") or number_type
    geo = facts.get("geo_city")
    tz = facts.get("timezone") or []

    caveats = [
        "Reference facts derive from Google libphonenumber metadata and public numbering plans — no live network state.",
        "Live ON/OFF, porting, SIM-swap and fraud tiers require an HLR/OSINT provider key (BYOK or admin system key).",
        "Spatial context is country/city precision only unless a cell lookup resolves an exact tower.",
    ]
    findings: list[dict[str, Any]] = []
    risks: list[str] = []

    if not facts.get("parse_ok"):
        findings.append({
            "code": "parse", "title": "Unparseable E.164",
            "detail": f"{phone} could not be parsed as a valid international number.",
            "severity": "risk",
        })
        risks.append("Number is not a valid E.164 international number.")
        return {
            "title": f"Assessment — unparseable ({phone})",
            "summary": "The supplied number failed E.164 parsing; no reference intelligence can be produced.",
            "risk_profile": "Unparseable number — treat as untrusted input and fail closed.",
            "geospatial_analysis": "No country prefix or timezone can be resolved, so no spatial precision exists.",
            "audit_next_steps": "Re-enter the number in full international format (+CC NDC SN) and re-run identification.",
            "findings": findings,
            "confidence": "low",
            "risks": risks,
            "next_actions": ["Re-enter the number in full international format (+CC NDC SN)."],
            "caveats": caveats,
        }

    findings.append({
        "code": "validity", "title": "Reference validity",
        "detail": f"{'VALID' if valid else 'NOT VALID'}"
                  f"{' · possible (region matches)' if facts.get('possible') else ' · not possible for any region'}",
        "severity": "info",
    })
    if carrier:
        findings.append({
            "code": "carrier", "title": "Carrier identity",
            "detail": f"{carrier}{f' · MCC {facts.get("mcc")} / MNC {facts.get("mnc")}' if facts.get('mcc') else ''}",
            "severity": "observation",
        })
    if number_type:
        findings.append({
            "code": "type", "title": "Number type",
            "detail": number_type, "severity": "info",
        })
    if geo or tz:
        findings.append({
            "code": "geo", "title": "Geographic context",
            "detail": " · ".join(x for x in [geo, iso, ", ".join(tz)] if x),
            "severity": "info",
        })
    for key in ("active", "ported", "roaming_country", "live_state", "line_state"):
        if facts.get(key) is not None:
            findings.append({
                "code": key, "title": key.replace("_", " ").title(),
                "detail": str(facts.get(key)), "severity": "observation",
            })
    if not facts.get("active") and not facts.get("live_state") and not facts.get("line_state"):
        findings.append({
            "code": "live-state", "title": "Live line state",
            "detail": "NOT AVAILABLE — no HLR provider key configured.",
            "severity": "observation",
        })
        risks.append("Live ON/OFF / porting / SIM-swap state is unknown without an HLR key.")
    presence = facts.get("presence") or {}
    if presence and any(presence.values()):
        present = [str(k).title() for k, v in presence.items() if v]
        findings.append({
            "code": "presence", "title": "Platform presence (probed)",
            "detail": f"{', '.join(present)} — keyless availability probe against public resolvers.",
            "severity": "observation",
        })
        if len(present) <= 1:
            risks.append("Sparse platform presence — weak account-linking signal.")
        else:
            risks.append("Multi-platform presence — the number is actively linked to messaging accounts.")
    elif facts.get("footprint_probed"):
        findings.append({
            "code": "presence", "title": "Platform presence (probed)",
            "detail": "No registered platform detected by the availability probe.",
            "severity": "observation",
        })
    if not valid:
        risks.append("Number is not valid — verification should fail closed.")
    if facts.get("sim_swap_risk") is not None and float(facts["sim_swap_risk"]) > 0.7:
        risks.append("Elevated SIM-swap risk — verify identity out-of-band.")
    if facts.get("fraud_score") is not None and float(facts["fraud_score"]) > 60:
        risks.append("Elevated fraud score from the licensed risk feed.")

    next_actions: list[str] = []
    if not facts.get("active") and not facts.get("live_state"):
        next_actions.append("Configure an HLR key (BYOK or admin system key) to surface live line state.")
    next_actions.append("Run the signaling audit to exercise the tiered reveal workflow.")
    next_actions.append("Resolve the serving cell via OpenCelliD to narrow spatial precision.")
    if not facts.get("active"):
        next_actions.append("Unlock tier 2 via the certified airlock for the full field reveal.")
    next_actions.append("Fold the observations into the active case.")

    confidence = "high" if valid and carrier else ("medium" if valid else "low")
    if valid:
        summary = (
            f"{phone} resolves to {carrier or 'an unknown carrier'} ({iso}) "
            f"as a {line_type or 'telephony'} number."
        )
    else:
        summary = f"{phone} failed validation and could not be characterized."

    route = facts.get("routing_location") or geo
    risk_profile = (
        f"{carrier or 'The carrier'} ({iso}) carries the number as a "
        f"{line_type or 'telephony'} line. "
        + (f"Fraud vectors: elevated SIM-swap risk reported." if float(facts.get("sim_swap_risk") or 0) > 0.7 else
           "Fraud vectors: no licensed risk feed configured — SIM-swap and billing-anomaly tiers are unknown (requires key).")
    )
    geospatial_analysis = (
        f"The +{facts.get('country_code', '?')} prefix anchors the number to {iso}"
        + (f" ({', '.join(tz)})" if tz else "")
        + (f". Spatial precision is {route or 'country-level'}" if route else ", country-level")
        + " — insufficient for real-time tracking without a cell-sector resolution."
    )
    audit_next_steps = (
        f"Target identified on {carrier or 'a'} network ({iso}); "
        + ("unlock tier 2 via the certified airlock to reveal IMSI/LAC and the cell sector, " if not facts.get("active") and not facts.get("live_state") else "")
        + "then resolve the serving cell via OpenCelliD to lock the tracking footprint."
    )

    return {
        "title": f"Assessment — {carrier or phone} ({iso})",
        "summary": summary,
        "risk_profile": risk_profile,
        "geospatial_analysis": geospatial_analysis,
        "audit_next_steps": audit_next_steps,
        "findings": findings,
        "confidence": confidence,
        "risks": risks,
        "next_actions": next_actions,
        "caveats": caveats,
    }


_SEVERITIES = {"info", "observation", "risk", "critical"}


def _normalize_ai(data: dict[str, Any], engine: str, model: str, facts: dict[str, Any]) -> dict[str, Any]:
    """Coerce arbitrary model JSON into the assessment schema, filling gaps
    with the heuristic. Model output is input, never authority."""
    base = heuristic_assessment(facts)
    findings: list[dict[str, Any]] = []
    for f in data.get("findings") or []:
        if not isinstance(f, dict):
            continue
        sev = str(f.get("severity", "info")).lower()
        if sev not in _SEVERITIES:
            sev = "info"
        findings.append({
            "code": str(f.get("code", "finding")),
            "title": str(f.get("title", "Finding")),
            "detail": str(f.get("detail", "")),
            "severity": sev,
        })
    confidence = str(data.get("confidence", base["confidence"])).lower()
    if confidence not in ("high", "medium", "low"):
        confidence = base["confidence"]
    return {
        "title": str(data.get("title") or base["title"]).strip() or base["title"],
        "summary": str(data.get("summary") or base["summary"]).strip() or base["summary"],
        "risk_profile": str(data.get("risk_profile") or base["risk_profile"]).strip() or base["risk_profile"],
        "geospatial_analysis": str(data.get("geospatial_analysis") or base["geospatial_analysis"]).strip() or base["geospatial_analysis"],
        "audit_next_steps": str(data.get("audit_next_steps") or base["audit_next_steps"]).strip() or base["audit_next_steps"],
        "findings": findings or base["findings"],
        "confidence": confidence,
        "risks": _as_str_list(data.get("risks")) or base["risks"],
        "next_actions": _as_str_list(data.get("next_actions")) or base["next_actions"],
        "caveats": _as_str_list(data.get("caveats")) or base["caveats"],
        "ai_used": True,
        "engine": engine,
        "model": model,
    }


async def run_phone_analysis(phone: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Produce a phone assessment. Returns the shared schema plus
    ``ai_used`` / ``engine`` / ``model``."""
    facts = build_fact_sheet(phone, context or {})
    user_prompt = f"Fact sheet (JSON):\n{json.dumps(facts, indent=2)}"

    if llm_client.is_configured():
        out = await asyncio.to_thread(llm_client.chat_json, ANALYST_SYSTEM_PROMPT, user_prompt)
        if isinstance(out, dict):
            return _normalize_ai(out, "openai-compatible", llm_client.model, facts)

    try:
        if await gateway.available():
            content = await gateway.chat(
                [
                    {"role": "system", "content": ANALYST_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                json_mode=True,
                temperature=0.2,
            )
            if content:
                data = json.loads(content)
                if isinstance(data, dict):
                    return _normalize_ai(data, "ollama", gateway.default_model, facts)
    except Exception as exc:  # noqa: BLE001 — model failures degrade to heuristic
        logger.warning("Model gateway analyst unavailable: %s", exc)

    return {
        "ai_used": False,
        "engine": "heuristic",
        "model": "deterministic-fallback",
        **heuristic_assessment(facts),
    }
