"""OSINT tools — web search / web fetch / geocoding / reverse image tests.

Covers the Tavily + DuckDuckGo web_search cascade, web_fetch page parsing,
geocoding wrappers, reverse_image_search provider fan-out, registry metadata,
and the Tavily key probe.  All external HTTP is respx-mocked; provider
internals that would otherwise hit the network are monkeypatched so no test
touches the wire or the host's real key store.
"""
import pytest
from unittest.mock import AsyncMock

from app.agent.tool_registry import registry
from app.services.settings_store import settings_store

DDG_HTML = """
<html><body>
<div class="result results_links results_links_deep web-result">
  <h2 class="result__title">
    <a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpage">Example Title</a>
  </h2>
  <a class="result__snippet" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpage">Some snippet &amp; more</a>
</div>
</body></html>
"""


def _no_keys(monkeypatch):
    monkeypatch.setattr(settings_store, "get_key", lambda name: None)


def _key_for(monkeypatch, name: str, value: str):
    monkeypatch.setattr(
        settings_store, "get_key",
        lambda n: value if n == name else None,
    )


# --------------------------------------------------------------------------- #
# web_search
# --------------------------------------------------------------------------- #
class TestWebSearch:
    @pytest.mark.asyncio
    async def test_empty_query_unavailable(self, monkeypatch):
        _no_keys(monkeypatch)
        from app.tools.web_search_tool import web_search
        res = await web_search("   ")
        assert res["state"] == "UNAVAILABLE"
        assert res["results"] == []

    @pytest.mark.asyncio
    async def test_tavily_available(self, monkeypatch):
        import respx
        from app.tools.web_search_tool import web_search
        _key_for(monkeypatch, "tavily_api_key", "tvly-test")
        async with respx.mock() as mock:
            mock.post("https://api.tavily.com/search").respond(
                200, json={
                    "query": "lagos",
                    "answer": "Lagos is a city.",
                    "results": [
                        {"title": "Lagos", "url": "https://example.com/lagos",
                         "content": "desc", "score": 0.99},
                    ],
                },
            )
            res = await web_search("lagos", max_results=3)
        assert res["state"] == "AVAILABLE"
        assert res["provider"] == "tavily"
        assert res["total"] == 1
        assert res["results"][0]["url"] == "https://example.com/lagos"
        assert res["answer"] == "Lagos is a city."

    @pytest.mark.asyncio
    async def test_tavily_failure_is_error(self, monkeypatch):
        import respx
        from app.tools.web_search_tool import web_search
        _key_for(monkeypatch, "tavily_api_key", "tvly-test")
        async with respx.mock() as mock:
            mock.post("https://api.tavily.com/search").respond(500)
            res = await web_search("lagos")
        assert res["state"] == "ERROR"
        assert res["provider"] == "tavily"
        assert res["results"] == []

    @pytest.mark.asyncio
    async def test_keyless_ddg_fallback(self, monkeypatch):
        import respx
        from app.tools.web_search_tool import web_search
        _no_keys(monkeypatch)
        async with respx.mock() as mock:
            mock.post("https://html.duckduckgo.com/html/").respond(200, html=DDG_HTML)
            res = await web_search("lagos")
        assert res["state"] == "AVAILABLE"
        assert res["provider"] == "duckduckgo"
        assert res["results"][0]["title"] == "Example Title"
        assert res["results"][0]["url"] == "https://example.com/page"
        assert res["results"][0]["content"] == "Some snippet & more"

    @pytest.mark.asyncio
    async def test_keyless_ddg_failure_is_unavailable(self, monkeypatch):
        import respx
        from app.tools.web_search_tool import web_search
        _no_keys(monkeypatch)
        async with respx.mock() as mock:
            mock.post("https://html.duckduckgo.com/html/").respond(403)
            res = await web_search("lagos")
        assert res["state"] == "UNAVAILABLE"
        assert res["provider"] is None


# --------------------------------------------------------------------------- #
# web_fetch
# --------------------------------------------------------------------------- #
class TestWebFetch:
    @pytest.mark.asyncio
    async def test_non_http_url_unavailable(self, monkeypatch):
        from app.tools.web_search_tool import web_fetch
        res = await web_fetch("file:///etc/passwd")
        assert res["state"] == "UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_fetch_error(self, monkeypatch):
        import respx
        from app.tools.web_search_tool import web_fetch
        async with respx.mock() as mock:
            mock.get("https://example.com/x").respond(404)
            res = await web_fetch("https://example.com/x")
        assert res["state"] == "ERROR"
        assert res["title"] is None

    @pytest.mark.asyncio
    async def test_fetch_success_returns_title_and_text(self, monkeypatch):
        import respx
        from app.tools.web_search_tool import web_fetch
        html = "<html><head><title>PAGE TITLE</title></head>" \
               "<body><script>var x=1;</script><p>Hello   world</p></body></html>"
        async with respx.mock() as mock:
            mock.get("https://example.com/").respond(200, html=html)
            res = await web_fetch("https://example.com/", max_chars=5000)
        assert res["state"] == "AVAILABLE"
        assert res["title"] == "PAGE TITLE"
        assert "Hello world" in res["text"]
        assert "var x=1" not in res["text"]


# --------------------------------------------------------------------------- #
# geocoding
# --------------------------------------------------------------------------- #
class TestGeocode:
    @pytest.mark.asyncio
    async def test_short_query_unavailable(self, monkeypatch):
        from app.tools.geocoding_tool import geocode_place
        res = await geocode_place("a")
        assert res["state"] == "UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_geocode_hit(self, monkeypatch):
        from app.tools import geocoding_tool
        monkeypatch.setattr(
            geocoding_tool, "geocode_search",
            AsyncMock(return_value={"lat": 6.5, "lon": 3.4, "source": "nominatim", "cached": False}),
        )
        res = await geocoding_tool.geocode_place("Lagos Island")
        assert res["state"] == "AVAILABLE"
        assert res["lat"] == 6.5
        assert res["lon"] == 3.4
        assert res["source"] == "nominatim"

    @pytest.mark.asyncio
    async def test_geocode_miss_is_error(self, monkeypatch):
        from app.tools import geocoding_tool
        monkeypatch.setattr(geocoding_tool, "geocode_search", AsyncMock(return_value=None))
        res = await geocoding_tool.geocode_place("Nowhereville")
        assert res["state"] == "ERROR"
        assert res["lat"] is None

    @pytest.mark.asyncio
    async def test_batch_geocode(self, monkeypatch):
        from app.tools import geocoding_tool

        class FakeCandidate:
            def model_dump(self):
                return {"query": "Lagos", "lat": 6.5, "lon": 3.4, "matched": True}

        monkeypatch.setattr(
            geocoding_tool, "geocode_batch",
            AsyncMock(return_value=[FakeCandidate()]),
        )
        res = await geocoding_tool.geocode_batch_texts(["Lagos"])
        assert res["state"] == "AVAILABLE"
        assert res["total"] == 1
        assert res["candidates"][0]["query"] == "Lagos"

    @pytest.mark.asyncio
    async def test_batch_empty_is_error(self, monkeypatch):
        from app.tools import geocoding_tool
        monkeypatch.setattr(geocoding_tool, "geocode_batch", AsyncMock(return_value=[]))
        res = await geocoding_tool.geocode_batch_texts(["Nothing"])
        assert res["state"] == "ERROR"


# --------------------------------------------------------------------------- #
# reverse_image_search
# --------------------------------------------------------------------------- #
class TestReverseImageSearch:
    @pytest.mark.asyncio
    async def test_no_provider_unavailable(self, monkeypatch):
        _no_keys(monkeypatch)
        from app.tools.reverse_image_tool import reverse_image_search
        res = await reverse_image_search(b"fake-jpeg")
        assert res["state"] == "UNAVAILABLE"
        assert res["matches"] == []

    @pytest.mark.asyncio
    async def test_tineye_only(self, monkeypatch):
        from app.tools import reverse_image_tool
        _key_for(monkeypatch, "tineye_api_key", "tk")
        monkeypatch.setattr(
            reverse_image_tool, "search_tineye",
            AsyncMock(return_value={
                "provider": "tineye", "state": "AVAILABLE",
                "detail": "1 match", "matches": [{"url": "https://src.example/a.jpg", "score": 99}],
            }),
        )
        monkeypatch.setattr(reverse_image_tool, "search_serper", AsyncMock())
        res = await reverse_image_tool.reverse_image_search(b"fake-jpeg")
        assert res["state"] == "AVAILABLE"
        assert res["provider"] == "tineye"
        assert res["total"] == 1
        reverse_image_tool.search_serper.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_serper_without_query_or_url_is_unavailable(self, monkeypatch):
        from app.tools import reverse_image_tool
        monkeypatch.setattr(
            settings_store, "get_key",
            lambda n: "sk" if n == "serper_api_key" else (None if n == "tineye_api_key" else None),
        )
        res = await reverse_image_tool.reverse_image_search(b"fake-jpeg")
        assert res["state"] == "UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_both_providers_fan_out(self, monkeypatch):
        from app.tools import reverse_image_tool
        monkeypatch.setattr(
            settings_store, "get_key",
            lambda n: {"tineye_api_key": "tk", "serper_api_key": "sk"}.get(n),
        )
        monkeypatch.setattr(
            reverse_image_tool, "search_tineye",
            AsyncMock(return_value={
                "provider": "tineye", "state": "AVAILABLE",
                "matches": [{"url": "https://a.example/1.jpg", "score": 99}],
            }),
        )
        monkeypatch.setattr(
            reverse_image_tool, "search_serper",
            AsyncMock(return_value={
                "provider": "serper", "state": "AVAILABLE",
                "matches": [{"title": "T", "image_url": "https://b.example/2.jpg"}],
            }),
        )
        res = await reverse_image_tool.reverse_image_search(b"fake-jpeg", search_query="lagos")
        assert res["state"] == "AVAILABLE"
        assert "tineye" in res["provider"] and "serper" in res["provider"]
        assert res["total"] == 2


# --------------------------------------------------------------------------- #
# Registry metadata
# --------------------------------------------------------------------------- #
class TestRegistry:
    def test_osint_tools_registered(self):
        expected = {
            "web_search": ("tavily", "osint"),
            "web_fetch": ("web", "osint"),
            "geocode_place": ("google_maps", "osint"),
            "geocode_batch_texts": ("google_maps", "osint"),
            "reverse_image_search": ("reverse_search", "osint"),
        }
        for tid, (provider, domain) in expected.items():
            tool = registry.get(tid)
            assert tool is not None, f"{tid} missing from registry"
            assert tool.spec.provider == provider
            assert tool.spec.domain == domain
            assert tool.is_async()

    def test_registry_has_specs_exportable(self):
        for tid in ("web_search", "geocode_place"):
            spec = registry.get(tid).spec
            assert isinstance(spec.input_schema, dict)
            assert spec.input_schema  # JSON-schema-exportable, non-empty


# --------------------------------------------------------------------------- #
# Tavily key probe
# --------------------------------------------------------------------------- #
class TestTavilyProbe:
    @pytest.mark.asyncio
    async def test_probe_success(self):
        import respx
        from app.services.key_probe import live_probe, PROVIDER_KEY_FIELDS
        assert "tavily" in PROVIDER_KEY_FIELDS
        assert PROVIDER_KEY_FIELDS["tavily"] == ("tavily_api_key",)
        async with respx.mock() as mock:
            mock.post("https://api.tavily.com/search").respond(200, json={"results": []})
            res = await live_probe("tavily", "tvly-test")
        assert res["valid"] is True
        assert "Tavily" in res["detail"]

    @pytest.mark.asyncio
    async def test_probe_rejects_bad_key(self):
        import respx
        from app.services.key_probe import live_probe
        async with respx.mock() as mock:
            mock.post("https://api.tavily.com/search").respond(401)
            res = await live_probe("tavily", "bad-key")
        assert res["valid"] is False
