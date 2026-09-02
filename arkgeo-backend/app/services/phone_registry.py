"""Public phone-numbering-plan registry facts (free OSINT tier).

Everything in this module is derived from *public* telecommunication
numbering plans (ITU E.164 country codes, national numbering plans, and
carrier NDC allocations published by national regulators such as the FCC,
OFCOM and NCC).  No external call, key, or license is required — the facts
are deterministic and fully verifiable against the regulator documents.

Used by both the passive ``/telecom/hlr-lookup`` free-fallback and the
certified ``/signaling/osint`` aggregator.
"""
from __future__ import annotations

from typing import Any, Optional

import phonenumbers
from phonenumbers import PhoneNumberFormat
from phonenumbers import carrier as pn_carrier
from phonenumbers import geocoder as pn_geocoder
from phonenumbers import timezone as pn_timezone

# ITU E.164 country calling codes → ISO 3166-1 alpha-2.
ITU_TO_ISO: dict[str, str] = {
    "1": "US", "7": "RU", "20": "EG", "27": "ZA", "30": "GR", "31": "NL",
    "32": "BE", "33": "FR", "34": "ES", "36": "HU", "39": "IT", "40": "RO",
    "41": "CH", "43": "AT", "44": "GB", "45": "DK", "46": "SE", "47": "NO",
    "48": "PL", "49": "DE", "51": "PE", "52": "MX", "53": "CU", "54": "AR",
    "55": "BR", "56": "CL", "57": "CO", "58": "VE", "61": "AU", "62": "ID",
    "63": "PH", "64": "NZ", "65": "SG", "66": "TH", "81": "JP", "82": "KR",
    "84": "VN", "86": "CN", "90": "TR", "91": "IN", "92": "PK", "93": "AF",
    "94": "LK", "95": "MM", "98": "IR", "212": "MA", "213": "DZ", "216": "TN",
    "218": "LY", "220": "GM", "221": "SN", "224": "GN", "225": "CI",
    "233": "GH", "234": "NG", "254": "KE", "255": "TZ", "256": "UG",
    "260": "ZM", "261": "MG", "263": "ZW", "351": "PT", "353": "IE",
    "354": "IS", "355": "AL", "358": "FI", "359": "BG", "370": "LT",
    "371": "LV", "372": "EE", "373": "MD", "375": "BY", "380": "UA",
    "381": "RS", "385": "HR", "386": "SI", "420": "CZ", "421": "SK",
    "880": "BD", "886": "TW", "966": "SA", "971": "AE", "972": "IL",
    "974": "QA", "977": "NP", "995": "GE", "998": "UZ",
}

# ISO 3166-1 alpha-2 → leading MCC (mobile country codes).
ISO_TO_MCC: dict[str, str] = {
    "BE": "206", "FR": "208", "ES": "214", "HU": "216", "HR": "219",
    "IT": "222", "RO": "226", "CZ": "230", "SK": "231", "AT": "232",
    "GB": "234", "DK": "238", "SE": "240", "NO": "242", "FI": "244",
    "LT": "246", "LV": "247", "EE": "248", "RU": "250", "UA": "255",
    "BY": "257", "PL": "260", "DE": "262", "PT": "268", "LU": "270",
    "BG": "284", "SI": "293", "US": "310", "CA": "302", "MX": "334",
    "JP": "440", "KR": "450", "CN": "460", "TW": "466", "BD": "470",
    "MY": "502", "AU": "505", "ID": "510", "PH": "515", "TH": "520",
    "SG": "525", "BR": "724", "EG": "602", "DZ": "603", "MA": "605",
    "ZA": "655", "GH": "620", "NG": "621", "CD": "630", "KE": "639",
    "TZ": "640", "UG": "641", "ZM": "645", "MG": "646", "ZW": "648",
    "CL": "730", "CO": "732", "VE": "734", "BO": "736", "EC": "740",
    "UY": "748", "AR": "722", "PE": "716", "PK": "410", "IN": "405",
    "TR": "286", "SA": "420", "AE": "424", "IL": "425", "QA": "427",
    "NP": "429", "IR": "432", "GE": "282", "UZ": "434",
}

# MCC → (primary MNC, operator). Public registry facts.
MCC_DEFAULT_MNC: dict[str, tuple[str, str]] = {
    "621": ("30", "MTN"),
    "234": ("15", "Vodafone"),
    "310": ("410", "AT&T"),
    "302": ("720", "Rogers"),
    "208": ("01", "Orange"),
    "262": ("01", "Telekom"),
    "214": ("01", "Telefónica"),
    "260": ("01", "Plus"),
    "602": ("01", "Orange EG"),
    "231": ("01", "Orange SK"),
    "505": ("01", "Telstra"),
    "440": ("20", "SoftBank"),
    "460": ("00", "China Mobile"),
    "510": ("10", "Telkomsel"),
    "466": ("97", "Taiwan Mobile"),
    "724": ("02", "TIM"),
    "732": ("101", "Comcel"),
    "334": ("020", "Telcel"),
    "530": ("01", "Vodafone NZ"),
    "515": ("01", "Smart"),
    "255": ("01", "Kievstar"),
    "250": ("99", "MTS"),
    "405": ("05", "Airtel IN"),
    "410": ("01", "Jazz PK"),
}

# Carrier name → (MCC, MNC) best-effort registry matching.
CARRIER_MCC_MNC: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("mtn",), "621", "30"),
    (("airtel",), "621", "20"),
    (("glo",), "621", "50"),
    (("9mobile", "etisalat"), "621", "60"),
    (("smile",), "621", "00"),
    (("starlink", "spacex"), "621", "00"),
    (("at&t", "att"), "310", "410"),
    (("t-mobile", "tmobile"), "310", "260"),
    (("verizon",), "310", "004"),
    (("vodafone",), "234", "15"),
    (("o2",), "234", "10"),
    (("orange",), "208", "01"),
    (("telenor",), "242", "01"),
    (("telia",), "240", "01"),
    (("etisalat",), "424", "03"),
    (("rogers",), "302", "720"),
    (("bell",), "302", "610"),
    (("telus",), "302", "220"),
)


def derive_mcc_mnc(carrier: str | None) -> dict[str, str]:
    """Best-effort MCC/MNC from the carrier name. Returns {} when unknown."""
    if not carrier:
        return {}
    name = carrier.lower()
    for subs, mcc, mnc in CARRIER_MCC_MNC:
        if any(s in name for s in subs):
            return {"mcc": mcc, "mnc": mnc}
    return {}


def country_code_from_itu(phone: str) -> tuple[str, str, str] | None:
    """Return (cc, iso2, nsn) for an E.164 number (longest ITU prefix match)."""
    digits = phone.lstrip("+")
    for length in (3, 2, 1):
        prefix = digits[:length]
        iso = ITU_TO_ISO.get(prefix)
        if iso:
            return prefix, iso, digits[length:]
    return None


# --------------------------------------------------------------------------- #
# Line-type rules from public national numbering plans (best-effort).
# Each entry: (iso2, ((prefix, line_type), ...)) — longest prefix wins.
# --------------------------------------------------------------------------- #
LINE_TYPE_PLAN: dict[str, tuple[tuple[str, str], ...]] = {
    "NG": (("7", "mobile"), ("8", "mobile"), ("9", "mobile"), ("1", "landline"), ("2", "landline")),
    "GB": (("7", "mobile"), ("3", "landline"), ("1", "landline"), ("2", "landline"), ("5", "landline"), ("8", "special")),
    "IN": (("9", "mobile"), ("8", "mobile"), ("7", "mobile"), ("6", "landline"), ("1", "landline"), ("2", "landline"), ("4", "landline")),
    "FR": (("6", "mobile"), ("7", "mobile"), ("8", "special"), ("1", "landline"), ("2", "landline"), ("3", "landline"), ("4", "landline"), ("5", "landline"), ("9", "landline")),
    "DE": (("15", "mobile"), ("16", "mobile"), ("17", "mobile"), ("1", "special"), ("30", "landline"), ("40", "landline"), ("89", "landline")),
    "ES": (("6", "mobile"), ("7", "mobile"), ("8", "landline"), ("9", "landline")),
    "IT": (("3", "mobile"), ("0", "special"), ("6", "landline"), ("2", "landline"), ("1", "landline")),
    "BR": (("9", "mobile"), ("6", "landline"), ("7", "landline"), ("8", "landline"), ("1", "landline"), ("2", "landline"), ("3", "landline")),
    "ZA": (("6", "mobile"), ("7", "mobile"), ("8", "mobile"), ("1", "landline"), ("2", "landline"), ("3", "landline")),
    "KE": (("7", "mobile"), ("1", "landline"), ("2", "landline")),
    "GH": (("2", "mobile"), ("5", "mobile"), ("3", "landline"), ("4", "landline")),
    "EG": (("1", "mobile"), ("2", "landline"), ("3", "landline"), ("4", "landline"), ("5", "landline"), ("6", "landline"), ("7", "landline"), ("8", "landline"), ("9", "landline")),
    "AE": (("5", "mobile"), ("2", "landline"), ("4", "landline"), ("6", "landline")),
    "SA": (("5", "mobile"), ("1", "landline"), ("2", "landline"), ("3", "landline"), ("4", "landline")),
    "PK": (("3", "mobile"), ("5", "mobile"), ("2", "landline"), ("4", "landline"), ("9", "special")),
    "BD": (("1", "mobile"), ("2", "landline"), ("3", "landline"), ("4", "landline")),
    "NP": (("9", "mobile"), ("1", "landline"), ("2", "landline"), ("3", "landline"), ("4", "landline")),
    "RU": (("9", "mobile"), ("4", "mobile"), ("8", "special"), ("3", "landline"), ("4", "landline"), ("7", "landline")),
    "TR": (("5", "mobile"), ("2", "landline"), ("3", "landline"), ("4", "landline"), ("8", "special")),
}


def resolve_line_type(iso2: str, nsn: str) -> str | None:
    """Longest-prefix line-type match on the national significant number."""
    plan = LINE_TYPE_PLAN.get(iso2)
    if not plan:
        return None
    # longest prefix first
    for prefix, line_type in sorted(plan, key=lambda p: len(p[0]), reverse=True):
        if nsn.startswith(prefix):
            return line_type
    return None


# --------------------------------------------------------------------------- #
# Carrier NDC registries (public national numbering plans).
# --------------------------------------------------------------------------- #
# Nigeria — NCC number-block allocations (NDC → operator).
NG_NDC_CARRIER: dict[str, str] = {
    "701": "Airtel", "702": "Smile", "703": "MTN", "704": "MTN", "705": "Glo",
    "706": "MTN", "707": "Airtel", "708": "Airtel", "709": "9mobile",
    "802": "Airtel", "803": "MTN", "804": "MTN", "805": "Glo", "806": "MTN",
    "807": "Glo", "808": "9mobile", "809": "9mobile", "810": "MTN", "811": "Glo",
    "812": "Airtel", "813": "MTN", "814": "MTN", "815": "Glo", "816": "MTN",
    "817": "Glo", "818": "9mobile", "819": "Airtel", "820": "Airtel",
    "901": "Airtel", "902": "Airtel", "903": "MTN", "904": "Airtel",
    "905": "Glo", "906": "MTN", "907": "Airtel", "908": "9mobile",
    "909": "9mobile", "911": "Glo", "912": "Airtel", "913": "MTN",
    "914": "MTN", "915": "Glo", "916": "MTN", "919": "Airtel",
}

# UK — OFCOM number allocations (4-digit mobile prefix → MNO, best-effort).
UK_MNO_PREFIX: dict[str, str] = {
    "711": "EE", "712": "EE", "713": "EE", "714": "EE", "715": "EE", "716": "EE",
    "717": "EE", "718": "EE", "719": "EE", "721": "O2", "722": "O2", "723": "O2",
    "724": "O2", "725": "O2", "726": "O2", "727": "O2", "728": "O2", "729": "O2",
    "731": "EE", "732": "EE", "733": "EE", "734": "EE", "735": "EE", "736": "EE",
    "737": "EE", "738": "EE", "739": "EE", "740": "Vodafone", "741": "Vodafone",
    "742": "Vodafone", "743": "Vodafone", "744": "Vodafone", "745": "Vodafone",
    "746": "Vodafone", "747": "Vodafone", "748": "Vodafone", "749": "Vodafone",
    "750": "O2", "751": "O2", "752": "O2", "753": "O2", "754": "O2", "755": "O2",
    "756": "O2", "757": "O2", "758": "O2", "759": "O2", "770": "BT", "771": "BT",
    "772": "O2", "773": "O2", "774": "O2", "775": "O2", "776": "O2", "777": "O2",
    "778": "O2", "779": "O2", "780": "EE", "781": "EE", "782": "EE", "783": "EE",
    "784": "EE", "785": "EE", "786": "EE", "787": "EE", "788": "EE", "789": "EE",
    "790": "EE", "791": "EE", "792": "EE", "793": "EE", "794": "EE", "795": "EE",
    "796": "Three", "797": "Three", "798": "Three", "799": "Three",
}

# US/Canada/NANP — area code → primary state / province (major exchanges).
NPA_REGION: dict[str, str] = {
    "201": "New Jersey", "202": "District of Columbia", "203": "Connecticut",
    "205": "Alabama", "206": "Washington (Seattle)", "208": "Idaho",
    "210": "Texas (San Antonio)", "212": "New York (Manhattan)", "213": "California (Los Angeles)",
    "214": "Texas (Dallas)", "215": "Pennsylvania (Philadelphia)", "216": "Ohio (Cleveland)",
    "217": "Illinois (Springfield)", "224": "Illinois (Chicago NW)", "239": "Florida (Fort Myers)",
    "240": "Maryland (suburban DC)", "248": "Michigan (Detroit metro)", "251": "Alabama (Mobile)",
    "253": "Washington (Tacoma)", "260": "Indiana (Fort Wayne)", "262": "Wisconsin (SE)",
    "267": "Pennsylvania (Philadelphia)", "269": "Michigan (SW)", "281": "Texas (Houston)",
    "303": "Colorado (Denver)", "305": "Florida (Miami)", "310": "California (LA/Beach Cities)",
    "312": "Illinois (Chicago)", "313": "Michigan (Detroit)", "314": "Missouri (St. Louis)",
    "315": "New York (Syracuse)", "317": "Indiana (Indianapolis)", "319": "Iowa (E)",
    "323": "California (Los Angeles)", "330": "Ohio (Akron)", "336": "North Carolina (Greensboro)",
    "347": "New York (Brooklyn)", "352": "Florida (Gainesville)", "360": "Washington (W)",
    "401": "Rhode Island (Providence)", "402": "Nebraska (Omaha)", "404": "Georgia (Atlanta)",
    "405": "Oklahoma (Oklahoma City)", "407": "Florida (Orlando)", "408": "California (San Jose)",
    "410": "Maryland (Baltimore)", "412": "Pennsylvania (Pittsburgh)", "413": "Massachusetts (W)",
    "414": "Wisconsin (Milwaukee)", "415": "California (San Francisco)", "416": "Ontario (Toronto)",
    "417": "Missouri (Springfield)", "419": "Ohio (Toledo)", "423": "Tennessee (E)",
    "424": "California (Los Angeles)", "425": "Washington (Seattle E)", "440": "Ohio (Cleveland S)",
    "443": "Maryland (Baltimore)", "469": "Texas (Dallas)", "470": "Georgia (Atlanta)",
    "480": "Arizona (Phoenix E)", "484": "Pennsylvania (Philadelphia)", "501": "Arkansas (Central)",
    "502": "Kentucky (Louisville)", "503": "Oregon (Portland)", "504": "Louisiana (New Orleans)",
    "505": "New Mexico (Albuquerque)", "508": "Massachusetts (E)", "510": "California (Oakland)",
    "512": "Texas (Austin)", "513": "Ohio (Cincinnati)", "514": "Quebec (Montreal)",
    "516": "New York (Long Island)", "518": "New York (Albany)", "520": "Arizona (Tucson)",
    "530": "California (N)", "540": "Virginia (W)", "541": "Oregon (S)", "551": "New Jersey (N)",
    "559": "California (Fresno)", "561": "Florida (West Palm Beach)", "562": "California (Long Beach)",
    "571": "Virginia (Northern)", "573": "Missouri (E)", "585": "New York (Rochester)",
    "601": "Mississippi (Jackson)", "602": "Arizona (Phoenix)", "603": "New Hampshire",
    "604": "British Columbia (Vancouver)", "605": "South Dakota", "606": "Kentucky (E)",
    "607": "New York (Binghamton)", "608": "Wisconsin (Madison)", "609": "New Jersey (S)",
    "610": "Pennsylvania (E)", "612": "Minnesota (Minneapolis)", "613": "Ontario (Ottawa)",
    "614": "Ohio (Columbus)", "615": "Tennessee (Nashville)", "616": "Michigan (Grand Rapids)",
    "617": "Massachusetts (Boston)", "619": "California (San Diego)", "623": "Arizona (Phoenix W)",
    "626": "California (Pasadena)", "630": "Illinois (Chicago W)", "631": "New York (Long Island E)",
    "646": "New York (Manhattan)", "650": "California (Peninsula)", "651": "Minnesota (St. Paul)",
    "678": "Georgia (Atlanta)", "702": "Nevada (Las Vegas)", "703": "Virginia (Northern)",
    "704": "North Carolina (Charlotte)", "713": "Texas (Houston)", "714": "California (Orange County)",
    "716": "New York (Buffalo)", "717": "Pennsylvania (Harrisburg)", "718": "New York (NYC boroughs)",
    "719": "Colorado (Colorado Springs)", "720": "Colorado (Denver)", "724": "Pennsylvania (W)",
    "725": "Nevada (Las Vegas)", "727": "Florida (Tampa Bay)", "732": "New Jersey (Central)",
    "734": "Michigan (Ann Arbor)", "737": "Texas (Austin)", "740": "Ohio (SE)",
    "754": "Florida (Fort Lauderdale)", "757": "Virginia (Hampton Roads)", "760": "California (S)",
    "770": "Georgia (Atlanta suburbs)", "772": "Florida (Treasure Coast)", "773": "Illinois (Chicago)",
    "774": "Massachusetts (W)", "775": "Nevada (Reno)", "778": "British Columbia",
    "781": "Massachusetts (Boston S)", "785": "Kansas (Topeka)", "786": "Florida (Miami)",
    "787": "Puerto Rico", "801": "Utah (Salt Lake City)", "802": "Vermont",
    "803": "South Carolina (Columbia)", "804": "Virginia (Richmond)", "805": "California (Santa Barbara)",
    "806": "Texas (Panhandle)", "808": "Hawaii", "810": "Michigan (Flint)",
    "812": "Indiana (S)", "813": "Florida (Tampa)", "814": "Pennsylvania (Central)",
    "815": "Illinois (N)", "816": "Missouri (Kansas City)", "817": "Texas (Fort Worth)",
    "818": "California (LA San Fernando)", "828": "North Carolina (W)", "832": "Texas (Houston)",
    "843": "South Carolina (Charleston)", "845": "New York (Hudson Valley)", "847": "Illinois (Chicago N)",
    "848": "New Jersey (Central)", "850": "Florida (Panhandle)", "856": "New Jersey (S)",
    "857": "Massachusetts (Boston)", "858": "California (San Diego)", "859": "Kentucky (Lexington)",
    "860": "Connecticut (Hartford)", "862": "New Jersey (Newark)", "863": "Florida (Central)",
    "865": "Tennessee (Knoxville)", "870": "Arkansas (S)", "901": "Tennessee (Memphis)",
    "903": "Texas (E)", "904": "Florida (Jacksonville)", "905": "Ontario (GTA)",
    "907": "Alaska (Anchorage)", "908": "New Jersey (Central)", "909": "California (Inland Empire)",
    "910": "North Carolina (Fayetteville)", "912": "Georgia (Savannah)", "913": "Kansas (Kansas City)",
    "914": "New York (Westchester)", "915": "Texas (El Paso)", "916": "California (Sacramento)",
    "917": "New York (NYC mobile)", "918": "Oklahoma (Tulsa)", "919": "North Carolina (Raleigh)",
    "920": "Wisconsin (E)", "925": "California (East Bay)", "928": "Arizona (N)",
    "929": "New York (NYC)", "931": "Tennessee (Middle)", "934": "New York (Long Island)",
    "936": "Texas (E)", "937": "Ohio (Dayton)", "940": "Texas (Denton)", "941": "Florida (Sarasota)",
    "949": "California (Orange County)", "951": "California (Riverside)", "952": "Minnesota (Twin Cities S)",
    "954": "Florida (Fort Lauderdale)", "956": "Texas (Rio Grande)", "959": "Connecticut (Hartford)",
    "970": "Colorado (N)", "971": "Oregon (Portland)", "972": "Texas (Dallas)",
    "973": "New Jersey (N)", "978": "Massachusetts (N)", "980": "North Carolina (Charlotte)",
    "984": "North Carolina (Raleigh)", "985": "Louisiana (S)", "986": "Idaho (N)",
}

# UK — national geographic dialling codes → region.
UK_CODE_REGION: dict[str, str] = {
    "20": "London", "161": "Manchester", "121": "Birmingham", "131": "Edinburgh",
    "141": "Glasgow", "113": "Leeds", "114": "Sheffield", "115": "Nottingham",
    "116": "Leicester", "117": "Bristol", "118": "Reading", "151": "Liverpool",
    "191": "Newcastle upon Tyne", "23": "Southampton/Portsmouth", "24": "Coventry",
    "28": "Northern Ireland", "29": "Cardiff", "122": "Bath", "1224": "Aberdeen",
    "1223": "Cambridge", "1273": "Brighton", "1274": "Bradford", "1904": "York",
    "1522": "Lincoln", "1733": "Peterborough", "2380": "Portsmouth", "1892": "Tunbridge Wells",
}

# India — STD area codes → city.
IN_CODE_REGION: dict[str, str] = {
    "11": "Delhi", "22": "Mumbai", "33": "Kolkata", "44": "Chennai",
    "80": "Bengaluru", "40": "Hyderabad", "20": "Pune", "79": "Ahmedabad",
    "124": "Gurugram", "120": "Noida", "141": "Jaipur", "522": "Lucknow",
    "44": "Chennai", "98": "Mumbai suburbs", "51": "Kanpur", "412": "Chennai (outer)",
}

# France — number zones.
FR_CODE_REGION: dict[str, str] = {
    "1": "Paris / Île-de-France", "2": "Northwest France", "3": "Northeast France",
    "4": "Southeast France", "5": "Southwest France", "9": "Overseas / VoIP",
}

# Germany — number zones (approximate).
DE_CODE_REGION: dict[str, str] = {
    "30": "Berlin", "40": "Hamburg", "89": "Munich", "69": "Frankfurt am Main",
    "211": "Düsseldorf", "221": "Cologne", "201": "Essen", "231": "Dortmund",
    "511": "Hannover", "341": "Leipzig", "351": "Dresden", "711": "Stuttgart",
    "69": "Frankfurt am Main",
}

# Nigeria — fixed-line area codes (NCC national numbering plan, leading digits
# of the NSN without the trunk 0). Mobile NDCs route nationally, not by city.
NG_CODE_REGION: dict[str, str] = {
    "1": "Lagos", "2": "Lagos",
    "4": "Port Harcourt (Rivers)", "5": "Ibadan (Oyo)", "6": "Enugu (Enugu)",
    "7": "Kaduna (Kaduna)", "8": "Abeokuta (Ogun)", "9": "Abuja (FCT)",
    "30": "Benin City (Edo)", "31": "Ilorin (Kwara)", "33": "Onitsha (Anambra)",
    "36": "Jos (Plateau)", "38": "Owerri (Imo)", "41": "Ado-Ekiti (Ekiti)",
    "44": "Aba (Abia)", "52": "Ondo (Ondo)", "54": "Warri (Delta)",
    "62": "Makurdi (Benue)", "64": "Lokoja (Kogi)",
}

# Nigeria — mobile NDCs route through national core networks (no fixed city).
NG_MOBILE_LEADS: tuple[str, ...] = ("7", "8", "9")


def resolve_geo_zone(iso2: str, nsn: str) -> str | None:
    """Best-effort geographic registration zone from public numbering plans."""
    if iso2 == "US" and len(nsn) >= 3:
        npa = nsn[:3]
        return NPA_REGION.get(npa)
    if iso2 == "CA":
        npa = nsn[:3]
        return NPA_REGION.get(npa)
    if iso2 == "NG":
        if nsn[:1] in NG_MOBILE_LEADS:
            return "national mobile network (no fixed city)"
        for prefix, region in sorted(NG_CODE_REGION.items(), key=lambda p: len(p[0]), reverse=True):
            if nsn.startswith(prefix):
                return region
        return None
    if iso2 == "GB":
        for prefix, region in sorted(UK_CODE_REGION.items(), key=lambda p: len(p[0]), reverse=True):
            if nsn.startswith(prefix):
                return region
    if iso2 == "IN":
        for prefix, region in sorted(IN_CODE_REGION.items(), key=lambda p: len(p[0]), reverse=True):
            if nsn.startswith(prefix):
                return region
    if iso2 == "FR":
        for prefix, region in FR_CODE_REGION.items():
            if nsn.startswith(prefix):
                return region
    if iso2 == "DE":
        for prefix, region in sorted(DE_CODE_REGION.items(), key=lambda p: len(p[0]), reverse=True):
            if nsn.startswith(prefix):
                return region
    return None


def derive_routing_location(iso2: str | None, nsn: str | None, geo_city: str | None) -> str | None:
    """Resolve the core routing-gateway location for a number.

    Google's libphonenumber geocoder often falls back to the *country name*
    (e.g. "Nigeria") when no city-level entry exists — a "city" that merely
    mirrors the country is misleading.  When that happens (or when no city is
    derivable at all) we fall back to the NDC-derived routing gateway, or a
    country-level marker when even that is unknown.  Never returns the raw
    country name as a "city".
    """
    if not iso2 or not nsn:
        return None
    zone = resolve_geo_zone(iso2, nsn)
    if zone:
        if zone == "national mobile network (no fixed city)":
            return "national mobile core routing gateway (no fixed city)"
        return f"{zone} core routing gateway"
    return "country-level core routing gateway"


def _resolve_carrier(iso2: str, nsn: str) -> str | None:
    if iso2 == "NG" and len(nsn) >= 3:
        return NG_NDC_CARRIER.get(nsn[:3])
    if iso2 == "GB" and nsn.startswith("7") and len(nsn) >= 4:
        # strip leading national 0 → mobile NSN is 10 digits starting with 7.
        # MNO prefix = first 3 digits after the leading '7'? OFCOM blocks are 4 digits
        # from the leading '7', e.g. 07700... → '770'.
        return UK_MNO_PREFIX.get(nsn[:3]) if len(nsn) >= 3 else None
    return None


def derive_free_e164(phone: str) -> dict[str, Any]:
    """Deterministic, registry-derived intelligence for an E.164 number.

    Pure public numbering-plan facts. Returns ``{"ok": False, ...}`` when the
    number cannot be parsed.
    """
    parsed = country_code_from_itu(phone)
    if not parsed:
        return {"ok": False, "reason": "unknown country calling code"}
    cc, iso2, nsn = parsed
    carrier = _resolve_carrier(iso2, nsn)
    line_type = resolve_line_type(iso2, nsn)
    mcc = ISO_TO_MCC.get(iso2)
    mnc = None
    if mcc:
        default = MCC_DEFAULT_MNC.get(mcc)
        if default:
            mnc = default[0]
    if carrier:
        matched = derive_mcc_mnc(carrier)
        if matched:
            mcc, mnc = matched.get("mcc") or mcc, matched.get("mnc") or mnc

    ndc = nsn[:3] if iso2 == "NG" else None
    return {
        "ok": True,
        "phone_e164": f"+{cc}{nsn}",
        "country_code": f"+{cc}",
        "iso2": iso2,
        "mcc": mcc,
        "mnc": mnc,
        "carrier": carrier,
        "line_type": line_type,
        "ndc": ndc,
        "sn": nsn,
        "source": "public numbering plan",
    }


# libphonenumber PhoneNumberType → human label (public Google metadata).
_PN_TYPE_LABEL: dict[int, str] = {
    0: "FIXED_LINE", 1: "MOBILE", 2: "FIXED_LINE_OR_MOBILE", 3: "TOLL_FREE",
    4: "PREMIUM_RATE", 5: "SHARED_COST", 6: "VOIP", 7: "PERSONAL_NUMBER",
    8: "PAGER", 9: "UAN", 10: "VOICEMAIL", 99: "UNKNOWN",
}


def _split_nsn(iso2: str, nsn: str, type_label: str) -> tuple[str | None, str | None]:
    """Best-effort (NDC, subscriber) split from public numbering structures.

    Returns (None, None) where the national destination code is not a
    well-established fixed length in the reference plan.
    """
    if iso2 in ("US", "CA"):
        return nsn[:6], nsn[6:]  # NPA-NXX (6) + subscriber (4)
    if iso2 == "NG" and type_label in ("MOBILE", "FIXED_LINE_OR_MOBILE"):
        return nsn[:3], nsn[3:]
    if iso2 == "GB" and type_label == "MOBILE":
        return nsn[:2], nsn[2:]  # leading '7' + switch digit
    if iso2 == "IN":
        return (nsn[:3], nsn[3:]) if type_label == "MOBILE" else (nsn[:2], nsn[2:])
    if iso2 == "CN" and type_label == "MOBILE":
        return nsn[:3], nsn[3:]
    if iso2 == "FR" and type_label in ("MOBILE", "FIXED_LINE_OR_MOBILE") and nsn[:1] in ("6", "7"):
        return nsn[:1], nsn[1:]
    if iso2 == "DE" and type_label == "MOBILE" and nsn[:2] in ("15", "16", "17"):
        return nsn[:3], nsn[3:]
    return None, None


def derive_phonenumbers_intel(e164: str) -> dict[str, Any]:
    """Real keyless intelligence from Google's libphonenumber metadata.

    Parsing, validation, number-type, carrier, geocoding (city/region) and
    timezone come straight from the bundled public metadata — no network call,
    no key. This is the Tier-1 extraction core.
    """
    try:
        num = phonenumbers.parse(e164, None)
    except phonenumbers.NumberParseException as exc:
        return {"ok": False, "reason": f"unparseable: {exc}"}

    nsn = str(num.national_number)
    possible = phonenumbers.is_possible_number(num)
    valid = phonenumbers.is_valid_number(num)
    iso2 = phonenumbers.region_code_for_number(num)
    if not iso2:
        cc_fallback = country_code_from_itu(e164)
        iso2 = cc_fallback[1] if cc_fallback else None
    type_label = _PN_TYPE_LABEL.get(phonenumbers.number_type(num), "UNKNOWN")
    ndc, subscriber = _split_nsn(iso2 or "", nsn, type_label)

    country_name = None
    try:
        country_name = pn_geocoder.country_name_for_number(num, "en")
    except Exception:  # noqa: BLE001 — metadata lookup is best-effort
        country_name = None
    geo_city = pn_geocoder.description_for_number(num, "en") or None
    # libphonenumber's geocoder falls back to the country name when no
    # city-level entry exists — a "city" equal to the country is a routing
    # fact, not a city. Fall back to the NDC routing-gateway location.
    city_is_country = (
        geo_city is None
        or (country_name and geo_city.strip().lower() == country_name.strip().lower())
    )
    routing_location = None
    if city_is_country:
        routing_location = derive_routing_location(iso2, nsn, geo_city)
        geo_city = None

    result: dict[str, Any] = {
        "ok": True,
        "e164": phonenumbers.format_number(num, PhoneNumberFormat.E164),
        "country_code": f"+{num.country_code}",
        "iso2": iso2,
        "national_number": nsn,
        "ndc": ndc,
        "subscriber_number": subscriber,
        "possible": possible,
        "valid": valid,
        "number_type": type_label,
        "carrier": pn_carrier.name_for_number(num, "en"),
        "geo_city": geo_city,
        "routing_location": routing_location,
        "timezone": sorted(t for t in pn_timezone.time_zones_for_number(num) if t != "Etc/Unknown"),
        "national_format": phonenumbers.format_number(num, PhoneNumberFormat.NATIONAL),
        "international_format": phonenumbers.format_number(num, PhoneNumberFormat.INTERNATIONAL),
    }
    if not result["timezone"]:
        result["timezone"] = pn_timezone.time_zones_for_number(num)
    return result
