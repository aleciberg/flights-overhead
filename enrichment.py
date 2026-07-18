"""
Enrichment lookups: flight routes, aircraft type, airline name.

Routes:        OpenSky /api/routes?callsign= — historical callsign->route
                                                lookup, not a per-flight estimate
                                                (see get_flight_route docstring)
Aircraft type: HexDB /api/v1/aircraft        — no auth, ~30-40% coverage
Airline name:  local ICAO prefix map  — instant, ~70% of commercial flights

All results are cached in-process so each callsign/icao24 is only fetched once.
"""

import re
import time
import logging
import requests
from typing import Optional, Tuple

import opensky_auth

logger = logging.getLogger(__name__)

_OPENSKY   = "https://opensky-network.org/api"
_HEXDB     = "https://hexdb.io/api/v1"
_HEXDB_AIRCRAFT = f"{_HEXDB}/aircraft"
_HEXDB_ROUTE    = f"{_HEXDB}/route/icao"

_route_cache:    dict = {}
_aircraft_cache: dict = {}

ROUTE_TTL = 86400 * 7      # 7 d    — callsign->route mapping rarely changes
AIRCRAFT_TTL = 86400 * 30  # 30 d   — type never changes


# ---------------------------------------------------------------------------
# Airport ICAO -> display name
# ---------------------------------------------------------------------------
AIRPORTS: dict = {
    # Pacific Northwest
    "KPDX": "Portland",       "KSEA": "Seattle",        "KGEG": "Spokane",
    "KEUG": "Eugene",         "KMFR": "Medford",        "KRDM": "Redmond OR",
    "KAST": "Astoria",        "KLMT": "Klamath Falls",  "KYKM": "Yakima",
    "KPUW": "Pullman",        "KBLI": "Bellingham",     "KPAE": "Everett",
    "KBFI": "Boeing Field",   "KTIW": "Tacoma Narrows",
    # Mountain West
    "KBOI": "Boise",          "KSLC": "Salt Lake City", "KDEN": "Denver",
    "KCOS": "Colo. Springs",  "KBZN": "Bozeman",        "KFCA": "Kalispell",
    "KMSO": "Missoula",       "KGTF": "Great Falls",    "KHLN": "Helena",
    "KBTM": "Butte",          "KIDA": "Idaho Falls",    "KTWF": "Twin Falls",
    "KRNO": "Reno",           "KLAS": "Las Vegas",      "KPHX": "Phoenix",
    "KTUS": "Tucson",         "KABQ": "Albuquerque",
    # California
    "KSFO": "San Francisco",  "KOAK": "Oakland",        "KSJC": "San Jose",
    "KSNA": "Orange County",  "KLAX": "Los Angeles",    "KBUR": "Burbank",
    "KLGB": "Long Beach",     "KSAN": "San Diego",      "KSMF": "Sacramento",
    "KFAT": "Fresno",         "KSBP": "San Luis Obispo", "KSBA": "Santa Barbara",
    "KPSP": "Palm Springs",   "KONT": "Ontario CA",
    # Midwest
    "KORD": "Chicago O'Hare", "KMDW": "Chicago Midway", "KMSP": "Minneapolis",
    "KSTL": "St. Louis",      "KCVG": "Cincinnati",     "KIND": "Indianapolis",
    "KDTW": "Detroit",        "KMKE": "Milwaukee",      "KDSM": "Des Moines",
    "KOMA": "Omaha",          "KMCI": "Kansas City",    "KTUL": "Tulsa",
    "KOKC": "Oklahoma City",  "KCMH": "Columbus OH",    "KDAY": "Dayton",
    # South
    "KATL": "Atlanta",        "KBNA": "Nashville",      "KMEM": "Memphis",
    "KMSY": "New Orleans",    "KIAH": "Houston Bush",   "KHOU": "Houston Hobby",
    "KDFW": "Dallas/FW",      "KDAL": "Dallas Love",    "KSAT": "San Antonio",
    "KAUS": "Austin",         "KELP": "El Paso",        "KMCO": "Orlando",
    "KTPA": "Tampa",          "KMIA": "Miami",          "KFLL": "Ft. Lauderdale",
    "KPBI": "West Palm Beach", "KJAX": "Jacksonville",   "KCLT": "Charlotte",
    "KRDU": "Raleigh",        "KRIC": "Richmond",       "KGRR": "Grand Rapids",
    "KBHM": "Birmingham AL",  "KHSV": "Huntsville",
    # Northeast
    "KJFK": "New York JFK",   "KLGA": "LaGuardia",      "KEWR": "Newark",
    "KBOS": "Boston",         "KBDL": "Hartford",       "KPVD": "Providence",
    "KPHL": "Philadelphia",   "KPIT": "Pittsburgh",     "KBWI": "Baltimore",
    "KDCA": "Washington DC",  "KIAD": "Dulles",         "KSYR": "Syracuse",
    "KBUF": "Buffalo",        "KROC": "Rochester NY",   "KALB": "Albany",
    "KMHT": "Manchester NH",  "KPWM": "Portland ME",    "KBTV": "Burlington VT",
    # Alaska / Hawaii
    "PANC": "Anchorage",      "PAFA": "Fairbanks",      "PAJN": "Juneau",
    "PHNL": "Honolulu",       "PHOG": "Maui",           "PHKO": "Kona",
    "PHLI": "Lihue",
    # Canada
    "CYVR": "Vancouver BC",   "CYYZ": "Toronto",        "CYUL": "Montreal",
    "CYEG": "Edmonton",       "CYYC": "Calgary",        "CYWG": "Winnipeg",
    "CYOW": "Ottawa",         "CYHZ": "Halifax",        "CYQR": "Regina",
    "CYXE": "Saskatoon",      "CYQB": "Quebec City",    "CYYJ": "Victoria BC",
    "CYXS": "Prince George",  "CYZF": "Yellowknife",
    # Mexico / Central America
    "MMMX": "Mexico City",    "MMUN": "Cancun",         "MMGL": "Guadalajara",
    "MMMY": "Monterrey",      "MPTO": "Panama City",    "MROC": "San José CR",
    "MGGT": "Guatemala City",
    # Caribbean
    "TJSJ": "San Juan",       "MKJP": "Kingston",       "MDSD": "Santo Domingo",
    "TNCM": "St. Maarten",
    # South America
    "SBGR": "São Paulo",      "SBGL": "Rio de Janeiro", "SAEZ": "Buenos Aires",
    "SCEL": "Santiago",       "SKBO": "Bogotá",         "SEQM": "Quito",
    "SPJC": "Lima",           "SBPA": "Porto Alegre",   "SBSV": "Salvador",
    "SBRF": "Recife",         "SBEG": "Manaus",
    # UK & Ireland
    "EGLL": "London Heathrow", "EGKK": "London Gatwick", "EGSS": "London Stansted",
    "EGGW": "London Luton",   "EGLC": "London City",    "EGBB": "Birmingham UK",
    "EGCC": "Manchester UK",  "EGPH": "Edinburgh",      "EGPF": "Glasgow",
    "EGGD": "Bristol",        "EGNT": "Newcastle",      "EGPD": "Aberdeen",
    "EIDW": "Dublin",         "EGAA": "Belfast",
    # Western Europe
    "LFPG": "Paris CDG",      "LFPO": "Paris Orly",     "EHAM": "Amsterdam",
    "EDDF": "Frankfurt",      "EDDM": "Munich",         "EDDB": "Berlin",
    "LEMD": "Madrid",         "LEBL": "Barcelona",      "LEPA": "Palma",
    "LIRF": "Rome",           "LIMC": "Milan",          "LSZH": "Zurich",
    "LSGG": "Geneva",         "LOWW": "Vienna",         "EBBR": "Brussels",
    "ELLX": "Luxembourg",     "LPPT": "Lisbon",         "LPPR": "Porto",
    "LGAV": "Athens",         "LTFM": "Istanbul",       "LCLK": "Larnaca",
    "LLBG": "Tel Aviv",       "OJAM": "Amman",
    # Scandinavia / Eastern Europe
    "EKCH": "Copenhagen",     "ENGM": "Oslo",           "ESSA": "Stockholm",
    "EFHK": "Helsinki",       "LKPR": "Prague",         "LHBP": "Budapest",
    "EPWA": "Warsaw",         "LROP": "Bucharest",      "LBSF": "Sofia",
    "LYBT": "Belgrade",       "LDZA": "Zagreb",
    # Russia / CIS
    "UUEE": "Moscow",         "UUDD": "Moscow DME",     "ULLI": "St. Petersburg",
    "UKBB": "Kyiv",
    # Middle East
    "OMDB": "Dubai",          "OMAA": "Abu Dhabi",      "OEJN": "Jeddah",
    "OERK": "Riyadh",         "OTHH": "Doha",           "OBBI": "Bahrain",
    "OMMU": "Muscat",         "OKBK": "Kuwait City",
    # Africa
    "HECA": "Cairo",          "HAAB": "Addis Ababa",    "HKJK": "Nairobi",
    "FAOR": "Johannesburg",   "FACT": "Cape Town",      "FALE": "Durban",
    "DNMM": "Lagos",          "DTTA": "Tunis",          "DAAG": "Algiers",
    "GMMN": "Casablanca",
    # South Asia
    "VIDP": "Delhi",          "VABB": "Mumbai",         "VOMM": "Chennai",
    "VOBL": "Bangalore",      "VECC": "Kolkata",        "VCBI": "Colombo",
    "VNKT": "Kathmandu",      "OPKC": "Karachi",        "OPIS": "Islamabad",
    # Southeast Asia
    "WSSS": "Singapore",      "WMKK": "Kuala Lumpur",   "VTBS": "Bangkok",
    "VTBD": "Bangkok DMK",    "WIII": "Jakarta",        "WADD": "Bali",
    "RPLL": "Manila",         "VVTS": "Ho Chi Minh City", "VVNB": "Hanoi",
    # East Asia
    "VHHH": "Hong Kong",      "RCTP": "Taipei",         "RKSI": "Seoul Incheon",
    "RKSS": "Seoul Gimpo",    "RJTT": "Tokyo Haneda",   "RJAA": "Tokyo Narita",
    "RJBB": "Osaka Kansai",   "RJOO": "Osaka Itami",    "RJFF": "Fukuoka",
    "ZSPD": "Shanghai Pudong", "ZSSS": "Shanghai HQ",    "ZBAA": "Beijing",
    "ZGGG": "Guangzhou",      "ZGSZ": "Shenzhen",       "ZUUU": "Chengdu",
    "ZUCK": "Chongqing",      "ZHHH": "Wuhan",          "ZPPP": "Kunming",
    # Oceania
    "YSSY": "Sydney",         "YMML": "Melbourne",      "YBBN": "Brisbane",
    "YPPH": "Perth",          "YPAD": "Adelaide",       "YBCS": "Cairns",
    "NZAA": "Auckland",       "NZCH": "Christchurch",   "NZWN": "Wellington",
    "NFFN": "Fiji",
}


def airport_name(icao: str) -> str:
    return AIRPORTS.get(icao.upper(), icao.upper())


# ---------------------------------------------------------------------------
# Airline ICAO prefix -> name  (local lookup, no network)
# ---------------------------------------------------------------------------
_AIRLINES: dict = {
    # US majors
    "AAL": "American Airlines",     "UAL": "United Airlines",
    "DAL": "Delta Air Lines",       "SWA": "Southwest Airlines",
    "ASA": "Alaska Airlines",       "JBU": "JetBlue Airways",
    "NKS": "Spirit Airlines",       "FFT": "Frontier Airlines",
    "HAL": "Hawaiian Airlines",     "SCX": "Sun Country Airlines",
    "AAY": "Allegiant Air",         "VXP": "Avelo Airlines",
    # US regionals
    "QXE": "Horizon Air",           "SKW": "SkyWest Airlines",
    "RPA": "Republic Airways",      "GJS": "GoJet Airlines",
    "WEN": "Endeavor Air",          "ASH": "Mesa Airlines",
    "PDT": "Piedmont Airlines",     "CPZ": "CommutAir",
    "BTA": "Boutique Air",          "OPT": "Key Lime Air",
    "SJS": "SeaPort Airlines",      "JIA": "PSA Airlines",
    # US cargo
    "FDX": "FedEx Express",         "UPS": "UPS Airlines",
    "ABX": "ABX Air",               "GTI": "Atlas Air",
    "NCR": "National Airlines",     "KMI": "Southern Air",
    "DHL": "DHL Aviation",
    # Canada
    "ACA": "Air Canada",            "WJA": "WestJet",
    "PVL": "Pacific Coastal",       "CFS": "Central Mountain Air",
    "CJT": "Cargojet Airways",      "TSC": "Air Transat",
    # Mexico / Central America
    "AMX": "Aeromexico",            "VOI": "Volaris",
    "VIV": "VivaAerobus",           "TAI": "TACA Airlines",
    # Europe
    "AFR": "Air France",            "BAW": "British Airways",
    "DLH": "Lufthansa",             "KLM": "KLM Royal Dutch",
    "IBE": "Iberia",                "AZA": "ITA Airways",
    "SAS": "Scandinavian Airlines", "FIN": "Finnair",
    "AUA": "Austrian Airlines",     "SWR": "SWISS",
    "EZY": "easyJet",               "RYR": "Ryanair",
    "VLG": "Vueling",               "NAX": "Norwegian Air",
    "TAP": "TAP Air Portugal",      "THY": "Turkish Airlines",
    "PGT": "Pegasus Airlines",      "ICE": "Icelandair",
    "WZZ": "Wizz Air",              "TOM": "TUI Airways",
    "AEA": "Air Europa",
    # Middle East
    "UAE": "Emirates",              "ETD": "Etihad Airways",
    "QTR": "Qatar Airways",         "SVA": "Saudia",
    "ELY": "El Al Israel Airlines", "RJA": "Royal Jordanian",
    # Asia-Pacific
    "JAL": "Japan Airlines",        "ANA": "All Nippon Airways",
    "CPA": "Cathay Pacific",        "KAL": "Korean Air",
    "AAR": "Asiana Airlines",       "CCA": "Air China",
    "CSN": "China Southern",        "CES": "China Eastern",
    "SIA": "Singapore Airlines",    "MAS": "Malaysia Airlines",
    "THA": "Thai Airways",          "GIA": "Garuda Indonesia",
    "PAL": "Philippine Airlines",   "QFA": "Qantas",
    "ANZ": "Air New Zealand",       "JST": "Jetstar Airways",
    "HXA": "Hainan Airlines",
    # South America
    "TAM": "LATAM Airlines",        "GLO": "Gol Airlines",
    "AVA": "Avianca",
    # Africa
    "ETH": "Ethiopian Airlines",    "KQA": "Kenya Airways",
    "MSR": "EgyptAir",              "RAM": "Royal Air Maroc",
    # International cargo
    "CLX": "Cargolux",              "MPH": "Martinair Cargo",
    "BOX": "DHL Air",               "TAY": "TNT Airways",
}

_AIRLINE_RE = re.compile(r'^([A-Z]{2,3})\d')


def get_airline(callsign: str) -> Optional[str]:
    """Return airline name from ICAO callsign prefix, or None for GA/unknown."""
    m = _AIRLINE_RE.match(callsign.upper())
    return _AIRLINES.get(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# Route lookup via the (undocumented but live) /api/routes endpoint.
#
# Both sources are historical callsign->route lookups, not a per-flight
# estimate: they answer "what route does this flight number typically fly"
# rather than "where did this specific aircraft's current leg start/end", so
# unlike /flights/aircraft's estDepartureAirport/estArrivalAirport (which is
# only known after a specific aircraft lands), these work for flights that
# are still airborne — every flight this app looks at.
#
# Coverage is spotty from either source alone (regional/codeshare flight
# numbers especially), so we try HexDB first, then fall back to OpenSky.
#
# Caveat: both reflect whenever that provider last recorded the callsign
# flying — could be stale, and airlines do occasionally reassign flight
# numbers to different city pairs — so this is "usually right", not live.
# ---------------------------------------------------------------------------

def _route_from_hexdb(callsign: str) -> Optional[Tuple[str, str]]:
    resp = requests.get(f"{_HEXDB_ROUTE}/{callsign}", timeout=6)
    if resp.status_code == 404:
        logger.info("route %s: not in HexDB", callsign)
        return None
    if not resp.ok:
        logger.info("route %s: HexDB HTTP %s", callsign, resp.status_code)
        return None
    data  = resp.json()
    parts = (data.get("route") or "").split("-")
    if len(parts) < 2:
        logger.info("route %s: HexDB route field unparseable: %r", callsign, data.get("route"))
        return None
    dep_icao, arr_icao = parts[0], parts[-1]
    result = (airport_name(dep_icao), airport_name(arr_icao))
    logger.info("route %s: HexDB dep=%s arr=%s -> %s", callsign, dep_icao, arr_icao, result)
    return result


def _route_from_opensky(callsign: str) -> Optional[Tuple[str, str]]:
    resp = requests.get(
        f"{_OPENSKY}/routes",
        params={"callsign": callsign},
        headers=opensky_auth.auth_headers(),
        timeout=8,
    )
    if resp.status_code == 404:
        logger.info("route %s: not in OpenSky's route database", callsign)
        return None
    if not resp.ok:
        logger.info("route %s: OpenSky HTTP %s", callsign, resp.status_code)
        return None
    data  = resp.json()
    route = data.get("route") or []
    if len(route) < 2:
        logger.info("route %s: OpenSky route field too short: %r", callsign, route)
        return None
    dep_icao, arr_icao = route[0], route[-1]
    result = (airport_name(dep_icao), airport_name(arr_icao))
    logger.info(
        "route %s: OpenSky dep=%s arr=%s (updated %s) -> %s",
        callsign, dep_icao, arr_icao, data.get("updateTime"), result,
    )
    return result


def get_flight_route(callsign: str) -> Optional[Tuple[str, Optional[str]]]:
    """Return (dep_name, arr_name) or None if neither source has this callsign."""
    now = int(time.time())
    if callsign in _route_cache:
        result, ts = _route_cache[callsign]
        if now - ts < ROUTE_TTL:
            return result

    result = None
    for lookup in (_route_from_hexdb, _route_from_opensky):
        try:
            result = lookup(callsign)
        except Exception as exc:
            logger.warning("route %s: %s failed: %s", callsign, lookup.__name__, exc)
            result = None
        if result:
            break

    _route_cache[callsign] = (result, now)
    return result


# ---------------------------------------------------------------------------
# Aircraft type lookup  (HexDB — no auth required)
# ---------------------------------------------------------------------------

def get_aircraft_type(icao24: str) -> Optional[str]:
    """Return a short type string like 'Boeing 737-900 N12345' or None."""
    now = time.time()
    if icao24 in _aircraft_cache:
        result, ts = _aircraft_cache[icao24]
        if now - ts < AIRCRAFT_TTL:
            return result

    try:
        resp = requests.get(f"{_HEXDB_AIRCRAFT}/{icao24}", timeout=6)
        if resp.status_code != 200:
            _aircraft_cache[icao24] = (None, now)
            return None
        data = resp.json()
        typ = (data.get("Type") or "").strip()
        reg = (data.get("Registration") or "").strip()
        result = f"{typ}  {reg}" if (typ and reg) else (typ or reg or None)
    except Exception:
        result = None

    _aircraft_cache[icao24] = (result, now)
    return result
