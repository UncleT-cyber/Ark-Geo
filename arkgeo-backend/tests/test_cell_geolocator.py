"""Tests for the keyless cell-tower geolocation engine and endpoints."""
from __future__ import annotations

import csv
import os

import pytest
from fastapi.testclient import TestClient

from app.services.cell_geolocator import (
    CellTower,
    CellTowerStore,
    GeoResult,
    ensure_seed,
    geolocate_by_phone,
    get_store,
)
from main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _seed_singleton():
    ensure_seed()
    yield



# --------------------------------------------------------------------------- #
# Unit — CellTowerStore
# --------------------------------------------------------------------------- #
def _sample_csv(tmp_path) -> str:
    p = tmp_path / "cells.csv"
    rows = [
        ("lat", "lon", "mcc", "mnc", "lac", "cellid", "range", "radio", "samples"),
        (6.5244, 3.3792, 621, 30, 1001, 12345, 1200, "GSM", 40),
        (6.6018, 3.2885, 621, 30, 1002, 12346, 1500, "GSM", 22),
        (6.4541, 3.3947, 621, 20, 2001, 22345, 1000, "UMTS", 31),
        (51.5074, -0.1278, 234, 15, 3001, 32345, 800, "LTE", 60),
    ]
    with open(p, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerows(rows)
    return str(p)


def test_load_csv_and_exact_cgi(tmp_path):
    store = CellTowerStore()
    n = store.load_csv(_sample_csv(tmp_path))
    assert n == 4
    hit = store.exact_cgi(621, 30, 1001, 12345)
    assert hit is not None
    assert hit.lat == 6.5244
    # LAC/CI miss falls through to CI-only match.
    assert store.exact_cgi(621, 30, 9999, 12346) is not None


def test_resolve_cgi_fallback_chain(tmp_path):
    store = CellTowerStore()
    store.load_csv(_sample_csv(tmp_path))
    # exact
    r = store.resolve_cgi(621, 30, 1001, 12345)
    assert r.method == "exact_cgi" and r.lat == 6.5244
    # LAC sector (no exact CI)
    r = store.resolve_cgi(621, 30, 1001, 99999)
    assert r.method == "lac_sector" and r.lat is not None
    # operator region only
    r = store.resolve_cgi(621, 30, None, 99999)
    assert r.method == "operator_region" and r.lat is not None
    # unknown operator
    r = store.resolve_cgi(999, 99, None, 1)
    assert r.method == "none" and r.lat is None


def test_multilaterate(tmp_path):
    store = CellTowerStore()
    store.load_csv(_sample_csv(tmp_path))
    obs = [
        {"mcc": 621, "mnc": 30, "lac": 1001, "cell_id": 12345, "rssi": -60},
        {"mcc": 621, "mnc": 30, "lac": 1002, "cell_id": 12346, "rssi": -70},
    ]
    r = store.multilaterate(obs)
    assert r.method == "multilateration" and r.lat is not None
    assert 6.4 < r.lat < 6.7 and 3.2 < r.lon < 3.5
    assert r.towers_used == 2
    # empty -> no fix
    assert store.multilaterate([{"mcc": 1, "mnc": 1, "cell_id": 1}]).lat is None


def test_geolocate_by_phone_coarse():
    # Process singleton is seeded with public towers for NG/GB/US/DE.
    store = get_store()
    res = geolocate_by_phone("+2348030000000")
    assert res.lat is not None and res.method == "operator_region"
    # Unknown prefix -> no fix, no crash.
    res2 = geolocate_by_phone("+0000000000")
    assert res2.lat is None and res2.method == "none"


# --------------------------------------------------------------------------- #
# Endpoint — keyless providers
# --------------------------------------------------------------------------- #
def test_cell_lookup_local_seed():
    r = client.post("/api/v1/telecom/cell-lookup",
                    json={"mcc": 621, "mnc": 30, "lac": 1001, "cell_id": 12345, "provider": "local"})
    assert r.status_code == 200
    d = r.json()
    assert d["looked_up"] is True
    assert d["provider"] == "local"
    assert d["lat"] == 6.5244
    assert d["method"] == "exact_cgi"


def test_cell_lookup_local_unknown_region():
    r = client.post("/api/v1/telecom/cell-lookup",
                    json={"mcc": 999, "mnc": 99, "cell_id": 1, "provider": "local"})
    assert r.status_code == 200
    assert r.json()["looked_up"] is False


def test_phone_locate_endpoint():
    r = client.post("/api/v1/telecom/phone-locate", json={"phone": "+2348030000000"})
    assert r.status_code == 200
    d = r.json()
    assert d["iso2"] == "NG"
    assert d["mcc"] == "621"
    assert d["lat"] is not None and d["method"] == "operator_region"
    # Honest disclaimer present.
    assert "operator-region" in d["detail"] or "region" in d["detail"].lower()


def test_cell_db_ingest_and_resolve(tmp_path):
    path = _sample_csv(tmp_path)
    r = client.post("/api/v1/telecom/cell-db/ingest", json={"path": path, "clear": True})
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True and d["ingested"] == 4
    # Now the CSV tower resolves exactly via the local provider.
    r2 = client.post("/api/v1/telecom/cell-lookup",
                     json={"mcc": 234, "mnc": 15, "lac": 3001, "cell_id": 32345, "provider": "local"})
    assert r2.status_code == 200 and r2.json()["lat"] == 51.5074


def test_cell_db_ingest_missing_file():
    r = client.post("/api/v1/telecom/cell-db/ingest", json={"path": "/no/such/file.csv"})
    assert r.status_code == 200
    assert r.json()["ok"] is False


def test_capture_geolocate_multilaterate():
    obs = [
        {"mcc": 621, "mnc": 30, "lac": 1001, "cell_id": 12345, "rssi": -60},
        {"mcc": 621, "mnc": 30, "lac": 1002, "cell_id": 12346, "rssi": -75},
        {"mcc": 621, "mnc": 20, "lac": 2001, "cell_id": 22345, "rssi": -82},
    ]
    r = client.post("/api/v1/telecom/capture-geolocate", json={"observations": obs})
    assert r.status_code == 200
    d = r.json()
    assert d["looked_up"] is True
    assert d["method"] == "multilateration"
    assert d["towers_used"] == 3
    assert 6.4 < d["lat"] < 6.7 and 3.2 < d["lon"] < 3.5


def test_capture_geolocate_no_fix():
    r = client.post("/api/v1/telecom/capture-geolocate",
                    json={"observations": [{"mcc": 1, "mnc": 1, "cell_id": 1}]})
    assert r.status_code == 200
    assert r.json()["looked_up"] is False


def test_investigate_dossier_keyless():
    r = client.post("/api/v1/telecom/investigate", json={"phone": "+2347049796480"})
    assert r.status_code == 200
    d = r.json()
    assert d["phone_e164"] == "+2347049796480"
    # Confirmed keyless facts present.
    assert d["reference"]["carrier"] == "MTN"
    assert d["reference"]["iso2"] == "NG"
    assert d["region"]["lat"] is not None
    # No fabricated name.
    assert d["osint"]["caller_name"] is None
    # Gated fields enumerated.
    assert "line-state" in d["gated"]
    # Analysis produced.
    assert d["analysis"]["title"]
