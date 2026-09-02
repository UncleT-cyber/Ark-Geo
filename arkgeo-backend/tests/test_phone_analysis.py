"""Tests for the AI-assisted phone analysis (/telecom/analyze) surface."""
import asyncio
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.services import phone_analysis
from app.services.phone_analysis import (
    ANALYST_SYSTEM_PROMPT,
    build_fact_sheet,
    heuristic_assessment,
    run_phone_analysis,
)
from main import app

client = TestClient(app)


# --------------------------------------------------------------------------- #
# Service — fact sheet + heuristic
# --------------------------------------------------------------------------- #
class TestFactSheet:
    def test_free_intel_derived_when_no_context(self):
        facts = build_fact_sheet("+2348030000000", {})
        assert facts["parse_ok"] is True
        assert facts["valid"] is True
        assert facts["iso2"] == "NG"
        assert facts["phone_e164"].startswith("+234")
        assert isinstance(facts["timezone"], list)

    def test_context_overrides_carrier_and_adds_tier_fields(self):
        facts = build_fact_sheet("+2348030000000", {
            "carrier": "Custom Carrier",
            "active": True,
            "ported": False,
            "requires_key": ["line-state"],
            "tier": 2,
        })
        assert facts["carrier"] == "Custom Carrier"
        assert facts["active"] is True
        assert facts["ported"] is False
        assert facts["requires_key"] == ["line-state"]
        assert facts["tier"] == 2

    def test_unparseable_phone(self):
        facts = build_fact_sheet("+999999", {})
        assert facts["parse_ok"] is False


class TestHeuristic:
    def test_valid_number_schema(self):
        facts = build_fact_sheet("+2348030000000", {})
        out = heuristic_assessment(facts)
        assert out["title"]
        assert out["summary"]
        assert out["confidence"] in ("high", "medium", "low")
        assert out["risk_profile"]
        assert out["geospatial_analysis"]
        assert out["audit_next_steps"]
        assert isinstance(out["findings"], list) and out["findings"]
        assert any(f["code"] == "carrier" for f in out["findings"])
        assert isinstance(out["risks"], list)
        assert isinstance(out["next_actions"], list) and out["next_actions"]
        assert isinstance(out["caveats"], list) and out["caveats"]
        for f in out["findings"]:
            assert f["severity"] in ("info", "observation", "risk", "critical")

    def test_unparseable_number(self):
        facts = build_fact_sheet("+999999", {})
        out = heuristic_assessment(facts)
        assert out["confidence"] == "low"
        assert any(f["code"] == "parse" for f in out["findings"])


# --------------------------------------------------------------------------- #
# Service — model path selection
# --------------------------------------------------------------------------- #
class TestRunAnalysis:
    def test_heuristic_when_no_model_reachable(self, monkeypatch):
        monkeypatch.setattr(phone_analysis, "llm_client", MagicMock(
            is_configured=MagicMock(return_value=False),
        ))
        monkeypatch.setattr(phone_analysis, "gateway", MagicMock(
            available=AsyncMock(return_value=False),
        ))

        async def go():
            return await run_phone_analysis("+2348030000000", {})

        out = asyncio.run(go())
        assert out["ai_used"] is False
        assert out["engine"] == "heuristic"
        assert out["model"] == "deterministic-fallback"
        assert out["title"]
        assert out["findings"]

    def test_openai_path_used_when_configured(self, monkeypatch):
        llm = MagicMock()
        llm.is_configured.return_value = True
        llm.model = "gpt-4o"
        llm.chat_json.return_value = {
            "title": "AI title",
            "summary": "AI summary",
            "findings": [
                {"code": "x", "title": "X", "detail": "dx", "severity": "risk"},
            ],
            "confidence": "medium",
            "risks": ["r1"],
            "next_actions": ["n1"],
            "caveats": ["c1"],
        }
        monkeypatch.setattr(phone_analysis, "llm_client", llm)
        monkeypatch.setattr(phone_analysis, "gateway", MagicMock(
            available=AsyncMock(return_value=True),
            chat=AsyncMock(return_value="{}"),
        ))

        async def go():
            return await run_phone_analysis("+2348030000000", {})

        out = asyncio.run(go())
        llm.chat_json.assert_called_once_with(
            ANALYST_SYSTEM_PROMPT, ANY,
        )
        assert out["ai_used"] is True
        assert out["engine"] == "openai-compatible"
        assert out["model"] == "gpt-4o"
        assert out["title"] == "AI title"
        assert out["findings"][0]["severity"] == "risk"

    def test_ollama_path_when_openai_missing(self, monkeypatch):
        monkeypatch.setattr(phone_analysis, "llm_client", MagicMock(
            is_configured=MagicMock(return_value=False),
        ))
        gateway = MagicMock()
        gateway.available = AsyncMock(return_value=True)
        gateway.default_model = "qwen2.5-coder:3b"
        gateway.chat = AsyncMock(return_value='{"title":"O","summary":"S","confidence":"high","findings":[],"risks":[],"next_actions":[],"caveats":[]}')
        monkeypatch.setattr(phone_analysis, "gateway", gateway)

        async def go():
            return await run_phone_analysis("+2348030000000", {})

        out = asyncio.run(go())
        assert out["ai_used"] is True
        assert out["engine"] == "ollama"
        assert out["model"] == "qwen2.5-coder:3b"

    def test_bad_model_json_degrades_to_heuristic(self, monkeypatch):
        monkeypatch.setattr(phone_analysis, "llm_client", MagicMock(
            is_configured=MagicMock(return_value=False),
        ))
        monkeypatch.setattr(phone_analysis, "gateway", MagicMock(
            available=AsyncMock(return_value=True),
            chat=AsyncMock(return_value="not json at all"),
        ))

        async def go():
            return await run_phone_analysis("+2348030000000", {})

        out = asyncio.run(go())
        assert out["ai_used"] is False
        assert out["engine"] == "heuristic"


# --------------------------------------------------------------------------- #
# Endpoint contract
# --------------------------------------------------------------------------- #
class TestAnalyzeEndpoint:
    def test_analyze_valid_number(self):
        import app.api.v1.endpoints.telecom as telecom_mod

        async def fake_run(phone, context):
            return {
                "ai_used": False, "engine": "heuristic", "model": "deterministic-fallback",
                "title": "t", "summary": "s",
                "risk_profile": "rp", "geospatial_analysis": "ga", "audit_next_steps": "an",
                "findings": [],
                "confidence": "medium", "risks": [], "next_actions": [], "caveats": [],
            }

        with patch.object(telecom_mod, "run_phone_analysis", AsyncMock(side_effect=fake_run)):
            resp = client.post("/api/v1/telecom/analyze", json={
                "phone": "+2348030000000",
                "context": {"carrier": "MTN"},
            })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["analyzed"] is True
        assert body["engine"] == "heuristic"
        assert body["phone_e164"] == "+2348030000000"
        assert body["confidence"] == "medium"
        assert body["risk_profile"] == "rp"
        assert body["geospatial_analysis"] == "ga"
        assert body["audit_next_steps"] == "an"
        assert set(body.keys()) >= {
            "analyzed", "ai_used", "engine", "model", "phone_e164", "title",
            "summary", "risk_profile", "geospatial_analysis", "audit_next_steps",
            "findings", "confidence", "risks", "next_actions", "caveats", "detail",
        }

    def test_analyze_rejects_bad_e164(self):
        resp = client.post("/api/v1/telecom/analyze", json={"phone": "abc"})
        assert resp.status_code == 422

    def test_analyze_rejects_short_number(self):
        resp = client.post("/api/v1/telecom/analyze", json={"phone": "+12345"})
        assert resp.status_code == 422
