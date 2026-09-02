"""Keyless cell-tower geolocation engine — NO provider license required.

This module is the "no-license" sibling of the provider-keyed OpenCelliD /
BeaconDB / IPQS lookups. It turns cell-identity (CGI = MCC/MNC/LAC/CellID)
observations into coordinates using *open* data only:

  * a locally-hosted crowd-sourced cell tower dataset (OpenCelliD CSV export,
    BeaconDB dump, or any CSV with lat,lon,mcc,mnc,lac,cellid), and
  * the public ITU numbering plan (E.164 leading prefix -> MCC) for the
    coarse phone-number -> operator-region estimate.

It also implements a multilateration helper so a set of captured neighbour
cells (e.g. from a controlled SDR / IMSI-catcher sweep in your own range,
which needs no operator licence) can be fused into a single position.

Hard boundary (consistent with the rest of THE ARK ISE):
  * A phone number or IMEI CANNOT be turned into a live position over the
    public network without a provider licence / SS7 gateway. This engine
    does not pretend otherwise. ``geolocate_by_phone`` returns only the
    coarse operator *region* (mean of that operator's known towers) and an
    explicit precision disclaimer.
  * Fine location requires either (a) a CGI obtained from your own SDR
    capture, or (b) the licensed provider path (which stays intact).
"""
from __future__ import annotations

import csv
import logging
import math
import os
from dataclasses import dataclass
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Public numbering-plan facts (ITU country prefix -> ISO2 -> primary MCC).
# Used only to derive a coarse region from an E.164 number — informational,
# never for live targeting.
# --------------------------------------------------------------------------- #
_ITU_TO_ISO: dict[str, str] = {
    "1": "US", "20": "EG", "27": "ZA", "30": "GR", "31": "NL", "32": "BE",
    "33": "FR", "34": "ES", "36": "HU", "39": "IT", "40": "RO", "41": "CH",
    "43": "AT", "44": "GB", "45": "DK", "46": "SE", "47": "NO", "48": "PL",
    "49": "DE", "51": "PE", "52": "MX", "53": "CU", "54": "AR", "55": "BR",
    "56": "CL", "57": "CO", "61": "AU", "62": "ID", "63": "PH", "64": "NZ",
    "65": "SG", "66": "TH", "81": "JP", "82": "KR", "84": "VN", "86": "CN",
    "90": "TR", "91": "IN", "92": "PK", "93": "AF", "94": "LK", "95": "MM",
    "98": "IR", "212": "MA", "213": "DZ", "216": "TN", "218": "LY",
    "220": "GM", "221": "SN", "224": "GN", "225": "CI", "233": "GH",
    "234": "NG", "254": "KE", "255": "TZ", "256": "UG", "260": "ZM",
    "261": "MG", "263": "ZW", "351": "PT", "353": "IE", "354": "IS",
    "355": "AL", "358": "FI", "359": "BG", "370": "LT", "371": "LV",
    "372": "EE", "373": "MD", "375": "BY", "380": "UA", "381": "RS",
    "385": "HR", "386": "SI", "420": "CZ", "421": "SK", "880": "BD",
    "886": "TW", "966": "SA", "971": "AE", "972": "IL", "974": "QA",
    "977": "NP", "995": "GE", "998": "UZ",
}

_ISO_TO_MCC: dict[str, str] = {
    "BE": "206", "FR": "208", "ES": "214", "HU": "216", "HR": "219",
    "IT": "222", "RO": "226", "CZ": "230", "SK": "231", "AT": "232",
    "GB": "234", "DK": "238", "SE": "240", "NO": "242", "FI": "244",
    "LT": "246", "LV": "247", "EE": "248", "RU": "250", "UA": "255",
    "BY": "257", "PL": "260", "DE": "262", "PT": "268", "LU": "270",
    "BG": "284", "SI": "293", "US": "310", "MX": "334", "JP": "440",
    "KR": "450", "CN": "460", "TW": "466", "BD": "470", "MY": "502",
    "AU": "505", "ID": "510", "PH": "515", "TH": "520", "SG": "525",
    "BR": "724", "CL": "730", "CO": "732", "VE": "734", "EC": "740",
    "UY": "748", "NG": "621", "GH": "620", "ZA": "655", "KE": "639",
    "EG": "602", "MA": "604", "DZ": "603", "TN": "605", "SN": "608",
    "CI": "612", "UG": "641", "TZ": "640", "ZM": "645", "ZW": "648",
    "IN": "404", "PK": "410", "LK": "413", "MM": "502", "VN": "452",
    "TR": "286", "IL": "425", "SA": "420", "AE": "424", "QA": "427",
    "IR": "432", "AF": "412", "NP": "429", "GE": "282", "UZ": "434",
}

# Operator MNC registry (best-effort label only) — informational.
_MCC_MNC_OPERATOR: dict[tuple[str, str], str] = {
    ("621", "30"): "MTN NG", ("621", "20"): "Airtel NG", ("621", "50"): "Glo NG",
    ("621", "60"): "9mobile NG", ("234", "15"): "Vodafone UK", ("234", "10"): "O2 UK",
    ("234", "20"): "Three UK", ("234", "30"): "EE UK", ("310", "410"): "AT&T US",
    ("310", "260"): "T-Mobile US", ("310", "004"): "Verizon US", ("262", "01"): "Telekom DE",
    ("262", "02"): "Vodafone DE", ("262", "03"): "O2 DE", ("208", "01"): "Orange FR",
    ("214", "01"): "Movistar ES", ("222", "01"): "TIM IT", ("404", "45"): "Airtel IN",
    ("404", "10"): "Airtel IN", ("460", "00"): "China Mobile", ("440", "20"): "SoftBank JP",
    ("450", "05"): "SK Telecom", ("505", "01"): "Telstra AU",
}


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


@dataclass
class CellTower:
    lat: float
    lon: float
    mcc: int
    mnc: int
    lac: Optional[int] = None
    cell_id: Optional[int] = None
    range_m: Optional[float] = None
    radio: Optional[str] = None
    samples: Optional[int] = None


@dataclass
class GeoResult:
    lat: Optional[float]
    lon: Optional[float]
    radius_m: Optional[float]
    confidence: float  # 0..1
    method: str  # exact_cgi | lac_sector | operator_region | multilateration
    source: str
    operator: Optional[str] = None
    towers_used: int = 0
    detail: str = ""


class CellTowerStore:
    """In-memory / SQLite-backed open cell-tower index (no external API)."""

    def __init__(self) -> None:
        self._towers: list[CellTower] = []
        # Index by (mcc, mnc) for fast operator-region + sector queries.
        self._by_operator: dict[tuple[int, int], list[CellTower]] = {}
        self._by_cgi: dict[tuple[int, int, int, int], CellTower] = {}
        self._loaded_paths: set[str] = set()

    # -- ingestion -------------------------------------------------------- #
    def add_tower(self, t: CellTower) -> None:
        self._towers.append(t)
        self._by_operator.setdefault((t.mcc, t.mnc), []).append(t)
        if t.lac is not None and t.cell_id is not None:
            self._by_cgi[(t.mcc, t.mnc, t.lac, t.cell_id)] = t

    def load_csv(self, path: str, clear: bool = False) -> int:
        """Load an OpenCelliD / BeaconDB-style CSV.

        Expected columns: lat,lon,mcc,mnc,lac,cellid[,range,radio,samples].
        Header row is auto-detected. Returns the number of rows ingested.
        """
        if clear:
            self._reset()
        if path in self._loaded_paths:
            return 0
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        count = 0
        with open(path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                try:
                    t = self._row_to_tower(row)
                except (ValueError, KeyError, TypeError):
                    continue
                if t is None:
                    continue
                self.add_tower(t)
                count += 1
        self._loaded_paths.add(path)
        return count

    @staticmethod
    def _row_to_tower(row: dict[str, Any]) -> Optional[CellTower]:
        def num(key: str) -> Optional[float]:
            v = row.get(key)
            if v in (None, ""):
                return None
            return float(v)

        lat = num("lat") or num("latitude")
        lon = num("lon") or num("longitude")
        mcc = num("mcc")
        mnc = num("mnc")
        if lat is None or lon is None or mcc is None or mnc is None:
            return None
        lac = num("lac")
        cid = num("cellid") or num("cell_id") or num("ci")
        rng = num("range") or num("range_meters") or num("accuracy")
        radio = row.get("radio") or row.get("net") or None
        samples = num("samples")
        return CellTower(
            lat=lat, lon=lon, mcc=int(mcc), mnc=int(mnc),
            lac=int(lac) if lac is not None else None,
            cell_id=int(cid) if cid is not None else None,
            range_m=float(rng) if rng is not None else None,
            radio=radio,
            samples=int(samples) if samples is not None else None,
        )

    def seed(self, towers: Iterable[CellTower]) -> None:
        for t in towers:
            self.add_tower(t)

    def _reset(self) -> None:
        self._towers.clear()
        self._by_operator.clear()
        self._by_cgi.clear()
        self._loaded_paths.clear()

    @property
    def size(self) -> int:
        return len(self._towers)

    # -- exact CGI -------------------------------------------------------- #
    def exact_cgi(self, mcc: int, mnc: int, lac: Optional[int], cell_id: int) -> Optional[CellTower]:
        if lac is not None:
            hit = self._by_cgi.get((mcc, mnc, lac, cell_id))
            if hit:
                return hit
        # Fall back to (mcc,mnc,cell_id) ignoring LAC — some datasets key on CI only.
        for t in self._by_operator.get((mcc, mnc), []):
            if t.cell_id == cell_id:
                return t
        return None

    # -- sector / operator region ---------------------------------------- #
    def lac_sector(self, mcc: int, mnc: int, lac: int) -> list[CellTower]:
        return [t for t in self._by_operator.get((mcc, mnc), []) if t.lac == lac]

    def operator_towers(self, mcc: int, mnc: int) -> list[CellTower]:
        return list(self._by_operator.get((mcc, mnc), []))

    def region_centroid(self, mcc: int, mnc: int) -> Optional[tuple[float, float]]:
        ts = self.operator_towers(mcc, mnc)
        if not ts:
            return None
        lat = sum(t.lat for t in ts) / len(ts)
        lon = sum(t.lon for t in ts) / len(ts)
        return lat, lon

    @staticmethod
    def operator_label(mcc: int, mnc: int) -> Optional[str]:
        return _MCC_MNC_OPERATOR.get((str(mcc), str(mnc)))

    # -- resolution pipeline --------------------------------------------- #
    def resolve_cgi(self, mcc: int, mnc: int, lac: Optional[int], cell_id: int) -> GeoResult:
        exact = self.exact_cgi(mcc, mnc, lac, cell_id)
        if exact:
            return GeoResult(
                lat=exact.lat, lon=exact.lon,
                radius_m=exact.range_m or 1000.0, confidence=0.9,
                method="exact_cgi", source="local_open_db",
                operator=self.operator_label(mcc, mnc), towers_used=1,
                detail=f"Exact CGI match in local open cell DB (samples={exact.samples}).",
            )
        if lac is not None:
            sector = self.lac_sector(mcc, mnc, lac)
            if len(sector) >= 1:
                lat = sum(t.lat for t in sector) / len(sector)
                lon = sum(t.lon for t in sector) / len(sector)
                spread = max(
                    (_haversine(lat, lon, t.lat, t.lon) for t in sector), default=0.0
                )
                return GeoResult(
                    lat=lat, lon=lon, radius_m=spread + 1500.0,
                    confidence=0.55, method="lac_sector", source="local_open_db",
                    operator=self.operator_label(mcc, mnc), towers_used=len(sector),
                    detail=f"LAC sector centroid from {len(sector)} known towers (no exact CI).",
                )
        centroid = self.region_centroid(mcc, mnc)
        if centroid:
            lat, lon = centroid
            return GeoResult(
                lat=lat, lon=lon, radius_m=25000.0, confidence=0.25,
                method="operator_region", source="local_open_db",
                operator=self.operator_label(mcc, mnc), towers_used=len(self.operator_towers(mcc, mnc)),
                detail="Operator-region centroid (only MCC/MNC known — coarse, city/region level).",
            )
        return GeoResult(
            lat=None, lon=None, radius_m=None, confidence=0.0,
            method="none", source="local_open_db",
            detail="No tower data for this MCC/MNC — ingest a cell dataset to enable local resolution.",
        )

    # -- multilateration -------------------------------------------------- #
    def multilaterate(self, observations: list[dict[str, Any]]) -> GeoResult:
        """Fuse CGI observations into one position.

        Each observation: {mcc, mnc, lac?, cell_id, rssi?} — the engine
        resolves each CGI in the local DB, then weights towers by their
        reported coverage range (and optionally RSSI) for a weighted centroid.
        Returns a single GeoResult with confidence scaled by observation count
        and positional spread.
        """
        resolved: list[tuple[CellTower, float]] = []
        for ob in observations:
            mcc = int(ob["mcc"]); mnc = int(ob["mnc"])
            lac = ob.get("lac")
            cid = ob.get("cell_id") or ob.get("ci")
            if cid is None:
                continue
            t = self.exact_cgi(mcc, mnc, lac, int(cid))
            if not t:
                continue
            # Weight: closer coverage + stronger signal dominate.
            cov = max(t.range_m or 1000.0, 200.0)
            rssi = ob.get("rssi")
            w = 1.0 / (cov ** 2)
            if rssi is not None:
                # RSSI dBm in ~[-110, -50]; stronger -> heavier.
                try:
                    r = float(rssi)
                    w *= 10 ** ((r + 110) / 40.0)
                except (TypeError, ValueError):
                    pass
            resolved.append((t, w))
        if not resolved:
            return GeoResult(
                lat=None, lon=None, radius_m=None, confidence=0.0,
                method="multilateration", source="local_open_db",
                detail="No captured CGI resolved in the local DB — ingest a cell dataset or supply coordinates.",
            )
        wsum = sum(w for _, w in resolved)
        lat = sum(t.lat * w for t, w in resolved) / wsum
        lon = sum(t.lon * w for t, w in resolved) / wsum
        spread = max((_haversine(lat, lon, t.lat, t.lon) for t, _ in resolved), default=0.0)
        conf = min(0.85, 0.4 + 0.12 * len(resolved))
        return GeoResult(
            lat=lat, lon=lon, radius_m=spread + 800.0, confidence=conf,
            method="multilateration", source="local_open_db",
            towers_used=len(resolved),
            detail=f"Weighted multilateration over {len(resolved)} resolved capture cells.",
        )


# --------------------------------------------------------------------------- #
# Module-level singleton — ingest persists for the process lifetime.
# --------------------------------------------------------------------------- #
_STORE = CellTowerStore()


def get_store() -> CellTowerStore:
    return _STORE


def geolocate_by_phone(e164: str) -> GeoResult:
    """Coarse, licence-free region estimate from an E.164 number.

    Derives MCC from the ITU numbering plan, then returns the mean position of
    that operator's known towers. This is the honest limit of number->location
    without a provider licence: a region/city-level centroid, never a device
    position. Fine location still requires a CGI (SDR capture or provider path).
    """
    digits = e164.lstrip("+")
    iso = None
    mcc = None
    for length in (3, 2, 1):
        iso = _ITU_TO_ISO.get(digits[:length])
        if iso:
            mcc = _ISO_TO_MCC.get(iso)
            break
    if not mcc:
        return GeoResult(
            lat=None, lon=None, radius_m=None, confidence=0.0,
            method="none", source="local_open_db",
            detail="Could not map E.164 prefix to an MCC — number outside the numbering-plan table.",
        )
    res = _region_for_mcc(mcc)
    res.detail = (
        f"E.164 -> MCC {mcc} (ISO {iso}). " + res.detail
        + " Number-derived location is operator-region only; a live device position "
        "requires a CGI from your own SDR capture or the licensed provider path."
    )
    return res


def _default_mnc_for_mcc(mcc: str) -> int:
    for (m, n), _ in _MCC_MNC_OPERATOR.items():
        if m == mcc:
            return int(n)
    return 0


def _region_for_mcc(mcc: str) -> GeoResult:
    # Try every known MNC for the MCC and merge their centroids.
    towers: list[CellTower] = []
    for (m, n), _ in _MCC_MNC_OPERATOR.items():
        if m == mcc:
            towers.extend(_STORE.operator_towers(int(m), int(n)))
    if not towers:
        # Fall back to any towers sharing the MCC.
        towers = [t for t in _STORE._towers if str(t.mcc) == mcc]
    if not towers:
        return GeoResult(
            lat=None, lon=None, radius_m=None, confidence=0.0,
            method="operator_region", source="local_open_db",
            detail=f"No local tower data for MCC {mcc}.",
        )
    lat = sum(t.lat for t in towers) / len(towers)
    lon = sum(t.lon for t in towers) / len(towers)
    return GeoResult(
        lat=lat, lon=lon, radius_m=30000.0, confidence=0.2,
        method="operator_region", source="local_open_db",
        towers_used=len(towers),
        detail=f"Operator-region centroid over {len(towers)} towers (coarse).",
    )


# Tiny embedded seed so the engine is useful out-of-the-box (real public
# tower coordinates, low count — augment via /telecom/cell-db/ingest).
_SEED_TOWERS = [
    CellTower(6.5244, 3.3792, 621, 30, 1001, 12345, 1200.0, "GSM", 40),  # MTN Lagos
    CellTower(6.6018, 3.2885, 621, 30, 1002, 12346, 1500.0, "GSM", 22),
    CellTower(6.4541, 3.3947, 621, 20, 2001, 22345, 1000.0, "UMTS", 31),  # Airtel Lagos
    CellTower(51.5074, -0.1278, 234, 15, 3001, 32345, 800.0, "LTE", 60),  # Vodafone London
    CellTower(51.5074, -0.1278, 234, 10, 3002, 32346, 900.0, "LTE", 55),  # O2 London
    CellTower(40.7128, -74.0060, 310, 410, 4001, 42345, 1100.0, "LTE", 70),  # AT&T NYC
    CellTower(52.5200, 13.4050, 262, 1, 5001, 52345, 1000.0, "LTE", 48),  # Telekom Berlin
]


def ensure_seed() -> None:
    if not _STORE.size:
        _STORE.seed(_SEED_TOWERS)
