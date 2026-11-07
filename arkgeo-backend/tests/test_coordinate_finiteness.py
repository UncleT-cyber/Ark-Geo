"""Regression tests: non-finite provider coordinates must never reach the map.

A geocoder / cell provider that returns ``NaN`` or ``Infinity`` (Python's
``json`` accepts those non-standard tokens, and ``float("nan")`` accepts the
string) used to flow straight through as a coordinate.  The value serializes
back out as the invalid JSON token ``NaN``, and Leaflet's ``flyTo`` →
``unproject`` then throws ``Invalid LatLng object: (NaN, NaN)``, crashing the
whole workbench render.  Every boundary now rejects non-finite coordinates.
"""
from __future__ import annotations

import math
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.models import GeoCandidate
from app.services.cell_geolocator import CellTowerStore
from app.services.geocoding_service import finite_coord
from main import app

client = TestClient(app)


class FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data or {}

    def json(self):
        return self._json

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class FakeAsyncClient:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, **kwargs):
        return self._response

    async def post(self, url, **kwargs):
        return self._response


# --------------------------------------------------------------------------- #
# finite_coord helper
# --------------------------------------------------------------------------- #
class TestFiniteCoord:
    @pytest.mark.parametrize("lat,lon", [
        (float("nan"), 0.0),
        (0.0, float("nan")),
        (float("inf"), 0.0),
        (0.0, float("-inf")),
        ("nan", "nan"),
        (None, None),
        ("not-a-number", 0.0),
        (91.0, 0.0),
        (0.0, 181.0),
        (-91.0, 0.0),
    ])
    def test_rejects_non_finite_or_out_of_range(self, lat, lon):
        assert finite_coord(lat, lon) is None

    def test_accepts_valid(self):
        assert finite_coord(6.5244, 3.3792) == {"lat": 6.5244, "lon": 3.3792}

    def test_coerces_numeric_strings(self):
        assert finite_coord("6.5244", "3.3792") == {"lat": 6.5244, "lon": 3.3792}


# --------------------------------------------------------------------------- #
# GeoCandidate model
# --------------------------------------------------------------------------- #
class TestGeoCandidateModel:
    def test_rejects_nan(self):
        with pytest.raises(Exception):
            GeoCandidate(query="Lagos", lat=float("nan"), lon=3.3792)

    def test_rejects_out_of_range(self):
        with pytest.raises(Exception):
            GeoCandidate(query="Lagos", lat=91.0, lon=3.3792)

    def test_accepts_valid(self):
        c = GeoCandidate(query="Lagos", lat=6.5244, lon=3.3792)
        assert math.isfinite(c.lat) and math.isfinite(c.lon)


# --------------------------------------------------------------------------- #
# Geocoding service — provider body carries NaN
# --------------------------------------------------------------------------- #
class TestGeocodeProviderNaN:
    @pytest.mark.asyncio
    async def test_google_nan_degrades_to_none(self):
        from app.services import geocoding_service as gs

        payload = {
            "status": "OK",
            "results": [{"geometry": {"location": {"lat": float("nan"), "lng": 3.3}}}],
        }
        fake = FakeAsyncClient(FakeResponse(200, payload))
        with patch.object(gs, "_maps_key", return_value="k"), \
             patch.object(gs.httpx, "AsyncClient", return_value=fake):
            assert await gs._google_geocode("Lagos") is None

    @pytest.mark.asyncio
    async def test_nominatim_string_nan_degrades_to_none(self):
        from app.services import geocoding_service as gs

        fake = FakeAsyncClient(FakeResponse(200, [{"lat": "nan", "lon": "nan"}]))
        with patch.object(gs.settings, "geo_nominatim_fallback", True), \
             patch.object(gs.httpx, "AsyncClient", return_value=fake):
            assert await gs._nominatim_geocode("Lagos") is None

    @pytest.mark.asyncio
    async def test_nominatim_valid_passes(self):
        from app.services import geocoding_service as gs

        fake = FakeAsyncClient(FakeResponse(200, [{"lat": "6.5244", "lon": "3.3792"}]))
        with patch.object(gs.settings, "geo_nominatim_fallback", True), \
             patch.object(gs.httpx, "AsyncClient", return_value=fake):
            assert await gs._nominatim_geocode("Lagos") == {"lat": 6.5244, "lon": 3.3792}

    def test_batch_endpoint_omits_nan_candidate(self):
        """The batch endpoint must never emit a NaN coordinate to the client."""
        payload = {
            "status": "OK",
            "results": [{"geometry": {"location": {"lat": float("nan"), "lng": 3.3}}}],
        }
        fake = FakeAsyncClient(FakeResponse(200, payload))
        with patch("app.services.geocoding_service._maps_key", return_value="k"), \
             patch("app.services.geocoding_service.httpx.AsyncClient", return_value=fake):
            r = client.post("/api/v1/maps/geocode/batch", json={"queries": ["Lagos"]})
        assert r.status_code == 200
        assert r.json()["candidates"] == []


# --------------------------------------------------------------------------- #
# Cell lookup — provider body carries NaN
# --------------------------------------------------------------------------- #
class TestCellLookupNaN:
    def test_opencellid_nan_degrades_to_not_found(self):
        fake = FakeAsyncClient(FakeResponse(200, {"lat": float("nan"), "lon": 3.3}))
        with patch("app.api.v1.endpoints.telecom.httpx.AsyncClient", return_value=fake):
            r = client.post("/api/v1/telecom/cell-lookup", json={
                "mcc": 621, "mnc": 30, "lac": 1001, "cell_id": 12345,
                "provider": "opencellid", "api_key": "client-key",
            })
        assert r.status_code == 200
        d = r.json()
        assert d["lat"] is None and d["lon"] is None

    def test_beacondb_open_nan_degrades_to_not_found(self):
        fake = FakeAsyncClient(FakeResponse(200, {"location": {"lat": "nan", "lng": 3.3}}))
        with patch("app.api.v1.endpoints.telecom.httpx.AsyncClient", return_value=fake):
            r = client.post("/api/v1/telecom/cell-lookup", json={
                "mcc": 621, "mnc": 30, "lac": 1001, "cell_id": 12345,
                "provider": "beacondb-open",
            })
        assert r.status_code == 200
        d = r.json()
        assert d["lat"] is None and d["lon"] is None
        assert "not found" in d["detail"].lower()


# --------------------------------------------------------------------------- #
# Cell geolocator CSV ingestion
# --------------------------------------------------------------------------- #
class TestCellCsvNaN:
    def test_nan_row_is_dropped(self, tmp_path):
        p = tmp_path / "cells.csv"
        p.write_text(
            "lat,lon,mcc,mnc,lac,cellid,range,radio,samples\n"
            "nan,nan,621,30,1001,12345,1200,GSM,40\n"
            "6.5244,3.3792,621,30,1002,12346,1500,GSM,22\n",
            encoding="utf-8",
        )
        store = CellTowerStore()
        loaded = store.load_csv(str(p))
        # Only the finite row survives; the NaN row never becomes a tower.
        assert loaded == 1

    def test_infinite_row_is_dropped(self, tmp_path):
        p = tmp_path / "cells.csv"
        p.write_text(
            "lat,lon,mcc,mnc,lac,cellid,range,radio,samples\n"
            "inf,3.3792,621,30,1001,12345,1200,GSM,40\n",
            encoding="utf-8",
        )
        store = CellTowerStore()
        assert store.load_csv(str(p)) == 0
